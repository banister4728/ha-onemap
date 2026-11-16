"""A place-name sensor per tracked person or device tracker."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.sensor import RestoreSensor
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, STATE_HOME, STATE_NOT_HOME
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from . import OneMapConfigEntry
from .api import OneMapAuthError, OneMapError, distance_m
from .const import (
    CONF_BUFFER,
    CONF_MIN_DISTANCE,
    CONF_TRACKED,
    CONF_USE_ZONES,
    DEFAULT_BUFFER,
    DEFAULT_MIN_DISTANCE,
    DEFAULT_USE_ZONES,
    DOMAIN,
    LOOKUP_COOLDOWN,
)

_LOGGER = logging.getLogger(__name__)
_IGNORED = {None, "unknown", "unavailable"}
ATTR_LOOKUP_LAT = "lookup_latitude"
ATTR_LOOKUP_LON = "lookup_longitude"


async def async_setup_entry(
    hass: HomeAssistant, entry: OneMapConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(OneMapPlaceSensor(hass, entry, source) for source in entry.options.get(CONF_TRACKED, []))


class OneMapPlaceSensor(RestoreSensor):
    """Where the tracker is, by name: a zone if it's in one, else the nearest OneMap building."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-radius"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: OneMapConfigEntry, source: str) -> None:
        self._entry = entry
        self._source = source
        options = entry.options
        self._buffer = int(options.get(CONF_BUFFER, DEFAULT_BUFFER))
        self._min_distance = float(options.get(CONF_MIN_DISTANCE, DEFAULT_MIN_DISTANCE))
        self._use_zones = options.get(CONF_USE_ZONES, DEFAULT_USE_ZONES)
        source_state = hass.states.get(source)
        label = source_state.name if source_state else source.split(".", 1)[1].replace("_", " ").title()
        self._attr_name = f"{label} place"
        self._attr_unique_id = f"{entry.entry_id}_{source}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="OneMap", manufacturer="Singapore Land Authority",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_extra_state_attributes: dict[str, Any] = {"source": source}
        self._lookup_pos: tuple[float, float] | None = None  # where the last OneMap answer was for
        self._last_call = 0.0
        self._busy = False
        self._retry_cancel = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore, so a restart doesn't spend a lookup on a place we already know.
        if (last := await self.async_get_last_state()) and (data := await self.async_get_last_sensor_data()):
            self._attr_native_value = data.native_value
            self._attr_extra_state_attributes = {**last.attributes, "source": self._source}
            self._attr_extra_state_attributes.pop("friendly_name", None)
            self._attr_extra_state_attributes.pop("icon", None)
            lat, lon = last.attributes.get(ATTR_LOOKUP_LAT), last.attributes.get(ATTR_LOOKUP_LON)
            if lat is not None and lon is not None:
                self._lookup_pos = (lat, lon)
        self.async_on_remove(async_track_state_change_event(self.hass, [self._source], self._async_source_changed))
        self.async_on_remove(self._cancel_retry)
        await self._async_update_place()

    @callback
    def _cancel_retry(self) -> None:
        if self._retry_cancel:
            self._retry_cancel()
            self._retry_cancel = None

    async def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        await self._async_update_place()

    async def _async_retry(self, _now) -> None:
        self._retry_cancel = None
        await self._async_update_place()

    def _zone_name(self, state: str) -> str:
        if state == STATE_HOME:
            zone = self.hass.states.get("zone.home")
            return zone.name if zone else "Home"
        return state  # a person or tracker in a zone takes the zone's name as its state

    async def _async_update_place(self) -> None:
        src = self.hass.states.get(self._source)
        if src is None or src.state in _IGNORED or self._busy:
            return

        if self._use_zones and src.state != STATE_NOT_HOME:
            self._lookup_pos = None  # leaving the zone always looks up afresh
            self._set({"zone": self._zone_name(src.state)}, self._zone_name(src.state))
            return

        lat, lon = src.attributes.get(ATTR_LATITUDE), src.attributes.get(ATTR_LONGITUDE)
        if lat is None or lon is None:
            return
        if self._lookup_pos and distance_m(lat, lon, *self._lookup_pos) < self._min_distance:
            return
        wait = self._last_call + LOOKUP_COOLDOWN - time.monotonic()
        if wait > 0:  # a burst of fixes: look up once, at the latest position, when the cooldown ends
            if not self._retry_cancel:
                self._retry_cancel = async_call_later(self.hass, wait, self._async_retry)
            return

        self._busy = True
        self._last_call = time.monotonic()
        try:
            places = await self._entry.runtime_data.async_reverse_geocode(lat, lon, self._buffer)
        except OneMapAuthError:
            self._entry.async_start_reauth(self.hass)
            return
        except OneMapError as err:
            _LOGGER.warning("OneMap lookup for %s failed: %s", self._source, err)
            return
        finally:
            self._busy = False

        self._lookup_pos = (lat, lon)
        place = next((p for p in places if p.name), None)
        attrs = place.as_dict() if place else {}
        attrs.pop("name", None)
        attrs.update({ATTR_LOOKUP_LAT: lat, ATTR_LOOKUP_LON: lon})
        self._set(attrs, place.name if place else None)

    @callback
    def _set(self, attrs: dict[str, Any], value: str | None) -> None:
        self._attr_native_value = value
        self._attr_extra_state_attributes = {"source": self._source, **attrs}
        self.async_write_ha_state()
