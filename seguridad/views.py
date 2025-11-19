from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import logout as auth_logout  
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator

from biblio.models import Usuarios, Roles, Libros, Prestamos, Bitacora, Libros, Reservas

# ---------- Helpers de sesión / roles ----------
def _usuario_autenticado(request):
    return request.session.get("id_usuario") is not None

def _obtener_rol_usuario(request):
    return request.session.get("rol_usuario")


# ESTA FUNCIÓN ES LA QUE FALTA O NO ESTÁ EN EL LUGAR CORRECTO
def requerir_cliente(vista):
    """Redirige a login si no hay sesión activa."""
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not _usuario_autenticado(request):
            messages.error(request, "Necesitas iniciar sesión como cliente para realizar esta acción.")
            # Asegúrate de que 'inicio_sesion' es la URL de login de tus clientes
            return redirect("inicio_sesion") 
        return vista(request, *args, **kwargs)
    return envoltura


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
    # Usuario logueado
    usuario_actual = Usuarios.objects.select_related("rol").get(
        id=request.session.get("id_usuario")
    )

    # Búsqueda
    query = request.GET.get('q', '').strip()
    if query:
        libros_qs = (
            Libros.objects.filter(titulo__icontains=query) |
            Libros.objects.filter(autor__icontains=query) |
            Libros.objects.filter(isbn__icontains=query) |
            Libros.objects.filter(categoria__icontains=query)
        ).distinct().order_by('autor','titulo')
    else:
        libros_qs = Libros.objects.all().order_by('titulo')

    # Paginación: 5 libros por página
    paginator = Paginator(libros_qs, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # POST: agregar libro
    if request.method == 'POST' and 'agregar_libro' in request.POST:
        try:
            anio_publicacion = str(request.POST.get('anio_publicacion'))

            portada_file = request.FILES.get('portada')  # puede venir vacío

            libro = Libros(
                isbn=request.POST.get('isbn'),
                titulo=request.POST.get('titulo'),
                autor=request.POST.get('autor'),
                categoria=request.POST.get('categoria'),
                editorial=request.POST.get('editorial'),
                anio_publicacion=anio_publicacion,
                stock_total=request.POST.get('stock', 0),
                portada=portada_file,            # archivo de imagen
                fecha_registro=timezone.now(),   # fecha automática
            )
            libro.save()
            messages.success(request, 'Libro agregado correctamente')
            return redirect('inventario')

        except Exception as e:
            messages.error(request, f'Error al agregar el libro: {str(e)}')
            return redirect('inventario')

    # POST: editar libro
    if request.method == 'POST' and 'editar_libro' in request.POST:
        try:
            libro_id = request.POST.get('libro_id')
            libro = get_object_or_404(Libros, id=libro_id)

            anio_publicacion = str(request.POST.get('anio_publicacion'))

            libro.isbn = request.POST.get('isbn')
            libro.titulo = request.POST.get('titulo')
            libro.autor = request.POST.get('autor')
            libro.categoria = request.POST.get('categoria')
            libro.editorial = request.POST.get('editorial')
            libro.anio_publicacion = anio_publicacion
            libro.stock_total = request.POST.get('stock', 0)

            # Si viene una nueva portada, la reemplazamos
            portada_file = request.FILES.get('portada')
            if portada_file:
                libro.portada = portada_file

            libro.save()

            Bitacora.objects.create(
                usuario=usuario_actual, 
                accion=f"EDITO EL LIBRO: '{libro.titulo}'",
                fecha=timezone.now()
            )

            messages.success(request, 'Libro actualizado correctamente')
            return redirect('inventario')

        except Exception as e:
            messages.error(request, f'Error al actualizar el libro: {str(e)}')
            return redirect('inventario')

    contexto = {
        "usuario_actual": usuario_actual,
        "page_obj": page_obj,
        "query": query,
    }

    return render(request, "seguridad/inventario.html", contexto)


# ---------- LÓGICA DE RESERVAS (CORREGIDA) ----------

@requerir_cliente # Usamos el decorador para forzar la sesión de cliente
@csrf_protect
def solicitar_reserva(request, libro_pk):
    # La view ahora exige POST Y protección CSRF
    if request.method == 'POST':
        # Obtener el objeto Usuarios usando la ID de sesión
        try:
            cliente = Usuarios.objects.get(id=request.session.get("id_usuario"))
        except Usuarios.DoesNotExist:
            messages.error(request, "Error de sesión. Por favor, vuelve a iniciar sesión.")
            return redirect("inicio_sesion")

        libro = get_object_or_404(Libros, id=libro_pk)
        
        # Validación de disponibilidad
        if libro.stock_disponible > 0:
            messages.warning(request, f'El libro "{libro.titulo}" está disponible y no requiere reserva.')
            return redirect('ficha_libro', pk=libro_pk)
            
        # 1. CRITERIO: Prevenir reservas duplicadas
        # Asumo que tu modelo Reservas tiene los campos 'cliente' (Foreign Key a Usuarios) y 'estado'
        if Reservas.objects.filter(cliente=cliente, libro=libro, estado='pendiente').exists():
            messages.info(request, f'Ya tienes una reserva pendiente para el libro "{libro.titulo}".')
            return redirect('ficha_libro', pk=libro_pk)

        # 2. Crear la Reserva (asumo 'estado'='pendiente' por defecto en el modelo)
        Reservas.objects.create(
            cliente=cliente, 
            libro=libro,
            fecha_reserva=timezone.now(),
            estado='pendiente' # Asegúrate que tu modelo acepte este valor
        )
        
        # Redirigir al listado de reservas del cliente (la nueva vista)
        messages.success(request, f'¡Reserva del libro "{libro.titulo}" creada con éxito! Estás en la lista de espera.')
        return redirect('listado_reservas') # Redirige al nuevo listado de reservas

    # Si llega un GET, lo tratamos como error (debería ser POST)
    messages.error(request, "Método inválido para realizar una reserva.")
    return redirect('ficha_libro', pk=libro_pk)


# NUEVA VISTA: LISTADO DE RESERVAS DEL CLIENTE
@requerir_cliente
def listado_reservas_view(request):
    try:
        cliente = Usuarios.objects.get(id=request.session.get("id_usuario"))
    except Usuarios.DoesNotExist:
        messages.error(request, "Error de sesión. Por favor, vuelve a iniciar sesión.")
        return redirect("inicio_sesion")

    # Obtener todas las reservas del cliente, pendientes y activas
    reservas_cliente = Reservas.objects.filter(
        cliente=cliente
    ).select_related('libro').order_by('-fecha_reserva')
    
    contexto = {
        'usuario_actual': cliente,
        'reservas': reservas_cliente,
        # Puedes añadir paginación aquí si el listado es muy largo
    }
    # Renderiza la nueva plantilla HTML que crearemos abajo
    return render(request, 'catalogo/reservas.html', contexto)


# VISTA DE CATÁLOGO (Mantengo tu lógica original)
def catalogo_view(request):
    # ... (Tu código actual de catalogo_view)
    libros = Libros.objects.all()
    query = request.GET.get('q')
    
    # ... (Implementa tu lógica de búsqueda/filtrado)
    
    context = {'libros': libros, 'query': query}
    return render(request, 'catalogo/catalogo.html', context)


# VISTA DE FICHA (Mantengo tu lógica original)
def ficha_libro(request, pk):
    libro = get_object_or_404(Libros, id=pk)
    
    # IMPORTANTE: Necesitas saber si el cliente ya tiene una reserva para el libro
    ya_reservado = False
    if _usuario_autenticado(request):
        try:
            cliente = Usuarios.objects.get(id=request.session.get("id_usuario"))
            ya_reservado = Reservas.objects.filter(
                cliente=cliente, 
                libro=libro, 
                estado__in=['pendiente', 'activa']
            ).exists()
        except Usuarios.DoesNotExist:
             pass # Si no existe, no puede haber reservado

    contexto = {
        'libro': libro,
        'ya_reservado': ya_reservado,
    }
    return render(request, 'catalogo/ficha_libro.html', contexto)