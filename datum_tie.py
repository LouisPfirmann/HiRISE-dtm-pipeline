# /// script
# requires-python = ">=3.11"
# dependencies = ["rasterio", "numpy"]
# ///
"""
Tie a point2dem DEM (heights above the 3,396.19 km sphere) to the MOLA
areoid, by the median offset against the USGS MOLA-HRSC blended DEM
(read remotely, windowed, via /vsicurl — nothing is downloaded in full).

Usage:  uv run datum_tie.py <in_dem.tif> <out_dem.tif>
"""

import sys

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds

BLEND_URL = ("/vsicurl/https://planetarymaps.usgs.gov/mosaic/Mars/"
             "HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif")


def main(src_path, dst_path):
    with rasterio.open(src_path) as src:
        z = src.read(1)
        nodata = src.nodata if src.nodata is not None else -3.4028234663852886e38
        z = np.where(z == nodata, np.nan, z)
        profile = src.profile

        with rasterio.open(BLEND_URL) as blend:
            wb = transform_bounds(src.crs, blend.crs, *src.bounds)
            win = blend.window(*wb).round_offsets().round_lengths()
            bz = blend.read(1, window=win)
            btr = blend.window_transform(win)
            bres = np.full(z.shape, np.nan, dtype=np.float64)
            reproject(bz.astype(np.float64), bres,
                      src_transform=btr, src_crs=blend.crs,
                      dst_transform=src.transform, dst_crs=src.crs,
                      src_nodata=blend.nodata, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)

    ok = ~np.isnan(z) & ~np.isnan(bres)
    shift = float(np.median(bres[ok] - z[ok]))
    print(f"sphere -> areoid median offset over {ok.sum():,} cells: {shift:+.0f} m")

    out = np.where(np.isnan(z), nodata, z + shift).astype(profile["dtype"])
    profile.update(nodata=nodata)
    with rasterio.open(dst_path, "w", **profile) as dst:
        dst.write(out, 1)
    print(f"wrote {dst_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
