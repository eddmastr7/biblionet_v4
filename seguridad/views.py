from functools import wraps
from datetime import datetime, timedelta
import random
import re
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.db import transaction, DatabaseError
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import logout as auth_logout
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.urls import reverse
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
    SolicitudVenta,
    Ventas,
    DetalleVenta,
    Proveedores,
    Compras,
    DetalleCompras,
)

# ---------- Helpers de sesión / roles ----------

def _usuario_autenticado(request):
    return request.session.get("id_usuario") is not None

def _obtener_rol_usuario(request):
    return request.session.get("rol_usuario")

def requerir_rol(*roles_permitidos):

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

    storage = messages.get_messages(request)
    for _ in storage:
        pass

    contexto = {"error": None}

    if request.method == "POST":
        correo = (request.POST.get("email") or "").strip().lower()
        contrasena = request.POST.get("password", "")
        recordar_sesion = request.POST.get("remember", "")

        if not correo or not contrasena:
            contexto["error"] = "Completa correo y contraseña."
            contexto["email"] = correo
            return render(request, "seguridad/login_empleados.html", contexto)

        try:
            
            usuario = (
                Usuarios.objects
                .select_related("rol")
                .get(
                    email=correo,
                    estado="activo",
                    rol__nombre__in=["administrador", "bibliotecario"],
                )
            )
        except Usuarios.DoesNotExist:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            contexto["email"] = correo
            return render(request, "seguridad/login_empleados.html", contexto)
        except Usuarios.MultipleObjectsReturned:
            contexto["error"] = (
                "Existen múltiples cuentas asociadas a este correo. "
                "Contacta al administrador del sistema."
            )
            contexto["email"] = correo
            return render(request, "seguridad/login_empleados.html", contexto)

        contrasena_bd = usuario.clave or ""
        if contrasena_bd.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
            coincide = check_password(contrasena, contrasena_bd)
        else:
            coincide = (contrasena == contrasena_bd)

        if not coincide:
            contexto["error"] = "Credenciales incorrectas. Intenta nuevamente."
            contexto["email"] = correo
            return render(request, "seguridad/login_empleados.html", contexto)

        # Login exitoso → guardar datos básicos en sesión
        request.session["id_usuario"] = usuario.id
        request.session["correo_usuario"] = usuario.email
        request.session["rol_usuario"] = usuario.rol.nombre

        # Recordar sesión (14 días) o sesión normal (hasta cerrar navegador)
        request.session.set_expiry(
            60 * 60 * 24 * 14 if recordar_sesion == "on" else 0
        )

        # Si es primer ingreso → obligar a cambiar contraseña
        if getattr(usuario, "primer_ingreso", False) and usuario.rol.nombre in (
            "administrador",
            "bibliotecario",
        ):
            request.session["primer_ingreso"] = True
            url_recuperar = reverse("recuperar_contrasena_empleado")
            return redirect(f"{url_recuperar}?email={usuario.email}&primer_ingreso=1")

        # Flujo normal según rol
        if usuario.rol.nombre == "administrador":
            return redirect("panel_administrador")
        else:
            return redirect("panel_bibliotecario")

    # GET → mostrar formulario
    return render(request, "seguridad/login_empleados.html", contexto)

def cerrar_sesion_empleado(request):
    auth_logout(request)

    for key in ["id_usuario", "correo_usuario", "rol_usuario"]:
        if key in request.session:
            del request.session[key]

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

    # Filtros de búsqueda
    query = (request.GET.get("q") or "").strip()
    estado_filtro = (request.GET.get("estado") or "").strip()

    empleados_qs = Usuarios.objects.select_related("rol").filter(
        rol__nombre__in=["administrador", "bibliotecario"]
    )

    if query:
        empleados_qs = empleados_qs.filter(nombre__icontains=query)

    if estado_filtro in ["activo", "inactivo"]:
        empleados_qs = empleados_qs.filter(estado__iexact=estado_filtro)

    empleados_activos = empleados_qs.filter(estado__iexact="activo").count()

    paginator = Paginator(empleados_qs.order_by("-fecha_creacion"), 10)
    page_number = request.GET.get("page")
    empleados_page = paginator.get_page(page_number)

    contexto = {
        "usuario_actual": usuario_actual,
        "total_libros": total_libros,
        "ventas_mensuales": None,
        "empleados_activos": empleados_activos,
        "empleados": empleados_page,
        "query": query,
        "estado_filtro": estado_filtro,
    }
    return render(request, "seguridad/admin_home.html", contexto)


@requerir_rol("administrador")
def editar_empleado(request, empleado_id):
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    if usuario_actual.rol.nombre != "administrador":
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect("panel_administrador")

    empleado = get_object_or_404(Usuarios, id=empleado_id)

    if request.method != "POST":
        return redirect("panel_administrador")

    nombre = (request.POST.get("nombre") or "").strip()
    apellido = (request.POST.get("apellido") or "").strip()
    email = (request.POST.get("email") or "").strip()
    estado = (request.POST.get("estado") or "").strip()

    if not (nombre and apellido and email and estado):
        messages.error(request, "Todos los campos son obligatorios.")
        return redirect("panel_administrador")

    if estado not in ["activo", "inactivo"]:
        messages.error(request, "Estado inválido.")
        return redirect("panel_administrador")

    if Usuarios.objects.exclude(id=empleado.id).filter(email=email).exists():
        messages.error(
            request,
            "Ya existe un usuario con ese correo electrónico."
        )
        return redirect("panel_administrador")

    empleado.nombre = nombre
    empleado.apellido = apellido
    empleado.email = email
    empleado.estado = estado
    empleado.save()

    messages.success(request, "Empleado actualizado correctamente.")
    return redirect("panel_administrador")


