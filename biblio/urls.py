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
    path("cliente/cerrar-sesion/", views.cerrar_sesion_cliente, name="cerrar_sesion_cliente"),
    path("cliente/configuracion/", views.configuracion_cliente, name="configuracion_cliente"),
    path("cliente/prestamos/", views.historial_prestamos_cliente, name="historial_prestamos_cliente"),
    path("reservas/", views.lista_reservas_clientes, name="lista_reservas_clientes"),
    path("cliente/reservas/<int:reserva_id>/cancelar/", views.cancelar_reserva, name="cancelar_reserva"),
    path("reservas/<int:reserva_id>/solicitar-factura/", views.solicitar_factura_reserva, name="solicitar_factura_reserva"),
    path("libros/<int:libro_id>/solicitar-factura/", views.solicitar_factura_libro, name="solicitar_factura_libro"),

    path('clientes/recuperar-contrasena/', views.recuperar_contrasena_cliente, name="recuperar_contrasena_cliente"),
]
