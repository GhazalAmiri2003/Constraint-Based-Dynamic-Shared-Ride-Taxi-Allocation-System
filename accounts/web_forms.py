from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class RegisterForm(UserCreationForm):

    ROLE_CHOICES = [
        ("PASSENGER", "Passenger"),
        ("DRIVER", "Driver"),
    ]

    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "Email",
            }
        ),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    class Meta:
        model = User

        fields = [
            "username",
            "email",
            "role",
            "password1",
            "password2",
        ]

        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Username",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["password1"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Password",
            }
        )

        self.fields["password2"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Confirm password",
            }
        )