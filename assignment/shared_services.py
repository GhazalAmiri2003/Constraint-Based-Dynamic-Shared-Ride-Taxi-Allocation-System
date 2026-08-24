from dataclasses import dataclass

from django.utils import timezone

from accounts.models import DriverProfile
from assignment.models import TaxiHold
from fleet.models import Vehicle
from pricing.services import PricingService
from rides.models import (
    Ride,
    RideRequest,
)
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.insertion import (
    SharedRouteInsertionError,
)
from shared_ride.models import (
    Route,
    RouteStop,
    SharedPassengerBaseline,
)
from shared_ride.ranking import (
    SharedRouteRankingError,
    SharedRouteRankingService,
)
from shared_ride.simulation import (
    SimulatedStop,
)


# =========================================================
# Error
# =========================================================

class SharedTaxiOptionError(Exception):
    pass


# =========================================================
# Proposed Route Stop
# =========================================================

@dataclass(frozen=True)
class ProposedRouteStop:

    sequence_number: int

    group_key: str

    passenger_count: int

    node_id: int

    node_name: str

    stop_type: str

    estimated_arrival_minutes: int

# =========================================================
# Shared Taxi Option
# =========================================================

@dataclass
class SharedTaxiOption:

    rank: int

    # Taxi
    vehicle_id: int

    driver_username: str

    vehicle_mode: str

    current_node_id: int

    current_node_name: str

    capacity: int

    # Passenger
    pickup_eta_minutes: int

    estimated_destination_arrival_minutes: int

    estimated_trip_duration_minutes: int

    # Shared impact
    expected_shared_delay_minutes: float

    total_passenger_delay_minutes: float

    available_seats_at_pickup: int

    # Route impact
    additional_route_time_minutes: int

    route_extension_km: float

    # Price
    estimated_price: float

    # Proposed future stop order
    proposed_route: tuple[
        ProposedRouteStop,
        ...
    ]

    # Used later for stale-route detection
    source_route_id: int | None

    source_route_revision: int | None

    route_total_time_minutes: int

    route_total_distance_km: float


# =========================================================
# Shared Taxi Option Service
# =========================================================

