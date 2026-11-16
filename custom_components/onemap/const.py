"""Constants for the OneMap Singapore integration."""

DOMAIN = "onemap"

API_BASE = "https://www.onemap.gov.sg"
TOKEN_URL = f"{API_BASE}/api/auth/post/getToken"
REVGEOCODE_URL = f"{API_BASE}/api/public/revgeocode"
SEARCH_URL = f"{API_BASE}/api/common/elastic/search"

CONF_TRACKED = "tracked_entities"
CONF_BUFFER = "buffer"
CONF_MIN_DISTANCE = "min_distance"
CONF_USE_ZONES = "use_zone_names"

DEFAULT_BUFFER = 100  # metres OneMap searches around the point (0-500)
DEFAULT_MIN_DISTANCE = 100  # metres a tracker must move before a new lookup
DEFAULT_USE_ZONES = True  # in an HA zone: show the zone, don't send the position to OneMap

# A token lasts 3 days; get a new one when less than this is left.
TOKEN_RENEW_MARGIN = 24 * 3600
# At most one lookup per tracker this often; a burst of GPS fixes waits for the last one.
LOOKUP_COOLDOWN = 60

SERVICE_REVERSE_GEOCODE = "reverse_geocode"
SERVICE_SEARCH = "search"
