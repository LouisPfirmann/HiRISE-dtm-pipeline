# /// script
# requires-python = ">=3.11"
# dependencies = ["rasterio", "numpy"]
# ///
"""
Scene-specific long-wavelength check: aggregate the juncture DTM to the
HRSC h2609 strip's 125 m resolution and compare relief. HRSC cannot see
4 m detail, but it is independent of this DTM's stereo geometry — a
scene-level tilt or scale error would show up here.

Usage: uv run scene_check_hrsc.py <juncture_dtm.tif> <h2609_0000_dt4.img>
"""

import sys

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin

AGG = 125.0  # m, HRSC grid


def main(dtm_path, hrsc_path):
    with rasterio.open(dtm_path) as src:
        z = src.read(1).astype(np.float64)
        nod = src.nodata if src.nodata is not None else -3.4028234663852886e38
        z[z == nod] = np.nan
        n = int(round(AGG / src.transform.a))
        h, w = (z.shape[0] // n) * n, (z.shape[1] // n) * n
        blocks = z[:h, :w].reshape(h // n, n, w // n, n)
        za = np.nanmean(np.nanmean(blocks, axis=3), axis=1)
        frac = np.isfinite(z[:h, :w]).reshape(h // n, n, w // n, n)
        cov = frac.mean(axis=(1, 3))
        za[cov < 0.5] = np.nan  # require half-full aggregation cells
        tra = from_origin(src.transform.c, src.transform.f, AGG, AGG)
        crs = src.crs

    with rasterio.open(hrsc_path) as hr:
        zh = np.full(za.shape, np.nan)
        reproject(hr.read(1).astype(np.float64), zh,
                  src_transform=hr.transform, src_crs=hr.crs,
                  dst_transform=tra, dst_crs=crs,
                  src_nodata=hr.nodata, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)

    ok = ~np.isnan(za) & ~np.isnan(zh)
    d = za[ok] - zh[ok]
    d0 = d - np.median(d)
    rel_ours = np.nanmax(za[ok]) - np.nanmin(za[ok])
    rel_hrsc = np.nanmax(zh[ok]) - np.nanmin(zh[ok])
    cc = np.corrcoef(za[ok], zh[ok])[0, 1]
    print(f"common 125 m cells: {ok.sum():,}")
    print(f"datum offset vs HRSC strip (median): {np.median(d):+.1f} m "
          f"(HRSC strip is sphere-referenced; expected large)")
    print(f"after offset removal: RMS {np.sqrt(np.mean(d0**2)):.1f} m, "
          f"95th pct |dz| {np.percentile(np.abs(d0),95):.1f} m")
    print(f"relief over common cells: ours {rel_ours:.0f} m, "
          f"HRSC {rel_hrsc:.0f} m ({100*rel_ours/rel_hrsc:.1f}%)")
    print(f"elevation correlation: r = {cc:.4f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
