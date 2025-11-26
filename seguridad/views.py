from functools import wraps
from datetime import datetime, timedelta
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import logout as auth_logout
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from biblio.utils import actualizar_bloqueo_por_mora

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


def _redirigir_segun_rol(rol):
    if rol == "administrador":
        return redirect("panel_administrador")
    else:
        return redirect("panel_bibliotecario")

# ---------- Login / Logout (empleados/admin) ----------

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
            "bibliotecario": "bibliotecario",
        }
        rol_bd = mapeo_roles.get(rol_formulario)

        if not rol_bd:
            contexto["error"] = "Rol inválido."
            return render(request, "seguridad/login_empleados.html", contexto)

        try:
            usuario = Usuarios.objects.select_related("rol").get(
                email=correo,
                rol__nombre=rol_bd,
                estado="activo",
            )
        except Usuarios.DoesNotExist:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            return render(request, "seguridad/login_empleados.html", contexto)

        contrasena_bd = usuario.clave or ""
        if contrasena_bd.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
            coincide = check_password(contrasena, contrasena_bd)
        else:
            coincide = contrasena == contrasena_bd

        if not coincide:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            return render(request, "seguridad/login_empleados.html", contexto)

        # Login exitoso: pisamos cualquier sesión previa
        request.session["id_usuario"] = usuario.id
        request.session["correo_usuario"] = usuario.email
        request.session["rol_usuario"] = usuario.rol.nombre
        request.session.set_expiry(
            60 * 60 * 24 * 14 if recordar_sesion == "on" else 0
        )

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
    # Usuario en sesión
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    # Total de libros (como ya lo tenías)
    total_libros = Libros.objects.count()

    # -----------------------------
    # Filtros de búsqueda
    # -----------------------------
    query = (request.GET.get("q") or "").strip()
    estado_filtro = (request.GET.get("estado") or "").strip()

    # Base: solo roles de administrador y bibliotecario
    empleados_qs = Usuarios.objects.select_related("rol").filter(
        rol__nombre__in=["administrador", "bibliotecario"]
    )

    # Buscar por nombre
    if query:
        empleados_qs = empleados_qs.filter(nombre__icontains=query)

    # Filtro por estado
    if estado_filtro in ["activo", "inactivo"]:
        empleados_qs = empleados_qs.filter(estado__iexact=estado_filtro)

    # Contar empleados activos (badge)
    empleados_activos = empleados_qs.filter(estado__iexact="activo").count()

    # Paginación (10 empleados por página)
    paginator = Paginator(empleados_qs.order_by("-fecha_creacion"), 10)
    page_number = request.GET.get("page")
    empleados_page = paginator.get_page(page_number)

    contexto = {
        "usuario_actual": usuario_actual,
        "total_libros": total_libros,
        "ventas_mensuales": None,  # placeholder
        "empleados_activos": empleados_activos,
        "empleados": empleados_page,
        "query": query,
        "estado_filtro": estado_filtro,
    }
    return render(request, "seguridad/admin_home.html", contexto)


