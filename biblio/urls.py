# biblio/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/<int:libro_id>/detalle/", views.detalle_libro, name="detalle_libro"),
    path("catalogo/<int:libro_id>/reservar/", views.reservar_libro, name="reservar_libro"),

    path("acerca-de/", views.acerca_de, name="acerca_de"),
    path("registro/", views.registro_cliente, name="registro_cliente"),
    path("login/", views.inicio_sesion_cliente, name="inicio_sesion_cliente"),
    path("pantalla_inicio_cliente/", views.pantalla_inicio_cliente, name="pantalla_inicio_cliente"),
    path("cerrar_sesion_cliente/", views.cerrar_sesion_cliente, name="cerrar_sesion_cliente"),
    path("reservas/", views.lista_reservas_clientes, name="lista_reservas_clientes"),
    path("cliente/reservas/<int:reserva_id>/cancelar/", views.cancelar_reserva, name="cancelar_reserva"),
]
