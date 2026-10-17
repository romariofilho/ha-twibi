"""Sensores binarios: link de internet e no do mesh online."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TwibiConfigEntry
from .entity import TwibiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TwibiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    entities: list[BinarySensorEntity] = [WanLinkSensor(coord), WanConnectedSensor(coord)]
    entities += [NodeOnlineSensor(coord, sn) for sn in coord.data.nodes]
    async_add_entities(entities)


class WanLinkSensor(TwibiEntity, BinarySensorEntity):
    """Cabo da WAN (porta de internet do Twibi principal) com link."""

    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, coord) -> None:
        super().__init__(coord, "wan_link")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.wan_link


class WanConnectedSensor(TwibiEntity, BinarySensorEntity):
    """Internet: Twibi tem IP na WAN."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coord) -> None:
        super().__init__(coord, "wan_connected")

    @property
    def is_on(self) -> bool:
        ip = self.coordinator.data.wan.get("ipaddr")
        return bool(ip) and ip != "0.0.0.0"


class NodeOnlineSensor(TwibiEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "node_online", serial)

    @property
    def is_on(self) -> bool:
        return self.node.get("status") == 1

    @property
    def extra_state_attributes(self) -> dict:
        n = self.node
        return {"principal": n.get("role") == 1, "local": n.get("location"), "firmware": n.get("fwversion"),
                "mac": n.get("ethaddr_l")}