def panel_bibliotecario(request):
    """
    Pantalla de inicio del bibliotecario.
    Muestra en tiempo real:
      - total de préstamos
      - préstamos activos
      - préstamos en mora
      - tabla con los préstamos (últimos registrados)
    """

    usuario_id = request.session.get("id_usuario")
    if not usuario_id:
        return redirect("cerrar_sesion")

    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(id=usuario_id)
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    prestamos_qs = (
        Prestamos.objects
        .select_related("cliente__usuario", "ejemplar__libro")
        .order_by("-fecha_inicio")
    )

    prestamos_total = prestamos_qs.count()
    prestamos_activos = prestamos_qs.filter(estado__iexact="activo").count()
    prestamos_en_mora = prestamos_qs.filter(estado__iexact="mora").count()

    prestamos_bibliotecario = prestamos_qs[:20]

    contexto = {
        "usuario_actual": usuario_actual,
        "prestamos_total": prestamos_total,
        "prestamos_activos": prestamos_activos,
        "prestamos_en_mora": prestamos_en_mora,
        "prestamos_bibliotecario": prestamos_bibliotecario,
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

        if not all([nombre, apellido, correo, contrasena, rol_formulario]):
            contexto["error"] = "Completa todos los campos obligatorios."
            return render(request, "seguridad/registrar_empleados.html", contexto)

        if len(contrasena) < 8:
            contexto["error"] = "La contraseña debe tener al menos 8 caracteres."
            return render(request, "seguridad/registrar_empleados.html", contexto)

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

    cliente.bloqueado = True

    if hasattr(cliente, "fecha_bloqueo"):
        cliente.fecha_bloqueo = timezone.now()

    if hasattr(cliente, "motivo_bloqueo") and not cliente.motivo_bloqueo:
        cliente.motivo_bloqueo = "Bloqueado manualmente por el administrador."

    if hasattr(cliente, "estado"):
        cliente.estado = "inactivo"

    cliente.save()

    try:
        Bitacora.objects.create(
            usuario=usuario_actual,
            accion=f"BLOQUEÓ CLIENTE ID={cliente.id}",
            fecha=timezone.now(),
        )
    except Exception:
        pass

    messages.success(request, "Cliente bloqueado correctamente.")
    return redirect("gestion_clientes")

@requerir_rol("administrador")
def desbloquear_cliente(request, cliente_id):
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

    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    regla_vigente = (
        ReglasPrestamo.objects.order_by("-fecha_actualizacion").first()
    )

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
                tarifa_mora = float(tarifa_mora_diaria)

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
        "regla": regla_vigente,
        "historial_reglas": historial_reglas,
    }
    return render(request, "seguridad/reglas.html", contexto)

