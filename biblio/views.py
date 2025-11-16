from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.db import transaction
from biblio.models import Usuarios, Roles, Clientes, Libros
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator

def inicio(request):
    # Renderiza tu plantilla: biblio/templates/publico/pagina_inicio.html
    return render(request, "publico/pagina_inicio.html")

from django.core.paginator import Paginator
from django.shortcuts import render
from biblio.models import Libros

def catalogo(request):
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
    }

    return render(request, "publico/catalogo.html", ctx)



def acerca_de(request):
    clientes_activos=Clientes.objects.filter(estado__iexact="activo").count()

    contexto = {
          'clientes_activos': clientes_activos
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
        nombre = request.POST.get("nombre","").strip().lower()
        apellido = request.POST.get("apellido","").strip().lower()
        email = request.POST.get("email","").strip().lower()
        password = request.POST.get("password","")
        confirm = request.POST.get("confirm_password","")

        # Validaciones mínimas - usando messages para errores
        if not all([nombre, apellido, email, password, confirm]):
            messages.error(request, "Completa todos los campos obligatorios.")
            return render(request, "publico/registro_cliente.html", {"form": request.POST.copy()})
        
        if len(password) < 8:
            messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
            return render(request, "publico/registro_cliente.html", {"form": request.POST.copy()})
        
        if password != confirm:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, "publico/registro_cliente.html", {"form": request.POST.copy()})
        
        if Usuarios.objects.filter(email=email).exists():
            messages.error(request, "Ya existe una cuenta con ese correo.")
            return render(request, "publico/registro_cliente.html", {"form": request.POST.copy()})

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
                    direccion=email,
                    estado="activo"
                )

            request.session["cliente_id"] = cliente.id
            request.session["cliente_email"] = usuario.email
            messages.success(request, "¡Cuenta creada con éxito! Ahora puedes iniciar sesión.")
            return redirect("inicio_sesion_cliente")
            
        except Exception as e:
            messages.error(request, f"Error al crear la cuenta: {str(e)}")
            return render(request, "publico/registro_cliente.html", {"form": request.POST.copy()})

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
    # Sin funcionalidad, solo muestra el template
    return render(request, 'clientes/lista_reservas_clientes.html')