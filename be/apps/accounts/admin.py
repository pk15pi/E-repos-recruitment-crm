from django import forms
from django.contrib import admin
from django.contrib.auth.forms import AuthenticationForm

from apps.accounts.models import User


class AdminLoginForm(AuthenticationForm):
    username = forms.CharField(label="User ID", widget=forms.TextInput(attrs={"autofocus": True}))


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff", "is_superuser")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")


admin.site.login_form = AdminLoginForm