@requerir_rol("bibliotecario")
@csrf_protect
def inventario(request):

    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    editorial_preseleccionada = (request.GET.get("editorial") or "").strip()

    if request.method == "POST":

        if "agregar_libro" in request.POST:
            isbn = (request.POST.get("isbn") or "").strip()
            titulo = (request.POST.get("titulo") or "").strip()
            autor = (request.POST.get("autor") or "").strip()
            categoria = (request.POST.get("categoria") or "").strip()
            editorial = (request.POST.get("editorial") or "").strip()
            anio_publicacion = (request.POST.get("anio_publicacion") or "").strip()
            stock_raw = (request.POST.get("stock") or "0").strip()

            precio_raw = (request.POST.get("precio_venta") or "0").strip()
            impuesto_raw = (request.POST.get("impuesto_porcentaje") or "0").strip()

            portada = request.FILES.get("portada")

            if not (isbn and titulo and autor):
                messages.error(request, "ISBN, título y autor son obligatorios.")
                return redirect("inventario")

            if Libros.objects.filter(isbn=isbn).exists():
                messages.error(request, f"Ya existe un libro con ISBN {isbn}.")
                return redirect("inventario")

            try:
                stock_total = int(stock_raw)
            except ValueError:
                stock_total = 0

            try:
                precio_venta = Decimal(precio_raw)
            except (InvalidOperation, TypeError):
                precio_venta = Decimal("0.00")

            try:
                impuesto_porcentaje = Decimal(impuesto_raw)
            except (InvalidOperation, TypeError):
                impuesto_porcentaje = Decimal("0.00")

            libro = Libros.objects.create(
                isbn=isbn,
                titulo=titulo,
                autor=autor,
                categoria=categoria,
                editorial=editorial,
                anio_publicacion=anio_publicacion,
                stock_total=stock_total,
                portada=portada,
                fecha_registro=timezone.now(),
                precio_venta=precio_venta,
                impuesto_porcentaje=impuesto_porcentaje,
            )

            messages.success(request, f"Libro '{libro.titulo}' agregado correctamente.")

            if editorial:
                url = f"{reverse('inventario')}?editorial={editorial}"
                return redirect(url)

            return redirect("inventario")

        if "editar_libro" in request.POST:
            libro_id = request.POST.get("libro_id")
            libro = get_object_or_404(Libros, id=libro_id)

            libro.titulo = (request.POST.get("titulo") or "").strip()
            libro.autor = (request.POST.get("autor") or "").strip()
            libro.categoria = (request.POST.get("categoria") or "").strip()
            libro.editorial = (request.POST.get("editorial") or "").strip()
            libro.anio_publicacion = (request.POST.get("anio_publicacion") or "").strip()

            stock_raw = (request.POST.get("stock") or "0").strip()
            precio_raw = (request.POST.get("precio_venta") or "0").strip()
            impuesto_raw = (request.POST.get("impuesto_porcentaje") or "0").strip()

            try:
                libro.stock_total = int(stock_raw)
            except ValueError:
                libro.stock_total = 0

            try:
                libro.precio_venta = Decimal(precio_raw)
            except (InvalidOperation, TypeError):
                libro.precio_venta = Decimal("0.00")

            try:
                libro.impuesto_porcentaje = Decimal(impuesto_raw)
            except (InvalidOperation, TypeError):
                libro.impuesto_porcentaje = Decimal("0.00")

            portada = request.FILES.get("portada")
            if portada:
                libro.portada = portada

            libro.save()
            messages.success(request, f"Libro '{libro.titulo}' actualizado correctamente.")
            return redirect("inventario")

        messages.error(request, "Acción no reconocida en inventario.")
        return redirect("inventario")

    query = (request.GET.get("q") or "").strip()

    libros_qs = Libros.objects.all().order_by("-fecha_registro", "titulo")

    if query:
        libros_qs = libros_qs.filter(
            Q(titulo__icontains=query)
            | Q(autor__icontains=query)
            | Q(isbn__icontains=query)
            | Q(categoria__icontains=query)
        )

    editoriales = (
        Libros.objects
        .exclude(editorial__isnull=True)
        .exclude(editorial__exact="")
        .values_list("editorial", flat=True)
        .distinct()
        .order_by("editorial")
    )

    paginator = Paginator(libros_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    contexto = {
        "usuario_actual": usuario_actual,
        "page_obj": page_obj,
        "query": query,
        "editoriales": editoriales,
        "editorial_preseleccionada": editorial_preseleccionada,
    }
    return render(request, "seguridad/inventario.html", contexto)


@requerir_rol("bibliotecario")
def gestion_prestamos(request):

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

    base = f"EJ-{libro.id}-"
    codigo = None

    for _ in range(10):
        sufijo = random.randint(1000, 9999)
        candidato = f"{base}{sufijo}"
        if not Ejemplares.objects.filter(codigo_interno=candidato).exists():
            codigo = candidato
            break

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

        libro.stock_total = (libro.stock_total or 0) - 1
        libro.save()

        ejemplar = _crear_ejemplar_para_libro(libro)

        fecha_fin = fecha_inicio + timedelta(days=regla.plazo_dias)

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

#------------------------ Ventas --------------------------

@requerir_rol("bibliotecario")
@csrf_protect
def realizar_venta(request):
    
    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    if request.method == "POST":
        solicitud_id = request.POST.get("solicitud_id")
        metodo_pago = (request.POST.get("metodo_pago") or "").strip()

        if not solicitud_id or not metodo_pago:
            messages.error(request, "Debes seleccionar la solicitud y el método de pago.")
            return redirect("realizar_venta")

        solicitud = get_object_or_404(
            SolicitudVenta.objects.select_related(
                "cliente",
                "cliente__usuario",
                "libro",
                "reserva",
            ),
            id=solicitud_id,
        )

        if solicitud.estado != "pendiente":
            messages.error(request, "Esta solicitud ya fue atendida o cancelada.")
            return redirect("realizar_venta")

        libro = solicitud.libro
        cliente = solicitud.cliente
        cantidad = solicitud.cantidad or 1

        stock_disponible = libro.stock_total or 0
        if stock_disponible < cantidad:
            messages.error(
                request,
                f"No hay suficiente stock para '{libro.titulo}'. "
                f"Disponible: {stock_disponible}, requerido: {cantidad}."
            )
            return redirect("realizar_venta")

        precio_unitario = libro.precio_venta or Decimal("0.00")
        porcentaje_impuesto = libro.impuesto_porcentaje or Decimal("0.00")

        impuesto_unitario = precio_unitario * porcentaje_impuesto / Decimal("100")
        subtotal = precio_unitario * cantidad
        impuesto_total = impuesto_unitario * cantidad
        total = subtotal + impuesto_total

        with transaction.atomic():
            venta = Ventas.objects.create(
                cliente=cliente,
                vendedor=usuario_actual,
                metodo_pago=metodo_pago,
                subtotal=subtotal,
                impuesto=impuesto_total,
                total=total,
                estado="pagada",
            )

            DetalleVenta.objects.create(
                venta=venta,
                libro=libro,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                impuesto_unitario=impuesto_unitario,
                total_linea=total,
            )

            libro.stock_total = stock_disponible - cantidad
            libro.save()

            solicitud.estado = "atendida"
            solicitud.save()

            if solicitud.reserva:
                solicitud.reserva.estado = "facturada"
                solicitud.reserva.save()

        messages.success(
            request,
            f"Venta #{venta.id} registrada para {cliente.usuario.nombre} "
            f"{cliente.usuario.apellido}. Total L. {total}."
        )
        return redirect("realizar_venta")

    solicitudes = (
        SolicitudVenta.objects
        .select_related("cliente", "cliente__usuario", "libro")
        .filter(estado="pendiente")
        .order_by("fecha_solicitud")
    )

    contexto = {
        "usuario_actual": usuario_actual,
        "solicitudes": solicitudes,
    }
    return render(request, "seguridad/realizar_venta.html", contexto)

def _generar_factura_pdf(venta):

    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    width, height = letter
    x_margin = 40
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x_margin, y, "BiblioNet - Factura")
    y -= 30

    c.setFont("Helvetica", 10)
    c.drawString(x_margin, y, f"N° factura: {venta.id}")
    y -= 15
    c.drawString(x_margin, y, f"Fecha: {venta.fecha_venta.strftime('%d/%m/%Y %H:%M')}")
    y -= 15

    cliente = venta.cliente
    c.drawString(x_margin, y, f"Cliente: {cliente.usuario.nombre} {cliente.usuario.apellido}")
    y -= 15
    c.drawString(x_margin, y, f"DNI: {cliente.dni}")
    y -= 15

    c.drawString(x_margin, y, f"Vendedor: {venta.vendedor.nombre} {venta.vendedor.apellido}")
    y -= 25

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Detalle de la venta")
    y -= 20

    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_margin, y, "Libro")
    c.drawString(x_margin + 220, y, "Cant.")
    c.drawString(x_margin + 260, y, "P. Unit")
    c.drawString(x_margin + 340, y, "Impuesto")
    c.drawString(x_margin + 420, y, "Total")
    y -= 15
    c.line(x_margin, y, width - x_margin, y)
    y -= 15

    c.setFont("Helvetica", 9)
    for det in venta.detalles.all():
        if y < 100:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 9)

        c.drawString(x_margin, y, det.libro.titulo[:30])
        c.drawString(x_margin + 220, y, str(det.cantidad))
        c.drawRightString(x_margin + 310, y, f"L. {det.precio_unitario:.2f}")
        c.drawRightString(x_margin + 390, y, f"{det.impuesto_unitario:.2f}%")
        c.drawRightString(x_margin + 480, y, f"L. {det.total_linea:.2f}")
        y -= 15

    y -= 20
    c.line(x_margin, y, width - x_margin, y)
    y -= 15

    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(x_margin + 400, y, "Subtotal:")
    c.drawRightString(x_margin + 480, y, f"L. {venta.subtotal:.2f}")
    y -= 15

    c.drawRightString(x_margin + 400, y, "Impuesto:")
    c.drawRightString(x_margin + 480, y, f"L. {venta.impuesto:.2f}")
    y -= 15

    c.drawRightString(x_margin + 400, y, "Total:")
    c.drawRightString(x_margin + 480, y, f"L. {venta.total:.2f}")
    y -= 30

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(x_margin, y, "Gracias por su compra.")

    c.showPage()
    c.save()

    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="factura_{venta.id}.pdf"'
    response.write(pdf)
    return response


