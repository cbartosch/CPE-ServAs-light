"""Road routing for dispatch legs.

The problem
-----------
Until now a dispatch leg was drawn as a straight line between hub and
intervention point. The travel *minutes* were modelled properly, from archetype
road speeds with a detour factor, but the drawn geometry was a schematic and said
so. Matching a dispatch to actual roads needs a routing engine.

Design
------
`Router` is a protocol with two implementations:

`StraightLineRouter`
    Always available, no network, no dependency. What shipped before.

`OSRMRouter`
    Calls an OSRM HTTP endpoint and returns real road geometry. OSRM is used
    because the API is a plain GET with no key, the response can be requested as
    GeoJSON so no polyline decoding is needed, and it can be self-hosted, which
    matters on a network that will not reach a public service.

Selection is by environment: ``ROUTING_PROVIDER=straight|osrm`` and ``OSRM_URL``.
The default stays ``straight``, so the map keeps working where nothing is
reachable, and a failed OSRM call degrades to a straight line for that leg rather
than blanking the layer.

What is deliberately NOT road-routed
------------------------------------
Ferry legs. A driving profile asked to route Fajardo to Vieques will either fail
or invent an absurd land path. The crossing stays an arc, and only the land
portion — hub to ferry terminal — is sent to the router.

Caching
-------
Routes are cached in-process and optionally on disk. A demo re-runs the same
scenarios repeatedly, and the public OSRM demo server has a usage policy that
discourages hammering it.
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

Coord = tuple[float, float]          # (lon, lat), matching deck.gl order

OSRM_PUBLIC = "https://router.project-osrm.org"
DEFAULT_TIMEOUT = 8.0


@dataclass(frozen=True, slots=True)
class Route:
    coordinates: tuple[Coord, ...]
    distance_m: float
    duration_s: float
    source: str                      # "straight" | "osrm" | "osrm-cache"
    on_roads: bool

    @property
    def path(self) -> list[list[float]]:
        """deck.gl PathLayer geometry."""
        return [[lon, lat] for lon, lat in self.coordinates]

    @property
    def duration_min(self) -> int:
        return int(round(self.duration_s / 60.0))

    @property
    def distance_km(self) -> float:
        return round(self.distance_m / 1000.0, 1)


@runtime_checkable
class Router(Protocol):
    name: str

    def route(self, waypoints: Iterable[Coord]) -> Route: ...


@dataclass(slots=True)
class StraightLineRouter:
    """No network. Geometry is the waypoints themselves."""

    name: str = "straight"

    def route(self, waypoints: Iterable[Coord]) -> Route:
        points = tuple(waypoints)
        if len(points) < 2:
            raise ValueError("a route needs at least two waypoints")
        return Route(points, distance_m=0.0, duration_s=0.0,
                     source="straight", on_roads=False)


@dataclass(slots=True)
class OSRMRouter:
    """Real road geometry from an OSRM endpoint.

    `opener` is injectable so the client can be tested against a canned response
    without a network.
    """

    base_url: str = OSRM_PUBLIC
    profile: str = "driving"
    timeout: float = DEFAULT_TIMEOUT
    cache_dir: pathlib.Path | None = None
    name: str = "osrm"
    opener: object | None = None
    _memo: dict[str, Route] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ url
    def url_for(self, waypoints: tuple[Coord, ...]) -> str:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in waypoints)
        return (f"{self.base_url.rstrip('/')}/route/v1/{self.profile}/{coords}"
                f"?overview=full&geometries=geojson&steps=false")

    @staticmethod
    def cache_key(waypoints: tuple[Coord, ...]) -> str:
        return "|".join(f"{lon:.5f},{lat:.5f}" for lon, lat in waypoints)

    # ---------------------------------------------------------------- parse
    @staticmethod
    def parse(payload: dict, *, source: str = "osrm") -> Route:
        if payload.get("code") != "Ok":
            raise ValueError(f"OSRM returned code {payload.get('code')!r}")
        routes = payload.get("routes") or []
        if not routes:
            raise ValueError("OSRM returned no routes")
        best = routes[0]
        coords = best.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            raise ValueError("OSRM route geometry has fewer than two points")
        return Route(
            coordinates=tuple((float(c[0]), float(c[1])) for c in coords),
            distance_m=float(best.get("distance", 0.0)),
            duration_s=float(best.get("duration", 0.0)),
            source=source, on_roads=True)

    # ----------------------------------------------------------------- disk
    def _disk_path(self, key: str) -> pathlib.Path | None:
        if self.cache_dir is None:
            return None
        safe = key.replace("|", "_").replace(",", "-").replace(".", "p")
        return pathlib.Path(self.cache_dir) / f"{self.profile}-{safe}.json"

    def _read_disk(self, key: str) -> Route | None:
        path = self._disk_path(key)
        if path is None or not path.exists():
            return None
        try:
            return self.parse(json.loads(path.read_text()), source="osrm-cache")
        except Exception:
            return None

    def _write_disk(self, key: str, payload: dict) -> None:
        path = self._disk_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
        except Exception:
            pass                      # a cache write must never break a render

    # ---------------------------------------------------------------- fetch
    def _fetch(self, url: str) -> dict:
        opener = self.opener or urllib.request.urlopen
        with opener(url, timeout=self.timeout) as response:  # type: ignore[operator]
            return json.loads(response.read().decode("utf-8"))

    def route(self, waypoints: Iterable[Coord]) -> Route:
        points = tuple(waypoints)
        if len(points) < 2:
            raise ValueError("a route needs at least two waypoints")
        key = self.cache_key(points)
        if key in self._memo:
            return self._memo[key]
        cached = self._read_disk(key)
        if cached is not None:
            self._memo[key] = cached
            return cached

        payload = self._fetch(self.url_for(points))
        route = self.parse(payload)
        self._write_disk(key, payload)
        self._memo[key] = route
        return route


@dataclass(slots=True)
class FallbackRouter:
    """Try the primary router; fall back per leg rather than per map.

    One unroutable leg should not blank the layer, and the caller needs to know
    which legs are real roads, which is what `Route.on_roads` carries.
    """

    primary: Router
    secondary: Router = field(default_factory=StraightLineRouter)
    name: str = "fallback"
    failures: int = 0

    def route(self, waypoints: Iterable[Coord]) -> Route:
        points = tuple(waypoints)
        try:
            return self.primary.route(points)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            self.failures += 1
            return self.secondary.route(points)


def router_from_env(env: dict[str, str] | None = None) -> Router:
    """Default is `straight`, so nothing breaks where nothing is reachable."""
    source = env if env is not None else os.environ
    provider = source.get("ROUTING_PROVIDER", "straight").strip().lower()
    if provider != "osrm":
        return StraightLineRouter()
    cache = source.get("OSRM_CACHE_DIR", "").strip()
    primary = OSRMRouter(
        base_url=source.get("OSRM_URL", OSRM_PUBLIC),
        profile=source.get("OSRM_PROFILE", "driving"),
        timeout=float(source.get("OSRM_TIMEOUT", DEFAULT_TIMEOUT)),
        cache_dir=pathlib.Path(cache) if cache else None)
    return FallbackRouter(primary=primary)


ROUTING_NOTE = (
    "Set ROUTING_PROVIDER=osrm and OSRM_URL to draw dispatch legs on real roads. "
    "The default is straight-line geometry, which needs no network. Ferry legs are "
    "never road-routed: a driving profile asked to cross to Vieques either fails or "
    "invents a land path, so the crossing stays an arc and only the land leg to the "
    "terminal is sent to the router."
)
