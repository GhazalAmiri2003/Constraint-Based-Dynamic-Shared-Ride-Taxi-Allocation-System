from dataclasses import dataclass, field

from django.conf import settings

from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.models import RouteStop


# =========================================================
# Simulation Input
# =========================================================

@dataclass(frozen=True)
class SimulatedStop:
    """
    یک Stop فرضی برای Simulation.

    group_key:
        شناسه منطقی Passenger Group.
        مثال:
        "rp:5"
        "request:12"
    """

    group_key: str
    passenger_count: int
    node: object
    stop_type: str


# =========================================================
# Result of One Stop
# =========================================================

@dataclass(frozen=True)
class SimulatedStopResult:

    sequence_number: int

    group_key: str

    node_id: int

    stop_type: str

    # چند دقیقه از Current Taxi Position
    # تا این Stop
    arrival_minutes: int

    # Occupancy بعد از اجرای Stop
    occupancy_after_stop: int

    # تعداد Passenger Groupهای داخل Taxi
    active_groups_after_stop: int

    # مسیر segment قبلی → این Stop
    segment_path_node_ids: list[int]

    segment_time_minutes: int

    segment_distance_km: float


# =========================================================
# Complete Simulation Result
# =========================================================

@dataclass
class RouteSimulationResult:

    is_valid: bool

    total_time_minutes: int

    total_distance_km: float

    stop_results: list[SimulatedStopResult] = field(
        default_factory=list
    )

    violations: list[str] = field(
        default_factory=list
    )

    pickup_eta_by_group: dict[str, int] = field(
        default_factory=dict
    )

    dropoff_eta_by_group: dict[str, int] = field(
        default_factory=dict
    )

    peak_occupancy: int = 0

    peak_active_groups: int = 0

# =========================================================
# Route Simulation Engine
# =========================================================

