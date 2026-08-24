from rest_framework import serializers

class TaxiOptionSerializer(
    serializers.Serializer
):
    rank = serializers.IntegerField()

    vehicle_id = serializers.IntegerField()
    driver_username = serializers.CharField()

    current_node_id = serializers.IntegerField()
    current_node_name = serializers.CharField()

    capacity = serializers.IntegerField()

    # Taxi → Pickup
    pickup_eta_minutes = serializers.IntegerField()
    pickup_distance_km = serializers.FloatField()

    pickup_path_node_ids = serializers.ListField(
        child=serializers.IntegerField()
    )

    # Pickup → Destination
    trip_eta_minutes = serializers.IntegerField()
    trip_distance_km = serializers.FloatField()

    trip_path_node_ids = serializers.ListField(
        child=serializers.IntegerField()
    )

    # Total
    total_eta_minutes = serializers.IntegerField()
    total_distance_km = serializers.FloatField()

    estimated_price = serializers.FloatField()
class TaxiSelectionSerializer(
    serializers.Serializer
):
    vehicle_id = serializers.IntegerField(
        min_value=1
    )