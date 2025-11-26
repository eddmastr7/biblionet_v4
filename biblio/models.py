from django.db import models


class Roles(models.Model):
    nombre = models.CharField(unique=True, max_length=50)
    descripcion = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'roles'


class Permisos(models.Model):
    modulo = models.CharField(max_length=100)
    accion = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'permisos'


class RolPermiso(models.Model):
    id = models.AutoField(primary_key=True)
    rol = models.ForeignKey(Roles, models.DO_NOTHING)
    permiso = models.ForeignKey(Permisos, models.DO_NOTHING)

    def __str__(self):
        return f"{self.rol} - {self.permiso}"

    class Meta:
        db_table = 'rol_permiso'


class Usuarios(models.Model):
    rol = models.ForeignKey(Roles, models.DO_NOTHING)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    email = models.CharField(unique=True, max_length=150)
    clave = models.CharField(max_length=255)
    estado = models.CharField(max_length=20, blank=True, null=True)
    fecha_creacion = models.DateTimeField(blank=True, null=True)

    # 🔹 Opcionales, tomados de la versión de tu compañera
    primer_ingreso = models.BooleanField(default=True)
    foto_perfil = models.ImageField(
        upload_to="perfiles/",
        blank=True,
        null=True
    )

    class Meta:
        db_table = 'usuarios'

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.email})"


class Bitacora(models.Model):
    usuario = models.ForeignKey(Usuarios, models.DO_NOTHING, blank=True, null=True)
    accion = models.CharField(max_length=255)
    fecha = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'bitacora'


class Clientes(models.Model):
    # Mantenemos tu relación 1 a 1 con Usuarios
    usuario = models.OneToOneField(Usuarios, on_delete=models.CASCADE)
    dni = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    estado = models.CharField(max_length=20, default="activo")

    # 🔹 Campo extra tomado de la versión de tu compañera
    telefono = models.CharField(max_length=20, blank=True, null=True)

    # 🔹 Campos de bloqueo que ya tenías
    bloqueado = models.BooleanField(default=False)
    motivo_bloqueo = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Ej: Mora en préstamos, incumplimiento de normas, etc."
    )
    fecha_bloqueo = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.usuario.nombre} {self.usuario.apellido} ({self.dni})"

    class Meta:
        db_table = 'clientes'


class Libros(models.Model):
    isbn = models.CharField(unique=True, max_length=20)
    titulo = models.CharField(max_length=255)
    autor = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    editorial = models.CharField(max_length=150, blank=True, null=True)
    anio_publicacion = models.TextField(blank=True, null=True)
    stock_total = models.IntegerField(blank=True, null=True)
    portada = models.ImageField(upload_to='portadas/', blank=True, null=True)
    fecha_registro = models.DateTimeField(blank=True, null=True)

    # 🔹 Campos que añadimos para ventas
    precio_venta = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Precio de venta al público (Lempiras)."
    )
    impuesto_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15.00,  # ISV por defecto
        help_text="Porcentaje de impuesto aplicado a este libro."
    )

    class Meta:
        db_table = 'libros'

    def __str__(self):
        return f"{self.titulo} ({self.isbn})"


class Ejemplares(models.Model):
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    codigo_interno = models.CharField(unique=True, max_length=50, blank=True, null=True)
    ubicacion = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'ejemplares'

    def __str__(self):
        return f"{self.codigo_interno} - {self.libro.titulo}"


class ReglasPrestamo(models.Model):
    plazo_dias = models.IntegerField()
    limite_prestamos = models.IntegerField()
    tarifa_mora_diaria = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    fecha_actualizacion = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'reglas_prestamo'

    def __str__(self):
        return f"Plazo: {self.plazo_dias} días - Límite: {self.limite_prestamos}"