@requerir_rol("administrador")
def editar_empleado(request, empleado_id):
    # Validar sesión
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    # Validar que sea administrador
    if usuario_actual.rol.nombre != "administrador":
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect("panel_administrador")

    empleado = get_object_or_404(Usuarios, id=empleado_id)

    if request.method != "POST":
        # No debería venir por GET, pero lo protegemos igual
        return redirect("panel_administrador")

    nombre = (request.POST.get("nombre") or "").strip()
    apellido = (request.POST.get("apellido") or "").strip()
    email = (request.POST.get("email") or "").strip()
    estado = (request.POST.get("estado") or "").strip()

    # Validaciones básicas
    if not (nombre and apellido and email and estado):
        messages.error(request, "Todos los campos son obligatorios.")
        return redirect("panel_administrador")

    if estado not in ["activo", "inactivo"]:
        messages.error(request, "Estado inválido.")
        return redirect("panel_administrador")

    # Validar que el correo no se repita en otro usuario
    if Usuarios.objects.exclude(id=empleado.id).filter(email=email).exists():
        messages.error(
            request,
            "Ya existe un usuario con ese correo electrónico."
        )
        return redirect("panel_administrador")

    # Actualizar datos
    empleado.nombre = nombre
    empleado.apellido = apellido
    empleado.email = email
    empleado.estado = estado
    empleado.save()

    messages.success(request, "Empleado actualizado correctamente.")
    return redirect("panel_administrador")


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
        fecha_fin__lt=hoy,
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
        {
            "nombre_formulario": "admin",
            "nombre_bd": "administrador",
            "nombre_mostrar": "Administrador",
        },
        {
            "nombre_formulario": "bibliotecario",
            "nombre_bd": "bibliotecario",
            "nombre_mostrar": "Bibliotecario",
        },
    ]

    contexto = {
        "exito": None,
        "error": None,
        "roles": roles_disponibles,
        "usuario_actual": Usuarios.objects.get(
            id=request.session.get("id_usuario")
        ),
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
        mapeo_roles = {
            "admin": "administrador",
            "bibliotecario": "bibliotecario",
        }
        rol_bd = mapeo_roles.get(rol_formulario)

        if not rol_bd:
            contexto["error"] = "Rol inválido."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        try:
            objeto_rol = Roles.objects.get(nombre=rol_bd)
        except Roles.DoesNotExist:
            contexto["error"] = (
                f"No existe el rol '{rol_bd}' en la base de datos."
            )
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
                fecha_creacion=timezone.localtime(),
            )

            Bitacora.objects.create(
                usuario=contexto["usuario_actual"],
                accion=f"REGISTRO EMPLEADO: {correo} como {rol_bd}",
                fecha=timezone.now(),
            )

            contexto["exito"] = (
                f"Empleado {nombre} {apellido} creado exitosamente."
            )

        except Exception as error:
            contexto["error"] = f"Error al crear el usuario: {str(error)}"

    return render(request, "seguridad/registrar_empleados.html", contexto)

# ---------- Gestión de clientes (bloqueo / desbloqueo) ----------

@requerir_rol("administrador")
def gestion_clientes(request):
    """
    Listado de clientes con filtros básicos:
    - Búsqueda por nombre, apellido o DNI
    - Filtro por estado (activo/inactivo)
    - Filtro 'solo bloqueados'
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    query = (request.GET.get("q") or "").strip()
    estado_filtro = (request.GET.get("estado") or "").strip()
    solo_bloqueados = request.GET.get("solo_bloqueados") == "1"

    clientes = Clientes.objects.select_related("usuario").all()

    if query:
        clientes = clientes.filter(
            Q(usuario__nombre__icontains=query)
            | Q(usuario__apellido__icontains=query)
            | Q(dni__icontains=query)
        )

    if estado_filtro == "activo":
        clientes = clientes.filter(estado="activo")
    elif estado_filtro == "inactivo":
        clientes = clientes.filter(estado="inactivo")

    if solo_bloqueados:
        clientes = clientes.filter(bloqueado=True)

    contexto = {
        "usuario_actual": usuario_actual,
        "clientes": clientes,
        "query": query,
        "estado_filtro": estado_filtro,
        "solo_bloqueados": solo_bloqueados,
    }
    return render(request, "seguridad/gestion_clientes.html", contexto)

@requerir_rol("administrador")
def bloquear_cliente(request, cliente_id):
    """
    Marca a un cliente como bloqueado.
    Se usa desde la tabla con un enlace + confirm() en el front.
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    cliente = get_object_or_404(Clientes, id=cliente_id)

    if cliente.bloqueado:
        messages.info(request, "El cliente ya se encuentra bloqueado.")
        return redirect("gestion_clientes")

    # Actualizar campos de bloqueo
    cliente.bloqueado = True

    # Si tu modelo tiene estos campos, los rellenamos de forma segura
    if hasattr(cliente, "fecha_bloqueo"):
        cliente.fecha_bloqueo = timezone.now()

    if hasattr(cliente, "motivo_bloqueo") and not cliente.motivo_bloqueo:
        cliente.motivo_bloqueo = "Bloqueado manualmente por el administrador."

    if hasattr(cliente, "estado"):
        cliente.estado = "inactivo"

    cliente.save()

    # Registrar en bitácora
    try:
        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=f"BLOQUEÓ CLIENTE ID={cliente.id}",
            fecha=timezone.now(),
        )
    except Exception:
        # Si por algo falla la bitácora, no rompemos el flujo principal
        pass

    messages.success(request, "Cliente bloqueado correctamente.")
    return redirect("gestion_clientes")

