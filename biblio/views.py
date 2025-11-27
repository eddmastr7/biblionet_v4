from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.db import transaction, DatabaseError
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator

from .utils import actualizar_bloqueo_por_mora
from seguridad.views import validar_fortaleza_contrasena

from biblio.models import (
    Usuarios,
    Roles,
    Clientes,
    Libros,
    Reservas,
    Prestamos,
    SolicitudVenta,
)


def inicio(request):
    cliente = None
    if request.session.get("cliente_id"):
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                id=request.session["cliente_id"]
            )
        except Clientes.DoesNotExist:
            cliente = None

    return render(request, "publico/pagina_inicio.html", {"cliente": cliente})


def _obtener_cliente_sesion(request):
    cliente = None
    usuario_cliente = None

    cliente_id = request.session.get("cliente_id")
    if cliente_id:
        try:
            # 👉 SIN filtro por estado, así también vienen los bloqueados/inactivos
            cliente = Clientes.objects.select_related("usuario").get(id=cliente_id)
            usuario_cliente = cliente.usuario
        except Clientes.DoesNotExist:
            pass

    return cliente, usuario_cliente

def catalogo(request):
    cliente = None
    usuario_cliente = None

    cliente_id = request.session.get("cliente_id")
    if cliente_id:
        try:
            cliente = Clientes.objects.select_related("usuario").get(id=cliente_id)
            usuario_cliente = cliente.usuario  # nombre del FK al modelo Usuarios
        except Clientes.DoesNotExist:
            cliente = None
            usuario_cliente = None

    q = (request.GET.get("q") or "").strip()
    categoria = (request.GET.get("categoria") or "").strip()
    estado = (request.GET.get("estado") or "").strip()
    orden = (request.GET.get("orden") or "recientes").strip()

    libros_qs = Libros.objects.all()

    if q:
        libros_qs = (
            libros_qs.filter(titulo__icontains=q)
            | libros_qs.filter(autor__icontains=q)
        ).distinct()

    if categoria:
        libros_qs = libros_qs.filter(categoria__icontains=categoria)

    if estado == "disponible":
        libros_qs = libros_qs.filter(stock_total__gt=0)
    elif estado == "prestado":
        libros_qs = libros_qs.filter(stock_total__lte=0)

    if orden == "titulo_asc":
        libros_qs = libros_qs.order_by("titulo")
    elif orden == "titulo_desc":
        libros_qs = libros_qs.order_by("-titulo")
    elif orden == "autor_asc":
        libros_qs = libros_qs.order_by("autor", "titulo")
    elif orden == "antiguos":
        libros_qs = libros_qs.order_by("anio_publicacion", "titulo")
    else:
        libros_qs = libros_qs.order_by("-fecha_registro", "titulo")

    paginator = Paginator(libros_qs, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ctx = {
        "libros": page_obj.object_list,
        "page_obj": page_obj,
        "total_libros": paginator.count,
        "q": q,
        "categoria": categoria,
        "estado": estado,
        "orden": orden,
        "cliente": cliente,
        "usuario_cliente": usuario_cliente,
    }

    return render(request, "publico/catalogo.html", ctx)


def acerca_de(request):
    clientes_activos = Clientes.objects.filter(estado__iexact="activo").count()

    cliente = None
    if request.session.get("cliente_id"):
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                id=request.session["cliente_id"]
            )
        except Clientes.DoesNotExist:
            cliente = None

    contexto = {
        "clientes_activos": clientes_activos,
        "cliente": cliente,
    }

    return render(request, "publico/acerca_de.html", contexto)


def _password_ok(raw, stored):
    stored = stored or ""
    if stored.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
        return check_password(raw, stored)
    return raw == stored


