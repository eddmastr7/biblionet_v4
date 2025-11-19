# seguridad/tests/test_roles.py
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, Group
from django.http import HttpResponse
from seguridad.decorators import role_required

def dummy_view(request):
    return HttpResponse("ok")

protected_emp = role_required('Empleado')(dummy_view)

class RoleRequiredTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user = User.objects.create_user(username="u", password="p")

    def test_denies_user_without_group(self):
        req = self.rf.get('/dummy')
        req.user = self.user  # autenticado pero sin grupo
        res = protected_emp(req)
        self.assertEqual(res.status_code, 403)

    def test_allows_user_in_group(self):
        g = Group.objects.create(name='Empleado')
        self.user.groups.add(g)
        req = self.rf.get('/dummy')
        req.user = self.user
        res = protected_emp(req)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"ok")

    def test_allows_superuser(self):
        self.user.is_superuser = True
        self.user.save()
        req = self.rf.get('/dummy')
        req.user = self.user
        res = protected_emp(req)
        self.assertEqual(res.status_code, 200)
