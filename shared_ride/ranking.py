from dataclasses import dataclass, field

from django.utils import timezone

from shared_ride.constraints import (
    ConstraintEvaluationResult,
    SharedConstraintEvaluationService,
)
from shared_ride.insertion import (
    EvaluatedInsertionCandidate,
    InsertionCandidate,
    SharedRouteInsertionService,
)
from shared_ride.simulation import (
    RouteSimulationResult,
    SharedRouteSimulationService,
)


# =========================================================
# Error
# =========================================================

class SharedRouteRankingError(Exception):
    pass


# =========================================================
# Ranking Metrics
# =========================================================

@dataclass(frozen=True)
class RouteRankingMetrics:
    """
    Metrics used only AFTER feasibility checking.

    ما واحدهای مختلف مثل minutes و km را
    داخل یک scalar score با هم جمع نمی‌کنیم.

    به جای آن یک deterministic
    lexicographic ranking داریم.
    """

    additional_travel_time_minutes: int

    total_passenger_delay_minutes: float

    pickup_wait_minutes: int

    route_extension_km: float


    def ranking_key(self):
        """
        Least-disruptive ranking policy:

        1. Lower total passenger delay
        2. Lower additional route time
        3. Lower pickup wait
        4. Lower route extension

        Passenger impact اولویت اصلی است.
        """

        return (
            self.total_passenger_delay_minutes,
            self.additional_travel_time_minutes,
            self.pickup_wait_minutes,
            self.route_extension_km,
        )


# =========================================================
# Decision for Every Generated Candidate
# =========================================================

@dataclass(frozen=True)
class FinalCandidateEvaluation:

    evaluated_candidate: (
        EvaluatedInsertionCandidate
    )

    constraints: (
        ConstraintEvaluationResult
    )

    metrics: (
        RouteRankingMetrics | None
    )


    @property
    def is_feasible(self):
        return (
            self.constraints.is_feasible
        )


# =========================================================
# Ranked Feasible Route
# =========================================================

@dataclass(frozen=True)
class RankedFeasibleRoute:

    rank: int

    candidate: InsertionCandidate

    simulation: RouteSimulationResult

    constraints: ConstraintEvaluationResult

    metrics: RouteRankingMetrics


# =========================================================
# Complete Selection Result
# =========================================================

@dataclass
class FeasibleRouteSelectionResult:

    # Route قبل از Passenger جدید
    baseline_route_simulation: (
        RouteSimulationResult
    )

    # همه candidateها، حتی rejectedها
    candidate_evaluations: list[
        FinalCandidateEvaluation
    ] = field(
        default_factory=list
    )

    # فقط feasibleها به ترتیب ranking
    feasible_routes: list[
        RankedFeasibleRoute
    ] = field(
        default_factory=list
    )


    @property
    def generated_candidate_count(self):
        return len(
            self.candidate_evaluations
        )


    @property
    def feasible_candidate_count(self):
        return len(
            self.feasible_routes
        )


    @property
    def rejected_candidate_count(self):
        return (
            self.generated_candidate_count
            - self.feasible_candidate_count
        )


    @property
    def best_route(self):
        """
        بهترین Route یا None.
        """

        if not self.feasible_routes:
            return None

        return self.feasible_routes[0]


# =========================================================
# Final Feasibility + Ranking Service
# =========================================================

