"""Coordenador: consulta o Twibi periodicamente e executa comandos."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, WIFI_RESTART_GRACE
from .lib.client import TwibiAuthError, TwibiClient, TwibiError

_LOGGER = logging.getLogger(__name__)


@dataclass
class TwibiData:
    """Fotografia do estado do Twibi em uma consulta."""

    info: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)  # serial -> MxpInfo
    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)  # MAC -> hostInfo
    remarks: dict[str, str] = field(default_factory=dict)  # MAC -> apelido
    blocked: dict[str, str] = field(default_factory=dict)  # MAC -> nome
    wan: dict[str, Any] = field(default_factory=dict)
    wan_rate: dict[str, Any] = field(default_factory=dict)
    wan_link: bool | None = None
    guest: dict[str, Any] = field(default_factory=dict)
    automaint: dict[str, Any] = field(default_factory=dict)
    roaming: dict[str, Any] = field(default_factory=dict)
    mesh_priority: dict[str, Any] = field(default_factory=dict)

    def name_for(self, mac: str) -> str:
        """Apelido do Twibi; senao hostname; senao o MAC."""
        mac = mac.upper()
        host = self.hosts.get(mac, {})
        hostname = (host.get("name") or "").splitlines()[0].strip() if host.get("name") else ""
        if hostname and not hostname.isprintable():
            hostname = ""
        return self.remarks.get(mac) or hostname or mac

    def node_name(self, serial: str) -> str:
        node = self.nodes.get(serial, {})
        return f"Twibi {node.get('location') or serial}"


type TwibiConfigEntry = ConfigEntry[TwibiCoordinator]


class TwibiCoordinator(DataUpdateCoordinator[TwibiData]):
    """Consulta o Twibi (uma conexao por ciclo) e centraliza as escritas."""

    config_entry: TwibiConfigEntry

    def __init__(self, hass: HomeAssistant, entry: TwibiConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval) if interval else DEFAULT_SCAN_INTERVAL,
        )
        self.host: str = entry.data[CONF_HOST]
        self._password: str = entry.data[CONF_PASSWORD]
        self._info: dict[str, Any] = {}
        self.known_macs: set[str] = set()
        self._write_lock = asyncio.Lock()

    def client(self) -> TwibiClient:
        return TwibiClient(self.host, self._password)

    async def _async_update_data(self) -> TwibiData:
        try:
            async with self.client() as t:
                if not self._info:
                    self._info = await t.basic_info()
                data = TwibiData(info=self._info)
                data.nodes = {n["serialNum"]: n for n in await t.nodes()}
                data.hosts = {h["ethaddr"].upper(): h for h in await t.hosts() if h.get("ethaddr")}
                data.remarks = await t.remarks()
                data.blocked = await t.blocked()
                wan = (await t.wan_status()).get("wan", [])
                data.wan = wan[0] if wan else {}
                rate = (await t.wan_rate()).get("wan", [])
                data.wan_rate = rate[0] if rate else {}
                data.wan_link = (await t.request(0x1207)).get("status")
                data.guest = await t.guest()
                data.automaint = await t.automaint()
                data.roaming = await t.roaming()
                data.mesh_priority = await t.mesh_priority()
        except TwibiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TwibiError as err:
            raise UpdateFailed(str(err)) from err
        self.known_macs |= set(data.hosts) | set(data.blocked)
        return data

    async def async_command(
        self,
        func: Callable[[TwibiClient], Awaitable[Any]],
        *,
        restarts_wifi: bool = False,
    ) -> None:
        """Executa uma escrita numa conexao propria e agenda nova consulta.

        Comandos que reiniciam o Wi-Fi do Twibi derrubam a rede (inclusive a do
        proprio HA, se ele estiver no Wi-Fi): a conexao pode cair antes da resposta.
        """
        async with self._write_lock:
            try:
                async with self.client() as t:
                    await func(t)
            except TwibiAuthError as err:
                raise HomeAssistantError(f"Twibi recusou a senha: {err}") from err
            except TwibiError as err:
                if not restarts_wifi:
                    raise HomeAssistantError(f"Twibi: {err}") from err
                _LOGGER.debug("conexao caiu durante comando que reinicia o Wi-Fi: %s", err)
        if restarts_wifi:
            self.hass.loop.call_later(
                WIFI_RESTART_GRACE, lambda: self.hass.async_create_task(self.async_request_refresh())
            )
        else:
            await asyncio.sleep(1.5)
            await self.async_refresh()  # imediato (async_request_refresh tem debounce de 10 s)
