from django.contrib import admin

# Register your models here.
from .models import (
    Roles, Permisos, RolPermiso, Usuarios, Bitacora,
    Clientes, Libros, Ejemplares, ReglasPrestamo, 
    Prestamos, Reservas, CatalogoPublico
)

# Registrar TODOS los modelos
admin.site.register(Roles)
admin.site.register(Permisos)
admin.site.register(RolPermiso)
admin.site.register(Usuarios)
admin.site.register(Bitacora)
admin.site.register(Clientes)
admin.site.register(Libros)
admin.site.register(Ejemplares)
admin.site.register(ReglasPrestamo)
admin.site.register(Prestamos)
admin.site.register(Reservas)
admin.site.register(CatalogoPublico)