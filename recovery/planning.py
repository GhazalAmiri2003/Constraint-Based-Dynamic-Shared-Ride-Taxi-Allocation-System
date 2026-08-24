from dataclasses import dataclass
from typing import Any

from assignment.services import (
    AssignmentError,
    AssignmentService,
)
from assignment.shared_services import (
    SharedTaxiOptionError,
    SharedTaxiOptionService,
)
from rides.models import RideRequest

from recovery.services import (
    AffectedPassengerGroup,
    RecoveryPriorityService,
)


# =========================================================
# Recovery Planning Error
# =========================================================

class RecoveryPlanningError(Exception):
    pass


# =========================================================
# Normalized Recovery Taxi Candidate
# =========================================================

@dataclass(frozen=True)
class RecoveryTaxiCandidate:

    # Passenger group that needs recovery
    ride_request_id: int
    ride_passenger_id: int

    ride_type: str

    # Replacement taxi
    vehicle_id: int

    # Original rank returned by the reused engine
    engine_rank: int

    # Time from NOW until pickup
    pickup_eta_minutes: float

    # Metric used when comparing Recovery Plans
    additional_delay_minutes: float

    # 0 = highest-priority passenger
    priority_index: int

    # Original option returned by:
    #
    # AssignmentService
    # or
    # SharedTaxiOptionService
    #
    # We keep this because later, during DB Transaction,
    # we need the exact proposed route / route revision.
    raw_option: Any


# =========================================================
# Recovery Plan
# =========================================================

@dataclass(frozen=True)
class RecoveryPlan:

    assignments: tuple[
        RecoveryTaxiCandidate,
        ...
    ]


    # =====================================================
    # Number of recovered groups
    # =====================================================

    @property
    def recovered_group_count(self):

        return len(
            self.assignments
        )


    # =====================================================
    # Total Additional Delay
    # =====================================================

    @property
    def total_additional_delay_minutes(self):

        return sum(
            candidate.additional_delay_minutes
            for candidate
            in self.assignments
        )


    # =====================================================
    # Total Pickup ETA
    # =====================================================

    @property
    def total_pickup_eta_minutes(self):

        return sum(
            candidate.pickup_eta_minutes
            for candidate
            in self.assignments
        )


    # =====================================================
    # Priority Penalty
    # =====================================================

    @property
    def priority_penalty(self):
        """
        Lower is better.

        Example:

        Group priority 0 = most urgent
        Group priority 1 = less urgent

        If only one passenger can be recovered,
        the plan containing priority 0 must win.
        """

        return sum(
            candidate.priority_index
            for candidate
            in self.assignments
        )


    # =====================================================
    # Replacement Vehicles
    # =====================================================

    @property
    def vehicle_ids(self):

        return tuple(
            candidate.vehicle_id
            for candidate
            in self.assignments
        )


    # =====================================================
    # Ranking Policy
    # =====================================================

    @property
    def ranking_key(self):
        """
        Recovery Plan ranking:

        1. Recover greatest number of groups
        2. Respect passenger recovery priority
        3. Lowest total additional delay
        4. Lowest total pickup ETA
        5. Vehicle IDs for deterministic ordering
        """

        return (
            -self.recovered_group_count,
            self.priority_penalty,
            self.total_additional_delay_minutes,
            self.total_pickup_eta_minutes,
            self.vehicle_ids,
        )


# =========================================================
# Final Planning Result
# =========================================================

@dataclass(frozen=True)
class RecoveryPlanningResult:

    affected_group_count: int

    candidate_count: int

    feasible_plan_count: int

    plans: tuple[
        RecoveryPlan,
        ...
    ]


    @property
    def best_plan(self):

        if not self.plans:
            return None

        return self.plans[0]


# =========================================================
# Recovery Plan Service
# =========================================================

