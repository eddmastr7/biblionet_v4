from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.db import transaction
from biblio.models import Usuarios, Roles, Clientes
from django.views.decorators.csrf import csrf_protect

def inicio(request):
    # Renderiza tu plantilla: biblio/templates/publico/pagina_inicio.html
    return render(request, "publico/pagina_inicio.html")

def catalogo(request):
    # Soporta búsqueda ?q=...
    q = (request.GET.get("q") or "").strip().lower()

    # Datos de ejemplo mientras conectas a la BD
    base = [
        {"titulo": " ", "autor": " ", "descripcion": " ", "disponible": True,  "imagen_url": ""},
        {"titulo": " ", "autor": " ", "descripcion": " ", "disponible": False, "imagen_url": ""},
        {"titulo": " ", "autor": " ", "descripcion": " ", "disponible": True,  "imagen_url": ""},
    ]

    if q:
        libros = [l for l in base if q in l["titulo"].lower() or q in l["autor"].lower() or q in (l["descripcion"] or "").lower()]
    else:
        libros = base

    ctx = {
        "libros": libros,
        "total_libros": len(libros),
    }
    # biblio/templates/publico/catalogo.html
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
        dni = request.POST.get("dni","").strip()
        telefono = request.POST.get("telefono","").strip()
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
                    dni=dni,
                    direccion=email,  
                    telefono=telefono,
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

