"""Small async client for the OneMap Singapore API.

Has no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import time
from typing import Any

import aiohttp

from .const import REVGEOCODE_URL, SEARCH_URL, TOKEN_RENEW_MARGIN, TOKEN_URL

TIMEOUT = aiohttp.ClientTimeout(total=20)
_MISSING = {"", "nil", "null", "none", "na", "n/a"}


class OneMapError(Exception):
    """OneMap could not be reached or answered with something unexpected."""


class OneMapAuthError(OneMapError):
    """The email or password was refused."""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _MISSING else text


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres; equirectangular is plenty at Singapore's scale."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371000 * math.hypot(math.radians(lat2 - lat1), x)


def _title(text: str | None) -> str | None:
    # OneMap answers in capitals: "PARKWAY PARADE" -> "Parkway Parade"
    return text.title() if text else None


@dataclass
class Place:
    """One reverse-geocode match."""

    building: str | None
    block: str | None
    road: str | None
    postal_code: str | None
    latitude: float | None
    longitude: float | None
    distance_m: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def name(self) -> str | None:
        """Building if it has one, else block and road: "Blk 81 Marine Parade Central"."""
        if self.building:
            return _title(self.building)
        if self.block and self.road:
            return f"Blk {self.block} {_title(self.road)}"
        return _title(self.road)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "building": _title(self.building),
            "block": self.block,
            "road": _title(self.road),
            "postal_code": self.postal_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "distance_m": None if self.distance_m is None else round(self.distance_m),
        }

    @classmethod
    def from_api(cls, item: dict[str, Any], lat: float, lon: float) -> Place:
        plat, plon = _float(item.get("LATITUDE")), _float(item.get("LONGITUDE"))
        return cls(
            building=_clean(item.get("BUILDINGNAME")),
            block=_clean(item.get("BLOCK")),
            road=_clean(item.get("ROAD")),
            postal_code=_clean(item.get("POSTALCODE")),
            latitude=plat,
            longitude=plon,
            distance_m=None if plat is None or plon is None else distance_m(lat, lon, plat, plon),
            raw=item,
        )


class OneMapClient:
    """Logs in with an email and password and keeps the 3-day token fresh by itself."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._expires: float = 0
        self._bearer = False  # header form that works, learned on the first refusal
        self._lock = asyncio.Lock()

    @property
    def token_expires(self) -> float:
        return self._expires

    async def async_login(self) -> None:
        """Get a new token. Raises OneMapAuthError if the account is refused."""
        try:
            async with self._session.post(
                TOKEN_URL, json={"email": self._email, "password": self._password}, timeout=TIMEOUT
            ) as resp:
                status = resp.status
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise OneMapError(f"OneMap login failed: {err}") from err
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            if status in (400, 401, 403) or (isinstance(data, dict) and data.get("error")):
                raise OneMapAuthError(str(data.get("error") if isinstance(data, dict) else status))
            raise OneMapError(f"OneMap login answered {status} without a token")
        self._token = token
        # expiry_timestamp is epoch seconds, sent as a string; assume 3 days if it's missing
        self._expires = _float(data.get("expiry_timestamp")) or time.time() + 3 * 24 * 3600

    async def _async_ensure_token(self) -> str:
        async with self._lock:
            if not self._token or self._expires - time.time() < TOKEN_RENEW_MARGIN:
                await self.async_login()
            return self._token  # type: ignore[return-value]

    async def _async_get(self, url: str, params: dict[str, Any], auth: bool) -> Any:
        for attempt in range(3):
            headers = {}
            if auth:
                token = await self._async_ensure_token()
                headers["Authorization"] = f"Bearer {token}" if self._bearer else token
            try:
                async with self._session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
                    if resp.status == 401 and auth and attempt < 2:
                        # first refusal: try the other header form; second: the token itself is stale
                        if attempt == 0:
                            self._bearer = not self._bearer
                        else:
                            self._token = None
                        continue
                    if resp.status >= 400:
                        raise OneMapError(f"OneMap answered {resp.status}")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise OneMapError(f"OneMap request failed: {err}") from err
        raise OneMapError("OneMap kept refusing the token")

    async def async_reverse_geocode(self, lat: float, lon: float, buffer: int) -> list[Place]:
        """Places within buffer metres (0-500), nearest first."""
        data = await self._async_get(
            REVGEOCODE_URL,
            {
                "location": f"{lat},{lon}",
                "buffer": max(0, min(500, int(buffer))),
                "addressType": "All",
                "otherFeatures": "N",
            },
            auth=True,
        )
        items = data.get("GeocodeInfo", []) if isinstance(data, dict) else []
        places = [Place.from_api(i, lat, lon) for i in items if isinstance(i, dict)]
        places.sort(key=lambda p: math.inf if p.distance_m is None else p.distance_m)
        return places

    async def async_search(self, query: str, page: int = 1) -> list[dict[str, Any]]:
        """Search by name, address or postal code. Needs no token."""
        data = await self._async_get(
            SEARCH_URL,
            {"searchVal": query, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": page},
            auth=False,
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        return [
            {
                "name": _title(_clean(r.get("BUILDING")) or _clean(r.get("SEARCHVAL"))),
                "address": _title(_clean(r.get("ADDRESS"))),
                "postal_code": _clean(r.get("POSTAL")),
                "latitude": _float(r.get("LATITUDE")),
                "longitude": _float(r.get("LONGITUDE")),
            }
            for r in results
            if isinstance(r, dict)
        ]
