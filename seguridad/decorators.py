from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist

def role_required(role_name: str):
    """
    Restringe acceso a usuarios que pertenezcan al Grupo indicado.
    Permite superuser. Devuelve 403 con template o fallback en texto.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            u = request.user
            if u.is_superuser or u.groups.filter(name=role_name).exists():
                return view_func(request, *args, **kwargs)

            # 403 con template si existe; si no, fallback simple para que los tests no rompan
            try:
                html = render_to_string('errors/403.html', {"path": request.path})
            except TemplateDoesNotExist:
                html = "403 Forbidden: acceso denegado"
            return HttpResponseForbidden(html)
        return _wrapped_view
    return decorator
