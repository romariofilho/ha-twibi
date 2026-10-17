"""Rastreadores (casa/fora) para cada aparelho conectado ao Twibi."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TwibiConfigEntry, TwibiCoordinator

# aparelhos que andam com a gente: ficam ativos por padrao
_MOBILE = re.compile(
    r"(galaxy|iphone|ipad|pixel|watch|ticwatch|sm-[a-z]\d|s2\d|s1\d|tab|tablet|celular|phone|android-|redmi|moto|xiaomi-)",
    re.I,
)


_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


def _is_mobile(mac: str, name: str) -> bool:
    # MAC aleatorio (bit "localmente administrado") = quase sempre celular/relogio/tablet
    try:
        if int(mac.split(":")[0], 16) & 0x02:
            return True
    except ValueError:
        pass
    return bool(_MOBILE.search(name or ""))


async def async_setup_entry(
    hass: HomeAssistant, entry: TwibiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    tracked: set[str] = set()

    # recria os que ja existiam (aparelhos fora de casa nao aparecem na lista do Twibi)
    registry = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        # ScannerEntity usa o proprio MAC como unique_id
        if ent.domain == "device_tracker" and _MAC_RE.match(ent.unique_id):
            tracked.add(ent.unique_id.upper())

    @callback
    def _add_new() -> None:
        new = [mac for mac in coord.data.hosts if mac not in tracked]
        if new:
            tracked.update(new)
            async_add_entities(TwibiTracker(coord, mac) for mac in new)

    async_add_entities(TwibiTracker(coord, mac) for mac in sorted(tracked))
    _add_new()
    entry.async_on_unload(coord.async_add_listener(_add_new))


class TwibiTracker(CoordinatorEntity[TwibiCoordinator], ScannerEntity):
    """Um aparelho da rede (identificado pelo MAC)."""

    _attr_translation_key = "client"

    def __init__(self, coordinator: TwibiCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac.upper()
        name = coordinator.data.name_for(self._mac)
        self._attr_name = name
        self._mobile = _is_mobile(self._mac, name)

    @property
    def entity_registry_enabled_default(self) -> bool:
        # ativo se for celular/relogio/tablet OU se o HA ja conhece o aparelho pelo MAC
        return self._mobile or super().entity_registry_enabled_default

    @property
    def _host(self) -> dict[str, Any]:
        return self.coordinator.data.hosts.get(self._mac, {})

    @property
    def mac_address(self) -> str:
        return self._mac.lower()

    @property
    def ip_address(self) -> str | None:
        return self._host.get("ipaddr")

    @property
    def hostname(self) -> str | None:
        name = self._host.get("name") or ""
        name = name.splitlines()[0].strip() if name else ""
        return name if name and name.isprintable() else None

    @property
    def is_connected(self) -> bool:
        return bool(self._host.get("online"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        h = self._host
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            "apelido_twibi": data.remarks.get(self._mac),
            "ip_reservado": bool(h.get("dhcp_static")),
            "bloqueado": self._mac in data.blocked,
        }
        if h:
            attrs.update({
                "no_mesh": data.node_name(h["assoc_sn"]) if h.get("assoc_sn") else None,
                "sinal_dbm": h.get("signal"),
                "conexao": {"BGN": "2.4 GHz", "AC": "5 GHz", "AX": "5 GHz (Wi-Fi 6)", "--": "cabo"}.get(
                    h.get("conn_mode", ""), h.get("conn_mode")
                ),
                "taxa_link_mbps": h.get("tx_rate"),
                "conectado_ha_s": h.get("condtion_time"),
                "upload_kB_s": h.get("uprate"),
                "download_kB_s": h.get("downrate"),
            })
        return attrs
