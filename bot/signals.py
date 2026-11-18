from django.db.models.signals import pre_delete
from django.dispatch import receiver


from bot.models import Server, ServerRemoved

def archive_removed_server(server: Server) -> ServerRemoved:
    country = getattr(server, "country", None)
    return ServerRemoved.objects.create(
        original_id=server.pk,
        hosting=server.hosting,
        ip_address=server.ip_address,
        user=server.user,
        password=server.password,
        max_keys=server.max_keys,
        keys_generated=server.keys_generated,
        is_active=bool(server.is_active),
        created_at=server.created_at,
        country_name=(getattr(country, "name", None) or "") if country is not None else "",
        country_name_for_app=(getattr(country, "name_for_app", None) or "") if country is not None else "",
        node_role=server.node_role or "",
        is_activated_vless=bool(server.is_activated_vless),
        is_pasarguard_activated=bool(server.is_pasarguard_activated),
        is_c3celeryty_activated=bool(server.is_c3celeryty_activated),
        hysteria_tls_sni=server.hysteria_tls_sni or "",
        hysteria_pin_sha256=server.hysteria_pin_sha256 or "",
        hysteria_cert_synced_at=server.hysteria_cert_synced_at,
    )


@receiver(pre_delete, sender=Server)
def cleanup_server_panels_on_delete(sender, instance, **kwargs):
    from bot.main.server_panel_cleanup import delete_server_from_panels

    archive_removed_server(instance)
    delete_server_from_panels(instance)