# ---------- Registro de cliente ----------
def registro_cliente(request):
    if request.method == "POST":
        form_data = request.POST.copy()

        nombre = form_data.get("nombre", "").strip().lower()
        apellido = form_data.get("apellido", "").strip().lower()
        email = form_data.get("email", "").strip().lower()
        dni = form_data.get("dni", "").strip()
        password = form_data.get("password", "")
        confirm = form_data.get("confirm_password", "")

        if not all([nombre, apellido, email, dni, password, confirm]):
            messages.error(request, "Completa todos los campos obligatorios.")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

        if len(password) < 8:
            messages.error(
                request,
                "La contraseña debe tener al menos 8 caracteres."
            )
            return render(request, "publico/registro_cliente.html", {"form": form_data})

        if password != confirm:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

        if Usuarios.objects.filter(email=email).exists():
            messages.error(request, "Ya existe una cuenta con ese correo.")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

        if Clientes.objects.filter(dni=dni).exists():
            messages.error(request, "Ya existe un cliente registrado con ese DNI.")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

        try:
            with transaction.atomic():
                rol, _ = Roles.objects.get_or_create(nombre="cliente")

                usuario = Usuarios.objects.create(
                    rol=rol,
                    nombre=nombre,
                    apellido=apellido,
                    email=email,
                    clave=make_password(password),
                    estado="activo",
                )

                cliente = Clientes.objects.create(
                    usuario=usuario,
                    dni=dni,
                    direccion=email,
                    estado="activo",
                )

            request.session["cliente_id"] = cliente.id
            request.session["cliente_email"] = usuario.email
            messages.success(
                request,
                "¡Cuenta creada con éxito! Ahora puedes iniciar sesión."
            )
            return redirect("inicio_sesion_cliente")

        except Exception as e:
            messages.error(request, f"Error al crear la cuenta: {str(e)}")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

    return render(request, "publico/registro_cliente.html")


def inicio_sesion_cliente(request):
    
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""

        if not email or not password:
            contexto = {"error": "Debes ingresar correo y contraseña."}
            return render(request, "publico/login_cliente.html", contexto)

        try:
            usuario = Usuarios.objects.get(
                email__iexact=email,
                estado__iexact="activo",
            )
        except Usuarios.DoesNotExist:
            contexto = {"error": "Correo o contraseña incorrectos."}
            return render(request, "publico/login_cliente.html", contexto)

        clave_db = getattr(usuario, "clave", None)

        if not clave_db:
            contexto = {
                "error": (
                    "No se encontró el campo de contraseña en el usuario. "
                    "Contacta al administrador del sistema."
                )
            }
            return render(request, "publico/login_cliente.html", contexto)

        password_ok = False

        if (
            isinstance(clave_db, str)
            and (
                clave_db.startswith("pbkdf2_")
                or clave_db.startswith("argon2")
                or clave_db.startswith("bcrypt")
            )
        ):
            password_ok = check_password(password, clave_db)
        else:
            password_ok = (password == clave_db)

        if not password_ok:
            contexto = {"error": "Correo o contraseña incorrectos."}
            return render(request, "publico/login_cliente.html", contexto)

        cliente = Clientes.objects.filter(usuario=usuario).first()
        if not cliente:
            contexto = {
                "error": (
                    "Tu usuario no está asociado a un cliente en el sistema. "
                    "Acércate a la biblioteca para que te registren correctamente."
                )
            }
            return render(request, "publico/login_cliente.html", contexto)

        request.session["cliente_id"] = cliente.id
        request.session["cliente_nombre"] = usuario.nombre
        request.session["cliente_email"] = usuario.email
        request.session["cliente_bloqueado"] = bool(cliente.bloqueado)

        return redirect("pantalla_inicio_cliente")

    return render(request, "publico/login_cliente.html")


