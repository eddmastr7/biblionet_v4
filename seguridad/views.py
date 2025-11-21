from functools import wraps
from datetime import datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import logout as auth_logout  
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
import random

from biblio.models import (
    Usuarios,
    Roles,
    Libros,
    Prestamos,
    Bitacora,
    ReglasPrestamo,
    Clientes,
    Ejemplares,
)

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

        contrasena_bd = usuario.clave or ""
        if contrasena_bd.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
            coincide = check_password(contrasena, contrasena_bd)
        else:
            coincide = (contrasena == contrasena_bd)

        if not coincide:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            return render(request, "seguridad/login_empleados.html", contexto)

        # Login exitoso: pisamos cualquier sesión previa
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
    # Por si en algún momento se usa el sistema de auth de Django
    auth_logout(request)

    # Borrar claves específicas que usamos para empleados
    for key in ["id_usuario", "correo_usuario", "rol_usuario"]:
        if key in request.session:
            del request.session[key]

    # Vaciar por completo la sesión y regenerar la cookie
    request.session.flush()

    messages.success(request, "Sesión de empleado cerrada correctamente.")
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

@requerir_rol("administrador")
@csrf_protect
def configurar_reglas_prestamo(request):
    """
    Vista para que el administrador configure las reglas generales de préstamo.
    Usa la última regla registrada o crea una nueva si no existe.
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    # Tomamos la última regla (puede ser la única) o None si no existe
    regla = ReglasPrestamo.objects.order_by("-fecha_actualizacion").first()

    if request.method == "POST":
        plazo_dias = request.POST.get("plazo_dias")
        limite_prestamos = request.POST.get("limite_prestamos")
        tarifa_mora_diaria = request.POST.get("tarifa_mora_diaria")
        # si después quieres descripción adicional, la agregamos; por ahora lo simplificamos
        descripcion = "Reglas generales de préstamo"

        if not plazo_dias or not limite_prestamos or not tarifa_mora_diaria:
            messages.error(request, "Completa todos los campos.")
        else:
            try:
                if regla is None:
                    regla = ReglasPrestamo()

                regla.plazo_dias = int(plazo_dias)
                regla.limite_prestamos = int(limite_prestamos)
                regla.tarifa_mora_diaria = tarifa_mora_diaria
                regla.descripcion = descripcion
                regla.fecha_actualizacion = timezone.now()
                regla.save()

                Bitacora.objects.create(
                    usuario=usuario_actual,
                    accion=(
                        f"ACTUALIZÓ REGLAS DE PRÉSTAMO: "
                        f"plazo={regla.plazo_dias} días, "
                        f"límite={regla.limite_prestamos}, "
                        f"mora={regla.tarifa_mora_diaria}"
                    ),
                    fecha=timezone.now()
                )

                messages.success(request, "Reglas de préstamo actualizadas correctamente.")
                return redirect("configurar_reglas_prestamo")

            except Exception as e:
                messages.error(request, f"Error al guardar las reglas: {str(e)}")

    contexto = {
        "usuario_actual": usuario_actual,
        "regla": regla,
    }
    return render(request, "seguridad/reglas.html", contexto)


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


@requerir_rol("bibliotecario")
def gestion_prestamos(request):
    """
    Lista de préstamos activos para el bibliotecario, con buscador y paginación.
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    query = (request.GET.get("q") or "").strip()

    prestamos_qs = (
        Prestamos.objects.select_related("cliente__usuario", "ejemplar__libro")
        .filter(estado="activo")
        .order_by("-fecha_inicio")
    )

    if query:
        prestamos_qs = prestamos_qs.filter(
            Q(cliente__usuario__nombre__icontains=query) |
            Q(cliente__usuario__apellido__icontains=query) |
            Q(cliente__dni__icontains=query)
        )

    paginator = Paginator(prestamos_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    contexto = {
        "usuario_actual": usuario_actual,
        "prestamos": page_obj,
        "query": query,
    }
    return render(request, "seguridad/gestion_prestamos.html", contexto)

UBICACIONES_PREDEFINIDAS = [
    "Estante A1 - Sección Literatura",
    "Estante B2 - Sección Ciencia",
    "Estante C3 - Sección Historia",
    "Estante D1 - Sección Infantil",
    "Depósito General",
]

def _crear_ejemplar_para_libro(libro):
    """
    Crea un Ejemplar físico para un libro dado, generando:
    - codigo_interno único (EJ-<id_libro>-####)
    - ubicacion aleatoria
    - estado aleatorio: nuevo / usado
    """
    base = f"EJ-{libro.id}-"
    codigo = None

    # Intentamos hasta 10 códigos diferentes para evitar colisión por unique
    for _ in range(10):
        sufijo = random.randint(1000, 9999)
        candidato = f"{base}{sufijo}"
        if not Ejemplares.objects.filter(codigo_interno=candidato).exists():
            codigo = candidato
            break

    # Último recurso si por alguna razón no se encontró libre
    if codigo is None:
        codigo = f"{base}{timezone.now().strftime('%H%M%S')}"

    ubicacion = random.choice(UBICACIONES_PREDEFINIDAS)
    estado = random.choice(["nuevo", "usado"])

    return Ejemplares.objects.create(
        libro=libro,
        codigo_interno=codigo,
        ubicacion=ubicacion,
        estado=estado,
    )

@requerir_rol("bibliotecario")
@csrf_protect
def registrar_prestamo(request):
    """
    Registrar un nuevo préstamo usando las reglas vigentes.
    - Busca cliente por DNI
    - Busca libro por ISBN
    - Crea un Ejemplar físico aleatorio (codigo_interno, ubicacion, estado)
    - Disminuye stock_total del libro
    - Muestra pantalla de detalle del préstamo + ejemplar
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    regla = ReglasPrestamo.objects.order_by("-fecha_actualizacion").first()
    hoy = timezone.localdate()

    if regla is None:
        messages.error(
            request,
            "No hay reglas de préstamo configuradas. Configúralas primero."
        )
        return redirect("configurar_reglas_prestamo")

    form_data = {"dni": "", "isbn": ""}

    if request.method == "POST":
        dni = (request.POST.get("dni") or "").strip()
        isbn = (request.POST.get("isbn") or "").strip()
        fecha_inicio_str = request.POST.get("fecha_inicio") or hoy.isoformat()

        form_data["dni"] = dni
        form_data["isbn"] = isbn

        # Validar campos obligatorios
        if not dni or not isbn:
            messages.error(request, "Completa todos los campos.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Parsear fecha de inicio
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "La fecha de inicio no es válida.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        if fecha_inicio < hoy:
            messages.error(request, "La fecha de inicio no puede ser anterior a hoy.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Buscar cliente por DNI
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                dni=dni, estado__iexact="activo"
            )
        except Clientes.DoesNotExist:
            messages.error(request, "No se encontró un cliente activo con ese DNI.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Validar límite de préstamos activos
        prestamos_activos_cliente = Prestamos.objects.filter(
            cliente=cliente,
            estado="activo",
        ).count()

        if prestamos_activos_cliente >= regla.limite_prestamos:
            messages.error(
                request,
                f"El cliente ya alcanzó el límite de {regla.limite_prestamos} préstamos activos."
            )
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Buscar libro por ISBN
        try:
            libro = Libros.objects.get(isbn=isbn)
        except Libros.DoesNotExist:
            messages.error(request, "No se encontró un libro con ese ISBN.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Validar stock
        if not libro.stock_total or libro.stock_total <= 0:
            messages.error(request, "No hay stock disponible para este libro.")
            return render(
                request,
                "seguridad/registrar_prestamo.html",
                {
                    "usuario_actual": usuario_actual,
                    "regla": regla,
                    "hoy": hoy,
                    "form_data": form_data,
                },
            )

        # Disminuir stock del libro
        libro.stock_total = (libro.stock_total or 0) - 1
        libro.save()

        # Crear ejemplar físico aleatorio (codigo_interno, ubicacion, estado)
        ejemplar = _crear_ejemplar_para_libro(libro)

        # Calcular fecha fin según plazo de la regla
        fecha_fin = fecha_inicio + timedelta(days=regla.plazo_dias)

        # Crear préstamo
        prestamo = Prestamos.objects.create(
            cliente=cliente,
            ejemplar=ejemplar,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            estado="activo",
        )

        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=(
                f"REGISTRO PRÉSTAMO: cliente={cliente.dni}, "
                f"ejemplar={ejemplar.codigo_interno}, id_prestamo={prestamo.id}"
            ),
            fecha=timezone.now(),
        )

        # En lugar de redirigir, mostramos pantalla con los datos del EJEMPLAR
        messages.success(request, "Préstamo registrado correctamente.")
        return render(
            request,
            "seguridad/detalle_prestamo.html",
            {
                "usuario_actual": usuario_actual,
                "prestamo": prestamo,
                "ejemplar": ejemplar,
                "libro": libro,
                "cliente": cliente,
            },
        )

    # GET: mostrar formulario vacío
    contexto = {
        "usuario_actual": usuario_actual,
        "regla": regla,
        "hoy": hoy,
        "form_data": form_data,
    }
    return render(request, "seguridad/registrar_prestamo.html", contexto)


@requerir_rol("bibliotecario")
@csrf_protect
def devolver_prestamo(request, prestamo_id):
    """
    Marca un préstamo como devuelto.
    """
    if request.method != "POST":
        return redirect("gestion_prestamos")

    prestamo = get_object_or_404(
        Prestamos,
        id=prestamo_id,
        estado="activo",
    )

    prestamo.fecha_devolucion = timezone.localdate()
    prestamo.estado = "devuelto"
    prestamo.save()

    # Opcional: marcar ejemplar como disponible
    # ejemplar = prestamo.ejemplar
    # ejemplar.estado = "disponible"
    # ejemplar.save()

    Bitacora.objects.create(
        usuario=Usuarios.objects.get(id=request.session.get("id_usuario")),
        accion=f"DEVOLVIÓ PRÉSTAMO id={prestamo.id}",
        fecha=timezone.now(),
    )

    messages.success(request, "El préstamo se marcó como devuelto.")
    return redirect("gestion_prestamos")


@requerir_rol("bibliotecario")
@csrf_protect
def renovar_prestamo(request, prestamo_id):
    """
    Renueva la fecha fin de un préstamo activo.
    """
    if request.method != "POST":
        return redirect("gestion_prestamos")

    prestamo = get_object_or_404(
        Prestamos,
        id=prestamo_id,
        estado="activo",
    )

    nueva_fecha_str = request.POST.get("nueva_fecha_fin")
    if not nueva_fecha_str:
        messages.error(request, "Debes seleccionar una nueva fecha de devolución.")
        return redirect("gestion_prestamos")

    try:
        nueva_fecha = datetime.strptime(nueva_fecha_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "La nueva fecha de devolución no es válida.")
        return redirect("gestion_prestamos")

    if nueva_fecha <= prestamo.fecha_fin:
        messages.error(
            request,
            "La nueva fecha de devolución debe ser mayor a la fecha actual de devolución."
        )
        return redirect("gestion_prestamos")

    prestamo.fecha_fin = nueva_fecha
    prestamo.save()

    Bitacora.objects.create(
        usuario=Usuarios.objects.get(id=request.session.get("id_usuario")),
        accion=f"RENOVÓ PRÉSTAMO id={prestamo.id} nueva_fecha={nueva_fecha}",
        fecha=timezone.now(),
    )

    messages.success(request, "El préstamo se renovó correctamente.")
    return redirect("gestion_prestamos")
