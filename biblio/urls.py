from django.urls import path
from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("catalogo/", views.catalogo, name="catalogo"),
    
    path("acerca-de/", views.acerca_de, name="acerca_de"),

    path("nicio_sesion_cliente/cliente/", views.inicio_sesion_cliente, name="inicio_sesion_cliente"),
    path("registro/", views.registro_cliente, name="registro_cliente"),
    path('pantalla_inicio/cliente/', views.pantalla_inicio_cliente, name='pantalla_inicio_cliente'), 
    path('cerrar_sesion_client/cliente/', views.cerrar_sesion_cliente, name='cerrar_sesion_cliente'),

]