@requerir_rol("administrador")
def desbloquear_cliente(request, cliente_id):
    """
    Quita el bloqueo de un cliente.
    """
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    cliente = get_object_or_404(Clientes, id=cliente_id)

    if not cliente.bloqueado:
        messages.info(request, "El cliente no está bloqueado.")
        return redirect("gestion_clientes")

    cliente.bloqueado = False

    # Opcional: limpiar motivo / fecha (o los dejas como histórico)
    # if hasattr(cliente, "motivo_bloqueo"):
    #     cliente.motivo_bloqueo = ""
    # if hasattr(cliente, "fecha_bloqueo"):
    #     cliente.fecha_bloqueo = None

    if hasattr(cliente, "estado"):
        cliente.estado = "activo"

    cliente.save()

    try:
        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=f"DESBLOQUEÓ CLIENTE ID={cliente.id}",
            fecha=timezone.now(),
        )
    except Exception:
        pass

    messages.success(request, "Cliente desbloqueado correctamente.")
    return redirect("gestion_clientes")

# ---------- Reglas de préstamo, inventario, préstamos ----------

@requerir_rol("administrador")
@csrf_protect
def configurar_reglas_prestamo(request):
    """
    Vista para que el administrador configure las reglas generales de préstamo.
    - Muestra la regla vigente (la última registrada).
    - Guarda una nueva regla y deja las anteriores como historial.
    """

    # Usuario en sesión
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    # Regla vigente = la última por fecha_actualizacion
    regla_vigente = (
        ReglasPrestamo.objects.order_by("-fecha_actualizacion").first()
    )

    # Historial completo de reglas (para mostrar en tabla si quieres)
    historial_reglas = ReglasPrestamo.objects.all().order_by("-fecha_actualizacion")

    if request.method == "POST":
        plazo_dias = (request.POST.get("plazo_dias") or "").strip()
        limite_prestamos = (request.POST.get("limite_prestamos") or "").strip()
        tarifa_mora_diaria = (request.POST.get("tarifa_mora_diaria") or "").strip()
        descripcion = "Reglas generales de préstamo"

        if not plazo_dias or not limite_prestamos or not tarifa_mora_diaria:
            messages.error(request, "Completa todos los campos.")
        else:
            try:
                plazo_dias_int = int(plazo_dias)
                limite_prestamos_int = int(limite_prestamos)
                # Si el campo en el modelo es DecimalField, Django hace el cast solo.
                tarifa_mora = float(tarifa_mora_diaria)

                # 👇 En vez de sobrescribir siempre la misma fila,
                # creamos una nueva (deja historial).
                nueva_regla = ReglasPrestamo.objects.create(
                    plazo_dias=plazo_dias_int,
                    limite_prestamos=limite_prestamos_int,
                    tarifa_mora_diaria=tarifa_mora,
                    descripcion=descripcion,
                    fecha_actualizacion=timezone.now(),
                )

                Bitacora.objects.create(
                    usuario=usuario_actual,
                    accion=(
                        "ACTUALIZÓ REGLAS DE PRÉSTAMO: "
                        f"plazo={nueva_regla.plazo_dias} días, "
                        f"límite={nueva_regla.limite_prestamos}, "
                        f"mora={nueva_regla.tarifa_mora_diaria}"
                    ),
                    fecha=timezone.now(),
                )

                messages.success(
                    request,
                    "Reglas de préstamo actualizadas correctamente."
                )
                return redirect("configurar_reglas_prestamo")

            except ValueError:
                messages.error(
                    request,
                    "Verifica que los campos numéricos tengan valores válidos."
                )
            except Exception as e:
                messages.error(
                    request,
                    f"Error al guardar las reglas: {str(e)}"
                )

    contexto = {
        "usuario_actual": usuario_actual,
        "regla": regla_vigente,          # regla vigente (para mostrar antes de cambiar)
        "historial_reglas": historial_reglas,  # por si en la plantilla quieres tabla de historial
    }
    return render(request, "seguridad/reglas.html", contexto)


