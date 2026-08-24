from rest_framework import serializers

from .models import RoadEdge, RoadNode


class RoadNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoadNode

        fields = (
            "id",
            "name",
            "x",
            "y",
        )

        read_only_fields = fields


class RoadEdgeSerializer(serializers.ModelSerializer):
    # نام Nodeها برای Frontend
    from_node_name = serializers.CharField(
        source="from_node.name",
        read_only=True,
    )

    to_node_name = serializers.CharField(
        source="to_node.name",
        read_only=True,
    )

    class Meta:
        model = RoadEdge

        fields = (
            "id",
            "from_node",
            "from_node_name",
            "to_node",
            "to_node_name",
            "distance_km",
            "travel_time_minutes",
            "road_type",
            "is_bidirectional",
        )

        read_only_fields = fields