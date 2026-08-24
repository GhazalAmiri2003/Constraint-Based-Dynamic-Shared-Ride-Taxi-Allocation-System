from django.core.management.base import BaseCommand
from django.db import transaction

from road_network.models import RoadEdge, RoadNode


class Command(BaseCommand):
    help = "Create the simulated road network."

    @transaction.atomic
    def handle(self, *args, **options):

        # -------------------------
        # 20 Road Nodes
        # -------------------------

        node_data = [
            ("N1", 0, 0),
            ("N2", 1, 0),
            ("N3", 2, 0),
            ("N4", 3, 0),
            ("N5", 4, 0),

            ("N6", 0, 1),
            ("N7", 1, 1),
            ("N8", 2, 1),
            ("N9", 3, 1),
            ("N10", 4, 1),

            ("N11", 0, 2),
            ("N12", 1, 2),
            ("N13", 2, 2),
            ("N14", 3, 2),
            ("N15", 4, 2),

            ("N16", 0, 3),
            ("N17", 1, 3),
            ("N18", 2, 3),
            ("N19", 3, 3),
            ("N20", 4, 3),
        ]

        nodes = {}

        # Nodeها را می‌سازیم یا Update می‌کنیم
        for name, x, y in node_data:
            node, _ = RoadNode.objects.update_or_create(
                name=name,
                defaults={
                    "x": x,
                    "y": y,
                },
            )

            nodes[name] = node

        # -------------------------
        # 33 Road Edges
        # -------------------------

        edge_data = [
            # Row 1
            ("N1", "N2", 1.0, 2, "MAIN"),
            ("N2", "N3", 1.0, 2, "LOCAL"),
            ("N3", "N4", 1.0, 2, "MAIN"),
            ("N4", "N5", 1.0, 2, "LOCAL"),

            # Row 2
            ("N6", "N7", 1.0, 2, "LOCAL"),
            ("N7", "N8", 1.0, 2, "MAIN"),
            ("N8", "N9", 1.0, 2, "MAIN"),
            ("N9", "N10", 1.0, 2, "LOCAL"),

            # Row 3
            ("N11", "N12", 1.0, 2, "LOCAL"),
            ("N12", "N13", 1.0, 2, "MAIN"),
            ("N13", "N14", 1.0, 2, "MAIN"),
            ("N14", "N15", 1.0, 2, "LOCAL"),

            # Row 4
            ("N16", "N17", 1.0, 2, "MAIN"),
            ("N17", "N18", 1.0, 2, "LOCAL"),
            ("N18", "N19", 1.0, 2, "MAIN"),
            ("N19", "N20", 1.0, 2, "LOCAL"),

            # Column 1
            ("N1", "N6", 1.2, 3, "LOCAL"),
            ("N6", "N11", 1.2, 3, "MAIN"),
            ("N11", "N16", 1.2, 3, "LOCAL"),

            # Column 2
            ("N2", "N7", 1.2, 3, "MAIN"),
            ("N7", "N12", 1.2, 3, "LOCAL"),
            ("N12", "N17", 1.2, 3, "MAIN"),

            # Column 3
            ("N3", "N8", 1.2, 3, "LOCAL"),
            ("N8", "N13", 1.2, 3, "MAIN"),
            ("N13", "N18", 1.2, 3, "LOCAL"),

            # Column 4
            ("N4", "N9", 1.2, 3, "MAIN"),
            ("N9", "N14", 1.2, 3, "LOCAL"),
            ("N14", "N19", 1.2, 3, "MAIN"),

            # Column 5
            ("N5", "N10", 1.2, 3, "LOCAL"),
            ("N10", "N15", 1.2, 3, "MAIN"),
            ("N15", "N20", 1.2, 3, "LOCAL"),

            # Faster cross-network roads
            ("N1", "N14", 4.2, 5, "HIGHWAY"),
            ("N7", "N20", 4.0, 5, "HIGHWAY"),
        ]

        desired_edges = {
            (from_name, to_name)
            for (
                from_name,
                to_name,
                _,
                _,
                _,
            ) in edge_data
        }

        network_names = set(nodes.keys())

        # Edgeهای قدیمی Development را پاک می‌کنیم
        existing_edges = RoadEdge.objects.filter(
            from_node__name__in=network_names,
            to_node__name__in=network_names,
        )

        for edge in existing_edges:
            key = (
                edge.from_node.name,
                edge.to_node.name,
            )

            if key not in desired_edges:
                edge.delete()

        # Edgeهای شبکه نهایی
        for (
            from_name,
            to_name,
            distance,
            travel_time,
            road_type,
        ) in edge_data:

            RoadEdge.objects.update_or_create(
                from_node=nodes[from_name],
                to_node=nodes[to_name],
                defaults={
                    "distance_km": distance,
                    "travel_time_minutes": travel_time,
                    "road_type": road_type,
                    "is_bidirectional": True,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Road network created: "
                "20 nodes and 33 edges."
            )
        )