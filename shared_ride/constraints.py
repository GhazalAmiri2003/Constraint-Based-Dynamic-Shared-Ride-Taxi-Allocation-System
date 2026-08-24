from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from shared_ride.simulation import (
    RouteSimulationResult,
)


# =========================================================
# Constraint Error
# =========================================================

class SharedConstraintError(Exception):
    pass


# =========================================================
# Structured Violation
# =========================================================

@dataclass(frozen=True)
class ConstraintViolation:

    code: str

    group_key: str | None

    actual_value: float | None

    limit_value: float | None

    message: str


# =========================================================
# Existing Passenger Delay Metrics
# =========================================================

@dataclass(frozen=True)
class ExistingPassengerDelay:

    group_key: str

    candidate_dropoff_minutes: int

    absolute_delay_minutes: float

    relative_delay: float


# =========================================================
# New Passenger Metrics
# =========================================================

@dataclass(frozen=True)
class NewPassengerMetrics:

    group_key: str

    pickup_wait_minutes: int

    shared_trip_time_minutes: int

    direct_trip_time_minutes: int

    absolute_detour_minutes: int

    relative_detour: float


# =========================================================
# Final Constraint Result
# =========================================================

@dataclass
class ConstraintEvaluationResult:

    is_feasible: bool

    violations: list[
        ConstraintViolation
    ] = field(
        default_factory=list
    )

    existing_passenger_delays: dict[
        str,
        ExistingPassengerDelay
    ] = field(
        default_factory=dict
    )

    new_passenger_metrics: (
        NewPassengerMetrics | None
    ) = None


# =========================================================
# Shared Constraint Evaluation Service
# =========================================================

