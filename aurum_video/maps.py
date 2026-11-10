"""Build stylised map data (SVG path + projected place markers) from a public-domain outline.

Places are illustrative markers: a marker that falls outside the simplified outline is nudged
inland so it sits on land. The map is a stylised graphic, not a navigational chart.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import ROOT, load_json

VIEW_W = 1000.0


def chaikin(ring: list[tuple[float, float]], iterations: int = 3) -> list[tuple[float, float]]:
    pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
    for _ in range(iterations):
        new = []
        n = len(pts)
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            new.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            new.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = new
    return pts


def point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _dist_to_edges(x, y, poly) -> float:
    best = float("inf")
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / ((dx * dx + dy * dy) or 1e-12)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def build_map(geojson_path: Path, places: dict, margin: float = 0.12) -> dict:
    geom = load_json(geojson_path)
    rings = geom["coordinates"] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
    outer = rings[0] if geom["type"] == "Polygon" else max(rings, key=len)
    lat0 = sum(p[1] for p in outer) / len(outer)
    kx = math.cos(math.radians(lat0))

    def proj(lon, lat):
        return lon * kx, -lat

    pts = [proj(*p) for p in outer]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    w, h = maxx - minx, maxy - miny
    scale = VIEW_W * (1 - 2 * margin) / max(w, h)
    view_h = VIEW_W  # square canvas keeps both orientations simple
    ox = (VIEW_W - w * scale) / 2
    oy = (view_h - h * scale) / 2

    def to_view(lon, lat):
        x, y = proj(lon, lat)
        return (ox + (x - minx) * scale, oy + (y - miny) * scale)

    ring = chaikin([to_view(*p) for p in outer], 3)
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in ring) + " Z"
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    out_places = {}
    for key, p in places.items():
        x, y = to_view(p["lon"], p["lat"])
        steps = 0
        while (not point_in_poly(x, y, ring) or _dist_to_edges(x, y, ring) < 9) and steps < 200:
            x += (cx - x) * 0.03
            y += (cy - y) * 0.03
            steps += 1
        out_places[key] = {"x": round(x, 1), "y": round(y, 1), "label": p["label"], "nudged": steps > 0}
    return {"path": path, "w": VIEW_W, "h": view_h, "places": out_places,
            "credit": load_json(ROOT / "assets" / "registry.json")["map_credit"]}


def map_for_slug(video_dir: Path) -> dict:
    cfg = load_json(video_dir / "places.json")
    return build_map(ROOT / cfg["outline"], cfg["places"])
