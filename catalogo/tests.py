from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from biblio.models import Roles, Usuarios, Clientes

class ClienteLoginTest(TestCase):
    """Pruebas para la vista de inicio de sesión de clientes."""

    def setUp(self):
        # 1. Crear el Rol 'cliente'
        self.rol_cliente, _ = Roles.objects.get_or_create(
            nombre="cliente",
            defaults={"descripcion": "Rol para clientes"}
        )

        # 2. Crear un Usuario para el cliente (con clave hasheada)
        self.password_raw = "Testing1234"
        self.user = Usuarios.objects.create(
            rol=self.rol_cliente,
            nombre="test",
            apellido="cliente",
            email="cliente@test.com",
            clave=make_password(self.password_raw), # Hash la contraseña
            estado="activo",
            fecha_creacion="2025-01-01 00:00:00"
        )

        # 3. Crear el Cliente asociado al Usuario
        self.cliente = Clientes.objects.create(
            usuario=self.user,
            dni="00000000A",
            direccion="Calle Falsa 123",
            telefono="12345678",
            estado="activo"
        )
        
        # Cliente de Django para simular peticiones
        self.client = Client()
        # URL de la vista de inicio de sesión
        self.login_url = reverse("inicio_sesion_cliente")
        # URL de redirección exitosa
        self.redirect_url = reverse("pantalla_inicio_cliente")

    def test_get_login_page(self):
        """Verifica que la página de login se carga correctamente (GET)."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "publico/login_cliente.html")
        
    def test_successful_login(self):
        """Prueba un inicio de sesión exitoso con credenciales correctas."""
        response = self.client.post(self.login_url, {
            "email": self.user.email,
            "password": self.password_raw
        }, follow=True) # follow=True sigue la redirección

        # Verifica redirección exitosa
        self.assertRedirects(response, self.redirect_url)
        # Verifica que la sesión contiene el ID del cliente
        self.assertTrue("cliente_id" in self.client.session)
        self.assertEqual(self.client.session["cliente_id"], self.cliente.id)
        self.assertContains(response, "pantalla_inicio_cliente.html") # Asegura que llegó al template final

    def test_login_wrong_password(self):
        """Prueba de login con contraseña incorrecta."""
        response = self.client.post(self.login_url, {
            "email": self.user.email,
            "password": "wrong_password"
        })

        # Debe permanecer en la página de login (status 200)
        self.assertEqual(response.status_code, 200)
        # Debe mostrar el mensaje de error definido en la vista
        self.assertIn("contraseña incorrecta.", response.context["ctx"]["error"])
        self.assertFalse("cliente_id" in self.client.session) # No debe haber sesión

    def test_login_non_existent_user(self):
        """Prueba de login con un correo que no existe."""
        response = self.client.post(self.login_url, {
            "email": "noexiste@test.com",
            "password": self.password_raw
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("usuario no existente", response.context["ctx"]["error"])
        self.assertFalse("cliente_id" in self.client.session)