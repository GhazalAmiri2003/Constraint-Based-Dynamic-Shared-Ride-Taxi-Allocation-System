from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    DriverRegistrationSerializer,
    PassengerRegistrationSerializer,
    UserSerializer,
)


class PassengerRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PassengerRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)

            return Response(
                {
                    "message": "Passenger registered successfully.",
                    "token": token.key,
                    "user": UserSerializer(user).data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class DriverRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DriverRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)

            return Response(
                {
                    "message": "Driver registered successfully.",
                    "token": token.key,
                    "user": UserSerializer(user).data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {
                    "detail": "Username and password are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(
            username=username,
            password=password,
        )

        if user is None:
            return Response(
                {
                    "detail": "Invalid username or password."
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "token": token.key,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            UserSerializer(request.user).data,
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.auth:
            request.auth.delete()

        return Response(
            {
                "message": "Logged out successfully."
            },
            status=status.HTTP_200_OK,
        )