def historial_ventas(request):
    
    usuario_id = request.session.get("id_usuario")
    if not usuario_id:
        return redirect("cerrar_sesion")

    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(id=usuario_id)
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    if usuario_actual.rol.nombre != "administrador":
        return redirect("panel_bibliotecario")

    ventas_qs = (
        Ventas.objects
        .select_related("cliente__usuario", "vendedor")
        .order_by("-id")
    )

    q = (request.GET.get("q") or "").strip()
    estado = (request.GET.get("estado") or "").strip()

    if q:
        ventas_qs = ventas_qs.filter(
            Q(cliente__dni__icontains=q) |
            Q(cliente__usuario__nombre__icontains=q) |
            Q(cliente__usuario__apellido__icontains=q) |
            Q(vendedor__nombre__icontains=q) |
            Q(vendedor__apellido__icontains=q) |
            Q(id__icontains=q)
        )

    if estado:
        ventas_qs = ventas_qs.filter(estado__iexact=estado)

    total_ventas = ventas_qs.count()
    total_monto = ventas_qs.aggregate(suma=Sum("total"))["suma"] or Decimal("0.00")

    paginator = Paginator(ventas_qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    contexto = {
        "usuario_actual": usuario_actual,
        "page_obj": page_obj,
        "query": q,
        "estado_filtro": estado,
        "total_ventas": total_ventas,
        "total_monto": total_monto,
    }

    return render(request, "seguridad/historial_ventas.html", contexto)


@csrf_protect
def historial_compras_cliente(request):
    """
    Muestra todas las ventas/facturaciones realizadas al cliente logueado.
    """
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para ver tu historial de compras.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    usuario = cliente.usuario

    ventas_qs = (
        Ventas.objects
        .select_related("cliente__usuario", "vendedor")
        .filter(cliente=cliente)
        .filter(estado__iexact="pagada")
        .order_by("-id")
    )

    q = (request.GET.get("q") or "").strip()
    if q:
        ventas_qs = ventas_qs.filter(
            Q(id__icontains=q) |
            Q(metodo_pago__icontains=q) |
            Q(vendedor__nombre__icontains=q) |
            Q(vendedor__apellido__icontains=q)
        )

    total_compras = ventas_qs.count()
    total_gastado = ventas_qs.aggregate(suma=Sum("total"))["suma"] or Decimal("0.00")

    paginator = Paginator(ventas_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    contexto = {
        "cliente": cliente,
        "usuario": usuario,
        "page_obj": page_obj,
        "total_compras": total_compras,
        "total_gastado": total_gastado,
        "query": q,
    }

    return render(request, "clientes/historial_compras_cliente.html", contexto)


# ----------------------- Facturacion ----------------------

@requerir_rol("bibliotecario")
@csrf_protect
def facturar_solicitud(request, solicitud_id):
    
    if request.method != "POST":
        return redirect("realizar_venta")

    try:
        usuario_actual = Usuarios.objects.select_related("rol").get(
            id=request.session.get("id_usuario")
        )
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    solicitud = get_object_or_404(
        SolicitudVenta.objects.select_related(
            "cliente",
            "cliente__usuario",
            "libro",
            "reserva",
        ),
        id=solicitud_id,
    )

    if solicitud.estado != "pendiente":
        messages.info(
            request,
            "Esta solicitud de venta ya fue procesada o cancelada."
        )
        return redirect("realizar_venta")

    cliente = solicitud.cliente
    libro = solicitud.libro
    cantidad = solicitud.cantidad or 1

    if libro.stock_total is None or libro.stock_total < cantidad:
        messages.error(
            request,
            f"No hay suficiente stock para '{libro.titulo}'. "
            f"Stock actual: {libro.stock_total or 0}."
        )
        return redirect("realizar_venta")

    precio_unit = libro.precio_venta or Decimal("0.00")
    impuesto_pct = libro.impuesto_porcentaje or Decimal("0.00")

    subtotal = (precio_unit * cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    impuesto = (subtotal * (impuesto_pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = subtotal + impuesto

    metodo_pago = (request.POST.get("metodo_pago") or "Efectivo").strip() or "Efectivo"

    with transaction.atomic():
        venta = Ventas.objects.create(
            cliente=cliente,
            vendedor=usuario_actual,
            metodo_pago=metodo_pago,
            subtotal=subtotal,
            impuesto=impuesto,
            total=total,
            estado="pagada",
        )

        DetalleVenta.objects.create(
            venta=venta,
            libro=libro,
            cantidad=cantidad,
            precio_unitario=precio_unit,
            impuesto_unitario=impuesto_pct,
            total_linea=total,
        )

        libro.stock_total = (libro.stock_total or 0) - cantidad
        if libro.stock_total < 0:
            libro.stock_total = 0
        libro.save()

        if solicitud.reserva:
            solicitud.reserva.estado = "facturada"
            solicitud.reserva.save()

        solicitud.estado = "atendida"
        solicitud.save()

    try:
        return _generar_factura_pdf(venta)
    except ImportError:
        messages.warning(
            request,
            "La venta se registró correctamente, pero falta la librería "
            "reportlab para generar el PDF. Te mostramos la factura en pantalla."
        )
        return redirect("realizar_venta")

#--------------------- Seguridad ------------------------

def recuperar_contrasena_empleado(request):
    
    primer_ingreso_flag = (
        request.GET.get("primer_ingreso") == "1"
        or request.POST.get("primer_ingreso") == "1"
        or request.session.get("primer_ingreso") is True
    )

    email_precargado = (request.GET.get("email") or "").strip().lower()

    if request.method == "POST":
        step = request.POST.get("step", "1")
        if step == "1":
            return paso_1_verificar_correo(request)
        elif step == "2":
            return paso_2_nueva_contrasena(request)

    contexto = {"step": 1}

    if primer_ingreso_flag and email_precargado:
        contexto["email"] = email_precargado
        contexto["primer_ingreso"] = True

    return render(request, "seguridad/recuperar_contraseña.html", contexto)


def paso_1_verificar_correo(request):
    
    email = (request.POST.get("email") or "").strip().lower()
    primer_ingreso_flag = request.POST.get("primer_ingreso") == "1"

    if not email:
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 1,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": "Por favor, complete el correo electrónico.",
            },
        )

    try:
        usuario = (
            Usuarios.objects
            .select_related("rol")
            .filter(
                email=email,
                estado="activo",
                rol__nombre__in=["administrador", "bibliotecario"],
            )
            .first()
        )

        if not usuario:
            return render(
                request,
                "seguridad/recuperar_contraseña.html",
                {
                    "step": 1,
                    "email": email,
                    "primer_ingreso": primer_ingreso_flag,
                    "error": "No se encontró un empleado activo con ese correo.",
                },
            )

        # Correo válido → pasar a paso 2
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 2,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
            },
        )

    except Exception:
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 1,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": "Error en el sistema. Por favor, intente más tarde.",
            },
        )


