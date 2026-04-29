# derm/models.py
from django.conf import settings
from django.db import models


class DermCase(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    image = models.ImageField(upload_to="derm/")
    result_label = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 🔥 сюда кладём ответ LLM один раз
    treatment_plan = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"DermCase #{self.id} {self.result_label or ''}"
