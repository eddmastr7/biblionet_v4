from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator

from biblio.models import Usuarios, Roles, Clientes, Libros, Reservas

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
            libros_qs.filter(titulo__icontains=q) |
            libros_qs.filter(autor__icontains=q)
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
                estado__iexact="activo"
            )
            usuario_cliente = cliente.usuario
        except Clientes.DoesNotExist:
            pass

    return cliente, usuario_cliente


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
            messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
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
                    estado="activo"
                )
                
                cliente = Clientes.objects.create(
                    usuario=usuario,
                    dni=dni,
                    direccion=email,
                    estado="activo"
                )

            request.session["cliente_id"] = cliente.id
            request.session["cliente_email"] = usuario.email
            messages.success(request, "¡Cuenta creada con éxito! Ahora puedes iniciar sesión.")
            return redirect("inicio_sesion_cliente")
            
        except Exception as e:
            messages.error(request, f"Error al crear la cuenta: {str(e)}")
            return render(request, "publico/registro_cliente.html", {"form": form_data})

    return render(request, "publico/registro_cliente.html")

@csrf_protect
def inicio_sesion_cliente(request):
    ctx = {}
    if request.method == "POST":
        email = request.POST.get("email","").strip().lower()
        password = request.POST.get("password","")

        try:
            user = Usuarios.objects.select_related("rol").get(
                email=email, rol__nombre="cliente", estado="activo"
            )
            cliente = Clientes.objects.get(usuario=user)

        except Usuarios.DoesNotExist:
            ctx["error"] = "usuario no existente"
            return render(request, "publico/login_cliente.html", ctx)
        
        except Clientes.DoesNotExist:
            ctx["error"] = "usuario no existente"
            return render(request, "publico/login_cliente.html", ctx)
       
        # Soporta hash y texto plano (por si tienes datos viejos)
        ok = False
        if user.clave:
            if user.clave.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
                ok = check_password(password, user.clave)
            else:
                ok = (password == user.clave)

        if not ok:
            ctx["error"] = "contraseña incorrecta."
            return render(request, "publico/login_cliente.html", ctx)

        request.session["cliente_id"] = cliente.id
        request.session["cliente_email"] = user.email
        return redirect("pantalla_inicio_cliente")

    return render(request, "publico/login_cliente.html")

def pantalla_inicio_cliente(request):
    # Verificar que el cliente está logueado
    if "cliente_id" not in request.session:
        messages.error(request, "Debes iniciar sesión")
        return redirect("inicio_sesion_cliente")
    
    try:
        cliente = Clientes.objects.get(id=request.session["cliente_id"])
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
    # Limpiar la sesión
    if "cliente_id" in request.session:
        del request.session["cliente_id"]
    if "cliente_email" in request.session:
        del request.session["cliente_email"]
    
    messages.success(request, "Sesión cerrada correctamente")
    return redirect("inicio_sesion_cliente") 

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
        "cliente": cliente,               # None si no está logueado
    }
    return render(request, "publico/detalle_libro.html", contexto)

