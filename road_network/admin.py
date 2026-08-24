from django.contrib import admin

from .models import RoadEdge, RoadNode


@admin.register(RoadNode)
class RoadNodeAdmin(admin.ModelAdmin):
    # اطلاعات اصلی Node
    list_display = (
        "id",
        "name",
        "x",
        "y",
    )

    # جستجو با نام Node
    search_fields = (
        "name",
    )


@admin.register(RoadEdge)
class RoadEdgeAdmin(admin.ModelAdmin):
    # اطلاعات اصلی Edge
    list_display = (
        "id",
        "from_node",
        "to_node",
        "distance_km",
        "travel_time_minutes",
        "road_type",
        "is_bidirectional",
    )

    # Filterهای Admin
    list_filter = (
        "road_type",
        "is_bidirectional",
    )

    # جستجو با نام Nodeها
    search_fields = (
        "from_node__name",
        "to_node__name",
    )