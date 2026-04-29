from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from .views import history

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('history/', history, name='history'),
    path('triage/', include(('triage.urls','triage'), namespace='triage')),
    path("derm/", include("derm.urls")),
    path('accounts/', include('accounts.urls')),
    path('admin/', admin.site.urls),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
