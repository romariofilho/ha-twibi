"""Sensores: internet (WAN), clientes conectados e nos do mesh."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import TwibiConfigEntry, TwibiData
from .entity import TwibiEntity


@dataclass(frozen=True, kw_only=True)
class HubSensor(SensorEntityDescription):
    value: Callable[[TwibiData], Any]


HUB_SENSORS: tuple[HubSensor, ...] = (
    HubSensor(key="clients_online", state_class=SensorStateClass.MEASUREMENT,
              value=lambda d: sum(1 for h in d.hosts.values() if h.get("online"))),
    HubSensor(key="wan_ip", entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.wan.get("ipaddr")),
    HubSensor(key="wan_gateway", entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.wan.get("gateway"),
              entity_registry_enabled_default=False),
    HubSensor(key="wan_dns", entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.wan.get("dns1"),
              entity_registry_enabled_default=False),
    HubSensor(key="wan_ipv6", entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.wan.get("ipv6addr"),
              entity_registry_enabled_default=False),
    HubSensor(key="wan_upload", device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
              native_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
              suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, suggested_display_precision=2,
              value=lambda d: d.wan_rate.get("uprate")),
    HubSensor(key="wan_download", device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
              native_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
              suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, suggested_display_precision=2,
              value=lambda d: d.wan_rate.get("downrate")),
    HubSensor(key="reserved_ips", entity_category=EntityCategory.DIAGNOSTIC,
              value=lambda d: sum(1 for h in d.hosts.values() if h.get("dhcp_static"))),
    HubSensor(key="auto_reboot_time", entity_category=EntityCategory.DIAGNOSTIC,
              value=lambda d: d.automaint.get("time") if d.automaint.get("status") else "desligado"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TwibiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    entities: list[SensorEntity] = [TwibiHubSensor(coord, d) for d in HUB_SENSORS]
    for serial in coord.data.nodes:
        entities += [
            NodeClientsSensor(coord, serial),
            NodeBackhaulSensor(coord, serial),
            NodeUptimeSensor(coord, serial),
            NodeIpSensor(coord, serial),
        ]
    async_add_entities(entities)


class TwibiHubSensor(TwibiEntity, SensorEntity):
    entity_description: HubSensor

    def __init__(self, coord, description: HubSensor) -> None:
        super().__init__(coord, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "auto_reboot_time":
            am = self.coordinator.data.automaint
            dias = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
            freq = (am.get("freq") or "").split(";")
            return {"dias": [d for d, f in zip(dias, freq) if f == "1"], "adiar_se_em_uso": am.get("delay")}
        return None


class NodeClientsSensor(TwibiEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "node_clients", serial)

    @property
    def native_value(self) -> int:
        return sum(1 for h in self.coordinator.data.hosts.values()
                   if h.get("online") and h.get("assoc_sn") == self.serial)


class NodeBackhaulSensor(TwibiEntity, SensorEntity):
    """Sinal do link entre este no e o no ao qual ele se conecta (so satelites)."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "node_backhaul", serial)
        # o no principal nao tem backhaul proprio
        self._attr_entity_registry_enabled_default = coord.data.nodes.get(serial, {}).get("role") != 1

    @property
    def _link(self) -> dict:
        lst = self.node.get("assoc_list") or []
        return lst[0] if lst else {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._link) and not self._link.get("wired_en")

    @property
    def native_value(self) -> int | None:
        link = self._link
        vals = [v for v in (link.get("wl5g_rssi"), link.get("wl2g_rssi")) if v]
        return max(vals) if vals else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        link = self._link
        return {
            "conectado_a": self.coordinator.data.node_name(link["assoc_sn"]) if link.get("assoc_sn") else None,
            "rssi_2g": link.get("wl2g_rssi"),
            "rssi_5g": link.get("wl5g_rssi"),
            "cabo": bool(link.get("wired_en")),
        }


class NodeUptimeSensor(TwibiEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "node_boot", serial)
        self._last: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        secs = self.node.get("powered_time")
        if secs is None:
            return None
        boot = (dt_util.utcnow() - timedelta(seconds=secs)).replace(microsecond=0)
        # evita "tremer" alguns segundos a cada consulta
        if self._last is None or abs((boot - self._last).total_seconds()) > 120:
            self._last = boot
        return self._last


class NodeIpSensor(TwibiEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "node_ip", serial)

    @property
    def native_value(self) -> str | None:
        return self.node.get("ipaddr")
