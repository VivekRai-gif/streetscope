import numpy as np
import pytest

from streetscope import cloud
from streetscope.shade import Grid

LAT, LON = 23.2104, 72.6862          # IIT Gandhinagar, UTM zone 43N (about 2.3 degrees west of the central meridian)


def _scene(n=60_000, seed=1):
    """Flat ground at 70 m, one 12 m block (a mapped building) and one green tree, in site metres."""
    r = np.random.default_rng(seed)
    x, z = r.uniform(-80, 80, n), r.uniform(-80, 80, n)
    h = 70 + r.normal(0, 0.03, n)
    rgb = np.tile(np.array([[150, 140, 120]], np.uint8), (n, 1))
    blk = (np.abs(x - 30) < 10) & (np.abs(z - 30) < 10)
    h[blk] = 82.0
    rgb[blk] = [205, 205, 200]
    tree = np.hypot(x + 30, z + 30) < 4
    h[tree] = 70 + 7 - np.hypot(x + 30, z + 30)[tree] * 0.5
    rgb[tree] = [70, 120, 50]
    pts = {"x": x, "z": z, "h": h, "cls": np.zeros(n, np.uint8), "nr": np.ones(n, np.uint8), "rgb": rgb,
           "derived": np.zeros(n, bool)}
    twin = {"buildings": [{"footprint": [[20, 20], [40, 20], [40, 40], [20, 40]]}]}
    return pts, twin, blk, tree


def test_ground_filter_removes_roofs_and_trees():
    pts, _, blk, _ = _scene()
    grid = Grid(80, 1.0)
    dtm, have = cloud.ground_surface(pts["x"], pts["z"], pts["h"], grid)
    assert have.mean() > 0.9
    assert np.abs(dtm - 70).max() < 0.5                 # the 12 m block and the tree are not ground


def test_prepare_classes_a_survey_without_labels():
    pts, twin, blk, tree = _scene()
    info = cloud.prepare(pts, 80, twin)
    assert info["ground_method"] == "morphological filter" and info["vegetation_method"].startswith("colour")
    assert (pts["cls"][blk] == 6).mean() > 0.95          # roof inside the mapped footprint -> building
    assert (np.isin(pts["cls"][tree], (3, 5))).mean() > 0.9   # green and raised -> vegetation
    ground = ~blk & ~tree
    assert (pts["cls"][ground] == 2).mean() > 0.97
    assert pts["derived"].all()                           # every class here is ours, and marked so


def test_dry_scrub_outside_footprints_is_vegetation_not_building():
    pts, twin, blk, _ = _scene()
    scrub = np.hypot(pts["x"] + 40, pts["z"] - 40) < 5
    pts["h"][scrub] = 74.0
    pts["rgb"][scrub] = [120, 110, 80]                    # brown-olive, not green: dry season
    cloud.prepare(pts, 80, twin)
    assert (pts["cls"][scrub] == 6).sum() == 0
    assert (pts["cls"][scrub] == 5).mean() > 0.9


def test_to_site_follows_true_north_not_the_utm_grid():
    from pyproj import Transformer

    from streetscope.geo import Frame

    to_utm = Transformer.from_crs(4326, 32643, always_xy=True)
    fr = Frame(LAT, LON)
    # points on a 400 m grid around the centre (41 x 41), in UTM
    gx, gz = np.meshgrid(np.linspace(-200, 200, 41), np.linspace(-200, 200, 41))
    la, lo = np.vectorize(fr.to_latlon)(gx.ravel(), gz.ravel())
    ux, uy = to_utm.transform(lo, la)
    d = {"x": np.asarray(ux), "y": np.asarray(uy), "z": np.full(len(ux), 70.0), "cls": np.zeros(len(ux), np.uint8),
         "nr": np.ones(len(ux), np.uint8), "rgb": None, "epsg": 32643}
    p = cloud.to_site(d, LAT, LON, 250)
    assert p["fit_error_m"] < 0.05
    assert np.abs(p["x"] - gx.ravel()).max() < 0.05 and np.abs(p["z"] - gz.ravel()).max() < 0.05
    # a plain offset would be off by metres here: the UTM grid is rotated about 0.9 degrees from true north
    off_x = (np.asarray(ux) - ux[840])           # 840: the centre of the 41 x 41 grid
    assert np.abs(off_x - gx.ravel()).max() > 2


def test_las_round_trip_reads_crs_colour_and_credit(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyproj import CRS, Transformer

    ux, uy = Transformer.from_crs(4326, 32643, always_xy=True).transform(LON, LAT)
    r = np.random.default_rng(2)
    n = 5000
    f = laspy.LasData(laspy.LasHeader(point_format=2, version="1.2"))
    f.header.scales = [0.001] * 3
    f.header.offsets = [ux, uy, 0]
    f.header.add_crs(CRS.from_epsg(32643))
    f.header.system_identifier = "Test drone survey"
    f.x, f.y, f.z = ux + r.uniform(-300, 300, n), uy + r.uniform(-200, 200, n), 70 + r.uniform(0, 1, n)
    f.red, f.green, f.blue = (np.full(n, 40000, np.uint16),) * 3
    path = tmp_path / "scan.laz"
    f.write(path)
    d = cloud.read(path)
    assert d["epsg"] == 32643 and d["count"] == n and d["label"] == "Test drone survey"
    assert d["rgb"].dtype == np.uint8 and d["rgb"].max() == 40000 >> 8
    loc = cloud.peek(path)
    assert abs(loc["lat"] - LAT) < 0.002 and abs(loc["lon"] - LON) < 0.002
    assert 190 <= loc["radius_m"] <= 200                  # half the shorter side, rounded down to 10 m


def test_a_file_without_crs_needs_an_epsg(tmp_path):
    laspy = pytest.importorskip("laspy")
    f = laspy.LasData(laspy.LasHeader(point_format=0, version="1.2"))
    f.x, f.y, f.z = np.arange(2000.0) + 263000, np.arange(2000.0) + 2568000, np.full(2000, 70.0)
    path = tmp_path / "nocrs.las"
    f.write(path)
    with pytest.raises(cloud.CloudError, match="EPSG"):
        cloud.read(path)
    assert cloud.read(path, epsg=32643)["epsg"] == 32643