class RecoveryPlanService:

    # =====================================================
    # Temporarily expose request as PENDING
    # =====================================================

    @staticmethod
    def _call_engine_as_pending(
        ride_request,
        engine_function,
    ):
        """
        Existing assignment engines intentionally support
        PENDING RideRequests.

        During Recovery the request is still ASSIGNED to
        the failed taxi.

        We DO NOT update the database here.

        We only temporarily change the Python object's
        status so the existing feasibility engine can be
        reused.

        The original status is restored immediately after
        evaluation.
        """

        original_status = (
            ride_request.status
        )

        try:

            ride_request.status = (
                RideRequest.Status.PENDING
            )

            return engine_function(
                ride_request
            )

        finally:

            ride_request.status = (
                original_status
            )


    # =====================================================
    # Private Candidates
    # =====================================================

    @classmethod
    def _generate_private_candidates(
        cls,
        ride_request,
    ):

        try:

            return (
                cls._call_engine_as_pending(
                    ride_request,

                    AssignmentService
                    .generate_private_taxi_options,
                )
            )

        except AssignmentError as error:

            raise RecoveryPlanningError(
                str(error)
            )


    # =====================================================
    # Shared Candidates
    # =====================================================

    @classmethod
    def _generate_shared_candidates(
        cls,
        ride_request,
    ):

        try:

            return (
                cls._call_engine_as_pending(
                    ride_request,

                    SharedTaxiOptionService
                    .generate_shared_taxi_options,
                )
            )

        except SharedTaxiOptionError as error:

            raise RecoveryPlanningError(
                str(error)
            )


    # =====================================================
    # Calculate Recovery Delay
    # =====================================================

    @staticmethod
    def _calculate_additional_delay(
        ride_type,
        option,
    ):
        """
        PRIVATE:
            Recovery disruption is represented by the
            replacement pickup ETA.

        SHARED:
            Include both:
            - recovered passenger pickup ETA
            - shared-route passenger disruption calculated
              by the Shared Ride Engine.
        """

        pickup_eta = float(
            option.pickup_eta_minutes
        )


        if (
            ride_type
            == RideRequest.RideType.SHARED
        ):

            route_delay = float(
                option
                .total_passenger_delay_minutes
            )

            return (
                pickup_eta
                + route_delay
            )


        return pickup_eta


    # =====================================================
    # Generate Candidates For One Passenger Group
    # =====================================================

    @classmethod
    def generate_candidates_for_group(
        cls,
        group,
        failed_vehicle_id,
        priority_index=0,
    ):
        """
        Reuse the existing assignment engines and normalize
        their results into RecoveryTaxiCandidate objects.
        """

        try:

            ride_request = (
                RideRequest.objects
                .select_related(
                    "pickup_node",
                    "destination_node",
                )
                .get(
                    pk=group.ride_request_id
                )
            )

        except RideRequest.DoesNotExist:

            raise RecoveryPlanningError(
                (
                    "Affected RideRequest "
                    f"{group.ride_request_id} "
                    "does not exist."
                )
            )


        # =================================================
        # Reuse Existing Assignment Engines
        # =================================================

        if (
            ride_request.ride_type
            == RideRequest.RideType.PRIVATE
        ):

            engine_options = (
                cls
                ._generate_private_candidates(
                    ride_request
                )
            )


        elif (
            ride_request.ride_type
            == RideRequest.RideType.SHARED
        ):

            engine_options = (
                cls
                ._generate_shared_candidates(
                    ride_request
                )
            )


        else:

            raise RecoveryPlanningError(
                "Unsupported RideRequest type."
            )


        feasible_candidates = []


        # Remaining time from original request deadline.
        #
        # Example:
        #
        # Maximum wait = 10 min
        # Passenger already waited 6 min
        #
        # Remaining pickup budget = 4 min
        remaining_pickup_budget = max(
            0.0,
            float(
                group.pickup_slack_minutes
            ),
        )


        for option in engine_options:

            # =============================================
            # Failed Taxi cannot recover its own passengers
            # =============================================

            if (
                option.vehicle_id
                == failed_vehicle_id
            ):

                continue


            # =============================================
            # Recovery-specific pickup constraint
            # =============================================

            pickup_eta = float(
                option.pickup_eta_minutes
            )


            # The normal Assignment Engine checks:
            #
            # pickup ETA <= configured maximum
            #
            # Recovery is stricter:
            #
            # previous waiting time
            #       +
            # replacement pickup ETA
            #       <=
            # original configured maximum
            #
            # Therefore we compare against remaining slack.
            if (
                pickup_eta
                > remaining_pickup_budget
            ):

                continue


            # =============================================
            # Feasible Recovery Candidate
            # =============================================

            feasible_candidates.append(

                RecoveryTaxiCandidate(

                    ride_request_id=(
                        group.ride_request_id
                    ),

                    ride_passenger_id=(
                        group.ride_passenger_id
                    ),

                    ride_type=(
                        ride_request.ride_type
                    ),

                    vehicle_id=(
                        option.vehicle_id
                    ),

                    engine_rank=(
                        option.rank
                    ),

                    pickup_eta_minutes=(
                        pickup_eta
                    ),

                    additional_delay_minutes=(
                        cls
                        ._calculate_additional_delay(
                            ride_request.ride_type,
                            option,
                        )
                    ),

                    priority_index=(
                        priority_index
                    ),

                    raw_option=(
                        option
                    ),
                )
            )


        return feasible_candidates


    # =====================================================
    # Generate Recovery Plans
    # =====================================================

    @classmethod
    def generate_recovery_plans(
        cls,
        affected_groups,
        failed_vehicle_id,
    ):
        """
        Generate and compare complete Recovery Plans.

        Scope:
        - maximum two affected passenger groups
        - one replacement assignment per taxi inside the
          same Recovery transaction

        Existing SHARED taxis may still receive one affected
        group because SharedTaxiOptionService already checks
        their current passengers and Route constraints.
        """

        ranked_groups = (
            RecoveryPriorityService
            .rank_groups(
                affected_groups
            )
        )


        if len(ranked_groups) > 2:

            raise RecoveryPlanningError(
                (
                    "Recovery planning supports "
                    "at most two affected groups."
                )
            )


        # =================================================
        # Generate candidate taxis for every group
        # =================================================

        candidate_lists = []


        for priority_index, group in enumerate(
            ranked_groups
        ):

            candidates = (
                cls
                .generate_candidates_for_group(
                    group=group,
                    failed_vehicle_id=(
                        failed_vehicle_id
                    ),
                    priority_index=(
                        priority_index
                    ),
                )
            )

            candidate_lists.append(
                candidates
            )


        candidate_count = sum(
            len(candidate_list)
            for candidate_list
            in candidate_lists
        )


        plans = []


        # =================================================
        # One-group Recovery Plans
        # =================================================

        for candidate_list in candidate_lists:

            for candidate in candidate_list:

                plans.append(
                    RecoveryPlan(
                        assignments=(
                            candidate,
                        )
                    )
                )


        # =================================================
        # Two-group Recovery Plans
        # =================================================

        if len(candidate_lists) == 2:

            first_candidates = (
                candidate_lists[0]
            )

            second_candidates = (
                candidate_lists[1]
            )


            for first in first_candidates:

                for second in second_candidates:

                    # -------------------------------------
                    # Conservative consistency rule:
                    #
                    # During one Recovery transaction,
                    # two affected groups are not assigned
                    # independently to the same taxi.
                    #
                    # Otherwise each engine result would
                    # have been calculated against the
                    # original state rather than after the
                    # first recovery insertion.
                    # -------------------------------------

                    if (
                        first.vehicle_id
                        == second.vehicle_id
                    ):

                        continue


                    plans.append(

                        RecoveryPlan(
                            assignments=(
                                first,
                                second,
                            )
                        )
                    )


        # =================================================
        # Rank Feasible Plans
        # =================================================

        plans.sort(
            key=lambda plan:
                plan.ranking_key
        )


        return RecoveryPlanningResult(

            affected_group_count=(
                len(ranked_groups)
            ),

            candidate_count=(
                candidate_count
            ),

            feasible_plan_count=(
                len(plans)
            ),

            plans=tuple(
                plans
            ),
        )