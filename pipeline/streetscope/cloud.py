"""Level 1 data from your own survey: a drone or LiDAR point cloud (LAS, LAZ or PLY) of any town or city.

The file says where it is (its coordinate system), so no map search is needed. We turn the points into the same 1 m
rasters as the USGS reader (ground, surface and vegetation height), so building heights, trees and shade come from
the survey, exactly as for USGS LiDAR.

Drone photogrammetry clouds usually have no classes and no multiple returns. Then we find the ground with a
progressive morphological filter (Zhang et al. 2003) and vegetation from colour (excess green, 2g - r - b).
Run: python -m streetscope build --cloud scan.laz --name campus      (centre and radius come from the file)
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from .geo import Frame
from .shade import Grid

GROUND_TOL_M = 0.4           # a point this close to the ground surface is ground
EXG_VEG = 0.045              # excess green above this is leaves or grass
PMF_WINDOWS = (3, 5, 9, 17, 33, 65)   # cells; the largest must be wider than the widest roof
PMF_DH0, PMF_SLOPE, PMF_DHMAX = 0.3, 0.15, 3.0


class CloudError(RuntimeError):
    pass


def read(path: str | Path, epsg: int | None = None, max_points: int = 30_000_000) -> dict:
    """Read a LAS, LAZ or PLY file. Returns raw coordinates in the file's CRS plus class, returns and colour."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".las", ".laz"):
        d = _read_las(p, max_points)
    elif ext == ".ply":
        d = _read_ply(p, max_points)
    else:
        raise CloudError(f"{p.name}: use a LAS, LAZ or PLY file")
    if epsg:
        d["epsg"] = int(epsg)
    if not d.get("epsg"):
        raise CloudError("the file does not say its coordinate system; give its EPSG code (for example 32643 for UTM 43N)")
    if d["count"] < 1000:
        raise CloudError("the file has fewer than 1,000 points")
    d["name"] = p.name
    return d


def _read_las(p: Path, max_points: int) -> dict:
    import laspy

    with laspy.open(p) as f:
        h = f.header
        n = int(h.point_count)
        epsg = None
        try:
            crs = h.parse_crs()
            if crs is not None:
                epsg = crs.to_epsg() or next((c.to_epsg() for c in getattr(crs, "sub_crs_list", []) if c.to_epsg()), None)
        except Exception:
            epsg = None
        ident = str(h.system_identifier or "").strip("\x00 ").strip()
        step = max(1, math.ceil(n / max_points))
        dims = set(h.point_format.dimension_names)
        xs, ys, zs, cl, nr, rgb = [], [], [], [], [], []
        for ch in f.chunk_iterator(2_000_000):
            xs.append(np.asarray(ch.x)[::step])
            ys.append(np.asarray(ch.y)[::step])
            zs.append(np.asarray(ch.z)[::step])
            cl.append(np.asarray(ch.classification, dtype=np.uint8)[::step])
            nr.append(np.asarray(ch.number_of_returns, dtype=np.uint8)[::step])
            if {"red", "green", "blue"} <= dims:
                rgb.append(np.stack([np.asarray(ch.red), np.asarray(ch.green), np.asarray(ch.blue)], 1)[::step])
    out = {"x": np.concatenate(xs), "y": np.concatenate(ys), "z": np.concatenate(zs), "cls": np.concatenate(cl),
           "nr": np.concatenate(nr), "epsg": epsg, "format": "LAZ" if p.suffix.lower() == ".laz" else "LAS", "file_points": n,
           "label": ident if ident.upper() not in ("", "OTHER", "MODIFICATION", "EXTRACTION", "MERGE") else None}
    out["rgb"] = _rgb8(np.concatenate(rgb)) if rgb else None
    out["count"] = len(out["x"])
    return out


def _rgb8(c: np.ndarray) -> np.ndarray | None:
    c = np.asarray(c)
    if not c.size or c.max() == 0:
        return None
    return (c >> 8).astype(np.uint8) if c.max() > 255 else c.astype(np.uint8)


PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "<i2", "int16": "<i2", "ushort": "<u2",
             "uint16": "<u2", "int": "<i4", "int32": "<i4", "uint": "<u4", "uint32": "<u4", "float": "<f4",
             "float32": "<f4", "double": "<f8", "float64": "<f8"}


