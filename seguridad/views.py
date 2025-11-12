from functools import wraps
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import logout as auth_logout  
from django.utils import timezone

from biblio.models import Usuarios, Roles, Libros, Prestamos, Bitacora

# ---------- Helpers de sesión / roles ----------
def _usuario_autenticado(request):
    return request.session.get("id_usuario") is not None

def _obtener_rol_usuario(request):
    return request.session.get("rol_usuario")

def requerir_rol(*roles_permitidos):
    """Redirige a login si no hay sesión o si el rol no está permitido."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not _usuario_autenticado(request):
                return redirect("inicio_sesion")
            if _obtener_rol_usuario(request) not in roles_permitidos:
                return redirect("inicio_sesion")
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador

# ---------- Login / Logout (empleados/admin) ----------
def _redirigir_segun_rol(rol):
    if rol=="administrador":
        return redirect("panel_administrador")
    else :
        return redirect('panel_bibliotecario')
    
    

@csrf_protect
def iniciar_sesion_empleado(request):
    if _usuario_autenticado(request):
        rol_actual = _obtener_rol_usuario(request)
        if rol_actual == "administrador":
            return redirect("panel_administrador")
        else:
            return redirect("panel_bibliotecario")
    
    contexto = {"error": None}
    if request.method == "POST":
        correo = request.POST.get("email", "").strip()
        contrasena = request.POST.get("password", "")
        rol_formulario = request.POST.get("rol", "")
        recordar_sesion = request.POST.get("remember", "")

        if not correo or not contrasena or not rol_formulario:
            contexto["error"] = "Completa correo, contraseña y rol."
            return render(request, "seguridad/login_empleados.html", contexto)

        mapeo_roles = {
            "admin": "administrador",
            "bibliotecario": "bibliotecario"
        }
        rol_bd = mapeo_roles.get(rol_formulario)
        
        if not rol_bd:
            contexto["error"] = "Rol inválido."
            return render(request, "seguridad/login_empleados.html", contexto)

        try:
            usuario = Usuarios.objects.select_related("rol").get(
                email=correo, rol__nombre=rol_bd, estado="activo"
            )
        except Usuarios.DoesNotExist:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            return render(request, "seguridad/login_empleados.html", contexto)

        # Verificar contraseña
        contrasena_bd = usuario.clave or ""
        if contrasena_bd.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
            coincide = check_password(contrasena, contrasena_bd)
        else:
            coincide = (contrasena == contrasena_bd)

        if not coincide:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            return render(request, "seguridad/login_empleados.html", contexto)

        # Login exitoso
        request.session["id_usuario"] = usuario.id
        request.session["correo_usuario"] = usuario.email
        request.session["rol_usuario"] = usuario.rol.nombre
        request.session.set_expiry(60 * 60 * 24 * 14 if recordar_sesion == "on" else 0)

        if usuario.rol.nombre == "administrador":
            return redirect("panel_administrador")
        else:
            return redirect("panel_bibliotecario")

    return render(request, "seguridad/login_empleados.html", contexto)

def cerrar_sesion_empleado(request):
    request.session.flush()
    return redirect("inicio_sesion")

# ---------- Paneles ----------
@requerir_rol("administrador")
def panel_administrador(request):
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    total_libros = Libros.objects.count()
    
    empleados_activos = Usuarios.objects.filter(
        rol__nombre__in=["administrador", "bibliotecario"], 
        estado__iexact="activo"
    ).count()
    
    empleados = Usuarios.objects.select_related("rol").filter(
        rol__nombre__in=["administrador", "bibliotecario"]
    ).order_by("-fecha_creacion")

    contexto = {
        "usuario_actual": usuario_actual,
        "total_libros": total_libros,
        "ventas_mensuales": None,
        "empleados_activos": empleados_activos,
        "empleados": empleados,
    }
    return render(request, "seguridad/admin_home.html", contexto)

@requerir_rol("bibliotecario")
def panel_bibliotecario(request):
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    total_libros = Libros.objects.count()
    prestamos_activos = Prestamos.objects.filter(estado="activo").count()
    
    hoy = timezone.localdate()
    prestamos_vencidos = Prestamos.objects.filter(
        fecha_devolucion__isnull=True, 
        fecha_fin__lt=hoy
    ).count()

    contexto = {
        "usuario_actual": usuario_actual,
        "total_libros": total_libros,
        "prestamos_activos": prestamos_activos,
        "prestamos_vencidos": prestamos_vencidos,
    }
    return render(request, "seguridad/bibliotecario_home.html", contexto)


@requerir_rol("administrador")
@csrf_protect
def registrar_empleado(request):
    
    roles_disponibles = [
        {"nombre_formulario": "admin", "nombre_bd": "administrador", "nombre_mostrar": "Administrador"},
        {"nombre_formulario": "bibliotecario", "nombre_bd": "bibliotecario", "nombre_mostrar": "Bibliotecario"},
    ]
    
    contexto = {
        "exito": None, 
        "error": None,
        "roles": roles_disponibles,
        "usuario_actual": Usuarios.objects.get(id=request.session.get("id_usuario"))
    }

    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip().lower()
        apellido = request.POST.get("apellido", "").strip().lower()
        correo = request.POST.get("email", "").strip()
        contrasena = request.POST.get("clave", "")
        rol_formulario = request.POST.get("rol", "")
        estado = request.POST.get("estado", "activo")

        # Validaciones
        if not all([nombre, apellido, correo, contrasena, rol_formulario]):
            contexto["error"] = "Completa todos los campos obligatorios."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        if len(contrasena) < 8:
            contexto["error"] = "La contraseña debe tener al menos 8 caracteres."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        # Mapear rol formulario a base de datos
        mapeo_roles = {"admin": "administrador", "bibliotecario": "bibliotecario"}
        rol_bd = mapeo_roles.get(rol_formulario)
        
        if not rol_bd:
            contexto["error"] = "Rol inválido."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        try:
            objeto_rol = Roles.objects.get(nombre=rol_bd)
        except Roles.DoesNotExist:
            contexto["error"] = f"No existe el rol '{rol_bd}' en la base de datos."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        if Usuarios.objects.filter(email=correo).exists():
            contexto["error"] = "Ya existe un usuario con ese correo."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        # Crear el usuario
        try:
            Usuarios.objects.create(
                rol=objeto_rol,
                nombre=nombre,
                apellido=apellido,
                email=correo,
                clave=make_password(contrasena),
                estado=estado,
                fecha_creacion=timezone.localtime()
            )

            Bitacora.objects.create(
                usuario=contexto["usuario_actual"], 
                accion=f"REGISTRO EMPLEADO: {correo} como {rol_bd}",
                fecha=timezone.now()
            )

            contexto["exito"] = f"Empleado {nombre} {apellido} creado exitosamente."
        
            
        except Exception as error:
            contexto["error"] = f"Error al crear el usuario: {str(error)}"

    return render(request, "seguridad/registrar_empleados.html", contexto)

@requerir_rol("bibliotecario")

def inventario(request):

    usuario_actual = Usuarios.objects.select_related("rol").get(
    id=request.session.get("id_usuario"))

    
    contexto = {
        "usuario_actual": usuario_actual
    }


    return render(request, "seguridad/inventario.html", contexto)