class SharedConstraintEvaluationService:

    # =====================================================
    # Settings Helpers
    # =====================================================

    @staticmethod
    def _max_absolute_delay():
        return float(
            getattr(
                settings,
                "MAX_SHARED_ABSOLUTE_DELAY_MINUTES",
                10,
            )
        )


    @staticmethod
    def _max_relative_delay():
        return float(
            getattr(
                settings,
                "MAX_SHARED_RELATIVE_DELAY",
                0.30,
            )
        )


    @staticmethod
    def _max_pickup_wait():
        return int(
            getattr(
                settings,
                "MAX_SHARED_PICKUP_WAIT_MINUTES",
                10,
            )
        )


    # =====================================================
    # Existing Passenger Evaluation
    # =====================================================

    @staticmethod
    def _evaluate_existing_passengers(
        *,
        simulation,
        existing_baselines,
        reference_time,
        baseline_simulation=None,
    ):
        """
        Delay هر Passenger موجود را بررسی می‌کند.

        در Shared-Ride simulator، ETAهای RouteSimulationResult
        همگی "simulated minutes from current taxi position" هستند.

        بنابراین وقتی baseline_simulation داده شود، Delay را
        نسبت به همان Route فعلی بدون Passenger جدید می‌سنجیم:

            candidate_dropoff_eta
            -
            current_route_dropoff_eta

        این کار باعث می‌شود مدت زمانی که کاربر در UI صبر می‌کند
        یا بین دو درخواست Pause می‌کند، به اشتباه Passenger Delay
        حساب نشود.

        SharedPassengerBaseline همچنان immutable باقی می‌ماند و
        direct_trip_time_minutes آن برای Relative Delay استفاده
        می‌شود.

        fallback قدیمی مبتنی بر wall-clock فقط برای compatibility
        با callerهای قدیمی که baseline_simulation نمی‌فرستند
        نگه داشته شده است.
        """

        violations = []

        delay_results = {}


        max_absolute_delay = (
            SharedConstraintEvaluationService
            ._max_absolute_delay()
        )

        max_relative_delay = (
            SharedConstraintEvaluationService
            ._max_relative_delay()
        )


        for (
            group_key,
            baseline,
        ) in existing_baselines.items():

            # =============================================
            # Candidate must contain Dropoff
            # =============================================

            if (
                group_key
                not in simulation.dropoff_eta_by_group
            ):
                violations.append(
                    ConstraintViolation(
                        code=(
                            "EXISTING_PASSENGER_DROPOFF_MISSING"
                        ),

                        group_key=group_key,

                        actual_value=None,

                        limit_value=None,

                        message=(
                            "Existing passenger has no "
                            "drop-off in candidate route."
                        ),
                    )
                )

                continue


            candidate_dropoff_minutes = (
                simulation
                .dropoff_eta_by_group[
                    group_key
                ]
            )


            # =============================================
            # Simulated-Time Delay
            # =============================================
            #
            # Preferred mode for this project:
            # compare the candidate against the route that
            # would be followed right now if the new
            # passenger were NOT inserted.
            #
            # Both values are measured from the same
            # current taxi node, so real wall-clock waiting
            # cannot create artificial delay.
            # =============================================

            if baseline_simulation is not None:

                if (
                    group_key
                    not in (
                        baseline_simulation
                        .dropoff_eta_by_group
                    )
                ):
                    violations.append(
                        ConstraintViolation(
                            code=(
                                "EXISTING_BASELINE_DROPOFF_MISSING"
                            ),

                            group_key=group_key,

                            actual_value=None,

                            limit_value=None,

                            message=(
                                "Existing passenger has no "
                                "drop-off in the current "
                                "baseline route simulation."
                            ),
                        )
                    )

                    continue


                baseline_dropoff_minutes = (
                    baseline_simulation
                    .dropoff_eta_by_group[
                        group_key
                    ]
                )


                absolute_delay_minutes = max(
                    0.0,

                    float(
                        candidate_dropoff_minutes
                        - baseline_dropoff_minutes
                    ),
                )


            # =============================================
            # Legacy Wall-Clock Fallback
            # =============================================
            #
            # Kept only so direct/older callers of the
            # constraint service do not break.
            # SharedRouteRankingService now always provides
            # baseline_simulation.
            # =============================================

            else:

                candidate_dropoff_at = (
                    reference_time
                    + timedelta(
                        minutes=(
                            candidate_dropoff_minutes
                        )
                    )
                )


                delay_seconds = (
                    candidate_dropoff_at
                    - baseline
                    .baseline_expected_dropoff_at
                ).total_seconds()


                absolute_delay_minutes = max(
                    0.0,
                    delay_seconds / 60.0,
                )


            # =============================================
            # Relative Delay
            # =============================================

            direct_trip_time = (
                baseline
                .direct_trip_time_minutes
            )


            if direct_trip_time <= 0:
                raise SharedConstraintError(
                    (
                        "Existing passenger baseline "
                        "direct trip time must be positive."
                    )
                )


            relative_delay = (
                absolute_delay_minutes
                / direct_trip_time
            )


            delay_result = (
                ExistingPassengerDelay(
                    group_key=group_key,

                    candidate_dropoff_minutes=(
                        candidate_dropoff_minutes
                    ),

                    absolute_delay_minutes=(
                        absolute_delay_minutes
                    ),

                    relative_delay=(
                        relative_delay
                    ),
                )
            )


            delay_results[
                group_key
            ] = delay_result


            # =============================================
            # Absolute Delay Constraint
            # =============================================

            if (
                absolute_delay_minutes
                > max_absolute_delay
            ):
                violations.append(
                    ConstraintViolation(
                        code=(
                            "ABSOLUTE_DELAY_EXCEEDED"
                        ),

                        group_key=group_key,

                        actual_value=(
                            absolute_delay_minutes
                        ),

                        limit_value=(
                            max_absolute_delay
                        ),

                        message=(
                            "Existing passenger absolute "
                            "delay exceeds the allowed limit."
                        ),
                    )
                )


            # =============================================
            # Relative Delay Constraint
            # =============================================

            if (
                relative_delay
                > max_relative_delay
            ):
                violations.append(
                    ConstraintViolation(
                        code=(
                            "RELATIVE_DELAY_EXCEEDED"
                        ),

                        group_key=group_key,

                        actual_value=(
                            relative_delay
                        ),

                        limit_value=(
                            max_relative_delay
                        ),

                        message=(
                            "Existing passenger relative "
                            "delay exceeds the allowed limit."
                        ),
                    )
                )


        return (
            delay_results,
            violations,
        )


    # =====================================================
    # New Passenger Evaluation
    # =====================================================

    @staticmethod
    def _evaluate_new_passenger(
        *,
        simulation,
        new_group_key,
        new_direct_trip_time_minutes,
    ):
        """
        Passenger جدید باید:

        1. به موقع Pickup شود.
        2. Shared Trip بیش از حد طولانی نشود.
        """

        violations = []


        if new_direct_trip_time_minutes <= 0:
            raise SharedConstraintError(
                (
                    "New passenger direct trip time "
                    "must be positive."
                )
            )


        # =============================================
        # Pickup must exist
        # =============================================

        if (
            new_group_key
            not in simulation.pickup_eta_by_group
        ):
            violations.append(
                ConstraintViolation(
                    code="NEW_PASSENGER_PICKUP_MISSING",

                    group_key=new_group_key,

                    actual_value=None,

                    limit_value=None,

                    message=(
                        "New passenger pickup is missing "
                        "from candidate route."
                    ),
                )
            )

            return None, violations


        # =============================================
        # Dropoff must exist
        # =============================================

        if (
            new_group_key
            not in simulation.dropoff_eta_by_group
        ):
            violations.append(
                ConstraintViolation(
                    code="NEW_PASSENGER_DROPOFF_MISSING",

                    group_key=new_group_key,

                    actual_value=None,

                    limit_value=None,

                    message=(
                        "New passenger drop-off is missing "
                        "from candidate route."
                    ),
                )
            )

            return None, violations


        pickup_wait = (
            simulation
            .pickup_eta_by_group[
                new_group_key
            ]
        )


        dropoff_eta = (
            simulation
            .dropoff_eta_by_group[
                new_group_key
            ]
        )


        # =================================================
        # Shared In-Vehicle Time
        # =================================================

        shared_trip_time = (
            dropoff_eta
            - pickup_wait
        )


        if shared_trip_time < 0:
            raise SharedConstraintError(
                (
                    "New passenger drop-off ETA "
                    "cannot be before pickup ETA."
                )
            )


        # =================================================
        # Shared Detour
        # =================================================

        absolute_detour = max(
            0,
            shared_trip_time
            - new_direct_trip_time_minutes,
        )


        relative_detour = (
            absolute_detour
            / new_direct_trip_time_minutes
        )


        metrics = NewPassengerMetrics(
            group_key=new_group_key,

            pickup_wait_minutes=(
                pickup_wait
            ),

            shared_trip_time_minutes=(
                shared_trip_time
            ),

            direct_trip_time_minutes=(
                new_direct_trip_time_minutes
            ),

            absolute_detour_minutes=(
                absolute_detour
            ),

            relative_detour=(
                relative_detour
            ),
        )


        # =================================================
        # Pickup Wait Constraint
        # =================================================

        max_pickup_wait = (
            SharedConstraintEvaluationService
            ._max_pickup_wait()
        )


        if pickup_wait > max_pickup_wait:

            violations.append(
                ConstraintViolation(
                    code=(
                        "PICKUP_WAIT_EXCEEDED"
                    ),

                    group_key=(
                        new_group_key
                    ),

                    actual_value=float(
                        pickup_wait
                    ),

                    limit_value=float(
                        max_pickup_wait
                    ),

                    message=(
                        "New passenger pickup wait "
                        "exceeds the allowed limit."
                    ),
                )
            )


        # =================================================
        # Absolute Shared Detour
        # =================================================

        max_absolute_delay = (
            SharedConstraintEvaluationService
            ._max_absolute_delay()
        )


        if (
            absolute_detour
            > max_absolute_delay
        ):

            violations.append(
                ConstraintViolation(
                    code=(
                        "NEW_PASSENGER_ABSOLUTE_DETOUR_EXCEEDED"
                    ),

                    group_key=(
                        new_group_key
                    ),

                    actual_value=float(
                        absolute_detour
                    ),

                    limit_value=(
                        max_absolute_delay
                    ),

                    message=(
                        "New passenger absolute shared "
                        "detour exceeds the allowed limit."
                    ),
                )
            )


        # =================================================
        # Relative Shared Detour
        # =================================================

        max_relative_delay = (
            SharedConstraintEvaluationService
            ._max_relative_delay()
        )


        if (
            relative_detour
            > max_relative_delay
        ):

            violations.append(
                ConstraintViolation(
                    code=(
                        "NEW_PASSENGER_RELATIVE_DETOUR_EXCEEDED"
                    ),

                    group_key=(
                        new_group_key
                    ),

                    actual_value=(
                        relative_detour
                    ),

                    limit_value=(
                        max_relative_delay
                    ),

                    message=(
                        "New passenger relative shared "
                        "detour exceeds the allowed limit."
                    ),
                )
            )


        return metrics, violations


    # =====================================================
    # Final Candidate Evaluation
    # =====================================================

    @staticmethod
    def evaluate(
        *,
        simulation: RouteSimulationResult,
        existing_baselines,
        new_group_key,
        new_direct_trip_time_minutes,
        reference_time=None,
        baseline_simulation=None,
    ):
        """
        Structural Simulation Result را تبدیل به
        Final Feasibility Result می‌کند.

        ترتیب مهم:

        1. Structural validity
        2. Existing passenger protection
        3. New passenger protection
        4. Final feasibility
        """

        if reference_time is None:
            reference_time = timezone.now()


        violations = []


        # =================================================
        # 1. Simulation Must Already Be Valid
        # =================================================

        if not simulation.is_valid:

            for simulation_violation in (
                simulation.violations
            ):

                violations.append(
                    ConstraintViolation(
                        code=(
                            "SIMULATION_INVALID"
                        ),

                        group_key=None,

                        actual_value=None,

                        limit_value=None,

                        message=(
                            simulation_violation
                        ),
                    )
                )


            return ConstraintEvaluationResult(
                is_feasible=False,
                violations=violations,
            )


        # =================================================
        # 2. Existing Passengers
        # =================================================

        (
            existing_delays,
            existing_violations,
        ) = (
            SharedConstraintEvaluationService
            ._evaluate_existing_passengers(
                simulation=simulation,

                existing_baselines=(
                    existing_baselines
                ),

                reference_time=(
                    reference_time
                ),

                baseline_simulation=(
                    baseline_simulation
                ),
            )
        )


        violations.extend(
            existing_violations
        )


        # =================================================
        # 3. New Passenger
        # =================================================

        (
            new_metrics,
            new_violations,
        ) = (
            SharedConstraintEvaluationService
            ._evaluate_new_passenger(
                simulation=simulation,

                new_group_key=(
                    new_group_key
                ),

                new_direct_trip_time_minutes=(
                    new_direct_trip_time_minutes
                ),
            )
        )


        violations.extend(
            new_violations
        )


        # =================================================
        # 4. Final Result
        # =================================================

        return ConstraintEvaluationResult(
            is_feasible=(
                len(violations) == 0
            ),

            violations=(
                violations
            ),

            existing_passenger_delays=(
                existing_delays
            ),

            new_passenger_metrics=(
                new_metrics
            ),
        )