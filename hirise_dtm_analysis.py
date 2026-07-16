# /// script
# requires-python = ">=3.11"
# dependencies = ["rasterio", "numpy", "matplotlib"]
# ///
"""
Slope + depth analysis of the self-made HiRISE stereo DTM (4 m/px) of the
"Juncture of branches of Dao Vallis" site (PSP_003468_1430 + PSP_003956_1430).

Run:  uv run hirise_dtm_analysis.py
"""

import math
from pathlib import Path

import numpy as np
import rasterio

HERE = Path(__file__).parent
OUT = HERE / "output"
RES = 4.0
SLOPE_LIMIT = 20.0


def hillshade(z, d, azdeg=315.0, altdeg=45.0):
    gy, gx = np.gradient(z, d, d)
    az, alt = math.radians(360.0 - azdeg + 90.0), math.radians(altdeg)
    sl = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    return np.clip(np.sin(alt)*np.sin(sl) + np.cos(alt)*np.cos(sl)*np.cos(az-asp), 0, 1)


def write_ply(path, xyz, rgb):
    rec = np.zeros(len(xyz), dtype=[("xyz", "<f4", 3), ("rgb", "u1", 3)])
    rec["xyz"], rec["rgb"] = xyz, rgb
    with open(path, "wb") as f:
        f.write((f"ply\nformat binary_little_endian 1.0\nelement vertex {len(xyz)}\n"
                 "property float x\nproperty float y\nproperty float z\n"
                 "property uchar red\nproperty uchar green\nproperty uchar blue\n"
                 "end_header\n").encode())
        f.write(rec.tobytes())
    print(f"  wrote {path.name}: {len(xyz):,} points")


def main():
    with rasterio.open(OUT / "hirise_dtm_juncture.tif") as src:
        z = src.read(1).astype(np.float64)
        z[z == src.nodata] = np.nan
        tr = src.transform

    gy, gx = np.gradient(z, RES, RES)
    slope = 100.0 * np.hypot(gx, gy)
    sv = slope[~np.isnan(slope)]
    print(f"valid cells: {len(sv):,} ({100*(~np.isnan(z)).mean():.0f}% of grid)")
    for t in (20, 25, 30, 35):
        print(f"  slope > {t}%: {100*(sv > t).mean():.1f}% of mapped area")
    print(f"  median {np.median(sv):.1f}%, p95 {np.percentile(sv,95):.1f}%, "
          f"p99 {np.percentile(sv,99):.1f}%")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    hs = hillshade(z, RES)
    h, w = z.shape
    ext = [0, w*RES/1000, 0, h*RES/1000]

    fig, axes = plt.subplots(1, 2, figsize=(10, 11), dpi=150)
    ax = axes[0]
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1)
    im = ax.imshow(z, cmap="cividis", extent=ext, alpha=0.6)
    ax.set_title("Elevation (4 m/px HiRISE stereo)", fontsize=10, loc="left",
                 fontweight="bold")
    ax.set_xlabel("East (km)"); ax.set_ylabel("North (km)")
    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.03)
    cb.set_label("Elevation (m, MOLA areoid)")

    ax = axes[1]
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1)
    im = ax.imshow(slope, cmap="Blues", extent=ext, alpha=0.65, vmin=0, vmax=45)
    ax.contour(np.flipud(slope), levels=[SLOPE_LIMIT], extent=ext,
               colors="#b3261e", linewidths=0.7)
    ax.set_title("Slope, 4 m baseline", fontsize=10, loc="left", fontweight="bold")
    ax.set_xlabel("East (km)"); ax.set_ylabel("")
    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.03)
    cb.set_label("Slope (%)"); cb.ax.axhline(SLOPE_LIMIT, color="#b3261e", lw=1.0)
    ax.legend(handles=[Line2D([], [], color="#b3261e", lw=1.0,
                              label="20% (11.3°)")],
              loc="lower right", fontsize=8, framealpha=0.9)
    fig.suptitle("Dao Vallis branch juncture — self-processed HiRISE stereo DTM\n"
                 "PSP_003468_1430 + PSP_003956_1430, ASP 3.7, -36.86°N 90.27°E",
                 fontsize=11)
    fig.text(0.01, 0.005, "Median ray-intersection error 0.5 m; datum tied to "
             "MOLA-HRSC blend (+6226 m). Gaps: correlation dropouts on "
             "textureless dust.", fontsize=7, color="#555555")
    fig.tight_layout(rect=[0, 0.01, 1, 0.97])
    fig.savefig(OUT / "hirise_dtm_maps.png", bbox_inches="tight")
    print("  wrote hirise_dtm_maps.png")

    rows, cols = np.mgrid[0:h, 0:w]
    xs, ys = rasterio.transform.xy(tr, rows, cols)
    xs = np.asarray(xs).reshape(z.shape); ys = np.asarray(ys).reshape(z.shape)
    ok = ~np.isnan(z)
    cmap = matplotlib.colormaps["cividis"]
    zn = (z - np.nanmin(z)) / (np.nanmax(z) - np.nanmin(z))
    rgb = (cmap(zn)[..., :3] * 255).astype(np.uint8)
    xyz = np.column_stack([xs[ok]-xs[ok].mean(), ys[ok]-ys[ok].mean(),
                           z[ok]]).astype(np.float32)
    write_ply(OUT / "point_cloud_juncture_4m.ply", xyz, rgb[ok])


if __name__ == "__main__":
    main()
