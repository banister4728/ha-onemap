"""OneMap Singapore: place names for your trackers, from Singapore's official map."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import OneMapAuthError, OneMapClient, OneMapError
from .const import CONF_BUFFER, DEFAULT_BUFFER, DOMAIN, SERVICE_REVERSE_GEOCODE, SERVICE_SEARCH

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OneMapConfigEntry = ConfigEntry[OneMapClient]

REVERSE_GEOCODE_SCHEMA = vol.Schema(
    {
        vol.Required("latitude"): cv.latitude,
        vol.Required("longitude"): cv.longitude,
        vol.Optional(CONF_BUFFER, default=DEFAULT_BUFFER): vol.All(vol.Coerce(int), vol.Range(0, 500)),
    }
)
SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("query"): cv.string,
        vol.Optional("page", default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once; they use whichever OneMap account is loaded."""

    def client() -> OneMapClient:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data
        raise HomeAssistantError("No OneMap account is set up")

    async def reverse_geocode(call: ServiceCall) -> ServiceResponse:
        try:
            places = await client().async_reverse_geocode(
                call.data["latitude"], call.data["longitude"], call.data[CONF_BUFFER]
            )
        except OneMapError as err:
            raise HomeAssistantError(str(err)) from err
        return {"places": [p.as_dict() for p in places]}

    async def search(call: ServiceCall) -> ServiceResponse:
        try:
            results = await client().async_search(call.data["query"], call.data["page"])
        except OneMapError as err:
            raise HomeAssistantError(str(err)) from err
        return {"results": results}

    hass.services.async_register(
        DOMAIN, SERVICE_REVERSE_GEOCODE, reverse_geocode, REVERSE_GEOCODE_SCHEMA, SupportsResponse.ONLY
    )
    hass.services.async_register(DOMAIN, SERVICE_SEARCH, search, SEARCH_SCHEMA, SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OneMapConfigEntry) -> bool:
    client = OneMapClient(async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await client.async_login()
    except OneMapAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except OneMapError as err:
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OneMapConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: OneMapConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
