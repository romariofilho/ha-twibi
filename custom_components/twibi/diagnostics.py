"""Diagnostico (senhas e SSIDs mascarados)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import TwibiConfigEntry

REDACT = {CONF_PASSWORD, "passwd", "mesh_pwd", "qrmsg", "ipv6addr", "ipaddr_wan"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TwibiConfigEntry) -> dict[str, Any]:
    data = asdict(entry.runtime_data.data) if entry.runtime_data.data else {}
    return {"entry": async_redact_data(dict(entry.data), REDACT), "data": async_redact_data(data, REDACT)}
