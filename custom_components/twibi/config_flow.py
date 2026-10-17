"""Fluxo de configuracao: IP do Twibi principal + senha de admin."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback

from .const import CONF_SCAN_INTERVAL, DEFAULT_HOST, DEFAULT_SCAN_INTERVAL, DOMAIN
from .lib.client import TwibiAuthError, TwibiClient, TwibiError


async def _validate(host: str, password: str) -> dict[str, Any]:
    async with TwibiClient(host, password) as t:
        info = await t.basic_info()
        main = next((n for n in await t.nodes() if n.get("role") == 1), {})
        info["model_name"] = main.get("mode") or "Twibi"
        return info


class TwibiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configura um sistema Twibi (mesh) pelo no principal."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate(user_input[CONF_HOST], user_input[CONF_PASSWORD])
            except TwibiAuthError:
                errors["base"] = "invalid_auth"
            except TwibiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.get("mesh_id") or info.get("sn"))
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(title=f"Intelbras {info['model_name']}", data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await _validate(entry.data[CONF_HOST], user_input[CONF_PASSWORD])
            except TwibiAuthError:
                errors["base"] = "invalid_auth"
            except TwibiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return TwibiOptionsFlow()


class TwibiOptionsFlow(OptionsFlow):
    """Intervalo de consulta."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = self.config_entry.options.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds()))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_INTERVAL, default=cur): vol.All(int, vol.Range(min=10, max=600)),
            }),
        )