def _read_ply(p: Path, max_points: int) -> dict:
    with p.open("rb") as f:
        head = b""
        while b"end_header" not in head:
            line = f.readline()
            if not line:
                raise CloudError("not a PLY file")
            head += line
        start = f.tell()
    lines = head.decode("ascii", "replace").splitlines()
    fmt = next((l.split()[1] for l in lines if l.startswith("format")), "")
    n, props, in_v, epsg = 0, [], False, None
    for l in lines:
        w = l.split()
        if not w:
            continue
        if w[0] == "element":
            in_v = w[1] == "vertex"
            if in_v:
                n = int(w[2])
        elif w[0] == "property" and in_v and w[1] != "list":
            props.append((w[2], PLY_TYPES.get(w[1], "<f4")))
        elif w[0] == "comment":
            m = re.search(r"EPSG[:\s]*(\d{4,5})", l, re.I)
            if m:
                epsg = int(m.group(1))
    names = [a for a, _ in props]
    if not {"x", "y", "z"} <= set(names):
        raise CloudError("the PLY has no x, y, z")
    if fmt == "binary_little_endian":
        a = np.memmap(p, dtype=np.dtype(props), mode="r", offset=start, shape=(n,))
    elif fmt == "ascii":
        a = np.loadtxt(p, skiprows=len(lines), max_rows=n, dtype=np.dtype([(k, "<f8") for k in names]))
    else:
        raise CloudError("only binary little-endian or ASCII PLY is supported")
    step = max(1, math.ceil(n / max_points))
    a = a[::step]
    cname = next((k for k in names if k.lower() in ("classification", "scalar_classification", "class")), None)
    rgb = None
    if {"red", "green", "blue"} <= set(names):
        rgb = _rgb8(np.stack([np.asarray(a["red"]), np.asarray(a["green"]), np.asarray(a["blue"])], 1).astype(np.uint16))
    return {"x": np.asarray(a["x"], dtype=np.float64), "y": np.asarray(a["y"], dtype=np.float64), "z": np.asarray(a["z"], dtype=np.float64),
            "cls": np.asarray(a[cname], dtype=np.uint8) if cname else np.zeros(len(a), np.uint8), "nr": np.ones(len(a), np.uint8),
            "rgb": rgb, "epsg": epsg, "format": "PLY", "file_points": n, "count": len(a)}


def peek(path: str | Path, epsg: int | None = None) -> dict:
    """Where a survey is, without reading every point (LAS/LAZ header; PLY files are read)."""
    p = Path(path)
    if p.suffix.lower() in (".las", ".laz"):
        import laspy

        with laspy.open(p) as f:
            h = f.header
            if not epsg:
                try:
                    crs = h.parse_crs()
                    epsg = (crs.to_epsg() or next((c.to_epsg() for c in getattr(crs, "sub_crs_list", []) if c.to_epsg()), None)) if crs else None
                except Exception:
                    epsg = None
            if not epsg:
                raise CloudError("the file does not say its coordinate system; give its EPSG code (for example 32643 for UTM 43N)")
            d = {"x": np.array([h.mins[0], h.maxs[0]]), "y": np.array([h.mins[1], h.maxs[1]]), "epsg": int(epsg), "count": int(h.point_count)}
    else:
        d = read(p, epsg, max_points=2_000_000)
    return {**locate(d), "epsg": d["epsg"], "points": d.get("file_points", d["count"])}


def _transformer(epsg: int):
    from pyproj import CRS, Transformer

    crs = CRS.from_epsg(epsg)
    if not crs.is_projected:
        raise CloudError(f"EPSG:{epsg} is not a projected coordinate system in metres or feet (use UTM, for example)")
    unit = crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0
    return Transformer.from_crs(crs, 4326, always_xy=True), float(unit)


def locate(d: dict) -> dict:
    """Centre (lat, lon) and the largest twin radius the survey covers."""
    tr, unit = _transformer(d["epsg"])
    qx, qy = np.percentile(d["x"], [1, 99]), np.percentile(d["y"], [1, 99])
    lon, lat = tr.transform((qx[0] + qx[1]) / 2, (qy[0] + qy[1]) / 2)
    w, h = (qx[1] - qx[0]) * unit, (qy[1] - qy[0]) * unit
    radius = float(np.clip(math.floor(min(w, h) / 2 / 10) * 10, 150, 800))
    return {"lat": float(lat), "lon": float(lon), "width_m": float(w), "height_m": float(h), "radius_m": radius}


