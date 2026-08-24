import heapq

from .models import RoadEdge, RoadNode


class RoadNetworkError(Exception):
    # خطای مربوط به Routing
    pass


class RoadNetworkService:

    @staticmethod
    def _build_graph():
        """
        Graph را از RoadEdgeهای Database می‌سازد.
        Weight فعلاً travel time است.
        """

        graph = {}

        # همه Nodeها باید حتی بدون Edge داخل Graph باشند
        for node in RoadNode.objects.all():
            graph[node.id] = []

        # Edgeها را از Database می‌گیریم
        edges = RoadEdge.objects.select_related(
            "from_node",
            "to_node",
        ).all()

        for edge in edges:
            # جهت اصلی Edge
            graph[edge.from_node_id].append(
                (
                    edge.to_node_id,
                    edge.travel_time_minutes,
                )
            )

            # اگر دوطرفه باشد، جهت برگشت هم اضافه می‌شود
            if edge.is_bidirectional:
                graph[edge.to_node_id].append(
                    (
                        edge.from_node_id,
                        edge.travel_time_minutes,
                    )
                )

        return graph

    @staticmethod
    def shortest_path(start_node, end_node):
        """
        کوتاه‌ترین مسیر را بر اساس Travel Time پیدا می‌کند.
        خروجی: list از RoadNodeها
        """

        # مبدا و مقصد یکسان
        if start_node.id == end_node.id:
            return [start_node]

        graph = RoadNetworkService._build_graph()

        # Node باید در Network وجود داشته باشد
        if start_node.id not in graph or end_node.id not in graph:
            raise RoadNetworkError(
                "Start or destination node is not in the road network."
            )

        # Priority Queue:
        # (total_time, current_node_id, path)
        queue = [
            (
                0,
                start_node.id,
                [start_node.id],
            )
        ]

        # بهترین زمان شناخته‌شده برای هر Node
        best_time = {
            start_node.id: 0
        }

        while queue:
            total_time, current_id, path = heapq.heappop(
                queue
            )

            # به مقصد رسیدیم
            if current_id == end_node.id:
                return [
                    RoadNode.objects.get(id=node_id)
                    for node_id in path
                ]

            # مسیر قدیمی‌تر و بدتر را نادیده بگیر
            if total_time > best_time.get(
                current_id,
                float("inf"),
            ):
                continue

            # Neighborهای Node فعلی
            for neighbor_id, edge_time in graph[current_id]:
                new_time = total_time + edge_time

                # اگر مسیر بهتری پیدا شد
                if new_time < best_time.get(
                    neighbor_id,
                    float("inf"),
                ):
                    best_time[neighbor_id] = new_time

                    heapq.heappush(
                        queue,
                        (
                            new_time,
                            neighbor_id,
                            path + [neighbor_id],
                        ),
                    )

        # هیچ Routeای پیدا نشد
        raise RoadNetworkError(
            "No route exists between the selected nodes."
        )

    @staticmethod
    def get_edge(from_node, to_node):
        """
        Edge واقعی بین دو Node متوالی را پیدا می‌کند.
        """

        # اول جهت مستقیم
        edge = RoadEdge.objects.filter(
            from_node=from_node,
            to_node=to_node,
        ).first()

        if edge:
            return edge

        # جهت برگشت فقط اگر Edge دوطرفه باشد
        edge = RoadEdge.objects.filter(
            from_node=to_node,
            to_node=from_node,
            is_bidirectional=True,
        ).first()

        if edge:
            return edge

        raise RoadNetworkError(
            f"No edge exists between "
            f"{from_node.name} and {to_node.name}."
        )

    @staticmethod
    def route_time(path):
        """
        مجموع ETA مسیر را بر حسب دقیقه محاسبه می‌کند.
        """

        if len(path) <= 1:
            return 0

        total_time = 0

        # هر دو Node متوالی یک Edge می‌سازند
        for index in range(len(path) - 1):
            edge = RoadNetworkService.get_edge(
                path[index],
                path[index + 1],
            )

            total_time += edge.travel_time_minutes

        return total_time

    @staticmethod
    def route_distance(path):
        """
        مجموع فاصله مسیر را بر حسب km محاسبه می‌کند.
        """

        if len(path) <= 1:
            return 0.0

        total_distance = 0.0

        for index in range(len(path) - 1):
            edge = RoadNetworkService.get_edge(
                path[index],
                path[index + 1],
            )

            total_distance += edge.distance_km

        return total_distance