"""Export a classified point cloud for the web point-cloud inspector (USGS 3DEP LiDAR, or your own survey via cli --cloud).

Run: python -m streetscope.points --site web/data/dupont

Writes points.bin.gz (8 bytes per point: int16 x, y, z in steps of scale_m (1 cm up to 320 m radius) in the site frame
with y up, uint8 class, uint8 height above ground in 0.25 m steps), points.rgb.gz (3 bytes per point, when the survey
has colour) and points.json (counts, source, class table).
Classes: 1 ground, 2 road, 3 building, 4 vegetation, 5 water, 0 other. Bit 0x80 marks a class we derived
(from footprints, road widths and multiple returns) rather than one the survey labelled.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from . import lidar
from .shade import Grid, polygon_mask, stamp_polyline

DERIVED = 0x80
NAMES = {0: "other", 1: "ground", 2: "road", 3: "building", 4: "vegetation", 5: "water"}


def classify(x, z, h, cls, nr, twin: dict, dtm: np.ndarray, grid: Grid):
    """Our class per point, plus height above ground. Survey labels win; we fill in the unlabelled points."""
    i = np.clip(np.floor((x - grid.x0) / grid.cell).astype(int), 0, grid.n - 1)
    j = np.clip(np.floor((z - grid.z0) / grid.cell).astype(int), 0, grid.n - 1)
    agl = h - dtm[j, i]
    bld = np.zeros((grid.n, grid.n), dtype=bool)
    for b in twin["buildings"]:
        sl, m = polygon_mask(grid, b["footprint"])
        if sl is not None:
            bld[sl] |= m
    road = np.zeros((grid.n, grid.n), dtype=bool)
    for r in twin["roads"]:
        if r["cls"] != "walk" and len(r["pts"]) > 1:
            stamp_polyline(grid, r["pts"], r["width_m"] / 2, road)
    in_b, on_r = bld[j, i], road[j, i]
    out = np.zeros(x.shape, dtype=np.uint8)
    lab = cls.astype(int)
    out[lab == 2] = 1
    out[(lab == 2) & on_r] = 2
    out[lab == 6] = 3
    out[np.isin(lab, (3, 4, 5))] = 4
    out[lab == 9] = 5
    # only the standard ASPRS codes are trusted; other codes (some older surveys reuse 17 and up) are classed by us
    un = ~np.isin(lab, (2, 6, 3, 4, 5, 9))
    low = un & (agl < 0.4)
    out[low] = np.where(on_r[low], 2, 1) | DERIVED
    b_ = un & ~low & in_b & (agl > 2.0)
    out[b_] = 3 | DERIVED
    v_ = un & ~low & ~b_ & (nr > 1) & (agl > 1.5)
    out[v_] = 4 | DERIVED
    return out, agl


def export(site: Path, max_points: int = 1_200_000, spacing_m: float = 0.7, seed: int = 3) -> dict:
    twin = json.loads((site / "twin.json").read_text(encoding="utf-8"))
    c, radius = twin["meta"]["center"], twin["meta"]["radius_m"]
    projects = lidar.find_projects(c["lat"], c["lon"])
    if not projects:
        raise lidar.LidarUnavailable("no USGS 3DEP project covers this point")
    want = json.loads((site / "lidar.json").read_text())["project"] if (site / "lidar.json").exists() else None
    project = next((p for p in projects if p["name"] == want), projects[0])
    pts = lidar.read_points(c["lat"], c["lon"], radius, project, spacing_m=spacing_m, max_nodes=400)
    dtm = lidar.rasterize(pts, radius)["dtm"]          # ground surface from the survey's own ground points
    source = f"USGS 3D Elevation Program LiDAR, project {project['name']}, read from AWS Open Data (usgs-lidar-public)"
    return write(site, twin, pts, dtm, source, spacing_m, max_points, seed)


def write(site: Path, twin: dict, pts: dict, dtm: np.ndarray, source: str, spacing_m: float, max_points: int = 1_200_000,
          seed: int = 3, note: str | None = None) -> dict:
    """Write points.bin.gz (+ points.rgb.gz when the survey has colour) and points.json for the web inspector."""
    radius = twin["meta"]["radius_m"]
    x, z, h, cls, nr = pts["x"], pts["z"], pts["h"].astype(np.float64), pts["cls"], pts["nr"]
    rgb, ours = pts.get("rgb"), pts.get("derived")
    keep = (np.abs(x) <= radius) & (np.abs(z) <= radius) & ~np.isin(cls, (7, 18))
    x, z, h, cls, nr = x[keep], z[keep], h[keep], cls[keep], nr[keep]
    rgb = rgb[keep] if rgb is not None else None
    ours = ours[keep] if ours is not None else None
    grid = Grid(radius, 1.0)
    klass, agl = classify(x, z, h, cls, nr, twin, dtm, grid)
    if ours is not None:
        klass[ours] |= DERIVED                         # classes we filled in for a survey that had none
    g0 = float(np.median(dtm))
    if len(x) > max_points:
        idx = np.random.default_rng(seed).choice(len(x), max_points, replace=False)
        idx.sort()
        x, z, h, klass, agl = x[idx], z[idx], h[idx], klass[idx], agl[idx]
        rgb = rgb[idx] if rgb is not None else None
    n = len(x)
    scale = 0.01 if radius <= 320 else 0.02 if radius <= 650 else 0.05   # int16 must reach the edge of the site
    rec = np.zeros(n, dtype=[("x", "<i2"), ("y", "<i2"), ("z", "<i2"), ("c", "u1"), ("a", "u1")])
    rec["x"] = np.clip(np.round(x / scale), -32767, 32767)
    rec["y"] = np.clip(np.round((h - g0) / scale), -32767, 32767)
    rec["z"] = np.clip(np.round(z / scale), -32767, 32767)
    rec["c"] = klass
    rec["a"] = np.clip(np.round(agl * 4), 0, 255)
    (site / "points.bin.gz").write_bytes(gzip.compress(rec.tobytes(), 6))
    if rgb is not None:
        (site / "points.rgb.gz").write_bytes(gzip.compress(np.ascontiguousarray(rgb, dtype=np.uint8).tobytes(), 6))
    else:
        (site / "points.rgb.gz").unlink(missing_ok=True)
    base = klass & 0x7F
    meta = {
        "count": n, "bytes_per_point": 8, "scale_m": scale, "frame": "site metres: x east, y up from the median ground, z south",
        "source": source, "spacing_m": spacing_m, "ground_height_m": round(g0, 2), "rgb": rgb is not None,
        "classes": {NAMES[k]: int((base == k).sum()) for k in NAMES},
        "derived": int(((klass & DERIVED) > 0).sum()),
        "derived_note": note or ("The survey labels ground and some buildings. Unlabelled points are classed by us: near the ground "
                                 "(road if inside an OpenStreetMap road width), inside a building footprint, or vegetation from multiple returns."),
    }
    (site / "points.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", required=True, help="site folder, for example web/data/dupont")
    ap.add_argument("--max-points", type=int, default=1_200_000)
    ap.add_argument("--spacing", type=float, default=0.7)
    a = ap.parse_args()
    meta = export(Path(a.site), a.max_points, a.spacing)
    print(json.dumps({k: meta[k] for k in ("count", "classes", "derived")}))


if __name__ == "__main__":
    main()