def paso_2_nueva_contrasena(request):
    email = (request.POST.get("email") or "").strip().lower()
    new_password = request.POST.get("new_password", "")
    confirm_password = request.POST.get("confirm_password", "")
    primer_ingreso_flag = request.POST.get("primer_ingreso") == "1"

    if new_password != confirm_password:
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 2,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": "Las contraseñas no coinciden.",
            },
        )

    if not validar_fortaleza_contrasena(new_password):
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 2,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": (
                    "La contraseña debe tener al menos 8 caracteres, incluir una letra "
                    "mayúscula, una minúscula, un número y un carácter especial."
                ),
            },
        )

    try:
        usuario = (
            Usuarios.objects
            .select_related("rol")
            .filter(
                email=email,
                estado="activo",
                rol__nombre__in=["administrador", "bibliotecario"],
            )
            .first()
        )

        if not usuario:
            return render(
                request,
                "seguridad/recuperar_contraseña.html",
                {
                    "step": 1,
                    "error": "Error en la recuperación. Por favor, inicie el proceso nuevamente.",
                },
            )

        usuario.clave = make_password(new_password)

        if primer_ingreso_flag or request.session.get("primer_ingreso"):
            if hasattr(usuario, "primer_ingreso"):
                usuario.primer_ingreso = False

        usuario.save()

        if "primer_ingreso" in request.session:
            del request.session["primer_ingreso"]

        contexto = {"step": 3}
        if primer_ingreso_flag:
            contexto[
                "mensaje_especial"
            ] = "¡Contraseña establecida! Ahora puedes acceder al sistema."

        return render(request, "seguridad/recuperar_contraseña.html", contexto)

    except DatabaseError:
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 2,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": "Error al guardar la nueva contraseña. Por favor, intente nuevamente.",
            },
        )
    except Exception:
        return render(
            request,
            "seguridad/recuperar_contraseña.html",
            {
                "step": 2,
                "email": email,
                "primer_ingreso": primer_ingreso_flag,
                "error": "Error inesperado. Intente nuevamente.",
            },
        )