class Prestamos(models.Model):
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    ejemplar = models.ForeignKey(Ejemplares, models.DO_NOTHING)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    fecha_devolucion = models.DateField(blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'prestamos'

    def __str__(self):
        return f"Préstamo #{self.id} - {self.ejemplar} - {self.cliente}"


class Reservas(models.Model):
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    fecha_reserva = models.DateTimeField(blank=True, null=True)
    fecha_vencimiento = models.DateTimeField(blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'reservas'

    def __str__(self):
        return f"Reserva #{self.id} - {self.libro} - {self.cliente}"


class CatalogoPublico(models.Model):
    id_libro = models.IntegerField(primary_key=True)
    titulo = models.CharField(max_length=255)
    autor = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, null=True, blank=True)
    editorial = models.CharField(max_length=150, null=True, blank=True)
    anio_publicacion = models.IntegerField(null=True, blank=True)
    portada = models.CharField(max_length=255, null=True, blank=True)
    total_ejemplares = models.IntegerField()
    disponibles = models.IntegerField()

    class Meta:
        db_table = 'catalogo_publico'
        managed = False  # VIEW en la BD

    def __str__(self):
        return self.titulo


# 🔹 NUEVO: Proveedores (de la versión de tu compañera)
class Proveedores(models.Model):
    id = models.AutoField(primary_key=True)
    nombre_comercial = models.CharField(max_length=150)
    rtn = models.CharField(max_length=50, unique=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    correo_contacto = models.CharField(max_length=150, blank=True, null=True)
    suministro = models.CharField(max_length=150, blank=True, null=True)
    estado = models.CharField(max_length=20, default="activo")
    fecha_registro = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "proveedores"

    def __str__(self):
        return self.nombre_comercial


# 🔹 NUEVO: Compras (cabecera)
class Compras(models.Model):
    id = models.AutoField(primary_key=True)
    proveedor = models.ForeignKey(
        Proveedores,
        on_delete=models.PROTECT,
        related_name="compras",
        db_column="proveedor_id",
    )
    usuario = models.ForeignKey(
        Usuarios,
        on_delete=models.PROTECT,
        related_name="compras_registradas",
        db_column="usuario_id",
    )
    numero_factura = models.CharField(max_length=50, unique=True)
    fecha = models.DateTimeField(blank=True, null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        db_table = "compras"

    def __str__(self):
        return f"{self.numero_factura} - {self.proveedor.nombre_comercial}"


# 🔹 NUEVO: DetalleCompras
class DetalleCompras(models.Model):
    id = models.AutoField(primary_key=True)
    compra = models.ForeignKey(
        Compras,
        on_delete=models.CASCADE,
        related_name="detalles",
        db_column="compra_id",
    )
    libro = models.ForeignKey(
        Libros,
        on_delete=models.PROTECT,
        related_name="detalles_compra",
        db_column="libro_id",
    )
    cantidad = models.IntegerField()
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "detalle_compras"

    def __str__(self):
        return f"{self.libro.titulo} x {self.cantidad}"


class Ventas(models.Model):
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    vendedor = models.ForeignKey(Usuarios, models.DO_NOTHING)
    fecha_venta = models.DateTimeField(auto_now_add=True)
    metodo_pago = models.CharField(max_length=50)  # Efectivo, Tarjeta, etc.
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    impuesto = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(
        max_length=20,
        default="pagada",  # pendiente, pagada, anulada
        blank=True,
        null=True,
    )

    class Meta:
        db_table = 'ventas'

    def __str__(self):
        return f"Venta #{self.id} - {self.cliente} - {self.total}"


class DetalleVenta(models.Model):
    venta = models.ForeignKey(
        Ventas,
        models.DO_NOTHING,
        related_name="detalles"
    )
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    impuesto_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    total_linea = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'detalle_ventas'

    def __str__(self):
        return f"DetalleVenta #{self.id} - Venta {self.venta_id}"


class SolicitudVenta(models.Model):
    ORIGEN_CHOICES = (
        ("reserva", "Desde reserva"),
        ("detalle", "Desde detalle"),
    )

    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    reserva = models.ForeignKey(
        Reservas,
        models.DO_NOTHING,
        blank=True,
        null=True,
    )
    cantidad = models.IntegerField(default=1)
    estado = models.CharField(
        max_length=20,
        default="pendiente",  # pendiente, atendida, cancelada
    )
    origen = models.CharField(
        max_length=20,
        choices=ORIGEN_CHOICES,
        default="detalle",
    )
    fecha_solicitud = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'solicitudes_venta'

    def __str__(self):
        return f"Solicitud #{self.id} - {self.cliente} - {self.libro}"
