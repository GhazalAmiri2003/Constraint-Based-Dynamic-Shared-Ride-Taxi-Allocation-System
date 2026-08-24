from django.db import models




from django.core.validators import MinValueValidator
from django.db import models


class RoadNode(models.Model):
    # نام یکتای Node
    name = models.CharField(
        max_length=100,
        unique=True,
    )

    # مختصات شبیه‌سازی
    x = models.FloatField()
    y = models.FloatField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.name


class RoadEdge(models.Model):

    class RoadType(models.TextChoices):
        # خیابان محلی
        LOCAL = "LOCAL", "Local"

        # خیابان اصلی
        MAIN = "MAIN", "Main"

        # مسیر سریع
        HIGHWAY = "HIGHWAY", "Highway"

    # Node شروع Edge
    from_node = models.ForeignKey(
        RoadNode,
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
    )

    # Node پایان Edge
    to_node = models.ForeignKey(
        RoadNode,
        on_delete=models.CASCADE,
        related_name="incoming_edges",
    )

    # فاصله ثابت Edge بر حسب km
    distance_km = models.FloatField(
        validators=[
            MinValueValidator(0.01),
        ]
    )

    # ETA ثابت Edge بر حسب دقیقه
    travel_time_minutes = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1),
        ]
    )

    # نوع جاده
    road_type = models.CharField(
        max_length=10,
        choices=RoadType.choices,
        default=RoadType.LOCAL,
    )

    # امکان حرکت در هر دو جهت
    is_bidirectional = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                # Edge نمی‌تواند Node را به خودش وصل کند
                condition=~models.Q(
                    from_node=models.F("to_node")
                ),
                name="road_edge_nodes_must_be_different",
            ),

            models.CheckConstraint(
                # فاصله باید مثبت باشد
                condition=models.Q(
                    distance_km__gt=0
                ),
                name="road_edge_distance_positive",
            ),

            models.CheckConstraint(
                # زمان باید مثبت باشد
                condition=models.Q(
                    travel_time_minutes__gt=0
                ),
                name="road_edge_time_positive",
            ),

            models.UniqueConstraint(
                # Edge تکراری در یک جهت ممنوع
                fields=[
                    "from_node",
                    "to_node",
                ],
                name="unique_road_edge_direction",
            ),
        ]

    def __str__(self):
        return (
            f"{self.from_node.name} -> "
            f"{self.to_node.name}"
        )