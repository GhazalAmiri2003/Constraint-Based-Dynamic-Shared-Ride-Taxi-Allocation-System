from dataclasses import dataclass
from django.conf import settings
from shared_ride.models import RouteStop
from shared_ride.simulation import (
    RouteSimulationResult,
    SharedRouteSimulationService,
    SimulatedStop,
)


class SharedRouteInsertionError(Exception):
    # خطاهای Candidate Generation
    pass


# =========================================================
# Candidate Route
# =========================================================

@dataclass(frozen=True)
class InsertionCandidate:
    """
    یک ترتیب فرضی از Route Stops
    بعد از اضافه شدن Passenger جدید.
    """

    # Zero-based insertion indexes
    pickup_index: int
    dropoff_index: int

    # Full candidate route
    stops: tuple[SimulatedStop, ...]


    @property
    def pickup_position(self):
        """
        Human-readable position.
        از 1 شروع می‌شود.
        """

        return self.pickup_index + 1


    @property
    def dropoff_position(self):
        """
        Human-readable position.
        از 1 شروع می‌شود.
        """

        return self.dropoff_index + 1


# =========================================================
# Evaluated Candidate
# =========================================================

@dataclass(frozen=True)
class EvaluatedInsertionCandidate:
    """
    Candidate + نتیجه Simulation همان Candidate.
    """

    candidate: InsertionCandidate

    simulation: RouteSimulationResult


# =========================================================
# Dynamic Route Insertion Service
# =========================================================

