from django.urls import path
from . import views

urlpatterns = [
    path("inicio_sesion/empleado/", views.iniciar_sesion_empleado, name="inicio_sesion"),
    path("salir/", views.cerrar_sesion_empleado, name="cerrar_sesion"),
    path("pantalla_inicio/administrador/", views.panel_administrador, name="panel_administrador"),
    path("pantalla_inicio/bibliotecario/", views.panel_bibliotecario, name="panel_bibliotecario"),
    path("empleados/registrar/", views.registrar_empleado, name="registrar_empleado"),
    path("empleados/inventario/",views.inventario, name="inventario")
    
]
