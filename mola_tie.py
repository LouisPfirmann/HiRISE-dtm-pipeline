# /// script
# requires-python = ">=3.11"
# dependencies = ["rasterio", "numpy", "scipy"]
# ///
"""
Register a DEM to the MOLA-HRSC blended DEM: horizontal + vertical
(Nuth & Kaab 2011, solved at the blend's 200 m scale), optional tilt.
This transfers MOLA's absolute control to the DEM — the same role ground
control points play in the official DTM pipeline, at the accuracy the
blend supports (tens of meters horizontally).

Usage: uv run mola_tie.py <in.tif> <out.tif> [--tilt]
"""

import math
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling, transform_bounds
from scipy.ndimage import shift as ndshift

BLEND_URL = ("/vsicurl/https://planetarymaps.usgs.gov/mosaic/Mars/"
             "HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif")
AGG = 200.0


def main(src_path, dst_path, do_tilt):
    with rasterio.open(src_path) as src:
        z = src.read(1).astype(np.float64)
        nodata = src.nodata if src.nodata is not None else -3.4028234663852886e38
        z[z == nodata] = np.nan
        tr, crs, profile = src.transform, src.crs, src.profile
        res = tr.a

        with rasterio.open(BLEND_URL) as blend:
            wb = transform_bounds(crs, blend.crs, *src.bounds)
            win = blend.window(*wb).round_offsets().round_lengths()
            bz = blend.read(1, window=win).astype(np.float64)
            btr = blend.window_transform(win)
            bcrs, bnod = blend.crs, blend.nodata

    # aggregate ours to the blend scale on our own grid axes
    n = int(round(AGG / res))
    h, w = (z.shape[0] // n) * n, (z.shape[1] // n) * n
    blocks = z[:h, :w].reshape(h // n, n, w // n, n)
    za = np.nanmean(np.nanmean(blocks, axis=3), axis=1)
    cov = np.isfinite(z[:h, :w]).reshape(h // n, n, w // n, n).mean(axis=(1, 3))
    za[cov < 0.5] = np.nan
    tra = from_origin(tr.c, tr.f, AGG, AGG)

    zb = np.full(za.shape, np.nan)
    reproject(bz, zb, src_transform=btr, src_crs=bcrs,
              dst_transform=tra, dst_crs=crs,
              src_nodata=bnod, dst_nodata=np.nan,
              resampling=Resampling.bilinear)

    # Nuth & Kaab in array axes at 200 m
    total_dx = total_dy = total_c = 0.0
    zs = za.copy()
    for _ in range(8):
        ok = ~np.isnan(zs) & ~np.isnan(zb)
        gy, gx = np.gradient(zb, AGG, AGG)
        good = ok & ~np.isnan(gx) & ~np.isnan(gy)
        d = zs[good] - zb[good]
        A = np.column_stack([gx[good], gy[good], np.ones(d.size)])
        (dx, dy, c), *_ = np.linalg.lstsq(A, d, rcond=None)
        total_dx += dx; total_dy += dy; total_c += c
        zs = ndshift(za, (total_dy / AGG, total_dx / AGG), order=1,
                     mode="constant", cval=np.nan) - total_c
        if math.hypot(dx, dy) < 0.5:
            break
    print(f"MOLA tie: horizontal shift ({total_dx:+.1f} E, {-total_dy:+.1f} N) m"
          f" = {math.hypot(total_dx, total_dy):.1f} m, vertical {total_c:+.1f} m")

    tilt_msg = "not applied"
    plane = 0.0
    if do_tilt:
        ok = ~np.isnan(zs) & ~np.isnan(zb)
        dzr = zs[ok] - zb[ok]
        rr, cc = np.where(ok)
        P = np.column_stack([rr * AGG, cc * AGG, np.ones(dzr.size)])
        coef, *_ = np.linalg.lstsq(P, dzr, rcond=None)
        rows, cols = np.mgrid[0:z.shape[0], 0:z.shape[1]]
        # plane in full-res array coords (same origin as aggregated grid)
        plane = coef[0] * rows * res + coef[1] * cols * res + coef[2]
        tilt_msg = (f"removed {1000*math.hypot(coef[0], coef[1]):.2f} m/km "
                    f"(fit against 200 m blend)")
    print(f"tilt: {tilt_msg}")

    out = ndshift(z, (total_dy / res, total_dx / res), order=1,
                  mode="constant", cval=np.nan) - total_c - plane
    out = np.where(np.isnan(out), nodata, out).astype(profile["dtype"])
    profile.update(nodata=nodata)
    with rasterio.open(dst_path, "w", **profile) as dst:
        dst.write(out, 1)
    print(f"wrote {dst_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--tilt"]
    main(args[0], args[1], "--tilt" in sys.argv)