def validar_fortaleza_contrasena(password):
    if len(password) < 8:
        return False

    tiene_mayuscula = any(c.isupper() for c in password)
    tiene_minuscula = any(c.islower() for c in password)
    tiene_numero = any(c.isdigit() for c in password)
    tiene_especial = any(not c.isalnum() for c in password)

    return (
        tiene_mayuscula
        and tiene_minuscula
        and tiene_numero
        and tiene_especial
    )

#------------------- Compras ---------------------

@requerir_rol("administrador")
@csrf_protect
def gestion_proveedores(request):
    try:
        usuario_actual = Usuarios.objects.get(id=request.session.get("id_usuario"))
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    query = (request.GET.get("q") or "").strip()

    proveedores_qs = Proveedores.objects.all().order_by("nombre_comercial")

    if query:
        proveedores_qs = proveedores_qs.filter(
            Q(nombre_comercial__icontains=query) |
            Q(rtn__icontains=query)
        )

    if request.method == "POST":
        if "agregar_proveedor" in request.POST:
            nombre_comercial = (request.POST.get("nombre_comercial") or "").strip()
            rtn = (request.POST.get("rtn") or "").strip()
            direccion = (request.POST.get("direccion") or "").strip()
            telefono = (request.POST.get("telefono") or "").strip()
            correo_contacto = (request.POST.get("correo_contacto") or "").strip()
            suministro = (request.POST.get("suministro") or "").strip()
            estado = (request.POST.get("estado") or "").strip() or "activo"

            if not nombre_comercial:
                messages.error(request, "El nombre comercial es obligatorio.")
                return redirect("gestion_proveedores")

            if not rtn:
                messages.error(request, "El RTN es obligatorio.")
                return redirect("gestion_proveedores")

            if not re.fullmatch(r"\d{14}", rtn):
                messages.error(request, "El RTN debe contener exactamente 14 dígitos numéricos.")
                return redirect("gestion_proveedores")

            if telefono:
                if not re.fullmatch(r"[2389]\d{7}", telefono):
                    messages.error(
                        request,
                        "El teléfono debe tener 8 dígitos y comenzar con 2, 3, 8 o 9."
                    )
                    return redirect("gestion_proveedores")

            if Proveedores.objects.filter(rtn=rtn).exists():
                messages.error(request, "Ya existe un proveedor con ese RTN.")
                return redirect("gestion_proveedores")

            Proveedores.objects.create(
                nombre_comercial=nombre_comercial,
                rtn=rtn,
                direccion=direccion or None,
                telefono=telefono or None,
                correo_contacto=correo_contacto or None,
                suministro=suministro or None,
                estado=estado,
            )

            messages.success(request, "Proveedor agregado correctamente.")
            return redirect("gestion_proveedores")

        if "editar_proveedor" in request.POST:
            proveedor_id = request.POST.get("proveedor_id")
            proveedor = get_object_or_404(Proveedores, id=proveedor_id)

            nombre_comercial = (request.POST.get("nombre_comercial") or "").strip()
            rtn = (request.POST.get("rtn") or "").strip()
            direccion = (request.POST.get("direccion") or "").strip()
            telefono = (request.POST.get("telefono") or "").strip()
            correo_contacto = (request.POST.get("correo_contacto") or "").strip()
            suministro = (request.POST.get("suministro") or "").strip()
            estado = (request.POST.get("estado") or "").strip() or "activo"

            if not nombre_comercial:
                messages.error(request, "El nombre comercial es obligatorio.")
                return redirect("gestion_proveedores")

            if not rtn:
                messages.error(request, "El RTN es obligatorio.")
                return redirect("gestion_proveedores")

            if not re.fullmatch(r"\d{14}", rtn):
                messages.error(request, "El RTN debe contener exactamente 14 dígitos numéricos.")
                return redirect("gestion_proveedores")

            if telefono:
                if not re.fullmatch(r"[2389]\d{7}", telefono):
                    messages.error(
                        request,
                        "El teléfono debe tener 8 dígitos y comenzar con 2, 3, 8 o 9."
                    )
                    return redirect("gestion_proveedores")

            if Proveedores.objects.filter(rtn=rtn).exclude(id=proveedor.id).exists():
                messages.error(request, "Ya existe otro proveedor con ese RTN.")
                return redirect("gestion_proveedores")

            proveedor.nombre_comercial = nombre_comercial
            proveedor.rtn = rtn
            proveedor.direccion = direccion or None
            proveedor.telefono = telefono or None
            proveedor.correo_contacto = correo_contacto or None
            proveedor.suministro = suministro or None
            proveedor.estado = estado
            proveedor.save()

            messages.success(request, "Proveedor actualizado correctamente.")
            return redirect("gestion_proveedores")

    paginator = Paginator(proveedores_qs, 10)
    page_number = request.GET.get("page")
    proveedores = paginator.get_page(page_number)

    contexto = {
        "proveedores": proveedores,
        "query": query,
        "usuario_actual": usuario_actual,
    }
    return render(request, "seguridad/proveedores.html", contexto)


