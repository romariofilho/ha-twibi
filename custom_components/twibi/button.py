"""Botao: reiniciar o sistema Twibi (todos os nos)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TwibiConfigEntry
from .entity import TwibiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TwibiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([RebootButton(entry.runtime_data)])


class RebootButton(TwibiEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "reboot")

    async def async_press(self) -> None:
        await self.coordinator.async_command(lambda t: t.reboot(), restarts_wifi=True)
