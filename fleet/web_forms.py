from django import forms

from fleet.models import Vehicle


class VehicleRegistrationForm(forms.ModelForm):

    class Meta:
        model = Vehicle

        fields = [
            "capacity",
            "current_node",
        ]

        widgets = {
            "capacity": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "max": 4,
                }
            ),

            "current_node": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
        }