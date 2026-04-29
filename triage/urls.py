from django.urls import path
from .views import triage_form, triage_history, triage_detail, triage_delete

app_name = "triage"

urlpatterns = [
    path("", triage_form, name="triage_form"),
    path("history/", triage_history, name="triage_history"),
    path("<int:pk>/", triage_detail, name="triage_detail"),
    path("<int:pk>/delete/", triage_delete, name="triage_delete"),
]
