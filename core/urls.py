from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from biblio import views as biblio_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Público
    path("", include("biblio.urls")),

    # Seguridad (empleados)
    path('seguridad/', include('seguridad.urls')),
]

# STATIC Y MEDIA
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
