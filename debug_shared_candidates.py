import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.utils import timezone

from assignment.shared_services import SharedTaxiOptionService
from fleet.models import Vehicle
from rides.models import RideRequest


def show_request(request_id):
    request = (
        RideRequest.objects
        .select_related(
            "pickup_node",
            "destination_node",
        )
        .get(pk=request_id)
    )

    print("\n" + "=" * 70)
    print(
        f"REQUEST #{request.id} "
        f"pickup={request.pickup_node_id} "
        f"destination={request.destination_node_id} "
        f"count={request.passenger_count} "
        f"status={request.status}"
    )

    if (
        request.status != RideRequest.Status.PENDING
        or request.ride_type != RideRequest.RideType.SHARED
    ):
        print("Not a pending SHARED request.")
        return

    direct = SharedTaxiOptionService._calculate_direct_trip(
        request
    )

    if direct is None:
        print("Direct passenger route is unreachable.")
        return

    print(
        f"Direct trip: "
        f"{direct['travel_time']} min, "
        f"{direct['distance']:.2f} km"
    )

    now = timezone.now()

    for vehicle in (
        Vehicle.objects
        .select_related(
            "driver__user",
            "current_node",
        )
        .order_by("id")
    ):
        print("\n--- VEHICLE", vehicle.id, "---")
        print(
            "driver=",
            vehicle.driver.user.username,
            "| status=",
            vehicle.driver.availability_status,
            "| mode=",
            vehicle.ride_mode,
            "| available=",
            vehicle.is_available,
            "| capacity=",
            vehicle.capacity,
            "| current_node=",
            vehicle.current_node_id,
        )

        if (
            vehicle.driver.availability_status != "ONLINE"
            or not vehicle.is_available
            or vehicle.current_node_id is None
            or vehicle.capacity < request.passenger_count
            or vehicle.ride_mode not in {"IDLE", "SHARED"}
        ):
            print("FILTERED BEFORE SHARED INSERTION.")
            continue

        if vehicle.ride_mode == "SHARED":
            state = (
                SharedTaxiOptionService
                ._load_shared_route_state(
                    vehicle
                )
            )

            if state is None:
                print(
                    "REJECTED: shared vehicle state "
                    "could not be loaded."
                )
                continue

            print(
                "Shared route:",
                state["route"].id,
                "revision=",
                state["route"].revision,
            )
            print(
                "Existing future stops:",
                [
                    (
                        stop.group_key,
                        stop.stop_type,
                        stop.node.id,
                    )
                    for stop
                    in state["existing_stops"]
                ],
            )
            print(
                "Initial onboard:",
                state["initial_onboard"],
            )
            print(
                "Existing baselines:",
                {
                    key: {
                        "direct_trip_time_minutes":
                            baseline.direct_trip_time_minutes,
                        "baseline_expected_dropoff_at":
                            str(
                                baseline
                                .baseline_expected_dropoff_at
                            ),
                        "baseline_route_revision":
                            baseline.baseline_route_revision,
                    }
                    for key, baseline
                    in state[
                        "existing_baselines"
                    ].items()
                },
            )

        option = (
            SharedTaxiOptionService
            ._evaluate_vehicle(
                vehicle=vehicle,
                ride_request=request,
                direct_trip=direct,
                reference_time=now,
            )
        )

        if option is None:
            print(
                "RESULT: REJECTED INSIDE "
                "INSERTION / SIMULATION / CONSTRAINTS / RANKING"
            )
            continue

        print("RESULT: FEASIBLE ✅")
        print(
            "pickup_eta=",
            option.pickup_eta_minutes,
            "| destination_eta=",
            option.estimated_destination_arrival_minutes,
            "| shared_delay=",
            option.expected_shared_delay_minutes,
            "| total_passenger_delay=",
            option.total_passenger_delay_minutes,
        )
        print(
            "route=",
            [
                (
                    stop.sequence_number,
                    stop.group_key,
                    stop.stop_type,
                    stop.node_id,
                    stop.estimated_arrival_minutes,
                )
                for stop
                in option.proposed_route
            ],
        )


pending_ids = list(
    RideRequest.objects
    .filter(
        status=RideRequest.Status.PENDING,
        ride_type=RideRequest.RideType.SHARED,
    )
    .order_by("id")
    .values_list("id", flat=True)
)

print("Pending shared request IDs:", pending_ids)

for request_id in pending_ids:
    show_request(request_id)