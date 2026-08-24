import pytest

from road_network.models import RoadEdge, RoadNode
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)


@pytest.fixture
def network():
    # Nodeهای شبکه تست
    n1 = RoadNode.objects.create(
        name="N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="N2",
        x=1,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="N3",
        x=1,
        y=1,
    )

    n4 = RoadNode.objects.create(
        name="N4",
        x=0,
        y=1,
    )

    # N1 ↔ N2
    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=2,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    # N2 ↔ N3
    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=1.5,
        travel_time_minutes=3,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    # N3 ↔ N4
    RoadEdge.objects.create(
        from_node=n3,
        to_node=n4,
        distance_km=2,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    # N1 ↔ N4 مستقیم
    RoadEdge.objects.create(
        from_node=n1,
        to_node=n4,
        distance_km=5,
        travel_time_minutes=8,
        road_type=RoadEdge.RoadType.HIGHWAY,
        is_bidirectional=True,
    )

    return n1, n2, n3, n4


@pytest.mark.django_db
def test_shortest_path_selects_fastest_route(network):
    n1, _, _, n4 = network

    path = RoadNetworkService.shortest_path(
        n1,
        n4,
    )

    assert [node.name for node in path] == [
        "N1",
        "N4",
    ]

    assert RoadNetworkService.route_time(path) == 8
    assert RoadNetworkService.route_distance(path) == 5


@pytest.mark.django_db
def test_shortest_path_can_use_multiple_edges(network):
    _, n2, _, n4 = network

    path = RoadNetworkService.shortest_path(
        n2,
        n4,
    )

    assert [node.name for node in path] == [
        "N2",
        "N3",
        "N4",
    ]

    assert RoadNetworkService.route_time(path) == 7
    assert RoadNetworkService.route_distance(path) == 3.5


@pytest.mark.django_db
def test_bidirectional_edge_allows_reverse_travel(network):
    n1, _, _, n4 = network

    path = RoadNetworkService.shortest_path(
        n4,
        n1,
    )

    assert [node.name for node in path] == [
        "N4",
        "N1",
    ]

    assert RoadNetworkService.route_time(path) == 8


@pytest.mark.django_db
def test_same_start_and_destination_returns_single_node(network):
    n1, _, _, _ = network

    path = RoadNetworkService.shortest_path(
        n1,
        n1,
    )

    assert path == [n1]

    assert RoadNetworkService.route_time(path) == 0
    assert RoadNetworkService.route_distance(path) == 0


@pytest.mark.django_db
def test_no_route_raises_error():
    n1 = RoadNode.objects.create(
        name="N1",
        x=0,
        y=0,
    )

    isolated = RoadNode.objects.create(
        name="ISOLATED",
        x=10,
        y=10,
    )

    with pytest.raises(RoadNetworkError):
        RoadNetworkService.shortest_path(
            n1,
            isolated,
        )