# biblio/utils.py
from django.utils import timezone
from .models import Clientes, Prestamos

def actualizar_bloqueo_por_mora(cliente: Clientes) -> bool:
    """
    Revisa si el cliente tiene préstamos en mora.
    - Si tiene, lo marca bloqueado (si no lo estaba) con motivo automático.
    - Si ya no tiene mora y su motivo era solo por mora, lo desbloquea.
    Devuelve True si el cliente queda bloqueado, False si no.
    """
    hoy = timezone.now().date()

    tiene_prestamos_en_mora = Prestamos.objects.filter(
        cliente=cliente,
        fecha_devolucion__isnull=True,  # aún no devuelto
        fecha_fin__lt=hoy,              # fecha fin ya pasó -> mora
    ).exists()

    if tiene_prestamos_en_mora:
        if not cliente.bloqueado:
            cliente.bloqueado = True
            cliente.motivo_bloqueo = "Bloqueo automático por préstamos en mora."
            cliente.fecha_bloqueo = timezone.now()
            cliente.save(update_fields=["bloqueado", "motivo_bloqueo", "fecha_bloqueo"])
        return True
    else:
        # Si no tiene mora y el motivo era solo por mora, lo podemos desbloquear automático
        if cliente.bloqueado and cliente.motivo_bloqueo and "mora" in cliente.motivo_bloqueo.lower():
            cliente.bloqueado = False
            cliente.motivo_bloqueo = ""
            cliente.fecha_bloqueo = None
            cliente.save(update_fields=["bloqueado", "motivo_bloqueo", "fecha_bloqueo"])

        return cliente.bloqueado  # puede seguir bloqueado por otro motivo manual
