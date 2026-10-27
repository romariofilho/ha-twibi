"""Interruptores: rede de convidados, LED dos nos, reinicio automatico, roaming, prioridades mesh/dual band,
UPnP, controle de banda, acesso por aparelho."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TwibiConfigEntry, TwibiCoordinator
from .entity import TwibiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TwibiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coord = entry.runtime_data
    entities: list[SwitchEntity] = [GuestSwitch(coord), AutoRebootSwitch(coord), FastRoamingSwitch(coord),
                                    MeshPrioritySwitch(coord), DualBandSwitch(coord), UpnpSwitch(coord),
                                    QosSwitch(coord)]
    entities += [LedSwitch(coord, sn) for sn in coord.data.nodes]
    async_add_entities(entities)

    # acesso a internet por aparelho (desativados por padrao; ative os que quiser)
    tracked: set[str] = set()
    registry = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if ent.domain == "switch" and ent.unique_id.startswith("access_"):
            tracked.add(ent.unique_id.removeprefix("access_").upper())

    @callback
    def _add_new() -> None:
        macs = set(coord.data.hosts) | set(coord.data.blocked)
        new = [m for m in macs if m not in tracked]
        if new:
            tracked.update(new)
            async_add_entities(AccessSwitch(coord, m) for m in new)

    async_add_entities(AccessSwitch(coord, m) for m in sorted(tracked))
    _add_new()
    entry.async_on_unload(coord.async_add_listener(_add_new))


class GuestSwitch(TwibiEntity, SwitchEntity):
    """Rede Wi-Fi de convidados (desliga sozinha apos o tempo configurado no app)."""

    def __init__(self, coord) -> None:
        super().__init__(coord, "guest_wifi")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.guest.get("enable"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        g = self.coordinator.data.guest
        w = (g.get("wlan") or [{}])[0]
        t = w.get("timeout")
        return {"ssid": w.get("ssid"), "desliga_apos_h": None if t in (None, -1) else round(t / 3600, 1)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_guest(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_guest(False))


class AutoRebootSwitch(TwibiEntity, SwitchEntity):
    """'Manutencao automatica' do app: reinicio diario no horario configurado."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "auto_reboot")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.automaint.get("status"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_automaint(enable=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_automaint(enable=False))


class FastRoamingSwitch(TwibiEntity, SwitchEntity):
    """'Roaming rapido' do app: o mesh leva o aparelho para o no mais perto.

    Sem ele o aparelho fica preso no no em que conectou. Mudar reinicia o Wi-Fi (~60 s).
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "fast_roaming")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.roaming.get("enable"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"aviso": "mudar reinicia o Wi-Fi do Twibi (~60 s)"}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_roaming(True), restarts_wifi=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_roaming(False), restarts_wifi=True)


class MeshPrioritySwitch(TwibiEntity, SwitchEntity):
    """'Prioridade Mesh' do app: prioriza o 5 GHz para o link entre os Twibis e limita
    a 6 os aparelhos em 5 GHz por no. Nao reinicia o Wi-Fi."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "mesh_priority")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.mesh_priority.get("limit_5Gdevice_switch"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_mesh_priority(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_mesh_priority(False))


class DualBandSwitch(TwibiEntity, SwitchEntity):
    """'Prioridade Dual Band' do app: o Twibi empurra para 5 GHz quem suporta. O app avisa
    que aparelhos antigos podem se confundir. Mudar reinicia o Wi-Fi (~35 s)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "dual_band")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.dual_band.get("dual_freq_switch"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"aviso": "mudar reinicia o Wi-Fi do Twibi (~35 s)"}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_dual_band(True), restarts_wifi=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_dual_band(False), restarts_wifi=True)


class UpnpSwitch(TwibiEntity, SwitchEntity):
    """UPnP (aparelhos abrem portas sozinhos). Nao reinicia o Wi-Fi."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "upnp")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.upnp.get("status"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_upnp(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_upnp(False))


class QosSwitch(TwibiEntity, SwitchEntity):
    """'Controle de Banda' do app: jogos e navegacao com prioridade. Nao reinicia o Wi-Fi."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord) -> None:
        super().__init__(coord, "qos")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.qos.get("status"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_qos(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda t: t.set_qos(False))


class LedSwitch(TwibiEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, serial: str) -> None:
        super().__init__(coord, "led", serial)

    @property
    def is_on(self) -> bool:
        return self.node.get("led") == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        sn = self.serial
        await self.coordinator.async_command(lambda t: t.set_led(sn, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        sn = self.serial
        await self.coordinator.async_command(lambda t: t.set_led(sn, False))


class AccessSwitch(CoordinatorEntity[TwibiCoordinator], SwitchEntity):
    """Ligado = aparelho pode usar a rede; desligado = na lista negra do Twibi."""

    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: TwibiCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac.upper()
        self._attr_unique_id = f"access_{self._mac.lower()}"
        # sem device proprio (evita criar ~60 devices); nome inclui o aparelho
        self._attr_name = f"Acesso à rede: {coordinator.data.name_for(self._mac)}"
        self._attr_icon = "mdi:web"

    @property
    def is_on(self) -> bool:
        return self._mac not in self.coordinator.data.blocked

    async def async_turn_off(self, **kwargs: Any) -> None:
        mac, name = self._mac, self.coordinator.data.name_for(self._mac)
        await self.coordinator.async_command(lambda t: t.set_blocked(mac, True, name))

    async def async_turn_on(self, **kwargs: Any) -> None:
        mac = self._mac
        await self.coordinator.async_command(lambda t: t.set_blocked(mac, False))