@requerir_rol("bibliotecario")
def inventario(request):
    # Usuario logueado
    usuario_actual = Usuarios.objects.select_related("rol").get(
        id=request.session.get("id_usuario")
    )

    # Búsqueda
    query = request.GET.get("q", "").strip()
    if query:
        libros_qs = (
            Libros.objects.filter(titulo__icontains=query)
            | Libros.objects.filter(autor__icontains=query)
            | Libros.objects.filter(isbn__icontains=query)
            | Libros.objects.filter(categoria__icontains=query)
        ).distinct().order_by("autor", "titulo")
    else:
        libros_qs = Libros.objects.all().order_by("titulo")

    # Paginación: 5 libros por página
    paginator = Paginator(libros_qs, 5)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # POST: agregar libro
    if request.method == "POST" and "agregar_libro" in request.POST:
        try:
            anio_publicacion = str(request.POST.get("anio_publicacion"))

            portada_file = request.FILES.get("portada")  # puede venir vacío

            libro = Libros(
                isbn=request.POST.get("isbn"),
                titulo=request.POST.get("titulo"),
                autor=request.POST.get("autor"),
                categoria=request.POST.get("categoria"),
                editorial=request.POST.get("editorial"),
                anio_publicacion=anio_publicacion,
                stock_total=request.POST.get("stock", 0),
                portada=portada_file,  # archivo de imagen
                fecha_registro=timezone.now(),  # fecha automática
            )
            libro.save()
            messages.success(request, "Libro agregado correctamente")
            return redirect("inventario")

        except Exception as e:
            messages.error(request, f"Error al agregar el libro: {str(e)}")
            return redirect("inventario")

    # POST: editar libro
    if request.method == "POST" and "editar_libro" in request.POST:
        try:
            libro_id = request.POST.get("libro_id")
            libro = get_object_or_404(Libros, id=libro_id)

            anio_publicacion = str(request.POST.get("anio_publicacion"))

            libro.titulo = request.POST.get("titulo")
            libro.autor = request.POST.get("autor")
            libro.categoria = request.POST.get("categoria")
            libro.editorial = request.POST.get("editorial")
            libro.anio_publicacion = anio_publicacion
            libro.stock_total = request.POST.get("stock", 0)

            # Si viene una nueva portada, la reemplazamos
            portada_file = request.FILES.get("portada")
            if portada_file:
                libro.portada = portada_file

            libro.save()

            Bitacora.objects.create(
                usuario=usuario_actual,
                accion=f"EDITO EL LIBRO: '{libro.titulo}'",
                fecha=timezone.now(),
            )

            messages.success(request, "Libro actualizado correctamente")
            return redirect("inventario")

        except Exception as e:
            messages.error(request, f"Error al actualizar el libro: {str(e)}")
            return redirect("inventario")

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
            Q(cliente__usuario__nombre__icontains=query)
            | Q(cliente__usuario__apellido__icontains=query)
            | Q(cliente__dni__icontains=query)
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
            messages.error(
                request,
                "La fecha de inicio no puede ser anterior a hoy."
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

        # Buscar cliente por DNI
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                dni=dni,
                estado__iexact="activo",
            )
        except Clientes.DoesNotExist:
            messages.error(
                request,
                "No se encontró un cliente activo con ese DNI."
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

        # 🔒 REVISAR MORA Y BLOQUEO (automático + manual)
        if actualizar_bloqueo_por_mora(cliente):
            messages.error(
                request,
                "El cliente está bloqueado (por mora o por decisión administrativa). "
                "No puede realizar nuevos préstamos hasta regularizar su situación."
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

        # Validar límite de préstamos activos
        prestamos_activos_cliente = Prestamos.objects.filter(
            cliente=cliente,
            estado="activo",
        ).count()

        if prestamos_activos_cliente >= regla.limite_prestamos:
            messages.error(
                request,
                (
                    "El cliente ya alcanzó el límite de "
                    f"{regla.limite_prestamos} préstamos activos."
                ),
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
            messages.error(
                request,
                "No hay stock disponible para este libro."
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
                "REGISTRO PRÉSTAMO: "
                f"cliente={cliente.dni}, "
                f"ejemplar={ejemplar.codigo_interno}, "
                f"id_prestamo={prestamo.id}"
            ),
            fecha=timezone.now(),
        )

        # Mostrar pantalla con los datos del EJEMPLAR
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
    Si hay mora, bloquea al cliente automáticamente.
    """
    if request.method != "POST":
        return redirect("gestion_prestamos")

    try:
        usuario_actual = Usuarios.objects.get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    prestamo = get_object_or_404(
        Prestamos,
        id=prestamo_id,
        estado="activo",
    )

    hoy = timezone.localdate()
    prestamo.fecha_devolucion = hoy
    prestamo.estado = "devuelto"
    prestamo.save()

    dias_mora = 0
    if prestamo.fecha_fin and hoy > prestamo.fecha_fin:
        dias_mora = (hoy - prestamo.fecha_fin).days

    if dias_mora > 0:
        regla = ReglasPrestamo.objects.order_by("-fecha_actualizacion").first()
        monto_mora = None
        if regla:
            # tarifa_mora_diaria es DecimalField, multiplicamos por int
            monto_mora = regla.tarifa_mora_diaria * dias_mora

        cliente = prestamo.cliente
        motivo = (
            f"Mora de {dias_mora} día(s) en devolución de préstamo ID={prestamo.id}"
        )
        if monto_mora is not None:
            motivo += f", monto estimado: L. {monto_mora}"

        cliente.bloqueado = True
        cliente.motivo_bloqueo = motivo
        cliente.fecha_bloqueo = timezone.now()
        cliente.save()

        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=(
                "DEVOLVIÓ PRÉSTAMO CON MORA "
                f"id={prestamo.id}, cliente={cliente.dni}, días_mora={dias_mora}"
            ),
            fecha=timezone.now(),
        )

        messages.warning(
            request,
            "Préstamo devuelto con "
            f"{dias_mora} día(s) de mora. "
            "El cliente ha sido bloqueado hasta que regularice la situación.",
        )
    else:
        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=f"DEVOLVIÓ PRÉSTAMO id={prestamo.id} sin mora",
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
        messages.error(
            request,
            "Debes seleccionar una nueva fecha de devolución."
        )
        return redirect("gestion_prestamos")

    try:
        nueva_fecha = datetime.strptime(nueva_fecha_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(
            request,
            "La nueva fecha de devolución no es válida."
        )
        return redirect("gestion_prestamos")

    if nueva_fecha <= prestamo.fecha_fin:
        messages.error(
            request,
            (
                "La nueva fecha de devolución debe ser mayor a la fecha "
                "actual de devolución."
            ),
        )
        return redirect("gestion_prestamos")

    prestamo.fecha_fin = nueva_fecha
    prestamo.save()

    Bitacora.objects.create(
        usuario=Usuarios.objects.get(id=request.session.get("id_usuario")),
        accion=(
            f"RENOVÓ PRÉSTAMO id={prestamo.id} "
            f"nueva_fecha={nueva_fecha}"
        ),
        fecha=timezone.now(),
    )

    messages.success(request, "El préstamo se renovó correctamente.")
    return redirect("gestion_prestamos")
