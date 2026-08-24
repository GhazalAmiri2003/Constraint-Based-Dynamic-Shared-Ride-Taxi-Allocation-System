import pytest

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import (
    PassengerProfile,
    UserProfile,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def passenger():
    # User احراز هویت‌شده
    user = User.objects.create_user(
        username="network_passenger",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    PassengerProfile.objects.create(
        user=user,
    )

    return user


def authenticate_client(api_client, user):
    token = Token.objects.create(
        user=user
    )

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.fixture
def network():
    # Nodeها
    n1 = RoadNode.objects.create(
        name="API_N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="API_N2",
        x=1,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="API_N3",
        x=2,
        y=0,
    )

    # N1 ↔ N2
    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=2,
        travel_time_minutes=4,
        is_bidirectional=True,
    )

    # N2 ↔ N3
    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=3,
        travel_time_minutes=5,
        is_bidirectional=True,
    )

    return n1, n2, n3


@pytest.mark.django_db
def test_authenticated_user_can_get_nodes(
    api_client,
    passenger,
    network,
):
    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/road-network/nodes/"
    )

    assert response.status_code == 200
    assert len(response.data) == 3

    assert response.data[0]["name"] == "API_N1"


@pytest.mark.django_db
def test_authenticated_user_can_get_edges(
    api_client,
    passenger,
    network,
):
    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/road-network/edges/"
    )

    assert response.status_code == 200
    assert len(response.data) == 2

    assert (
        response.data[0]["from_node_name"]
        == "API_N1"
    )

    assert (
        response.data[0]["to_node_name"]
        == "API_N2"
    )


@pytest.mark.django_db
def test_route_api_returns_fastest_route(
    api_client,
    passenger,
    network,
):
    authenticate_client(
        api_client,
        passenger,
    )

    n1, _, n3 = network

    response = api_client.get(
        "/api/road-network/route/",
        {
            "start": n1.id,
            "end": n3.id,
        },
    )

    assert response.status_code == 200

    assert [
        node["name"]
        for node in response.data["path"]
    ] == [
        "API_N1",
        "API_N2",
        "API_N3",
    ]

    assert (
        response.data["total_time_minutes"]
        == 9
    )

    assert (
        response.data["total_distance_km"]
        == 5
    )


@pytest.mark.django_db
def test_route_requires_start_and_end(
    api_client,
    passenger,
):
    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/road-network/route/"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_invalid_node_is_rejected(
    api_client,
    passenger,
    network,
):
    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/road-network/route/",
        {
            "start": 999999,
            "end": 888888,
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_unauthenticated_user_cannot_access_network(
    api_client,
):
    response = api_client.get(
        "/api/road-network/nodes/"
    )

    assert response.status_code == 401