class SharedRouteRankingService:

    # =====================================================
    # Active Existing Passenger Groups
    # =====================================================

    @staticmethod
    def _get_active_existing_groups(
        *,
        existing_stops,
        initial_onboard,
    ):
        """
        تمام Passenger Groupهایی که قبل از
        request جدید در این Shared Ride فعال‌اند.

        شامل:
        - already onboard
        - assigned but waiting for pickup
        - onboard with pending dropoff
        """

        return (
            set(initial_onboard.keys())
            |
            {
                stop.group_key
                for stop
                in existing_stops
            }
        )


    # =====================================================
    # Validate Existing Baseline Coverage
    # =====================================================

    @staticmethod
    def _get_relevant_baselines(
        *,
        active_existing_groups,
        existing_baselines,
    ):
        """
        هر Existing Active Passenger باید
        Baseline داشته باشد.

        Baselineهای اضافی مربوط به Passengerهای
        completed شده نادیده گرفته می‌شوند.
        """

        missing_groups = (
            active_existing_groups
            - set(
                existing_baselines.keys()
            )
        )


        if missing_groups:

            missing_text = ", ".join(
                sorted(missing_groups)
            )

            raise SharedRouteRankingError(
                (
                    "Missing baseline for active "
                    "passenger groups: "
                    f"{missing_text}"
                )
            )


        return {
            group_key:
                existing_baselines[
                    group_key
                ]

            for group_key
            in active_existing_groups
        }


    # =====================================================
    # Build Ranking Metrics
    # =====================================================

    @staticmethod
    def _build_metrics(
        *,
        baseline_simulation,
        candidate_simulation,
        constraint_result,
    ):
        """
        Metrics مخصوص candidate feasible.

        هیچ candidate invalid به این مرحله
        نمی‌رسد.
        """

        # =============================================
        # Additional Travel Time
        # =============================================

        additional_travel_time = max(
            0,

            candidate_simulation
            .total_time_minutes

            - baseline_simulation
            .total_time_minutes,
        )


        # =============================================
        # Route Extension
        # =============================================

        route_extension = max(
            0.0,

            candidate_simulation
            .total_distance_km

            - baseline_simulation
            .total_distance_km,
        )


        # =============================================
        # Existing Passenger Delay
        # =============================================

        existing_delay_total = sum(
            delay.absolute_delay_minutes

            for delay
            in (
                constraint_result
                .existing_passenger_delays
                .values()
            )
        )


        new_metrics = (
            constraint_result
            .new_passenger_metrics
        )


        if new_metrics is None:
            raise SharedRouteRankingError(
                (
                    "Feasible candidate is missing "
                    "new passenger metrics."
                )
            )


        # =============================================
        # Total Passenger Delay
        # =============================================
        #
        # Existing delay
        # +
        # New passenger shared detour
        #
        # این معیار میزان disruption کلی
        # روی Passengerها را نشان می‌دهد.

        total_passenger_delay = (
            existing_delay_total
            + new_metrics
            .absolute_detour_minutes
        )


        # =============================================
        # Pickup Wait
        # =============================================

        pickup_wait = (
            new_metrics
            .pickup_wait_minutes
        )


        return RouteRankingMetrics(
            additional_travel_time_minutes=(
                additional_travel_time
            ),

            total_passenger_delay_minutes=float(
                total_passenger_delay
            ),

            pickup_wait_minutes=(
                pickup_wait
            ),

            route_extension_km=float(
                route_extension
            ),
        )


    # =====================================================
    # Evaluate + Rank All Candidate Routes
    # =====================================================

    @staticmethod
    def evaluate_and_rank(
        *,
        current_node,
        vehicle_capacity,
        existing_stops,
        new_pickup,
        new_dropoff,
        existing_baselines,
        new_direct_trip_time_minutes,
        initial_onboard=None,
        reference_time=None,
    ):
        """
        Main complex route-decision workflow.

        Pipeline:

        Existing Route Simulation
                ↓
        Generate ALL Insertions
                ↓
        Simulate EVERY Candidate
                ↓
        Apply ALL Constraints
                ↓
        Build Feasible Set
                ↓
        Calculate Disruption Metrics
                ↓
        Rank Feasible Routes
                ↓
        Return Best Route
        """

        if initial_onboard is None:
            initial_onboard = {}


        if reference_time is None:
            reference_time = (
                timezone.now()
            )


        existing_stops = tuple(
            existing_stops
        )


        # =================================================
        # 1. Current Route Must Be Valid
        # =================================================

        baseline_simulation = (
            SharedRouteSimulationService
            .simulate(
                current_node=current_node,

                vehicle_capacity=(
                    vehicle_capacity
                ),

                stops=existing_stops,

                initial_onboard=(
                    initial_onboard
                ),
            )
        )


        if not baseline_simulation.is_valid:

            violation_text = ", ".join(
                baseline_simulation
                .violations
            )

            raise SharedRouteRankingError(
                (
                    "Current shared route is invalid: "
                    f"{violation_text}"
                )
            )


        # =================================================
        # 2. Existing Passenger Groups
        # =================================================

        active_existing_groups = (
            SharedRouteRankingService
            ._get_active_existing_groups(
                existing_stops=(
                    existing_stops
                ),

                initial_onboard=(
                    initial_onboard
                ),
            )
        )


        relevant_baselines = (
            SharedRouteRankingService
            ._get_relevant_baselines(
                active_existing_groups=(
                    active_existing_groups
                ),

                existing_baselines=(
                    existing_baselines
                ),
            )
        )


        # =================================================
        # 3. Generate + Simulate ALL Insertions
        # =================================================

        evaluated_insertions = (
            SharedRouteInsertionService
            .evaluate_candidates(
                current_node=current_node,

                vehicle_capacity=(
                    vehicle_capacity
                ),

                existing_stops=(
                    existing_stops
                ),

                new_pickup=(
                    new_pickup
                ),

                new_dropoff=(
                    new_dropoff
                ),

                initial_onboard=(
                    initial_onboard
                ),
            )
        )


        final_evaluations = []


        # =================================================
        # 4. Constraint Evaluation for EVERY Candidate
        # =================================================

        for evaluated in (
            evaluated_insertions
        ):

            constraint_result = (
                SharedConstraintEvaluationService
                .evaluate(
                    simulation=(
                        evaluated.simulation
                    ),

                    existing_baselines=(
                        relevant_baselines
                    ),

                    new_group_key=(
                        new_pickup.group_key
                    ),

                    new_direct_trip_time_minutes=(
                        new_direct_trip_time_minutes
                    ),

                    reference_time=(
                        reference_time
                    ),

                    # IMPORTANT:
                    # Existing-passenger delay must be
                    # measured against the current route
                    # simulation from the same taxi node.
                    # Real UI waiting time must not count
                    # as simulated passenger delay.
                    baseline_simulation=(
                        baseline_simulation
                    ),
                )
            )


            # =============================================
            # 5. Ranking Metrics ONLY if feasible
            # =============================================

            metrics = None


            if constraint_result.is_feasible:

                metrics = (
                    SharedRouteRankingService
                    ._build_metrics(
                        baseline_simulation=(
                            baseline_simulation
                        ),

                        candidate_simulation=(
                            evaluated.simulation
                        ),

                        constraint_result=(
                            constraint_result
                        ),
                    )
                )


            final_evaluations.append(
                FinalCandidateEvaluation(
                    evaluated_candidate=(
                        evaluated
                    ),

                    constraints=(
                        constraint_result
                    ),

                    metrics=(
                        metrics
                    ),
                )
            )


        # =================================================
        # 6. Feasible Set ONLY
        # =================================================

        feasible_evaluations = [
            evaluation

            for evaluation
            in final_evaluations

            if evaluation.is_feasible
        ]


        # =================================================
        # 7. Least-Disruptive Ranking
        # =================================================

        feasible_evaluations.sort(
            key=lambda evaluation: (
                evaluation
                .metrics
                .ranking_key()

                + (
                    evaluation
                    .evaluated_candidate
                    .candidate
                    .pickup_index,

                    evaluation
                    .evaluated_candidate
                    .candidate
                    .dropoff_index,
                )
            )
        )


        # =================================================
        # 8. Assign Rank
        # =================================================

        ranked_routes = []


        for rank, evaluation in enumerate(
            feasible_evaluations,
            start=1,
        ):

            evaluated = (
                evaluation
                .evaluated_candidate
            )


            ranked_routes.append(
                RankedFeasibleRoute(
                    rank=rank,

                    candidate=(
                        evaluated.candidate
                    ),

                    simulation=(
                        evaluated.simulation
                    ),

                    constraints=(
                        evaluation.constraints
                    ),

                    metrics=(
                        evaluation.metrics
                    ),
                )
            )


        # =================================================
        # 9. Final Selection Result
        # =================================================

        return FeasibleRouteSelectionResult(
            baseline_route_simulation=(
                baseline_simulation
            ),

            candidate_evaluations=(
                final_evaluations
            ),

            feasible_routes=(
                ranked_routes
            ),
        )