class SharedRouteSimulationService:

    # =====================================================
    # Simulate Candidate Route
    # =====================================================

    @staticmethod
    def simulate(
        *,
        current_node,
        vehicle_capacity,
        stops,
        initial_onboard=None,
    ):
        """
        یک candidate stop sequence را از موقعیت
        فعلی Taxi شبیه‌سازی می‌کند.

        هیچ Database write انجام نمی‌دهد.

        initial_onboard مثال:

        {
            "rp:7": 2
        }

        یعنی Passenger Group شماره 7
        قبلاً Pickup شده و 2 نفر داخل Taxi هستند.
        """

        if current_node is None:
            raise ValueError(
                "Taxi current node is required."
            )


        if vehicle_capacity <= 0:
            raise ValueError(
                "Vehicle capacity must be positive."
            )


        if initial_onboard is None:
            initial_onboard = {}


        # Copy:
        # caller state نباید تغییر کند.
        onboard = dict(
            initial_onboard
        )


        violations = []

        stop_results = []

        pickup_eta_by_group = {}

        dropoff_eta_by_group = {}


        # =================================================
        # Validate Initial Passenger State
        # =================================================

        for group_key, count in onboard.items():

            if count <= 0:
                violations.append(
                    (
                        "INVALID_PASSENGER_COUNT:"
                        f"{group_key}"
                    )
                )


        current_occupancy = sum(
            onboard.values()
        )


        max_groups = getattr(
            settings,
            "MAX_SHARED_PASSENGER_GROUPS",
            2,
        )


        # Taxi از همان ابتدا نباید Over Capacity باشد.
        if (
            current_occupancy
            > vehicle_capacity
        ):
            violations.append(
                "INITIAL_CAPACITY_EXCEEDED"
            )


        if len(onboard) > max_groups:
            violations.append(
                "INITIAL_GROUP_LIMIT_EXCEEDED"
            )


        # اگر Initial State خراب است،
        # ادامه Simulation معنی ندارد.
        if violations:
            return RouteSimulationResult(
                is_valid=False,
                total_time_minutes=0,
                total_distance_km=0.0,
                violations=violations,
                peak_occupancy=current_occupancy,
                peak_active_groups=len(onboard),
            )


        # =================================================
        # Runtime State
        # =================================================

        current_position = current_node

        cumulative_time = 0

        cumulative_distance = 0.0

        peak_occupancy = (
            current_occupancy
        )

        peak_active_groups = (
            len(onboard)
        )


        # برای تشخیص Duplicate Pickup
        picked_groups = set(
            onboard.keys()
        )


        # برای تشخیص Duplicate Dropoff
        dropped_groups = set()


        # =================================================
        # Simulate Every Stop
        # =================================================

        for sequence_number, stop in enumerate(
            stops,
            start=1,
        ):

            # ---------------------------------------------
            # Basic Stop Validation
            # ---------------------------------------------

            if stop.passenger_count <= 0:

                violations.append(
                    (
                        "INVALID_PASSENGER_COUNT:"
                        f"{stop.group_key}"
                    )
                )

                break


            if stop.stop_type not in {
                RouteStop.StopType.PICKUP,
                RouteStop.StopType.DROPOFF,
            }:

                violations.append(
                    (
                        "INVALID_STOP_TYPE:"
                        f"{stop.group_key}"
                    )
                )

                break


            # ---------------------------------------------
            # Graph Route:
            # Previous Position → Stop
            # ---------------------------------------------

            try:
                segment_path = (
                    RoadNetworkService
                    .shortest_path(
                        current_position,
                        stop.node,
                    )
                )

            except RoadNetworkError:

                violations.append(
                    (
                        "UNREACHABLE_STOP:"
                        f"{stop.group_key}:"
                        f"{stop.node.id}"
                    )
                )

                # وقتی Stop unreachable باشد،
                # ETA Stopهای بعدی هم قابل محاسبه نیست.
                break


            segment_time = (
                RoadNetworkService
                .route_time(
                    segment_path
                )
            )


            segment_distance = (
                RoadNetworkService
                .route_distance(
                    segment_path
                )
            )


            cumulative_time += (
                segment_time
            )

            cumulative_distance += (
                segment_distance
            )


            segment_path_node_ids = [
                node.id
                for node in segment_path
            ]


            # =============================================
            # PICKUP
            # =============================================

            if (
                stop.stop_type
                == RouteStop.StopType.PICKUP
            ):

                # Pickup دوباره ممنوع
                if (
                    stop.group_key
                    in picked_groups
                ):

                    violations.append(
                        (
                            "DUPLICATE_PICKUP:"
                            f"{stop.group_key}"
                        )
                    )

                    break


                # Passenger قبلاً Dropoff شده؟
                if (
                    stop.group_key
                    in dropped_groups
                ):

                    violations.append(
                        (
                            "PICKUP_AFTER_DROPOFF:"
                            f"{stop.group_key}"
                        )
                    )

                    break


                # Passenger وارد Taxi می‌شود.
                onboard[
                    stop.group_key
                ] = stop.passenger_count


                picked_groups.add(
                    stop.group_key
                )


                current_occupancy += (
                    stop.passenger_count
                )


                pickup_eta_by_group[
                    stop.group_key
                ] = cumulative_time


                # -----------------------------------------
                # Capacity Constraint
                # -----------------------------------------

                if (
                    current_occupancy
                    > vehicle_capacity
                ):

                    violations.append(
                        (
                            "CAPACITY_EXCEEDED:"
                            f"{stop.group_key}"
                        )
                    )


                # -----------------------------------------
                # Maximum Active Groups
                # -----------------------------------------

                if len(onboard) > max_groups:

                    violations.append(
                        (
                            "PASSENGER_GROUP_LIMIT_EXCEEDED:"
                            f"{stop.group_key}"
                        )
                    )


            # =============================================
            # DROPOFF
            # =============================================

            else:

                # Passenger باید واقعاً داخل Taxi باشد.
                #
                # این Rule هم:
                # pickup-before-dropoff
                # و هم duplicate dropoff را پوشش می‌دهد.
                if (
                    stop.group_key
                    not in onboard
                ):

                    if (
                        stop.group_key
                        in dropped_groups
                    ):

                        violations.append(
                            (
                                "DUPLICATE_DROPOFF:"
                                f"{stop.group_key}"
                            )
                        )

                    else:

                        violations.append(
                            (
                                "DROPOFF_BEFORE_PICKUP:"
                                f"{stop.group_key}"
                            )
                        )

                    break


                onboard_count = (
                    onboard[
                        stop.group_key
                    ]
                )


                # Count موجود در Stop باید با
                # Passenger Group واقعی یکسان باشد.
                if (
                    onboard_count
                    != stop.passenger_count
                ):

                    violations.append(
                        (
                            "PASSENGER_COUNT_MISMATCH:"
                            f"{stop.group_key}"
                        )
                    )

                    break


                current_occupancy -= (
                    onboard_count
                )


                del onboard[
                    stop.group_key
                ]


                dropped_groups.add(
                    stop.group_key
                )


                dropoff_eta_by_group[
                    stop.group_key
                ] = cumulative_time


            # =============================================
            # State Safety
            # =============================================

            if current_occupancy < 0:

                violations.append(
                    "NEGATIVE_OCCUPANCY"
                )


            # Peak values برای Debug / Ranking / Report
            peak_occupancy = max(
                peak_occupancy,
                current_occupancy,
            )


            peak_active_groups = max(
                peak_active_groups,
                len(onboard),
            )


            # =============================================
            # Store Stop Result
            # =============================================

            stop_results.append(
                SimulatedStopResult(
                    sequence_number=(
                        sequence_number
                    ),

                    group_key=(
                        stop.group_key
                    ),

                    node_id=(
                        stop.node.id
                    ),

                    stop_type=(
                        stop.stop_type
                    ),

                    arrival_minutes=(
                        cumulative_time
                    ),

                    occupancy_after_stop=(
                        current_occupancy
                    ),

                    active_groups_after_stop=(
                        len(onboard)
                    ),

                    segment_path_node_ids=(
                        segment_path_node_ids
                    ),

                    segment_time_minutes=(
                        segment_time
                    ),

                    segment_distance_km=float(
                        segment_distance
                    ),
                )
            )


            # اگر این Stop constraint را شکسته،
            # ادامه Route لازم نیست.
            if violations:
                break


            # موقعیت Taxi برای segment بعدی
            current_position = (
                stop.node
            )


        # =================================================
        # Complete Route Validation
        # =================================================

        if not violations:

            # در پایان Candidate کامل،
            # هیچ Passenger Group نباید
            # بدون Dropoff باقی مانده باشد.
            if onboard:

                for group_key in onboard:

                    violations.append(
                        (
                            "MISSING_DROPOFF:"
                            f"{group_key}"
                        )
                    )


        # =================================================
        # Final Result
        # =================================================

        return RouteSimulationResult(
            is_valid=(
                len(violations) == 0
            ),

            total_time_minutes=(
                cumulative_time
            ),

            total_distance_km=float(
                cumulative_distance
            ),

            stop_results=(
                stop_results
            ),

            violations=(
                violations
            ),

            pickup_eta_by_group=(
                pickup_eta_by_group
            ),

            dropoff_eta_by_group=(
                dropoff_eta_by_group
            ),

            peak_occupancy=(
                peak_occupancy
            ),

            peak_active_groups=(
                peak_active_groups
            ),
        )