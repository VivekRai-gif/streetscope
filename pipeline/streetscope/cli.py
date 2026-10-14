"""Command line: python -m streetscope build --lat 28.5672 --lon 77.2100 --name aiims

With your own drone or LiDAR survey: python -m streetscope build --cloud scan.laz --name campus
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import date
from pathlib import Path

import numpy as np

from . import canopy, cloud, lidar, osm, points, scenarios, shade, traffic, twin


def build_site(args: argparse.Namespace) -> Path:
    survey = None
    if args.cloud:
        print(f"survey: reading {Path(args.cloud).name}", flush=True)
        survey = cloud.read(args.cloud, args.cloud_epsg)
        loc = cloud.locate(survey)
        if args.lat is None or args.lon is None:
            args.lat, args.lon = round(loc["lat"], 6), round(loc["lon"], 6)
        if not args.radius:
            args.radius = loc["radius_m"]
        args.lidar = "off"
        print(f"survey: {survey['count']:,} points ({survey['format']}, EPSG:{survey['epsg']}, colour {'yes' if survey['rgb'] is not None else 'no'}), "
              f"{loc['width_m']:.0f} x {loc['height_m']:.0f} m around {args.lat:.5f}, {args.lon:.5f}", flush=True)
    if args.lat is None or args.lon is None:
        raise SystemExit("give --lat and --lon, or a survey with --cloud")
    args.radius = args.radius or 300
    out = Path(args.out) / args.name
    out.mkdir(parents=True, exist_ok=True)
    if args.osm:
        elements = osm.load(args.osm)
        signals_queried = osm.queried_signals(args.osm)
        print(f"read {len(elements)} OpenStreetMap elements from {args.osm}")
    else:
        print("asking Overpass (can take a minute)...")
        elements = osm.fetch(args.lat, args.lon, int(args.radius + 40))
        signals_queried = True
        (out / "osm.raw.json").write_text(json.dumps({"elements": elements, "queried": ["signals"]}), encoding="utf-8")
        print(f"downloaded {len(elements)} elements")
    t = twin.build(elements, args.lat, args.lon, args.radius, args.name)
    t["meta"]["signals_queried"] = signals_queried
    got_lidar = False
    if args.lidar != "off":
        lcache = out / "lidar.npz"
        try:
            if lcache.exists():
                r, name = lidar.load(lcache), json.loads((out / "lidar.json").read_text())["project"]
                print("lidar: using cached", lcache)
            else:
                projects = lidar.find_projects(args.lat, args.lon)
                if not projects:
                    raise lidar.LidarUnavailable("no USGS 3DEP project covers this point")
                print(f"lidar: reading {projects[0]['name']} from AWS Open Data (can take a minute)...")
                pts = lidar.read_points(args.lat, args.lon, args.radius, projects[0])
                r, name = lidar.rasterize(pts, args.radius), projects[0]["name"]
                lidar.save(lcache, r)
                (out / "lidar.json").write_text(json.dumps({"project": name}))
            info = lidar.apply(t, r, name)
            got_lidar = True
            print(f"lidar: measured {info['buildings_measured']} of {info['buildings_total']} building heights, "
                  f"{info['tree_tops_found']} tree tops, {info['canopy_cover_pct']}% cover")
        except lidar.LidarUnavailable as exc:
            print("lidar skipped:", exc)
    if not args.no_canopy and not got_lidar:
        cache = out / "canopy.bin"
        try:
            n = shade.Grid(args.radius, 1.0).n
            if cache.exists() and cache.stat().st_size == n * n:   # a cache from another radius is the wrong size
                chm = np.frombuffer(cache.read_bytes(), dtype=np.uint8).reshape(n, n)
                print("canopy map: using cached", cache)
            else:
                print("canopy map: reading a window from AWS Open Data...")
                chm = canopy.to_grid(canopy.read_window(args.lat, args.lon, args.radius), args.lat, args.lon, args.radius)
                cache.write_bytes(chm.tobytes())
            info = canopy.apply(t, chm)
            print(f"canopy map: {info['tree_tops_found']} tree tops, {info['canopy_cover_pct']}% cover, "
                  f"{info['osm_trees']} trees from OpenStreetMap, {info['trees_total']} in total")
        except canopy.CanopyUnavailable as exc:
            print("canopy map skipped:", exc)
    if survey is not None:
        pts = cloud.to_site(survey, args.lat, args.lon, args.radius)
        print(f"survey: ground and vegetation from {len(pts['x']):,} points...", flush=True)
        how = cloud.prepare(pts, args.radius, t)
        r = lidar.rasterize(pts, args.radius)
        cov = cloud.coverage(pts, args.radius)
        label = args.cloud_label or survey.get("label") or f"your survey ({survey['name']})"   # LAS system identifier, if set
        info = lidar.apply(t, r, label, covered=cov, attribution=f"Survey: {label}", source=f"{label}, {how['vegetation_method']}",
                           licence=args.cloud_licence or "as given by the survey owner", kind="The survey", tag="survey")
        t["meta"]["survey"] = {"file": survey["name"], "label": label, "format": survey["format"], "epsg": survey["epsg"],
                               "points": int(survey["file_points"]), "used_points": int(len(pts["x"])), "rgb": survey["rgb"] is not None,
                               "coverage_pct": round(float(cov.mean() * 100), 1), "ground": how["ground_method"],
                               "vegetation": how["vegetation_method"], "derived_pct": how["derived_pct"], "fit_error_m": round(pts["fit_error_m"], 3),
                               "buildings_measured": info["buildings_measured"], "buildings_mapped": info["buildings_total"],
                               "tree_tops": info["tree_tops_found"]}
        t["stats"]["canopy"]["note"] = (f"tree tops from the survey's vegetation ({how['vegetation_method']}) inside the area it covers "
                                        f"({t['meta']['survey']['coverage_pct']}%); outside it, from the canopy map")
        print(f"survey: measured {info['buildings_measured']} of {info['buildings_total']} building heights, {info['tree_tops_found']} tree tops, "
              f"{info['canopy_cover_pct']}% cover where the survey covers (ground: {how['ground_method']}, vegetation: {how['vegetation_method']})", flush=True)
        note = (f"This survey came without classes. We found the ground with a morphological filter, vegetation from colour "
                f"(excess green) and buildings as other points 2.5 m or more above the ground: {how['derived_pct']}% of points are classed by us."
                if how["derived_pct"] > 50 else None)
        meta_p = points.write(out, t, pts, r["dtm"], f"{label}: {survey['format']} file, {survey['file_points']:,} points", 0.25,
                              max_points=args.cloud_web_points, note=note)
        print(f"survey: wrote {meta_p['count']:,} points for the point-cloud view", flush=True)
    day = date.fromisoformat(args.date)
    hours = list(range(6, 19))
    print("computing hourly shade...", flush=True)
    stack, meta, walk2 = shade.compute(t, day, args.tz, hours)
    t["shade"] = meta
    gz = lambda b: gzip.compress(b, 6)
    (out / meta["file"]).write_bytes(gz(stack.tobytes()))
    (out / meta["walk_file"]).write_bytes(gz(walk2.tobytes()))
    for old in ("shade.bin", "walk.bin"):
        (out / old).unlink(missing_ok=True)
    print("planning what-if fixes...")
    n_trees = args.trees or int(min(200, max(25, meta["walk_cells"] / 80)))   # about one tree per 80 m2 of walkway
    sc, arrays = scenarios.build(t, day, args.tz, hours, stack, meta, walk2, n_trees)
    for item in sc:
        st, wk = arrays[item["id"]]
        (out / item["files"]["shade"]).write_bytes(gz(st.tobytes()))
        (out / item["files"]["walk"]).write_bytes(gz(wk.tobytes()))
    t["scenarios"] = sc
    print("screening traffic...")
    t["traffic"] = traffic.analyse(t)
    (out / "twin.json").write_text(json.dumps(t, separators=(",", ":")), encoding="utf-8")
    s = t["stats"]
    print(f"{args.name}: {s['road_ways']} road ways, {s['buildings']} buildings, {s['trees']} trees, {s['bus_stops']} bus stops")
    print("walkway shade % by hour:", dict(zip(meta["hours"], meta["walk_shade_pct"])))
    for g in s["gaps"]:
        print("  gap:", g)
    tr = t["traffic"]
    if tr:
        print(f"  traffic: {tr['summary']['links_over_capacity']} links over capacity, top area score "
              f"{tr['areas'][0]['score'] if tr['areas'] else '-'}, {len(tr['solutions'])} candidate fixes (simulated)")
    for item in sc:
        print(f"  fix {item['id']}: day-mean walkway shade {item['baseline_day_mean_shade_pct']}% -> {item['day_mean_shade_pct']}%, "
              f"{item['extra_walk_m2']} m2 more footpath, cost {item['cost_inr']} (assumed)")
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="streetscope")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a street twin for a place")
    b.add_argument("--lat", type=float, help="centre latitude (optional with --cloud)")
    b.add_argument("--lon", type=float, help="centre longitude (optional with --cloud)")
    b.add_argument("--radius", type=float, default=None, help="half the side of the square in metres (default 300, or what the survey covers)")
    b.add_argument("--name", required=True)
    b.add_argument("--out", default="web/data")
    b.add_argument("--osm", help="use a saved Overpass JSON instead of downloading")
    b.add_argument("--no-canopy", action="store_true", help="skip the canopy height map")
    b.add_argument("--lidar", choices=["auto", "off"], default="auto", help="use USGS 3DEP LiDAR where it exists (US only)")
    b.add_argument("--date", default=date.today().isoformat())
    b.add_argument("--trees", type=int, default=0, help="street trees in the what-if scenarios (0 = about one per 80 m2 of walkway)")
    b.add_argument("--tz", type=float, default=5.5, help="hours from UTC at the site")
    b.add_argument("--cloud", help="your own drone or LiDAR point cloud: LAS, LAZ or PLY (measures buildings and trees)")
    b.add_argument("--cloud-epsg", type=int, help="EPSG code of the cloud if the file does not say, e.g. 32643 for UTM 43N")
    b.add_argument("--cloud-label", default="", help="who made the survey, shown with the points")
    b.add_argument("--cloud-licence", default="", help="the survey's licence, shown with the points")
    b.add_argument("--cloud-web-points", type=int, default=2_000_000, help="points kept for the web point-cloud view")
    b.set_defaults(fn=build_site)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
