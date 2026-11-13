from django.conf import settings
from django.contrib.auth.backends import ModelBackend


class AdminAliasBackend(ModelBackend):
    """Allow the configured platform administrator to use a short admin ID."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        login = username or kwargs.get("email")
        if login and login.casefold() == settings.DJANGO_ADMIN_LOGIN_ALIAS.casefold():
            login = settings.DJANGO_ADMIN_LOGIN_EMAIL
        return super().authenticate(request, username=login, password=password, **kwargs)
