"""Integracao Intelbras Twibi (Twibi Giga / Tenda Nova) via protocolo local TCP 9000."""
from __future__ import annotations

import ipaddress

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_IP, ATTR_MAC, ATTR_NAME, ATTR_NAMES, DOMAIN, PLATFORMS
from .coordinator import TwibiConfigEntry, TwibiCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _mac(value: str) -> str:
    mac = str(value).strip().upper().replace("-", ":")
    parts = mac.split(":")
    if len(parts) != 6 or not all(len(p) == 2 and all(c in "0123456789ABCDEF" for c in p) for p in parts):
        raise vol.Invalid(f"MAC invalido: {value}")
    return mac


def _ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except ValueError as err:
        raise vol.Invalid(f"IP invalido: {value}") from err


SCHEMA_MAC = vol.Schema({vol.Required(ATTR_MAC): _mac})
SCHEMA_RESERVE = vol.Schema({vol.Required(ATTR_MAC): _mac, vol.Required(ATTR_IP): _ipv4})
SCHEMA_RENAME = vol.Schema({vol.Required(ATTR_MAC): _mac, vol.Required(ATTR_NAME): cv.string})
SCHEMA_RENAME_MANY = vol.Schema({vol.Required(ATTR_NAMES): {_mac: cv.string}})


def _coordinator(hass: HomeAssistant) -> TwibiCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Nenhum Twibi configurado/carregado")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra os servicos (uma vez, independentes das entradas)."""

    async def reserve_ip(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        mac, ip = call.data[ATTR_MAC], call.data[ATTR_IP]
        await coord.async_command(lambda t: t.set_static_ip(mac, ip, True), restarts_wifi=True)

    async def remove_reservation(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        mac = call.data[ATTR_MAC]
        await coord.async_command(lambda t: t.set_static_ip(mac, "", False), restarts_wifi=True)

    async def rename_device(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        names = {call.data[ATTR_MAC]: call.data[ATTR_NAME]}
        await coord.async_command(lambda t: t.set_remarks(names))

    async def rename_devices(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        names = dict(call.data[ATTR_NAMES])
        await coord.async_command(lambda t: t.set_remarks(names))

    async def block_device(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        mac = call.data[ATTR_MAC]
        name = coord.data.name_for(mac) if coord.data else mac
        await coord.async_command(lambda t: t.set_blocked(mac, True, name))

    async def unblock_device(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        mac = call.data[ATTR_MAC]
        await coord.async_command(lambda t: t.set_blocked(mac, False))

    async def iot_assistant(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        mac = call.data[ATTR_MAC].upper()
        host = coord.data.hosts.get(mac, {}) if coord.data else {}
        ip = host.get("ipaddr")
        if not ip or not host.get("online"):
            raise ServiceValidationError(f"{mac} nao esta conectado ao Twibi")
        await coord.async_command(lambda t: t.iot_assistant(ip))

    async def list_devices(call: ServiceCall) -> dict:
        coord = _coordinator(hass)
        data = coord.data
        out = []
        for mac, h in sorted(data.hosts.items(), key=lambda kv: _ip_key(kv[1].get("ipaddr", ""))):
            out.append({
                "mac": mac,
                "ip": h.get("ipaddr"),
                "name": data.name_for(mac),
                "hostname": (h.get("name") or "").splitlines()[0] if h.get("name") else "",
                "online": bool(h.get("online")),
                "reserved": bool(h.get("dhcp_static")),
                "blocked": mac in data.blocked,
                "node": data.node_name(h.get("assoc_sn", "")) if h.get("assoc_sn") else None,
            })
        return {"devices": out}

    hass.services.async_register(DOMAIN, "reserve_ip", reserve_ip, SCHEMA_RESERVE)
    hass.services.async_register(DOMAIN, "remove_reservation", remove_reservation, SCHEMA_MAC)
    hass.services.async_register(DOMAIN, "rename_device", rename_device, SCHEMA_RENAME)
    hass.services.async_register(DOMAIN, "rename_devices", rename_devices, SCHEMA_RENAME_MANY)
    hass.services.async_register(DOMAIN, "block_device", block_device, SCHEMA_MAC)
    hass.services.async_register(DOMAIN, "unblock_device", unblock_device, SCHEMA_MAC)
    hass.services.async_register(DOMAIN, "iot_assistant", iot_assistant, SCHEMA_MAC)
    hass.services.async_register(
        DOMAIN, "list_devices", list_devices, vol.Schema({}), supports_response=SupportsResponse.ONLY
    )
    return True


def _ip_key(ip: str) -> tuple:
    try:
        return tuple(int(x) for x in ip.split("."))
    except ValueError:
        return (999,)


async def async_setup_entry(hass: HomeAssistant, entry: TwibiConfigEntry) -> bool:
    coordinator = TwibiCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: TwibiConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TwibiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
