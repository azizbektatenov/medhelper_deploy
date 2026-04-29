from django.conf import settings
from django.db import models

class Consultation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    sex = models.CharField(max_length=10)
    age = models.PositiveIntegerField()
    symptoms = models.TextField()
    llm_answer = models.TextField(blank=True)   # ответ LLM
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consultation #{self.id} ({self.created_at:%Y-%m-%d})"