class SharedRouteInsertionService:

    # =====================================================
    # Expected Candidate Count
    # =====================================================

    @staticmethod
    def expected_candidate_count(
        existing_stop_count,
    ):
        """
        برای k Stop موجود:

        (k + 1)(k + 2)
        ----------------
                2

        candidate معتبر برای insertion داریم.

        منظور از معتبر در اینجا فقط:
        Pickup position < Dropoff position

        است.

        Capacity / Delay / Reachability
        بعداً بررسی می‌شوند.
        """

        if existing_stop_count < 0:
            raise SharedRouteInsertionError(
                "Existing stop count cannot be negative."
            )

        return (
            (existing_stop_count + 1)
            * (existing_stop_count + 2)
            // 2
        )


    # =====================================================
    # Validate New Passenger Stop Pair
    # =====================================================

    @staticmethod
    def _validate_new_stop_pair(
        *,
        existing_stops,
        new_pickup,
        new_dropoff,
        initial_onboard,
    ):
        """
        Pickup و Dropoff Passenger جدید
        باید یک pair معتبر باشند.
        """

        # Pickup type
        if (
            new_pickup.stop_type
            != RouteStop.StopType.PICKUP
        ):
            raise SharedRouteInsertionError(
                "New pickup stop must have PICKUP type."
            )


        # Dropoff type
        if (
            new_dropoff.stop_type
            != RouteStop.StopType.DROPOFF
        ):
            raise SharedRouteInsertionError(
                "New drop-off stop must have DROPOFF type."
            )


        # Same passenger group
        if (
            new_pickup.group_key
            != new_dropoff.group_key
        ):
            raise SharedRouteInsertionError(
                "Pickup and drop-off must belong to the same passenger group."
            )


        if not new_pickup.group_key:
            raise SharedRouteInsertionError(
                "Passenger group key is required."
            )


        # Same passenger count
        if (
            new_pickup.passenger_count
            != new_dropoff.passenger_count
        ):
            raise SharedRouteInsertionError(
                "Pickup and drop-off passenger counts must match."
            )


        if new_pickup.passenger_count <= 0:
            raise SharedRouteInsertionError(
                "Passenger count must be positive."
            )


        # Nodes are required
        if (
            new_pickup.node is None
            or new_dropoff.node is None
        ):
            raise SharedRouteInsertionError(
                "Pickup and drop-off nodes are required."
            )


        new_group = (
            new_pickup.group_key
        )


        # ---------------------------------------------
        # New passenger must not already exist
        # in remaining route.
        # ---------------------------------------------

        existing_group_keys = {
            stop.group_key
            for stop in existing_stops
        }


        if new_group in existing_group_keys:
            raise SharedRouteInsertionError(
                "Passenger group already exists in the current route."
            )


        # ---------------------------------------------
        # New passenger must not already be onboard
        # ---------------------------------------------

        if new_group in initial_onboard:
            raise SharedRouteInsertionError(
                "Passenger group is already onboard."
            )


        # ---------------------------------------------
        # Maximum Active Passenger Groups
        # ---------------------------------------------

        active_existing_groups = (
            set(initial_onboard.keys())
            |
            {
                stop.group_key
                for stop in existing_stops
            }
        )


        max_groups = getattr(
            settings,
            "MAX_SHARED_PASSENGER_GROUPS",
            2,
        )


        # Taxi از قبل به حداکثر تعداد
        # Passenger Group رسیده است.
        #
        # حتی اگر Passenger جدید بعد از
        # Dropoff یکی از Groupها Pickup شود،
        # نباید سومین Active Assignment
        # به همان Shared Ride اضافه شود.
        if (
            len(active_existing_groups)
            >= max_groups
        ):
            raise SharedRouteInsertionError(
                (
                    "Shared taxi already has the "
                    "maximum number of active "
                    "passenger groups."
                )
            )


    # =====================================================
    # Generate All Valid Insertions
    # =====================================================

    @staticmethod
    def generate_candidates(
        *,
        existing_stops,
        new_pickup,
        new_dropoff,
        initial_onboard=None,
    ):
        """
        تمام insertionهای ممکن را تولید می‌کند.

        Existing stop order همیشه حفظ می‌شود.

        تنها شرط ordering در این مرحله:

            Pickup < Dropoff

        است.

        Constraintهای واقعی مثل:
        - capacity
        - passenger groups
        - reachability
        - delays

        در مرحله Simulation / Constraint Evaluation
        بررسی می‌شوند.
        """

        if initial_onboard is None:
            initial_onboard = {}


        # Caller list نباید تغییر کند.
        existing_stops = tuple(
            existing_stops
        )


        SharedRouteInsertionService._validate_new_stop_pair(
            existing_stops=existing_stops,
            new_pickup=new_pickup,
            new_dropoff=new_dropoff,
            initial_onboard=initial_onboard,
        )


        candidates = []


        existing_count = len(
            existing_stops
        )


        # =================================================
        # Pickup Position
        # =================================================

        for pickup_index in range(
            existing_count + 1
        ):

            # ابتدا Pickup را insert می‌کنیم.
            with_pickup = (
                existing_stops[
                    :pickup_index
                ]
                + (
                    new_pickup,
                )
                + existing_stops[
                    pickup_index:
                ]
            )


            # =============================================
            # Dropoff Position
            # =============================================

            # Dropoff باید حتماً بعد از Pickup باشد.
            for dropoff_index in range(
                pickup_index + 1,
                len(with_pickup) + 1,
            ):

                candidate_stops = (
                    with_pickup[
                        :dropoff_index
                    ]
                    + (
                        new_dropoff,
                    )
                    + with_pickup[
                        dropoff_index:
                    ]
                )


                candidates.append(
                    InsertionCandidate(
                        pickup_index=(
                            pickup_index
                        ),

                        dropoff_index=(
                            dropoff_index
                        ),

                        stops=(
                            candidate_stops
                        ),
                    )
                )


        # Defensive assertion:
        # generator باید دقیقاً تعداد تئوری
        # candidateها را تولید کند.
        expected_count = (
            SharedRouteInsertionService
            .expected_candidate_count(
                existing_count
            )
        )


        if len(candidates) != expected_count:
            raise SharedRouteInsertionError(
                (
                    "Generated candidate count "
                    "does not match expected count."
                )
            )


        return candidates


    # =====================================================
    # Simulate Every Candidate
    # =====================================================

    @staticmethod
    def evaluate_candidates(
        *,
        current_node,
        vehicle_capacity,
        existing_stops,
        new_pickup,
        new_dropoff,
        initial_onboard=None,
    ):
        """
        تمام Candidateها را تولید می‌کند
        و تک‌تک آن‌ها را Simulation می‌کند.

        هنوز Delay constraints اینجا بررسی نمی‌شوند.

        بنابراین simulation.is_valid یعنی:

        Structural + Operational validity

        مثل:
        - graph reachability
        - capacity
        - max passenger groups
        - pickup/dropoff ordering
        - passenger state
        """

        if initial_onboard is None:
            initial_onboard = {}


        candidates = (
            SharedRouteInsertionService
            .generate_candidates(
                existing_stops=existing_stops,
                new_pickup=new_pickup,
                new_dropoff=new_dropoff,
                initial_onboard=initial_onboard,
            )
        )


        evaluated_candidates = []


        for candidate in candidates:

            simulation = (
                SharedRouteSimulationService
                .simulate(
                    current_node=current_node,

                    vehicle_capacity=(
                        vehicle_capacity
                    ),

                    stops=(
                        candidate.stops
                    ),

                    initial_onboard=(
                        initial_onboard
                    ),
                )
            )


            evaluated_candidates.append(
                EvaluatedInsertionCandidate(
                    candidate=candidate,
                    simulation=simulation,
                )
            )


        return evaluated_candidates


    # =====================================================
    # Structurally Valid Candidates
    # =====================================================

    @staticmethod
    def get_structurally_valid_candidates(
        *,
        current_node,
        vehicle_capacity,
        existing_stops,
        new_pickup,
        new_dropoff,
        initial_onboard=None,
    ):
        """
        فقط Candidateهایی را برمی‌گرداند
        که Simulation Engine رد نکرده باشد.

        توجه:
        این‌ها هنوز Final Feasible Route نیستند.

        Delay constraints در مرحله بعد
        بررسی خواهند شد.
        """

        evaluated_candidates = (
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


        return [
            evaluated
            for evaluated
            in evaluated_candidates
            if evaluated.simulation.is_valid
        ]