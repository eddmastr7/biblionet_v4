# catalogo/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q 
from django.contrib import messages 
from django.utils import timezone
from .models import Libro, Reserva # <<-- REVISAR ESTO: Asumo que estos son tus modelos
from biblio.models import Clientes, Usuarios # IMPORTANTE: Importar tus modelos de cliente

# VISTA DE RESERVA (IMPLEMENTACIÓN COMPLETA)

def solicitar_reserva(request, libro_pk):
    # **PRIMERO: VERIFICAR SESIÓN PERSONALIZADA DEL CLIENTE**
    if "cliente_id" not in request.session:
        messages.error(request, "Necesitas iniciar sesión para reservar.")
        # Redirige a tu URL de login de cliente
        return redirect("inicio_sesion_cliente") 
    
    if request.method == 'POST':
        try:
            # 1. Obtener los objetos del cliente y el libro usando la ID de la sesión
            cliente_id = request.session["cliente_id"]
            cliente = Clientes.objects.get(id=cliente_id)
            # Asumo que tu modelo 'Libro' en catalogo es igual al 'Libros' en biblio
            libro = get_object_or_404(Libro, pk=libro_pk) 
            
            # Validación de disponibilidad (asumo que tu modelo Libro tiene un campo 'stock_total')
            if libro.stock_total > 0:
                messages.warning(request, f'El libro "{libro.titulo}" está disponible y no requiere reserva.')
                return redirect('ficha_libro', pk=libro_pk)
            
            # 2. CRITERIO: Prevenir reservas duplicadas
            # Asumo que el campo de cliente en Reserva es un ForeignKey a Clientes
            if Reserva.objects.filter(cliente=cliente, libro=libro, estado='pendiente').exists():
                messages.info(request, f'Ya tienes una reserva pendiente para el libro "{libro.titulo}".')
                return redirect('ficha_libro', pk=libro_pk)

            # 3. Crear la Reserva
            Reserva.objects.create(
                cliente=cliente, 
                libro=libro,
                estado='pendiente', # Asumiendo un campo 'estado' en Reserva
                fecha_reserva=timezone.now(),
            )
            
            messages.success(request, f'¡Reserva del libro "{libro.titulo}" creada con éxito! Estás en la lista de espera.')
            # Redirige al listado de reservas del cliente
            return redirect('listado_reservas_clientes') 
            
        except Clientes.DoesNotExist:
            messages.error(request, "Error de sesión: Cliente no encontrado.")
            return redirect("inicio_sesion_cliente")
        except Exception as e:
            messages.error(request, f"Ocurrió un error al reservar: {e}")
            return redirect('ficha_libro', pk=libro_pk)

    # Si llega un GET, lo ignoramos o redirigimos
    return redirect('ficha_libro', pk=libro_pk)

# VISTA DE CATÁLOGO (sin cambios)
def catalogo_view(request):
    # ... (Tu código actual de catalogo_view)
    libros = Libro.objects.all()
    query = request.GET.get('q')
    disponible_filter = request.GET.get('disponible')
    
    if query:
        libros = libros.filter(Q(titulo__icontains=query) | Q(autor__icontains=query))
    if disponible_filter == 'si':
        libros = libros.filter(disponible=True)
    elif disponible_filter == 'no':
        libros = libros.filter(disponible=False)
        
    context = {'libros': libros, 'query': query}
    return render(request, 'catalogo/catalogo.html', context)


# VISTA DE FICHA (sin cambios)
def ficha_libro(request, pk):
    libro = get_object_or_404(Libro, pk=pk)
    context = {'libro': libro}
    return render(request, 'catalogo/ficha_libro.html', context)