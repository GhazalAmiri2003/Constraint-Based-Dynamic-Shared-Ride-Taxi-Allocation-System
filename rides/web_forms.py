from django import forms

from rides.models import RideRequest


class RideRequestForm(forms.ModelForm):

    class Meta:
        model = RideRequest

        fields = [
            "ride_type",
            "passenger_count",
            "pickup_node",
            "destination_node",
            "notes",
        ]

        widgets = {
            "ride_type": forms.Select(
                attrs={"class": "form-control"}
            ),

            "passenger_count": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "max": 4,
                }
            ),

            # Selected on the map; backend validation stays unchanged.
            "pickup_node": forms.HiddenInput(
                attrs={"id": "id_pickup_node"}
            ),

            "destination_node": forms.HiddenInput(
                attrs={"id": "id_destination_node"}
            ),

            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional notes",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        pickup = cleaned_data.get("pickup_node")
        destination = cleaned_data.get("destination_node")

        if pickup and destination and pickup == destination:
            raise forms.ValidationError(
                "Pickup and destination must be different."
            )

        return cleaned_data
