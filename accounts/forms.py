from django import forms
from .models import UserProfile


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "full_name",
            "sex",
            "age",
            "height_cm",
            "weight_kg",
            "smoker",
            "pregnant",
            "chronic",
            "allergies",
            "meds",
            "contraindications",
        ]
        widgets = {
            "chronic": forms.Textarea(attrs={"rows": 2}),
            "allergies": forms.Textarea(attrs={"rows": 2}),
            "meds": forms.Textarea(attrs={"rows": 2}),
            "contraindications": forms.Textarea(attrs={"rows": 2}),
        }
