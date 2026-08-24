import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from assignment.models import TaxiHold
from fleet.models import Vehicle
from rides.models import Ride, RideRequest
from shared_ride.models import Route, RouteStop


print("\n=== VEHICLES ===")
for row in Vehicle.objects.values(
    "id",
    "ride_mode",
    "is_available",
    "current_node_id",
    "driver__availability_status",
).order_by("id"):
    print(row)


print("\n=== ACTIVE RIDES ===")
for row in Ride.objects.filter(
    status__in=[
        "ASSIGNED",
        "ACCEPTED",
        "IN_PROGRESS",
    ]
).values(
    "id",
    "vehicle_id",
    "ride_type",
    "status",
).order_by("id"):
    print(row)


print("\n=== ACTIVE ROUTES ===")
for row in Route.objects.filter(
    status="ACTIVE"
).values(
    "id",
    "ride_id",
    "ride__vehicle_id",
    "revision",
    "status",
).order_by("id"):
    print(row)


print("\n=== PENDING STOPS ===")
for row in RouteStop.objects.filter(
    status="PENDING"
).values(
    "id",
    "route_id",
    "route__ride_id",
    "route__ride__vehicle_id",
    "ride_passenger__ride_request_id",
    "stop_type",
    "node_id",
    "sequence_number",
).order_by(
    "route_id",
    "sequence_number",
):
    print(row)


print("\n=== ACTIVE HOLDS ===")
for row in TaxiHold.objects.filter(
    status="ACTIVE"
).values(
    "id",
    "ride_request_id",
    "vehicle_id",
    "status",
    "expires_at",
).order_by("id"):
    print(row)


print("\n=== PENDING SHARED REQUESTS ===")
for row in RideRequest.objects.filter(
    status="PENDING",
    ride_type="SHARED",
).values(
    "id",
    "passenger_id",
    "pickup_node_id",
    "destination_node_id",
    "passenger_count",
).order_by("id"):
    print(row)


print("\n=== SHARED VEHICLE ROUTE SUMMARY ===")
for vehicle in Vehicle.objects.filter(
    ride_mode="SHARED"
).select_related(
    "driver__user",
    "current_node",
).order_by("id"):

    print(
        f"\nVehicle #{vehicle.id}",
        f"driver={vehicle.driver.user.username}",
        f"available={vehicle.is_available}",
        f"node={vehicle.current_node_id}",
        f"driver_status={vehicle.driver.availability_status}",
    )

    rides = Ride.objects.filter(
        vehicle=vehicle,
        ride_type="SHARED",
        status__in=[
            "ASSIGNED",
            "ACCEPTED",
            "IN_PROGRESS",
        ],
    ).order_by("-id")

    print("  active shared rides:", list(
        rides.values_list(
            "id",
            "status",
        )
    ))

    for ride in rides:
        routes = Route.objects.filter(
            ride=ride,
            status="ACTIVE",
        )

        print(
            f"  ride #{ride.id} active routes:",
            list(
                routes.values_list(
                    "id",
                    "revision",
                )
            ),
        )

        for route in routes:
            print(
                "   stops:",
                list(
                    RouteStop.objects.filter(
                        route=route
                    ).values_list(
                        "id",
                        "ride_passenger__ride_request_id",
                        "stop_type",
                        "node_id",
                        "status",
                        "sequence_number",
                    ).order_by(
                        "sequence_number"
                    )
                ),
            )