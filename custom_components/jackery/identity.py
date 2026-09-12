"""Persistent child identity; independent of transport and Home Assistant."""

from urllib.parse import quote, unquote


def child_device_identifier(host: str, child: str) -> str:
    """Scope a physical child to its host without altering either serial."""
    return f"child:{quote(host, safe='')}:{quote(child, safe='')}"


def child_unique_id(host: str, child: str, family: str, key: str) -> str:
    """Build a child entity ID from fixed family/key tokens and encoded serials."""
    return f"jackery_{child_device_identifier(host, child)}:{family}:{key}"


def http_unique_id(host: str, child: str, key: str) -> str:
    """Keep normal HTTP IDs; escape the ambiguous historical host/child delimiter."""
    if "_http_sm_" in host or "_http_sm_" in child:
        return child_unique_id(host, child, "http", key)
    return f"jackery_{host}_http_sm_{child}_{key}"


def parse_child_device_identifier(identifier: str) -> tuple[str, str] | None:
    """Recognize only canonical encoded identifiers, including on resumed setup."""
    parts = identifier.split(":")
    if len(parts) != 3 or parts[0] != "child":
        return None
    host, child = unquote(parts[1]), unquote(parts[2])
    if not host or not child or child_device_identifier(host, child) != identifier:
        return None
    return host, child


def parse_child_unique_id(uid: str) -> tuple[str, str, str, str] | None:
    """Read the new namespace; never interpret a legacy serial by splitting it."""
    if not uid.startswith("jackery_child:"):
        return None
    parts = uid.removeprefix("jackery_").split(":")
    if len(parts) != 5 or not parts[3] or not parts[4]:
        return None
    device = parse_child_device_identifier(":".join(parts[:3]))
    return (*device, parts[3], parts[4]) if device else None