def to_site(d: dict, lat: float, lon: float, radius: float) -> dict:
    """Points in the twin's frame (x east, z south, metres), cropped to the twin square.

    A projected grid is not aligned with true north away from its central meridian (UTM can be off by a degree), so the
    mapping is an affine fit to exact transforms of a 9 x 9 grid of control points, not just an offset."""
    tr, unit = _transformer(d["epsg"])
    fr = Frame(lat, lon)
    gx = np.linspace(np.percentile(d["x"], 0.5), np.percentile(d["x"], 99.5), 9)
    gy = np.linspace(np.percentile(d["y"], 0.5), np.percentile(d["y"], 99.5), 9)
    cx, cy = np.meshgrid(gx, gy)
    lo, la = tr.transform(cx.ravel(), cy.ravel())
    tx = (np.asarray(lo) - lon) * fr._kx
    tz = -(np.asarray(la) - lat) * fr._kz
    ox, oy = gx.mean(), gy.mean()
    A = np.stack([cx.ravel() - ox, cy.ravel() - oy, np.ones(cx.size)], 1)
    mx, *_ = np.linalg.lstsq(A, tx, rcond=None)
    mz, *_ = np.linalg.lstsq(A, tz, rcond=None)
    fit_err = float(np.abs(np.concatenate([A @ mx - tx, A @ mz - tz])).max())
    dx, dy = d["x"] - ox, d["y"] - oy
    x = mx[0] * dx + mx[1] * dy + mx[2]
    z = mz[0] * dx + mz[1] * dy + mz[2]
    keep = (np.abs(x) <= radius) & (np.abs(z) <= radius)
    # photogrammetry leaves a few wild points far below the ground and far above the roofs (water, glass, sky)
    lo, hi = np.percentile(d["z"][keep], [1, 99.9]) if keep.any() else (0, 0)
    keep &= (d["z"] >= lo - 8 / unit) & (d["z"] <= hi + 25 / unit)
    if keep.sum() < 1000:
        raise CloudError("almost no points fall inside the twin area")
    out = {"x": x[keep], "z": z[keep], "h": d["z"][keep] * unit, "cls": d["cls"][keep].copy(), "nr": d["nr"][keep].copy(),
           "rgb": d["rgb"][keep] if d.get("rgb") is not None else None, "fit_error_m": fit_err}
    out["derived"] = np.zeros(len(out["x"]), dtype=bool)
    return out


