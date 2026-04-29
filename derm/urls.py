from django.urls import path
from .views import derm_form, derm_history, derm_detail, derm_delete


app_name = 'derm'

urlpatterns = [
    path('', derm_form, name='derm_form'),
    path('history/', derm_history, name='derm_history'),
    path('<int:pk>/', derm_detail, name='derm_detail'),
    path('<int:pk>/delete/', derm_delete, name='derm_delete'),
]
