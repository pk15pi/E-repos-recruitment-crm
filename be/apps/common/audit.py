def client_ip(request) -> str | None:
    addr = request.META.get("REMOTE_ADDR")
    if not addr:
        return None
    return addr[:64]


def record_audit(request, action: str, obj, detail: str = "", organization=None) -> None:
    from apps.audit.models import AuditEvent

    user = getattr(request, "user", None)
    actor = user if user is not None and getattr(user, "is_authenticated", False) else None
    AuditEvent.objects.create(
        organization=organization if organization is not None else getattr(request, "organization", None),
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id="" if obj is None else str(getattr(obj, "pk", "")),
        detail=(detail or "")[:500],
        ip_address=client_ip(request) if request is not None else None,
    )