class SharedTaxiOptionService:

    # =====================================================
    # New Passenger Group Key
    # =====================================================

    @staticmethod
    def _new_group_key(
        ride_request,
    ):
        """
        RidePassenger هنوز ساخته نشده است.

        بنابراین قبل از confirmation از
        RideRequest ID به عنوان temporary
        group identifier استفاده می‌کنیم.
        """

        return (
            f"request:{ride_request.id}"
        )


    # =====================================================
    # Existing RidePassenger Group Key
    # =====================================================

    @staticmethod
    def _ride_passenger_group_key(
        ride_passenger_id,
    ):
        return (
            f"rp:{ride_passenger_id}"
        )


    # =====================================================
    # Passenger Direct Route
    # =====================================================

    @staticmethod
    def _calculate_direct_trip(
        ride_request,
    ):
        """
        Direct passenger route:

        Pickup → Destination

        برای:
        - direct trip time
        - direct distance
        - estimated price
        """

        try:
            path = (
                RoadNetworkService
                .shortest_path(
                    ride_request.pickup_node,
                    ride_request.destination_node,
                )
            )

        except RoadNetworkError:
            return None


        travel_time = (
            RoadNetworkService
            .route_time(
                path
            )
        )


        distance = (
            RoadNetworkService
            .route_distance(
                path
            )
        )


        if travel_time <= 0:
            return None


        # Proposal فرمول تخفیف مخصوص Shared
        # تعریف نکرده است.
        #
        # پس فعلاً همان standard distance/time
        # estimator موجود را روی مسیر مستقیم
        # Passenger استفاده می‌کنیم.
        estimated_price = (
            PricingService
            .calculate_private_price(
                distance_km=distance,

                travel_time_minutes=(
                    travel_time
                ),
            )
        )


        return {
            "path": path,

            "travel_time": (
                travel_time
            ),

            "distance": (
                distance
            ),

            "estimated_price": (
                estimated_price
            ),
        }


    # =====================================================
    # Find Active Shared Ride
    # =====================================================

    @staticmethod
    def _get_active_shared_ride(
        vehicle,
    ):
        """
        Shared Vehicle باید دقیقاً یک
        active Shared Ride داشته باشد.
        """

        rides = list(
            Ride.objects
            .filter(
                vehicle=vehicle,

                ride_type=(
                    RideRequest
                    .RideType
                    .SHARED
                ),

                status__in=[
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,
                    Ride.Status.IN_PROGRESS,
                ],
            )
            .order_by("-id")[:2]
        )


        if len(rides) != 1:
            return None


        return rides[0]


    # =====================================================
    # Load Current Shared Route State
    # =====================================================

    @staticmethod
    def _load_shared_route_state(
        vehicle,
    ):
        """
        Database Route state را به input
        موردنیاز Pure Simulation Engine
        تبدیل می‌کند.
        """

        ride = (
            SharedTaxiOptionService
            ._get_active_shared_ride(
                vehicle
            )
        )


        if ride is None:
            return None


        route = (
            Route.objects
            .filter(
                ride=ride,
                status=Route.Status.ACTIVE,
            )
            .first()
        )


        if route is None:
            return None


        all_stops = list(
            RouteStop.objects
            .filter(
                route=route
            )
            .exclude(
                status=(
                    RouteStop
                    .Status
                    .CANCELLED
                )
            )
            .select_related(
                "node",
                "ride_passenger",
                "ride_passenger__ride_request",
            )
            .order_by(
                "sequence_number"
            )
        )


        # =============================================
        # Pending Future Stops
        # =============================================

        pending_stops = [
            stop

            for stop
            in all_stops

            if (
                stop.status
                == RouteStop.Status.PENDING
            )
        ]


        # =============================================
        # Groups With Pending Dropoff
        # =============================================

        pending_dropoff_ids = {
            stop.ride_passenger_id

            for stop
            in pending_stops

            if (
                stop.stop_type
                == RouteStop.StopType.DROPOFF
            )
        }


        # =============================================
        # Completed Pickups
        # Passenger Already Onboard
        # =============================================

        completed_pickup_ids = {
            stop.ride_passenger_id

            for stop
            in all_stops

            if (
                stop.stop_type
                == RouteStop.StopType.PICKUP

                and stop.status
                == RouteStop.Status.COMPLETED
            )
        }


        onboard_ids = (
            completed_pickup_ids
            &
            pending_dropoff_ids
        )


        initial_onboard = {}


        # =============================================
        # Existing Simulated Stops
        # =============================================

        existing_stops = []


        for stop in pending_stops:

            ride_request = (
                stop
                .ride_passenger
                .ride_request
            )


            group_key = (
                SharedTaxiOptionService
                ._ride_passenger_group_key(
                    stop.ride_passenger_id
                )
            )


            existing_stops.append(
                SimulatedStop(
                    group_key=group_key,

                    passenger_count=(
                        ride_request
                        .passenger_count
                    ),

                    node=stop.node,

                    stop_type=(
                        stop.stop_type
                    ),
                )
            )


        # =============================================
        # Initial Onboard State
        # =============================================

        passenger_count_by_id = {}


        for stop in all_stops:

            passenger_count_by_id[
                stop.ride_passenger_id
            ] = (
                stop
                .ride_passenger
                .ride_request
                .passenger_count
            )


        for ride_passenger_id in (
            onboard_ids
        ):

            group_key = (
                SharedTaxiOptionService
                ._ride_passenger_group_key(
                    ride_passenger_id
                )
            )


            initial_onboard[
                group_key
            ] = (
                passenger_count_by_id[
                    ride_passenger_id
                ]
            )


        # =============================================
        # Active Existing Groups
        # =============================================

        active_ride_passenger_ids = {
            stop.ride_passenger_id
            for stop
            in pending_stops
        }


        # =============================================
        # Baselines
        # =============================================

        baseline_objects = (
            SharedPassengerBaseline.objects
            .filter(
                ride_passenger_id__in=(
                    active_ride_passenger_ids
                )
            )
        )


        existing_baselines = {
            (
                SharedTaxiOptionService
                ._ride_passenger_group_key(
                    baseline.ride_passenger_id
                )
            ):
                baseline

            for baseline
            in baseline_objects
        }


        return {
            "ride": ride,

            "route": route,

            "existing_stops": tuple(
                existing_stops
            ),

            "initial_onboard": (
                initial_onboard
            ),

            "existing_baselines": (
                existing_baselines
            ),
        }


    # =====================================================
    # Evaluate One Vehicle
    # =====================================================

    @staticmethod
    def _evaluate_vehicle(
        *,
        vehicle,
        ride_request,
        direct_trip,
        reference_time,
    ):
        """
        IDLE:
            empty route

        SHARED:
            load existing Route
            and run insertion engine
        """

        new_group_key = (
            SharedTaxiOptionService
            ._new_group_key(
                ride_request
            )
        )


        new_pickup = SimulatedStop(
            group_key=new_group_key,

            passenger_count=(
                ride_request
                .passenger_count
            ),

            node=(
                ride_request
                .pickup_node
            ),

            stop_type=(
                RouteStop
                .StopType
                .PICKUP
            ),
        )


        new_dropoff = SimulatedStop(
            group_key=new_group_key,

            passenger_count=(
                ride_request
                .passenger_count
            ),

            node=(
                ride_request
                .destination_node
            ),

            stop_type=(
                RouteStop
                .StopType
                .DROPOFF
            ),
        )


        # =================================================
        # IDLE Taxi
        # =================================================

        if (
            vehicle.ride_mode
            == Vehicle.RideMode.IDLE
        ):

            existing_stops = ()

            initial_onboard = {}

            existing_baselines = {}

            source_route = None


        # =================================================
        # Existing SHARED Taxi
        # =================================================

        elif (
            vehicle.ride_mode
            == Vehicle.RideMode.SHARED
        ):

            state = (
                SharedTaxiOptionService
                ._load_shared_route_state(
                    vehicle
                )
            )


            if state is None:
                return None


            existing_stops = (
                state[
                    "existing_stops"
                ]
            )

            initial_onboard = (
                state[
                    "initial_onboard"
                ]
            )

            existing_baselines = (
                state[
                    "existing_baselines"
                ]
            )

            source_route = (
                state[
                    "route"
                ]
            )


        # =================================================
        # PRIVATE / Invalid Mode
        # =================================================

        else:
            return None


        # =================================================
        # Complete Shared Route Algorithm
        # =================================================

        try:
            selection = (
                SharedRouteRankingService
                .evaluate_and_rank(
                    current_node=(
                        vehicle.current_node
                    ),

                    vehicle_capacity=(
                        vehicle.capacity
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

                    existing_baselines=(
                        existing_baselines
                    ),

                    new_direct_trip_time_minutes=(
                        direct_trip[
                            "travel_time"
                        ]
                    ),

                    initial_onboard=(
                        initial_onboard
                    ),

                    reference_time=(
                        reference_time
                    ),
                )
            )

        except (
            SharedRouteInsertionError,
            SharedRouteRankingError,
            ValueError,
        ):
            return None


        best_route = (
            selection.best_route
        )


        # No feasible insertion
        if best_route is None:
            return None


        new_metrics = (
            best_route
            .constraints
            .new_passenger_metrics
        )


        if new_metrics is None:
            return None


        # =================================================
        # Find New Passenger Pickup Result
        # =================================================

        pickup_result = next(
            (
                result

                for result
                in best_route
                .simulation
                .stop_results

                if (
                    result.group_key
                    == new_group_key

                    and result.stop_type
                    == RouteStop.StopType.PICKUP
                )
            ),
            None,
        )


        if pickup_result is None:
            return None


        # =================================================
        # Available Seats At New Pickup
        # =================================================

        available_seats_at_pickup = (
            vehicle.capacity
            - pickup_result
            .occupancy_after_stop
        )


        # =================================================
        # Proposed Route
        # =================================================

        proposed_route = tuple(
            ProposedRouteStop(
                sequence_number=index,

                group_key=stop.group_key,

                passenger_count=(
                    stop.passenger_count
                ),

                node_id=(
                    stop.node.id
                ),

                node_name=(
                    stop.node.name
                ),

                stop_type=(
                    stop.stop_type
                ),

                estimated_arrival_minutes=(
                    stop_result
                    .arrival_minutes
                ),
            )

            for index, (
                stop,
                stop_result,
            ) in enumerate(
                zip(
                    best_route
                    .candidate
                    .stops,

                    best_route
                    .simulation
                    .stop_results,
                ),
                start=1,
            )
        )


        dropoff_eta = (
            best_route
            .simulation
            .dropoff_eta_by_group[
                new_group_key
            ]
        )


        return SharedTaxiOption(
            rank=0,

            # Taxi
            vehicle_id=(
                vehicle.id
            ),

            driver_username=(
                vehicle
                .driver
                .user
                .username
            ),

            vehicle_mode=(
                vehicle.ride_mode
            ),

            current_node_id=(
                vehicle.current_node_id
            ),

            current_node_name=(
                vehicle.current_node.name
            ),

            capacity=(
                vehicle.capacity
            ),

            # ETA
            pickup_eta_minutes=(
                new_metrics
                .pickup_wait_minutes
            ),

            estimated_destination_arrival_minutes=(
                dropoff_eta
            ),

            estimated_trip_duration_minutes=(
                new_metrics
                .shared_trip_time_minutes
            ),

            # Delay
            expected_shared_delay_minutes=float(
                new_metrics
                .absolute_detour_minutes
            ),

            total_passenger_delay_minutes=float(
                best_route
                .metrics
                .total_passenger_delay_minutes
            ),

            available_seats_at_pickup=(
                available_seats_at_pickup
            ),

            # Route impact
            additional_route_time_minutes=(
                best_route
                .metrics
                .additional_travel_time_minutes
            ),

            route_extension_km=float(
                best_route
                .metrics
                .route_extension_km
            ),

            # Complete proposed route metrics
            route_total_time_minutes=(
                best_route
                .simulation
                .total_time_minutes
            ),

            route_total_distance_km=float(
                best_route
                .simulation
                .total_distance_km
            ),



            # Price
            estimated_price=float(
                direct_trip[
                    "estimated_price"
                ]
            ),

            proposed_route=(
                proposed_route
            ),

            source_route_id=(
                source_route.id
                if source_route
                else None
            ),

            source_route_revision=(
                source_route.revision
                if source_route
                else None
            ),
        )


    # =====================================================
    # Taxi Option Ranking
    # =====================================================

    @staticmethod
    def _taxi_option_ranking_key(
        option,
    ):
        """
        Feasibility already passed.

        Across taxis we prefer:

        1. Lower total passenger disruption
        2. Lower pickup ETA
        3. Lower additional route time
        4. Lower route extension
        5. Lower vehicle ID
        """

        return (
            option
            .total_passenger_delay_minutes,

            option
            .pickup_eta_minutes,

            option
            .additional_route_time_minutes,

            option
            .route_extension_km,

            option
            .vehicle_id,
        )


    # =====================================================
    # Generate Shared Taxi Options
    # =====================================================

    @staticmethod
    def generate_shared_taxi_options(
        ride_request,
        reference_time=None,
    ):
        """
        Complete Shared Taxi Candidate Workflow.

        1. Validate request
        2. Calculate direct passenger trip
        3. Find operational taxis
        4. Exclude held/private taxis
        5. Evaluate IDLE taxis
        6. Evaluate SHARED taxis through insertion engine
        7. Keep feasible taxis only
        8. Rank feasible options
        """

        # =================================================
        # 1. RideRequest Validation
        # =================================================

        if (
            ride_request.status
            != RideRequest.Status.PENDING
        ):
            raise SharedTaxiOptionError(
                (
                    "Only pending ride requests "
                    "can generate shared taxi options."
                )
            )


        if (
            ride_request.ride_type
            != RideRequest.RideType.SHARED
        ):
            raise SharedTaxiOptionError(
                (
                    "This method only supports "
                    "shared ride requests."
                )
            )


        if reference_time is None:
            reference_time = (
                timezone.now()
            )


        # =================================================
        # 2. Passenger Direct Route
        # =================================================

        direct_trip = (
            SharedTaxiOptionService
            ._calculate_direct_trip(
                ride_request
            )
        )


        if direct_trip is None:
            return []


        # =================================================
        # 3. Expire Old Holds
        # =================================================

        TaxiHold.objects.filter(
            status=TaxiHold.Status.ACTIVE,

            expires_at__lte=(
                reference_time
            ),
        ).update(
            status=(
                TaxiHold.Status.EXPIRED
            ),

            updated_at=(
                reference_time
            ),
        )


        # =================================================
        # 4. Vehicles With Active Hold
        # =================================================

        held_vehicle_ids = (
            TaxiHold.objects
            .filter(
                status=TaxiHold.Status.ACTIVE,

                expires_at__gt=(
                    reference_time
                ),
            )
            .values_list(
                "vehicle_id",
                flat=True,
            )
        )


        # =================================================
        # 5. Operational Candidate Set
        # =================================================

        candidate_vehicles = (
            Vehicle.objects
            .select_related(
                "driver",
                "driver__user",
                "current_node",
            )
            .filter(
                driver__availability_status=(
                    DriverProfile
                    .AvailabilityStatus
                    .ONLINE
                ),

                is_available=True,

                current_node__isnull=False,

                # Basic capacity check.
                # Dynamic capacity is checked again
                # inside Route Simulation.
                capacity__gte=(
                    ride_request
                    .passenger_count
                ),

                # PRIVATE is explicitly excluded.
                ride_mode__in=[
                    Vehicle.RideMode.IDLE,
                    Vehicle.RideMode.SHARED,
                ],
            )
            .exclude(
                id__in=(
                    held_vehicle_ids
                )
            )
        )


        feasible_options = []


        # =================================================
        # 6. Evaluate Every Taxi
        # =================================================

        for vehicle in (
            candidate_vehicles
        ):

            option = (
                SharedTaxiOptionService
                ._evaluate_vehicle(
                    vehicle=vehicle,

                    ride_request=(
                        ride_request
                    ),

                    direct_trip=(
                        direct_trip
                    ),

                    reference_time=(
                        reference_time
                    ),
                )
            )


            if option is not None:
                feasible_options.append(
                    option
                )


        # =================================================
        # 7. Rank Feasible Taxis ONLY
        # =================================================

        feasible_options.sort(
            key=(
                SharedTaxiOptionService
                ._taxi_option_ranking_key
            )
        )


        # =================================================
        # 8. Assign Final Rank
        # =================================================

        for rank, option in enumerate(
            feasible_options,
            start=1,
        ):
            option.rank = rank


        return feasible_options