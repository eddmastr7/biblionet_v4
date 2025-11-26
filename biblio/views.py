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
    # Detectar si hay cliente logueado por sesión
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
    """
    Devuelve (cliente, usuario_cliente) si hay cliente logueado en la sesión,
    si no, (None, None).
    """
    cliente = None
    usuario_cliente = None

    cliente_id = request.session.get("cliente_id")
    if cliente_id:
        try:
            cliente = Clientes.objects.select_related("usuario").get(
                id=cliente_id,
                estado__iexact="activo",
            )
            usuario_cliente = cliente.usuario
        except Clientes.DoesNotExist:
            pass

    return cliente, usuario_cliente


def catalogo(request):
    # ⬇️ info de cliente logueado (según nuestra sesión propia)
    cliente, usuario_cliente = _obtener_cliente_sesion(request)

    q = (request.GET.get("q") or "").strip()
    categoria = (request.GET.get("categoria") or "").strip()
    estado = (request.GET.get("estado") or "").strip()
    orden = (request.GET.get("orden") or "recientes").strip()

    # Base
    libros_qs = Libros.objects.all()

    # Buscar por título o autor
    if q:
        libros_qs = (
            libros_qs.filter(titulo__icontains=q)
            | libros_qs.filter(autor__icontains=q)
        ).distinct()

    # Filtrar por categoría (sin perder lo anterior)
    if categoria:
        libros_qs = libros_qs.filter(categoria__icontains=categoria)

    # Filtrar por estado usando stock_total directo
    if estado == "disponible":
        libros_qs = libros_qs.filter(stock_total__gt=0)
    elif estado == "prestado":
        libros_qs = libros_qs.filter(stock_total__lte=0)

    # Orden
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
        # ⬇️ para que el template sepa si hay cliente logueado
        "cliente": cliente,
        "usuario_cliente": usuario_cliente,
    }

    return render(request, "publico/catalogo.html", ctx)


def acerca_de(request):
    clientes_activos = Clientes.objects.filter(estado__iexact="activo").count()

    # Detectar si hay cliente logueado
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
    # Detecta hash común de Django
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

        # Validaciones mínimas - usando messages para errores
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

        # Crear usuario cliente
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
                    direccion=email,  # por ahora reusamos el correo como dirección
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
    """
    Login de clientes usando la tabla Usuarios (campo 'clave').
    - Busca usuario por email y estado='activo'
    - Valida contraseña (soporta texto plano o hash pbkdf2/bcrypt/argon2)
    - Verifica que exista un Cliente asociado
    - Guarda datos básicos en sesión y redirige a pantalla_inicio_cliente
    """
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""

        if not email or not password:
            contexto = {"error": "Debes ingresar correo y contraseña."}
            return render(request, "publico/login_cliente.html", contexto)

        # 1) Buscar usuario por email
        try:
            usuario = Usuarios.objects.get(
                email__iexact=email,
                estado__iexact="activo",
            )
        except Usuarios.DoesNotExist:
            contexto = {"error": "Correo o contraseña incorrectos."}
            return render(request, "publico/login_cliente.html", contexto)

        # 2) Tomar la contraseña desde el campo 'clave'
        clave_db = getattr(usuario, "clave", None)

        if not clave_db:
            contexto = {
                "error": (
                    "No se encontró el campo de contraseña en el usuario. "
                    "Contacta al administrador del sistema."
                )
            }
            return render(request, "publico/login_cliente.html", contexto)

        # 3) Verificar contraseña
        password_ok = False

        # Si parece hash de Django (pbkdf2_ / argon2 / bcrypt), usamos check_password
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
            # Caso simple: se guarda en texto plano
            password_ok = (password == clave_db)

        if not password_ok:
            contexto = {"error": "Correo o contraseña incorrectos."}
            return render(request, "publico/login_cliente.html", contexto)

        # 4) Verificar que ese usuario tenga un Cliente asociado
        cliente = Clientes.objects.filter(usuario=usuario).first()
        if not cliente:
            contexto = {
                "error": (
                    "Tu usuario no está asociado a un cliente en el sistema. "
                    "Acércate a la biblioteca para que te registren correctamente."
                )
            }
            return render(request, "publico/login_cliente.html", contexto)

        # 5) Guardar datos en sesión (el bloqueo lo usamos SOLO para reservas/préstamos)
        request.session["cliente_id"] = cliente.id
        request.session["cliente_nombre"] = usuario.nombre
        request.session["cliente_email"] = usuario.email
        request.session["cliente_bloqueado"] = bool(cliente.bloqueado)

        return redirect("pantalla_inicio_cliente")

    # GET: solo mostrar el formulario
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

    # Traemos cliente + su usuario asociado
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

        # Validación básica
        if not (nombre and apellido and email):
            messages.error(request, "Nombre, apellido y correo son obligatorios.")
        else:
            # Validar que el correo no esté usado por otro usuario
            email_en_uso = (
                Usuarios.objects.filter(email__iexact=email)
                .exclude(id=usuario.id)
                .exists()
            )
            if email_en_uso:
                messages.error(request, "El correo ingresado ya está en uso por otro usuario.")
            else:
                # Guardar cambios
                usuario.nombre = nombre
                usuario.apellido = apellido
                usuario.email = email
                usuario.save()

                cliente.direccion = direccion
                cliente.save()

                # Refrescar datos básicos en la sesión (si los usas)
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
    # Verificar que el cliente está logueado
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
    """
    Cierra la sesión del cliente (limpia la sesión) 
    y lo regresa a la página de inicio pública.
    """
    request.session.flush()  # borra todos los datos de la sesión
    messages.success(request, "Has cerrado sesión correctamente.")
    return redirect("inicio")  # o "inicio_sesion_cliente" si quieres mandarlo al login