@csrf_protect
def configuracion_cliente(request):
    """
    Perfil / configuración del cliente:
    - Solo si hay cliente_id en sesión
    - Permite editar nombre, apellido, email y dirección
    - NO permite editar el DNI
    """
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para acceder a esta sección.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(
        Clientes.objects.select_related("usuario"),
        id=request.session["cliente_id"],
    )
    usuario = cliente.usuario

    if request.method == "POST":
        nombre = (request.POST.get("nombre") or "").strip()
        apellido = (request.POST.get("apellido") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        direccion = (request.POST.get("direccion") or "").strip()

        if not (nombre and apellido and email):
            messages.error(request, "Nombre, apellido y correo son obligatorios.")
        else:

            email_en_uso = (
                Usuarios.objects.filter(email__iexact=email)
                .exclude(id=usuario.id)
                .exists()
            )
            if email_en_uso:
                messages.error(request, "El correo ingresado ya está en uso por otro usuario.")
            else:
                usuario.nombre = nombre
                usuario.apellido = apellido
                usuario.email = email
                usuario.save()

                cliente.direccion = direccion
                cliente.save()

                request.session["cliente_nombre"] = usuario.nombre
                request.session["cliente_email"] = usuario.email

                messages.success(request, "Tus datos se actualizaron correctamente.")
                return redirect("configuracion_cliente")

    contexto = {
        "usuario": usuario,
        "cliente": cliente,
    }
    return render(request, "clientes/configuracion_cliente.html", contexto)


def pantalla_inicio_cliente(request):

    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión")
        return redirect("inicio_sesion_cliente")

    try:
        cliente = Clientes.objects.select_related("usuario").get(
            id=request.session["cliente_id"]
        )
        usuario = cliente.usuario

        context = {
            "cliente": cliente,
            "usuario": usuario,
        }
        return render(request, "clientes/pantalla_inicio_cliente.html", context)

    except Clientes.DoesNotExist:
        messages.error(request, "Cliente no encontrado")
        return redirect("inicio_sesion_cliente")


def cerrar_sesion_cliente(request):

    request.session.flush()
    messages.success(request, "Has cerrado sesión correctamente.")
    return redirect("inicio")


def lista_reservas_clientes(request):
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para ver tus reservas.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    usuario = cliente.usuario

    reservas = (
        Reservas.objects
        .select_related("libro")
        .filter(cliente=cliente, estado__iexact="activa")
        .order_by("-fecha_reserva")
    )

    contexto = {
        "cliente": cliente,
        "usuario": usuario,
        "reservas": reservas,
    }
    return render(request, "clientes/lista_reservas_clientes.html", contexto)


def historial_prestamos_cliente(request):
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para ver tu historial de préstamos.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    usuario = cliente.usuario

    prestamos_qs = (
        Prestamos.objects
        .select_related("ejemplar", "ejemplar__libro")
        .filter(cliente=cliente)
        .order_by("-fecha_inicio")
    )

    prestamos_activos = [p for p in prestamos_qs if p.estado == "activo"]
    prestamos_historicos = [p for p in prestamos_qs if p.estado != "activo"]

    contexto = {
        "cliente": cliente,
        "usuario": usuario,
        "prestamos_activos": prestamos_activos,
        "prestamos_historicos": prestamos_historicos,
    }
    return render(request, "clientes/historial_prestamos.html", contexto)


@csrf_protect
def reservar_libro(request, libro_id):

    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para reservar un libro.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    libro = get_object_or_404(Libros, id=libro_id)

    # 🔴 Bloqueo por estado manual (admin) o por mora
    if getattr(cliente, "bloqueado", False) or actualizar_bloqueo_por_mora(cliente):
        messages.error(
            request,
            "No puedes reservar libros porque tu cuenta está bloqueada "
            "(por mora o por decisión administrativa). "
            "Acércate a la biblioteca para regularizar tu situación."
        )
        return redirect("lista_reservas_clientes")

    if request.method != "POST":
        return redirect("detalle_libro", libro_id=libro.id)

    ya_tiene_reserva = Reservas.objects.filter(
        cliente=cliente,
        libro=libro,
        estado__iexact="activa",
    ).exists()

    if ya_tiene_reserva:
        messages.info(request, "Ya tienes una reserva activa para este libro.")
        return redirect("lista_reservas_clientes")

    ahora = timezone.now()
    fecha_vencimiento = ahora + timedelta(days=2)

    Reservas.objects.create(
        cliente=cliente,
        libro=libro,
        fecha_reserva=ahora,
        fecha_vencimiento=fecha_vencimiento,
        estado="activa",
    )

    messages.success(request, "Reserva realizada correctamente.")
    return redirect("lista_reservas_clientes")



@csrf_protect
def cancelar_reserva(request, reserva_id):
    """
    Cancela una reserva del cliente logueado.
    """
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para gestionar tus reservas.")
        return redirect("inicio_sesion_cliente")

    if request.method != "POST":
        return redirect("lista_reservas_clientes")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])

    reserva = get_object_or_404(
        Reservas,
        id=reserva_id,
        cliente=cliente,
    )

    if reserva.estado and reserva.estado.lower() != "activa":
        messages.info(request, "Esta reserva ya no se encuentra activa.")
        return redirect("lista_reservas_clientes")

    reserva.estado = "cancelada"
    reserva.save()

    messages.success(request, "La reserva se canceló correctamente.")
    return redirect("lista_reservas_clientes")


