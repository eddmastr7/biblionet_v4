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

    class Meta:
        db_table = 'usuarios'


class Bitacora(models.Model):
    usuario = models.ForeignKey(Usuarios, models.DO_NOTHING, blank=True, null=True)
    accion = models.CharField(max_length=255)
    fecha = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'bitacora'


class Clientes(models.Model):
    usuario = models.OneToOneField(Usuarios, on_delete=models.CASCADE)
    dni = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    estado = models.CharField(max_length=20, default="activo")

    # 🔴 NUEVOS CAMPOS DE BLOQUEO
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

    class Meta:
        db_table = 'libros'


class Ejemplares(models.Model):
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    codigo_interno = models.CharField(unique=True, max_length=50, blank=True, null=True)
    ubicacion = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'ejemplares'


class ReglasPrestamo(models.Model):
    plazo_dias = models.IntegerField()
    limite_prestamos = models.IntegerField()
    tarifa_mora_diaria = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    fecha_actualizacion = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'reglas_prestamo'


class Prestamos(models.Model):
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    ejemplar = models.ForeignKey(Ejemplares, models.DO_NOTHING)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    fecha_devolucion = models.DateField(blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'prestamos'


class Reservas(models.Model):
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    libro = models.ForeignKey(Libros, models.DO_NOTHING)
    fecha_reserva = models.DateTimeField(blank=True, null=True)
    fecha_vencimiento = models.DateTimeField(blank=True, null=True)
    estado = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'reservas'


class CatalogoPublico(models.Model):
    id_libro = models.IntegerField(primary_key=True)
    titulo = models.CharField(max_length=255)
    autor = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, null=True, blank=True)
    editorial = models.CharField(max_length=150, null=True, blank=True)
    anio_publicacion = models.IntegerField(null=True, blank=True)  # YEAR en MySQL
    portada = models.CharField(max_length=255, null=True, blank=True)
    total_ejemplares = models.IntegerField()
    disponibles = models.IntegerField()

    class Meta:
        db_table = 'catalogo_publico'
        managed = False  # 👈 Si esto es una VIEW; si quieres tabla normal, quita esta línea