def lista_reservas_clientes(request):
    """
    Muestra las reservas activas del cliente logueado.
    """
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
    """
    Muestra al cliente todos sus préstamos:
    - pestaña de préstamos activos
    - pestaña de historial (devueltos, vencidos, etc.)
    """
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para ver tu historial de préstamos.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    usuario = cliente.usuario  # FK hacia Usuarios

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
    """
    Crea una reserva para el cliente logueado sobre el libro indicado.
    Luego redirige a la lista de reservas del cliente.
    """
    # Verificar que el cliente esté logueado (usamos la sesión, no auth de Django)
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para reservar un libro.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    libro = get_object_or_404(Libros, id=libro_id)

    # 🔒 Bloquear reservas de clientes con mora o bloqueo administrativo
    if actualizar_bloqueo_por_mora(cliente):
        messages.error(
            request,
            "No puedes reservar libros porque tu cuenta está bloqueada "
            "(por mora o por decisión administrativa). "
            "Acércate a la biblioteca para regularizar tu situación."
        )
        return redirect("lista_reservas_clientes")

    # Solo aceptamos POST desde el formulario del catálogo/detalle
    if request.method != "POST":
        return redirect("detalle_libro", libro_id=libro.id)

    # Evitar reservas duplicadas activas para el mismo libro y cliente
    ya_tiene_reserva = Reservas.objects.filter(
        cliente=cliente,
        libro=libro,
        estado__iexact="activa",
    ).exists()

    if ya_tiene_reserva:
        messages.info(request, "Ya tienes una reserva activa para este libro.")
        return redirect("lista_reservas_clientes")

    ahora = timezone.now()
    fecha_vencimiento = ahora + timedelta(days=2)  # ajusta los días si quieres

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

    # Solo aceptamos POST
    if request.method != "POST":
        return redirect("lista_reservas_clientes")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])

    # Solo puede cancelar reservas que sean suyas
    reserva = get_object_or_404(
        Reservas,
        id=reserva_id,
        cliente=cliente,
    )

    # Si ya no está activa, no hacemos nada
    if reserva.estado and reserva.estado.lower() != "activa":
        messages.info(request, "Esta reserva ya no se encuentra activa.")
        return redirect("lista_reservas_clientes")

    reserva.estado = "cancelada"
    reserva.save()

    messages.success(request, "La reserva se canceló correctamente.")
    return redirect("lista_reservas_clientes")


