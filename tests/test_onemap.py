"""Tests against a real Home Assistant core, with OneMap's web API mocked."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onemap.api import Place
from custom_components.onemap.const import (
    CONF_BUFFER,
    CONF_MIN_DISTANCE,
    CONF_TRACKED,
    CONF_USE_ZONES,
    DOMAIN,
    REVGEOCODE_URL,
    SEARCH_URL,
    TOKEN_URL,
)

TOKEN = {"access_token": "tok", "expiry_timestamp": "9999999999"}
PARKWAY = {
    "GeocodeInfo": [
        {"BUILDINGNAME": "NIL", "BLOCK": "81", "ROAD": "MARINE PARADE CENTRAL", "POSTALCODE": "440081",
         "LATITUDE": "1.3030", "LONGITUDE": "103.9060"},
        {"BUILDINGNAME": "PARKWAY PARADE", "BLOCK": "80", "ROAD": "MARINE PARADE ROAD", "POSTALCODE": "449269",
         "LATITUDE": "1.30107", "LONGITUDE": "103.90528"},
    ]
}
OPTIONS = {CONF_TRACKED: ["person.jamie"], CONF_BUFFER: 100, CONF_MIN_DISTANCE: 100, CONF_USE_ZONES: True}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="me@example.com", data={CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret123"},
        options=OPTIONS,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_place_names():
    assert Place.from_api(PARKWAY["GeocodeInfo"][1], 1.3011, 103.9053).name == "Parkway Parade"
    hdb = Place.from_api(PARKWAY["GeocodeInfo"][0], 1.3011, 103.9053)
    assert hdb.building is None and hdb.name == "Blk 81 Marine Parade Central"
    mrt = Place.from_api({"BUILDINGNAME": "MARINE PARADE MRT STATION"}, 1.3, 103.9)
    assert mrt.name == "Marine Parade MRT Station"
    assert Place.from_api({"BUILDINGNAME": "ST ANDREW'S CATHEDRAL"}, 1.3, 103.9).name == "St Andrew's Cathedral"


async def test_config_flow(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret123"}
    )
    assert result["step_id"] == "settings"
    with patch("custom_components.onemap.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], OPTIONS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_TRACKED] == ["person.jamie"]


async def test_config_flow_bad_password(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, status=401, json={"error": "Invalid email or password"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "wrongpass1"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_place_sensor(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.get(REVGEOCODE_URL, json=PARKWAY)
    hass.states.async_set("person.jamie", "not_home", {"latitude": 1.3011, "longitude": 103.9053, "friendly_name": "Jamie"})
    await _setup(hass)

    state = hass.states.get("sensor.onemap_jamie_place")
    assert state.state == "Parkway Parade"  # nearest of the two
    assert state.attributes["postal_code"] == "449269"
    calls = aioclient_mock.call_count

    # a small move: no new lookup
    hass.states.async_set("person.jamie", "not_home", {"latitude": 1.3012, "longitude": 103.9053, "friendly_name": "Jamie"})
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls

    # in a zone: the zone's name, nothing sent
    hass.states.async_set("person.jamie", "home", {"latitude": 1.32, "longitude": 103.85, "friendly_name": "Jamie"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.onemap_jamie_place").state == "Home"
    assert aioclient_mock.call_count == calls


async def test_bearer_fallback(hass: HomeAssistant, aioclient_mock):
    """If OneMap refuses the bare token, the client tries 'Bearer <token>'."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    seen = []

    async def revgeo(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        auth = aioclient_mock.mock_calls[-1][3].get("Authorization") if aioclient_mock.mock_calls[-1][3] else None
        seen.append(auth)
        if auth == "Bearer tok":
            return AiohttpClientMockResponse(method, url, json=PARKWAY)
        return AiohttpClientMockResponse(method, url, status=401, json={"error": "unauthorised"})

    aioclient_mock.get(REVGEOCODE_URL, side_effect=revgeo)
    await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN, "reverse_geocode", {"latitude": 1.3011, "longitude": 103.9053}, blocking=True, return_response=True
    )
    assert response["places"][0]["name"] == "Parkway Parade"
    assert seen == ["tok", "Bearer tok"]


async def test_search(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.get(
        SEARCH_URL,
        json={"found": 1, "results": [{"SEARCHVAL": "PARKWAY PARADE", "BUILDING": "PARKWAY PARADE", "POSTAL": "449269",
                                       "ADDRESS": "80 MARINE PARADE ROAD PARKWAY PARADE SINGAPORE 449269",
                                       "LATITUDE": "1.30107", "LONGITUDE": "103.90528"}]},
    )
    await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN, "search", {"query": "Parkway Parade"}, blocking=True, return_response=True
    )
    assert response["results"][0]["postal_code"] == "449269"