def gestion_compras(request):
    # Verificar sesión
    try:
        usuario_actual = Usuarios.objects.get(id=request.session.get("id_usuario"))
    except Usuarios.DoesNotExist:
        return redirect("cerrar_sesion")

    query = (request.GET.get("q") or "").strip()
    fecha_desde = (request.GET.get("fecha_desde") or "").strip()
    fecha_hasta = (request.GET.get("fecha_hasta") or "").strip()

    # Base queryset (ya con proveedor, usuario y detalles)
    compras_qs = (
        Compras.objects
        .select_related("proveedor", "usuario")
        .prefetch_related("detalles__libro")
        .all()
        .order_by("-fecha", "-id")
    )

    # Filtros de búsqueda
    if query:
        compras_qs = compras_qs.filter(
            Q(proveedor__nombre_comercial__icontains=query) |
            Q(proveedor__rtn__icontains=query) |
            Q(numero_factura__icontains=query)
        )

    if fecha_desde:
        compras_qs = compras_qs.filter(fecha__date__gte=fecha_desde)

    if fecha_hasta:
        compras_qs = compras_qs.filter(fecha__date__lte=fecha_hasta)

    # ------------------------------
    # POST: crear o editar una compra
    # ------------------------------
    if request.method == "POST":

        if "agregar_compra" in request.POST:
            proveedor_nombre = (request.POST.get("proveedor_nombre") or "").strip()
            metodo_pago = (request.POST.get("metodo_pago") or "").strip()

            libro_ids = request.POST.getlist("libro_id[]")
            cantidades = request.POST.getlist("cantidad[]")
            costos = request.POST.getlist("costo_unitario[]")

            # ✅ Validar proveedor (solo activos)
            if not proveedor_nombre:
                messages.error(request, "Debe seleccionar un proveedor.")
                return redirect("gestion_compras")

            try:
                proveedor = Proveedores.objects.get(
                    nombre_comercial=proveedor_nombre,
                    estado="activo"
                )
            except Proveedores.DoesNotExist:
                messages.error(
                    request,
                    "El proveedor indicado no existe o no está activo."
                )
                return redirect("gestion_compras")
            except Proveedores.MultipleObjectsReturned:
                messages.error(
                    request,
                    "Existe más de un proveedor con ese nombre. "
                    "Use nombres únicos o edite los proveedores."
                )
                return redirect("gestion_compras")

            # Validar método de pago
            if not metodo_pago:
                messages.error(request, "Debe seleccionar un método de pago.")
                return redirect("gestion_compras")

            # Validar ítems
            items = []
            for idx, libro_id in enumerate(libro_ids):
                libro_id = (libro_id or "").strip()
                cant = (cantidades[idx] if idx < len(cantidades) else "").strip()
                costo = (costos[idx] if idx < len(costos) else "").strip()

                # Fila completamente vacía → la ignoramos
                if not (libro_id or cant or costo):
                    continue

                if not (libro_id and cant and costo):
                    messages.error(
                        request,
                        "Todas las filas deben tener libro, cantidad y costo unitario. "
                        "Elimine las filas que no vaya a usar."
                    )
                    return redirect("gestion_compras")

                libro = get_object_or_404(Libros, id=libro_id)

                try:
                    cant_int = int(cant)
                    costo_dec = float(costo)
                except ValueError:
                    messages.error(request, "Cantidad y costo unitario deben ser numéricos.")
                    return redirect("gestion_compras")

                if cant_int <= 0:
                    messages.error(request, "La cantidad debe ser mayor que cero.")
                    return redirect("gestion_compras")

                if costo_dec <= 0:
                    messages.error(request, "El costo unitario debe ser mayor que cero.")
                    return redirect("gestion_compras")

                subtotal = cant_int * costo_dec
                items.append({
                    "libro": libro,
                    "cantidad": cant_int,
                    "costo_unitario": costo_dec,
                    "subtotal": subtotal,
                })

            if not items:
                messages.error(request, "Debe agregar al menos un libro a la compra.")
                return redirect("gestion_compras")

            # Número de factura: SIEMPRE automático
            ultima = Compras.objects.order_by("-id").first()
            siguiente = (ultima.id if ultima else 0) + 1
            numero_factura = f"FAC-{siguiente:06d}"

            total_compra = sum(i["subtotal"] for i in items)

            # Guardar SOLO fecha (sin hora)
            fecha_hoy = timezone.now().date()

            try:
                compra = Compras.objects.create(
                    proveedor=proveedor,
                    usuario=usuario_actual,
                    numero_factura=numero_factura,
                    fecha=fecha_hoy,
                    total=total_compra,
                    metodo_pago=metodo_pago,
                )
            except Exception:
                messages.error(
                    request,
                    "Error al registrar la compra. Verifique que los datos sean correctos."
                )
                return redirect("gestion_compras")

            # Crear detalles y actualizar stock
            for item in items:
                DetalleCompras.objects.create(
                    compra=compra,
                    libro=item["libro"],
                    cantidad=item["cantidad"],
                    costo_unitario=item["costo_unitario"],
                    subtotal=item["subtotal"],
                )

                libro = item["libro"]
                libro.stock_total = (libro.stock_total or 0) + item["cantidad"]
                libro.save()

            # Bitácora
            Bitacora.objects.create(
                usuario=usuario_actual,
                accion=(
                    f"REGISTRÓ COMPRA id={compra.id} "
                    f"factura={compra.numero_factura} "
                    f"proveedor={compra.proveedor.nombre_comercial} "
                    f"total={compra.total}"
                ),
                fecha=timezone.now(),
            )

            messages.success(request, "La compra se registró correctamente.")
            return redirect("gestion_compras")

        # ==========================
        # ✏️ EDITAR COMPRA
        # ==========================
        if "editar_compra" in request.POST:
            compra_id = request.POST.get("compra_id")
            proveedor_nombre = (request.POST.get("proveedor_nombre") or "").strip()
            metodo_pago = (request.POST.get("metodo_pago") or "").strip()

            compra = get_object_or_404(Compras, id=compra_id)

            if not proveedor_nombre:
                messages.error(request, "Debe seleccionar un proveedor.")
                return redirect("gestion_compras")

            try:
                proveedor = Proveedores.objects.get(
                    nombre_comercial=proveedor_nombre,
                    estado="activo"
                )
            except Proveedores.DoesNotExist:
                messages.error(
                    request,
                    "El proveedor indicado no existe o no está activo."
                )
                return redirect("gestion_compras")
            except Proveedores.MultipleObjectsReturned:
                messages.error(
                    request,
                    "Existe más de un proveedor con ese nombre. "
                    "Use nombres únicos o edite los proveedores."
                )
                return redirect("gestion_compras")

            if not metodo_pago:
                messages.error(request, "Debe seleccionar un método de pago.")
                return redirect("gestion_compras")

            compra.proveedor = proveedor
            compra.metodo_pago = metodo_pago
            compra.save()

            Bitacora.objects.create(
                usuario=usuario_actual,
                accion=(
                    f"EDITÓ COMPRA id={compra.id} "
                    f"factura={compra.numero_factura} "
                    f"proveedor={compra.proveedor.nombre_comercial} "
                    f"total={compra.total}"
                ),
                fecha=timezone.now(),
            )

            messages.success(request, "La compra se actualizó correctamente.")
            return redirect("gestion_compras")

    # ------------------------------
    # GET / después de procesar POST
    # ------------------------------
    paginator = Paginator(compras_qs, 10)
    page_number = request.GET.get("page")
    compras = paginator.get_page(page_number)

    # Solo proveedores ACTIVOS para los selects del HTML
    proveedores = Proveedores.objects.filter(estado="activo").order_by("nombre_comercial")
    libros = Libros.objects.all().order_by("titulo")

    context = {
        "compras": compras,
        "query": query,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "proveedores": proveedores,
        "libros": libros,
        "usuario_actual": usuario_actual,
    }

    return render(request, "seguridad/gestion_compras.html", context)


