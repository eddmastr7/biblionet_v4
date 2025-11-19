# seguridad/tests/test_auth_login.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

class AuthLoginTests(TestCase):
    def setUp(self):
        self.username = "user1"
        self.password = "pass12345"
        self.user = User.objects.create_user(username=self.username, password=self.password)

    def test_login_get_ok(self):
        url = reverse('login-page')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_login_post_ok_redirects_to_account(self):
        url = reverse('login-page')
        res = self.client.post(url, {"username": self.username, "password": self.password})
        # debe redirigir a mi-cuenta
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('mi-cuenta'), res.headers.get('Location', ''))

    def test_login_post_invalid_stays_on_page(self):
        url = reverse('login-page')
        res = self.client.post(url, {"username": self.username, "password": "wrong"})
        # se queda en login (200) y no autentica
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.wsgi_request.user.is_authenticated)

    def test_account_requires_login(self):
        url = reverse('mi-cuenta')
        res = self.client.get(url)
        # redirige a login (no asumimos ruta exacta, solo que es redirect y contiene 'login')
        self.assertEqual(res.status_code, 302)
        self.assertIn('login', res.headers.get('Location', ''))

    def test_logout_redirects(self):
        self.client.login(username=self.username, password=self.password)
        url = reverse('logout-page')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 302)  # redirige (destino puede variar)
