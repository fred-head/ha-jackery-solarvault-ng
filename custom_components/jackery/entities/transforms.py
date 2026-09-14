"""Pure value transformations shared by Home Assistant entities."""

COMM_MODE_LOCAL = 1
COMM_MODE_CLOUD = 2

COMM_MODE_LABELS: dict[int, str] = {
    COMM_MODE_LOCAL: "local",
    COMM_MODE_CLOUD: "cloud",
}


def plug_comm_mode(item: dict) -> int | None:
    """Read plug commMode (1=local, 2=cloud)."""
    val = item.get("commMode")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def plug_mqtt_control_allowed(item: dict) -> tuple[bool, str]:
    """Check if MQTT control is allowed for plug; return allowed and reason."""
    mode = plug_comm_mode(item)
    if mode == COMM_MODE_LOCAL:
        return True, ""
    if mode == COMM_MODE_CLOUD:
        return (
            False,
            "Smart plug is cloud-connected (commMode=2) and cannot be controlled via MQTT. Please use the Jackery App.",
        )
    if mode is None:
        return (
            False,
            "Unknown commMode. MQTT control is only supported when commMode=1 (local).",
        )
    return (
        False,
        f"Smart plug commMode={mode} does not support MQTT control. Only commMode=1 (local) is supported.",
    )
