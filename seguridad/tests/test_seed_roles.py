# seguridad/tests/test_seed_roles.py
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth.models import Group

class SeedRolesCommandTests(TestCase):
    def test_seed_roles_creates_groups(self):
        call_command('seed_roles')
        self.assertTrue(Group.objects.filter(name='Administrador').exists())
        self.assertTrue(Group.objects.filter(name='Empleado').exists())

    def test_seed_roles_idempotent(self):
        call_command('seed_roles')
        call_command('seed_roles')
        self.assertEqual(Group.objects.filter(name='Administrador').count(), 1)
        self.assertEqual(Group.objects.filter(name='Empleado').count(), 1)