@csrf_protect
def solicitar_factura_reserva(request, reserva_id):
    """
    El cliente pide que una reserva se facture.
    Crea una SolicitudVenta en estado 'pendiente'
    que verá el bibliotecario en 'Realizar Venta'.
    """
    # Debe estar logueado como cliente
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión para solicitar una factura.")
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])

    # Solo dejamos que el cliente dueño de la reserva la facture
    reserva = get_object_or_404(Reservas, id=reserva_id, cliente=cliente)

    # Solo aceptamos POST desde el botón "Facturar"
    if request.method != "POST":
        return redirect("lista_reservas_clientes")

    # Validar que la reserva esté activa y no vencida
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

    # Verificar stock disponible del libro
    if not libro.stock_total or libro.stock_total <= 0:
        messages.error(
            request,
            "No hay stock disponible para este libro. "
            "Consulta con la biblioteca antes de intentar la compra."
        )
        return redirect("lista_reservas_clientes")

    # Evitar solicitudes duplicadas para la misma reserva
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

    # Crear la solicitud de venta
    SolicitudVenta.objects.create(
        cliente=cliente,
        libro=libro,
        reserva=reserva,
        cantidad=1,
        origen="reserva",
        # estado queda por defecto "pendiente"
    )

    messages.success(
        request,
        "Tu solicitud de facturación fue enviada al área de ventas. "
        "Un bibliotecario procesará tu compra."
    )
    return redirect("lista_reservas_clientes")


@csrf_protect
def solicitar_factura_libro(request, libro_id):
    """
    El cliente pide comprar un libro directamente desde el detalle.
    Crea una SolicitudVenta en estado 'pendiente' (origen = 'detalle')
    que verá el bibliotecario en 'Realizar Venta'.
    """
    # Debe estar logueado como cliente
    if "cliente_id" not in request.session:
        messages.error(
            request,
            "Debes iniciar sesión para solicitar una factura."
        )
        return redirect("inicio_sesion_cliente")

    cliente = get_object_or_404(Clientes, id=request.session["cliente_id"])
    libro = get_object_or_404(Libros, id=libro_id)

    # Solo aceptamos POST desde el botón "Comprar / Facturar"
    if request.method != "POST":
        return redirect("detalle_libro", libro_id=libro.id)

    # Verificar stock disponible del libro
    if not libro.stock_total or libro.stock_total <= 0:
        messages.error(
            request,
            "No hay stock disponible para este libro. "
            "Consulta con la biblioteca antes de intentar la compra."
        )
        return redirect("detalle_libro", libro_id=libro.id)

    # Evitar solicitudes duplicadas para este cliente y libro
    ya_existe = SolicitudVenta.objects.filter(
        cliente=cliente,
        libro=libro,
        reserva__isnull=True,               # 👈 viene desde detalle, sin reserva
        estado__in=["pendiente", "en_proceso"],
    ).exists()

    if ya_existe:
        messages.info(
            request,
            "Ya tienes una solicitud de compra pendiente para este libro."
        )
        return redirect("pantalla_inicio_cliente")

    # Crear la solicitud de venta
    SolicitudVenta.objects.create(
        cliente=cliente,
        libro=libro,
        cantidad=1,
        origen="detalle",  # 👈 importante para distinguir el origen
        # estado = "pendiente" por defecto
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
        "cliente": cliente,  # None si no está logueado
    }
    return render(request, "publico/detalle_libro.html", contexto)


# ============ RECUPERAR CONTRASEÑA CLIENTE ============
def recuperar_contrasena_cliente(request):
    """
    Flujo de recuperación de contraseña para CLIENTES.
    Usa un template con pasos:
      - step 1: pedir correo
      - step 2: nueva contraseña
      - step 3: éxito
    """
    if request.method == "POST":
        step = request.POST.get("step", "1")

        if step == "1":
            return paso_1_verificar_email_cliente(request)
        elif step == "2":
            return paso_2_nueva_contrasena_cliente(request)

    # GET o step no válido -> mostrar paso 1
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