@csrf_protect
def solicitar_factura_reserva(request, reserva_id):

    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para solicitar una factura.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])

    reserva = get_object_or_404(Reservas, id=reserva_id, cliente=cliente)

    if request.method != "POST":
        return redirect("lista_reservas_clientes")

    ahora = timezone.now()
    if (
        not reserva.estado
        or reserva.estado.lower() != "activa"
        or (reserva.fecha_vencimiento and reserva.fecha_vencimiento < ahora)
    ):
        messages.error(
            request,
            "Esta reserva ya no está activa o se encuentra vencida. "
            "No es posible generar una solicitud de factura."
        )
        return redirect("lista_reservas_clientes")

    libro = reserva.libro

    if not libro.stock_total or libro.stock_total <= 0:
        messages.error(
            request,
            "No hay stock disponible para este libro. "
            "Consulta con la biblioteca antes de intentar la compra."
        )
        return redirect("lista_reservas_clientes")

    ya_existe = SolicitudVenta.objects.filter(
        reserva=reserva,
        estado__in=["pendiente", "en_proceso"],
    ).exists()

    if ya_existe:
        messages.info(
            request,
            "Ya existe una solicitud de factura pendiente para esta reserva."
        )
        return redirect("lista_reservas_clientes")

    SolicitudVenta.objects.create(
        cliente=cliente,
        libro=libro,
        reserva=reserva,
        cantidad=1,
        origen="reserva",
    )

    messages.success(
        request,
        "Tu solicitud de facturación fue enviada al área de ventas. "
        "Un bibliotecario procesará tu compra."
    )
    return redirect("lista_reservas_clientes")


@csrf_protect
def solicitar_factura_libro(request, libro_id):
    
    if "cliente_id" not in request.session:
        messages.error(
            request,
            "Debes iniciar sesión para solicitar una factura."
        )
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    libro = get_object_or_404(Libros, id=libro_id)

    if request.method != "POST":
        return redirect("detalle_libro", libro_id=libro.id)

    if not libro.stock_total or libro.stock_total <= 0:
        messages.error(
            request,
            "No hay stock disponible para este libro. "
            "Consulta con la biblioteca antes de intentar la compra."
        )
        return redirect("detalle_libro", libro_id=libro.id)

    ya_existe = SolicitudVenta.objects.filter(
        cliente=cliente,
        libro=libro,
        reserva__isnull=True,
        estado__in=["pendiente", "en_proceso"],
    ).exists()

    if ya_existe:
        messages.info(
            request,
            "Ya tienes una solicitud de compra pendiente para este libro."
        )
        return redirect("pantalla_inicio_cliente")

    SolicitudVenta.objects.create(
        cliente=cliente,
        libro=libro,
        cantidad=1,
        origen="detalle",
    )

    messages.success(
        request,
        "Tu solicitud de compra fue enviada al área de ventas. "
        "Un bibliotecario procesará tu venta."
    )
    return redirect("pantalla_inicio_cliente")