def ground_surface(x: np.ndarray, z: np.ndarray, h: np.ndarray, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Bare-earth heights on the grid from unclassified points: a progressive morphological filter.

    Openings with growing windows remove objects narrower than the window; a cell whose lowest point rises above the
    opened surface by more than the slope allows is not ground. Returns (dtm, cells that had points)."""
    from scipy import ndimage

    n = grid.n
    ci = np.floor((x - grid.x0) / grid.cell).astype(int)
    cj = np.floor((z - grid.z0) / grid.cell).astype(int)
    ok = (ci >= 0) & (ci < n) & (cj >= 0) & (cj < n)
    flat = cj[ok] * n + ci[ok]
    zmin = np.full(n * n, np.inf)
    np.minimum.at(zmin, flat, h[ok])
    zmin = zmin.reshape(n, n)
    have = np.isfinite(zmin)
    if not have.any():
        raise CloudError("no points inside the grid")
    near = ndimage.distance_transform_edt(~have, return_distances=False, return_indices=True)
    surf = zmin[tuple(near)]
    # one-cell pits (multipath, wells) would pull the opening down; a small median removes them first
    surf = ndimage.median_filter(surf, size=3)
    nonground = np.zeros((n, n), dtype=bool)
    prev, w_prev = surf, 1
    for k, w in enumerate(PMF_WINDOWS):
        w_cells = max(1, int(round(w / grid.cell))) | 1
        op = ndimage.grey_opening(prev, size=(w_cells, w_cells))
        dh = PMF_DH0 if k == 0 else min(PMF_DH0 + PMF_SLOPE * (w - w_prev), PMF_DHMAX)
        nonground |= (prev - op) > dh
        prev, w_prev = op, w
    ground = have & ~nonground
    if ground.sum() < 50:
        raise CloudError("could not find the ground in the survey")
    near = ndimage.distance_transform_edt(~ground, return_distances=False, return_indices=True)
    dtm = surf[tuple(near)]
    smooth = ndimage.uniform_filter(dtm, size=5)
    dtm = np.where(ground, dtm, smooth)
    return dtm.astype(np.float32), have


def prepare(pts: dict, radius: float, twin: dict | None = None) -> dict:
    """Fill in the classes a drone survey lacks (ground, vegetation, building), marking them as ours.

    With the twin, a raised point is a building only inside a mapped footprint; outside, a dull brown-green one is
    dry-season scrub (common in Indian surveys before the monsoon), and anything else stays unclassified."""
    grid = Grid(radius, 1.0)
    cls, derived = pts["cls"], pts["derived"]
    unl = ~np.isin(cls, (2, 3, 4, 5, 6, 9))
    info = {"survey_ground": bool((cls == 2).mean() > 0.01), "survey_vegetation": bool(np.isin(cls, (3, 4, 5)).mean() > 0.005)}
    if info["survey_ground"]:
        from .lidar import rasterize

        dtm = rasterize({**pts, "cls": cls}, radius)["dtm"]
        info["ground_method"] = "survey classes"
    else:
        dtm, _ = ground_surface(pts["x"], pts["z"], pts["h"], grid)
        info["ground_method"] = "morphological filter"
    i = np.clip(np.floor((pts["x"] - grid.x0) / grid.cell).astype(int), 0, grid.n - 1)
    j = np.clip(np.floor((pts["z"] - grid.z0) / grid.cell).astype(int), 0, grid.n - 1)
    agl = pts["h"] - dtm[j, i]
    if not info["survey_ground"]:
        g = unl & (agl < GROUND_TOL_M)
        cls[g], derived[g] = 2, True
        unl &= ~g
    veg = np.zeros(len(cls), dtype=bool)
    if not info["survey_vegetation"] and pts.get("rgb") is not None and not (pts["nr"] > 1).any():
        c = pts["rgb"].astype(np.float32)
        s = c.sum(1) + 1.0
        exg = (2 * c[:, 1] - c[:, 0] - c[:, 2]) / s
        veg = unl & (exg > EXG_VEG) & (agl >= GROUND_TOL_M)
        cls[veg & (agl >= 2.0)] = 5
        cls[veg & (agl < 2.0)] = 3
        derived[veg] = True
        info["vegetation_method"] = "colour (excess green)"
    elif info["survey_vegetation"]:
        info["vegetation_method"] = "survey classes"
    else:
        info["vegetation_method"] = "multiple returns" if (pts["nr"] > 1).any() else "none"
    b = unl & ~veg & (agl >= 2.5)
    if not (cls == 6).any():
        if twin is not None:
            from scipy import ndimage

            from .canopy import building_mask

            inside = ndimage.binary_dilation(building_mask(twin, grid), iterations=2)[j, i]
            if pts.get("rgb") is not None:
                c = pts["rgb"].astype(np.float32)
                exg = (2 * c[:, 1] - c[:, 0] - c[:, 2]) / (c.sum(1) + 1.0)
                dry = b & ~inside & (exg > -0.03) & (c.mean(1) < 165)
                cls[dry & (agl >= 2.0)], derived[dry] = 5, True
                b &= ~dry
            b &= inside
        cls[b], derived[b] = 6, True
    info["derived_pct"] = round(float(derived.mean() * 100), 1)
    info["classes"] = {k: int((cls == c).sum()) for k, c in (("ground", 2), ("vegetation", 5), ("low vegetation", 3), ("building", 6))}
    return info


def coverage(pts: dict, radius: float) -> np.ndarray:
    """Grid cells the survey actually saw (a few metres of slack around each point)."""
    from scipy import ndimage

    grid = Grid(radius, 1.0)
    n = grid.n
    ci = np.clip(np.floor((pts["x"] - grid.x0) / grid.cell).astype(int), 0, n - 1)
    cj = np.clip(np.floor((pts["z"] - grid.z0) / grid.cell).astype(int), 0, n - 1)
    m = np.zeros((n, n), dtype=bool)
    m[cj, ci] = True
    return ndimage.binary_closing(m, iterations=3) | m

