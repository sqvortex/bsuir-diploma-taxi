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