@requerir_rol("administrador")
def comprobante_compra_pdf(request, compra_id):
    compra = get_object_or_404(
        Compras.objects
        .select_related("proveedor", "usuario")
        .prefetch_related("detalles__libro"),
        id=compra_id,
    )

    return _generar_comprobante_compra_pdf(compra)


def _generar_comprobante_compra_pdf(compra):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    width, height = letter
    x_margin = 40
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x_margin, y, "BiblioNet")
    y -= 22
    c.setFont("Helvetica", 12)
    c.drawString(x_margin, y, "Comprobante de compra")
    y -= 30

    c.setFont("Helvetica", 10)
    c.drawString(x_margin, y, f"N° factura: {compra.numero_factura}")
    y -= 15

    if compra.fecha:
        c.drawString(x_margin, y, f"Fecha de compra: {compra.fecha.strftime('%d/%m/%Y')}")
    else:
        c.drawString(x_margin, y, "Fecha de compra: —")
    y -= 15

    metodo = compra.metodo_pago or "—"
    c.drawString(x_margin, y, f"Método de pago: {metodo}")
    y -= 15

    if compra.usuario:
        c.drawString(
            x_margin,
            y,
            f"Registrado por: {compra.usuario.nombre} {compra.usuario.apellido}"
        )
    else:
        c.drawString(x_margin, y, "Registrado por: —")
    y -= 25

    proveedor = compra.proveedor
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Proveedor")
    y -= 18

    c.setFont("Helvetica", 10)
    c.drawString(x_margin, y, f"Nombre comercial: {proveedor.nombre_comercial}")
    y -= 15
    c.drawString(x_margin, y, f"RTN: {proveedor.rtn}")
    y -= 15

    tel = proveedor.telefono or "—"
    c.drawString(x_margin, y, f"Teléfono: {tel}")
    y -= 15

    direccion = proveedor.direccion or "—"
    c.drawString(x_margin, y, f"Dirección: {direccion}")
    y -= 25

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Libros de la compra")
    y -= 20

    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_margin, y, "Libro")
    c.drawString(x_margin + 260, y, "Cant.")
    c.drawRightString(x_margin + 360, y, "Costo unit.")
    c.drawRightString(x_margin + 460, y, "Subtotal")
    y -= 12
    c.line(x_margin, y, width - x_margin, y)
    y -= 14

    c.setFont("Helvetica", 9)
    detalles = list(compra.detalles.all())

    if not detalles:
        c.drawString(x_margin, y, "No hay libros registrados en esta compra.")
        y -= 20
    else:
        for det in detalles:
            if y < 80:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 9)

            titulo = det.libro.titulo if det.libro else "—"
            if det.libro and det.libro.isbn:
                titulo = f"{titulo} ({det.libro.isbn})"
            c.drawString(x_margin, y, titulo[:55])

            c.drawString(x_margin + 260, y, str(det.cantidad))

            c.drawRightString(
                x_margin + 360,
                y,
                f"L. {det.costo_unitario:.2f}"
            )

            c.drawRightString(
                x_margin + 460,
                y,
                f"L. {det.subtotal:.2f}"
            )
            y -= 14

    y -= 10
    c.line(x_margin, y, width - x_margin, y)
    y -= 18

    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(x_margin + 360, y, "Total compra (L.):")
    c.drawRightString(x_margin + 460, y, f"L. {compra.total:.2f}")
    y -= 25

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(x_margin, y, "Comprobante generado por BiblioNet.")

    c.showPage()
    c.save()

    pdf = buffer.getvalue()
    buffer.close()

    filename = f"comprobante_{compra.numero_factura}.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response
