from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    SEX_CHOICES = [
        ("мужской", "Мужской"),
        ("женский", "Женский"),
        ("не указан", "Предпочитаю не указывать"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)

    full_name = models.CharField("Имя / как к вам обращаться", max_length=150, blank=True)

    sex = models.CharField("Пол", max_length=20, choices=SEX_CHOICES, blank=True)
    age = models.PositiveIntegerField("Возраст", null=True, blank=True)
    height_cm = models.PositiveIntegerField("Рост (см)", null=True, blank=True)
    weight_kg = models.FloatField("Вес (кг)", null=True, blank=True)

    chronic = models.TextField("Хронические заболевания", blank=True)
    allergies = models.TextField("Аллергии", blank=True)
    meds = models.TextField("Постоянные препараты", blank=True)

    contraindications = models.TextField(
        "Противопоказания к лекарствам",
        blank=True,
        help_text="Например: НПВС противопоказаны, аллергия на пенициллин и т.д."
    )

    smoker = models.BooleanField("Курение", default=False)
    pregnant = models.BooleanField("Беременность", default=False)  # игнорируй для мужчин

    def __str__(self):
        return f"Профиль {self.user.username}"

    @property
    def bmi(self):
        """ИМТ, если есть рост и вес."""
        if self.height_cm and self.weight_kg:
            h = self.height_cm / 100
            return round(self.weight_kg / (h * h), 1)
        return None
