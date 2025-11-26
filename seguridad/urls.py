from django.urls import path
from . import views

urlpatterns = [
    path("inicio_sesion/empleado/", views.iniciar_sesion_empleado, name="inicio_sesion"),
    path("salir/", views.cerrar_sesion_empleado, name="cerrar_sesion"),

    path("pantalla_inicio/administrador/", views.panel_administrador, name="panel_administrador"),
    path("pantalla_inicio/bibliotecario/", views.panel_bibliotecario, name="panel_bibliotecario"),

    path("empleados/registrar/", views.registrar_empleado, name="registrar_empleado"),
    path("empleados/editar/<int:empleado_id>/", views.editar_empleado, name="editar_empleado"),
    path("empleados/inventario/", views.inventario, name="inventario"),
    path('empleados/recuperar-contrasena/', views.recuperar_contrasena_empleado, name='recuperar_contrasena_empleado'),

    # Gestión de préstamos
    path("prestamos/gestion/", views.gestion_prestamos, name="gestion_prestamos"),
    path("prestamos/registrar/", views.registrar_prestamo, name="registrar_prestamo"),
    path("prestamos/<int:prestamo_id>/devolver/", views.devolver_prestamo, name="devolver_prestamo"),
    path("prestamos/<int:prestamo_id>/renovar/", views.renovar_prestamo, name="renovar_prestamo"),
    path("reglas-prestamo/configuracion/", views.configurar_reglas_prestamo, name="configurar_reglas_prestamo"),

    # Gestión de clientes
    path("clientes/", views.gestion_clientes, name="gestion_clientes"),
    path("clientes/<int:cliente_id>/bloquear/", views.bloquear_cliente, name="bloquear_cliente"),
    path("clientes/<int:cliente_id>/desbloquear/", views.desbloquear_cliente, name="desbloquear_cliente"),

    #Ventas
    path("ventas/realizar/", views.realizar_venta, name="realizar_venta"),
    path("ventas/facturar/<int:solicitud_id>/", views.facturar_solicitud, name="facturar_solicitud"),
    path("ventas/historial/", views.historial_ventas, name="historial_ventas"),
    path("cliente/historial-compras/",views.historial_compras_cliente, name="historial_compras_cliente"),

    #Compras
    path("proveedores/", views.gestion_proveedores, name="gestion_proveedores"),
    path("compras/comprobante/<int:compra_id>/", views.comprobante_compra_pdf,name="comprobante_compra_pdf"),
    path("compras/", views.gestion_compras, name="gestion_compras"),
    path("compras/comprobante/<int:compra_id>/", views.comprobante_compra_pdf, name="comprobante_compra_pdf"),
]
