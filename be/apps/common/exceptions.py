from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"
    default_detail = "Conflict."


class OrganizationReadOnly(APIException):
    status_code = 403
    default_code = "organization_read_only"
    default_detail = "This organization is read-only. Contact the platform owner to restore write access."


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        return response
    code = getattr(exc, "default_code", "error") or "error"
    if isinstance(data, dict) and set(data.keys()) == {"detail"}:
        message = str(data["detail"])
        details: dict | list = {}
    elif isinstance(data, list):
        message = "Request failed."
        details = {"non_field_errors": [str(item) for item in data]}
    elif response.status_code == 400:
        message = "Validation failed."
        details = data if isinstance(data, dict) else {"detail": data}
    else:
        message = "Request failed."
        details = data if isinstance(data, (dict, list)) else {"detail": str(data)}
    response.data = {"error": {"code": str(code), "message": message, "details": details}}
    return response
