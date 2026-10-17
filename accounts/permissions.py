"""
Разграничение доступа по ролям (раздел 4.3 ТЗ).

Использование во вьюхе:

    @role_required(User.Role.DISPATCHER, User.Role.ADMIN)
    def dispatcher_page(request): ...

Не вошедший пользователь отправляется на страницу входа,
вошедший с другой ролью получает ошибку 403 «Доступ запрещён».
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("Эта страница недоступна для вашей роли.")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


class RoleRequiredMixin:
    """
    То же самое для вьюх-классов (ListView, CreateView и т. п.).

    class RouteList(RoleRequiredMixin, ListView):
        allowed_roles = [User.Role.DISPATCHER, User.Role.ADMIN]
    """

    allowed_roles = []

    @classmethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        return role_required(*cls.allowed_roles)(view)