####### DETALLES DE LIBROS ########

def detalle_libro(request, libro_id):
    """
    Muestra la información completa de un libro del catálogo.
    Si hay cliente logueado (cliente_id en sesión), le permite reservar.
    """
    libro = get_object_or_404(Libros, id=libro_id)
    disponible = (libro.stock_total or 0) > 0

    cliente = None
    if request.session.get("cliente_id"):
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                id=request.session["cliente_id"]
            )
        except Clientes.DoesNotExist:
            cliente = None

    contexto = {
        "libro": libro,
        "disponible": disponible,
        "cliente": cliente,
    }
    return render(request, "publico/detalle_libro.html", contexto)


# ============ RECUPERAR CONTRASEÑA CLIENTE ============
def recuperar_contrasena_cliente(request):

    if request.method == "POST":
        step = request.POST.get("step", "1")

        if step == "1":
            return paso_1_verificar_email_cliente(request)
        elif step == "2":
            return paso_2_nueva_contrasena_cliente(request)

    return render(
        request,
        "publico/recuperar_contraseña_cliente.html",
        {"step": 1},
    )


def paso_1_verificar_email_cliente(request):
    """Paso 1 para clientes - verifica email"""
    email = (request.POST.get("email") or "").strip().lower()

    if not email:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 1,
                "email": email,
                "error": "Por favor, ingresa tu correo electrónico.",
            },
        )

    try:
        # Buscar usuario con rol CLIENTE y activo
        usuario = Usuarios.objects.get(
            email=email,
            estado="activo",
            rol__nombre__iexact="cliente",
        )

        # Email válido, pasar al paso 2
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 2,
                "email": email,
            },
        )

    except Usuarios.DoesNotExist:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 1,
                "email": email,
                "error": "El correo electrónico no existe o no corresponde a un cliente.",
            },
        )
    except Exception:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 1,
                "email": email,
                "error": "Error en el sistema. Por favor, intente más tarde.",
            },
        )


def paso_2_nueva_contrasena_cliente(request):
    """Paso 2 para clientes - establecer nueva contraseña"""
    email = (request.POST.get("email") or "").strip().lower()
    new_password = request.POST.get("new_password", "") or ""
    confirm_password = request.POST.get("confirm_password", "") or ""

    # Validaciones
    if new_password != confirm_password:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 2,
                "email": email,
                "error": "Las contraseñas no coinciden.",
            },
        )

    if not validar_fortaleza_contrasena(new_password):
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 2,
                "email": email,
                "error": (
                    "La contraseña debe tener al menos 8 caracteres, "
                    "incluir una letra mayúscula, una minúscula, "
                    "un número y un carácter especial."
                ),
            },
        )

    try:
        # Buscar usuario con rol CLIENTE y activo
        usuario = Usuarios.objects.get(
            email=email,
            estado="activo",
            rol__nombre__iexact="cliente",
        )

        # Actualizar la contraseña (campo 'clave')
        usuario.clave = make_password(new_password)
        usuario.save()

        # Paso 3: éxito
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {"step": 3},
        )

    except Usuarios.DoesNotExist:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 1,
                "error": "Error en la recuperación. Por favor, inicia el proceso nuevamente.",
            },
        )
    except DatabaseError:
        return render(
            request,
            "publico/recuperar_contraseña_cliente.html",
            {
                "step": 2,
                "email": email,
                "error": "Error al guardar la nueva contraseña. Por favor, intente nuevamente.",
            },
        )
