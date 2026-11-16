"""Setup screens: the OneMap account, then which trackers get a place sensor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OneMapAuthError, OneMapClient, OneMapError
from .const import (
    CONF_BUFFER,
    CONF_MIN_DISTANCE,
    CONF_TRACKED,
    CONF_USE_ZONES,
    DEFAULT_BUFFER,
    DEFAULT_MIN_DISTANCE,
    DEFAULT_USE_ZONES,
    DOMAIN,
)

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


def _settings_schema(options: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_TRACKED, default=options.get(CONF_TRACKED, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["person", "device_tracker"], multiple=True)
            ),
            vol.Required(CONF_BUFFER, default=options.get(CONF_BUFFER, DEFAULT_BUFFER)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=10, unit_of_measurement="m")
            ),
            vol.Required(
                CONF_MIN_DISTANCE, default=options.get(CONF_MIN_DISTANCE, DEFAULT_MIN_DISTANCE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=10, max=2000, step=10, unit_of_measurement="m")
            ),
            vol.Required(CONF_USE_ZONES, default=options.get(CONF_USE_ZONES, DEFAULT_USE_ZONES)): bool,
        }
    )


async def _async_check_login(hass, email: str, password: str) -> str | None:
    """None if the account works, else the error key for the form."""
    try:
        await OneMapClient(async_get_clientsession(hass), email, password).async_login()
    except OneMapAuthError:
        return "invalid_auth"
    except OneMapError:
        return "cannot_connect"
    return None


class OneMapConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._account: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if not (error := await _async_check_login(self.hass, email, user_input[CONF_PASSWORD])):
                self._account = {CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                return await self.async_step_settings()
            errors["base"] = error
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(ACCOUNT_SCHEMA, user_input), errors=errors
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="OneMap", data=self._account, options=user_input)
        return self.async_show_form(step_id="settings", data_schema=_settings_schema({}))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (error := await _async_check_login(self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): ACCOUNT_SCHEMA.schema[CONF_PASSWORD]}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OneMapOptionsFlow()


class OneMapOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=_settings_schema(self.config_entry.options))
