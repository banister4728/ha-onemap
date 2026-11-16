# OneMap Singapore for Home Assistant

Place names for your people and trackers, from [OneMap](https://www.onemap.gov.sg), Singapore's official map by the Singapore Land Authority.

`sensor.onemap_jamie_place` → **Tampines Mall**, with the block, road and postal code as attributes.

## What it does

- **A place sensor per person or device tracker you pick.** Outside your zones it shows the nearest building OneMap knows (a mall, a hospital, an HDB block such as "Blk 81 Marine Parade Central"). Inside a zone it shows the zone, and sends nothing to OneMap.
- **Few lookups.** A tracker must move (100 m by default) before it's looked up again, and each tracker is looked up at most once a minute. The last answer survives restarts.
- **Signs itself in.** OneMap tokens last 3 days; the integration gets a new one before it runs out. If OneMap ever refuses the password, Home Assistant asks you for the new one.
- **Two actions** that return data:
  - `onemap.reverse_geocode`: buildings and addresses near a latitude and longitude, nearest first.
  - `onemap.search`: find a place by name, address or postal code.

## Install

1. In HACS, open the menu (⋮) → **Custom repositories**. Add `https://github.com/banister4728/ha-onemap` with type **Integration**.
2. Find **OneMap Singapore** in HACS and download it.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → OneMap Singapore.** Sign in with your OneMap account, then pick the people or trackers to follow.

You need a free OneMap API account: register on the OneMap developer site with an email address and set the password from the email it sends.

Change the people, search radius or move distance later under the integration's **Configure** button.

## Examples

```yaml
action: onemap.reverse_geocode
data:
  latitude: 1.3011
  longitude: 103.9053
response_variable: here
```

```yaml
action: onemap.search
data:
  query: "449269"
response_variable: found
```

## Privacy

Positions go to OneMap only when a tracker is outside every zone (with the zone option on) and has moved. Your email and password are kept in Home Assistant's own config storage, like any other integration's login.

## Limits

OneMap is free, with a rate limit far above what a household uses. This integration makes a handful of lookups per person per day.

Not affiliated with the Singapore Land Authority. Map data © OneMap, Singapore Land Authority.
