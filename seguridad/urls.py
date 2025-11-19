from django.urls import path
from . import views

urlpatterns = [
    # 1. Ruta principal del catálogo con búsqueda y filtro
    path('catalogo/', views.catalogo_view, name='catalogo_url'), 
    
    # 2. Ruta para ver los detalles del libro ('Ver Ficha')
    path('libro/<int:pk>/', views.ficha_libro, name='ficha_libro'),
    
    # 3. Ruta para procesar la reserva (POST)
    path('reservar/<int:libro_pk>/', views.solicitar_reserva, name='solicitar_reserva'), 
    
    # ¡NUEVA RUTA! 4. Listado de Reservas del Cliente
    path('mis-reservas/', views.listado_reservas_view, name='listado_reservas'), 
]