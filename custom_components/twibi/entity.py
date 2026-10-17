"""Entidades base: dispositivos do HA = nos do mesh Twibi."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TwibiCoordinator


def node_device_info(coord: TwibiCoordinator, serial: str) -> DeviceInfo:
    node = coord.data.nodes.get(serial, {}) if coord.data else {}
    info = DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer="Intelbras",
        model=node.get("mode") or "Twibi",
        name=coord.data.node_name(serial) if coord.data else f"Twibi {serial}",
        serial_number=serial,
        sw_version=node.get("fwversion"),
        configuration_url=None,
    )
    if node.get("ethaddr_l"):
        info["connections"] = {(CONNECTION_NETWORK_MAC, node["ethaddr_l"].lower())}
    return info


class TwibiEntity(CoordinatorEntity[TwibiCoordinator]):
    """Entidade ligada a um no do mesh (o principal por padrao)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TwibiCoordinator, key: str, serial: str | None = None) -> None:
        super().__init__(coordinator)
        self.serial = serial or coordinator.data.info.get("sn", "twibi")
        self._attr_unique_id = f"{self.serial}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = node_device_info(coordinator, self.serial)

    @property
    def node(self) -> dict:
        return self.coordinator.data.nodes.get(self.serial, {})
