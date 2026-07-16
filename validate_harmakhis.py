# /// script
# requires-python = ">=3.11"
# dependencies = ["rasterio", "numpy", "matplotlib", "scipy"]
# ///
"""
Compare the pipeline's Harmakhis Vallis DTM against the official
USGS-produced DTEEC_012579_1420_012434_1420_U01 (same stereo pair).

Usage:
  uv run validate_harmakhis.py <ours.tif> <official.IMG> <outdir>

Writes <outdir>/comparison.png and <outdir>/stats.txt.
Ours must already be areoid-tied (datum_tie.py); the official DTEEC
product is referenced to the MOLA areoid by definition.
"""

import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


def hillshade(z, d, azdeg=315.0, altdeg=45.0):
    gy, gx = np.gradient(z, d, d)
    az, alt = math.radians(360.0 - azdeg + 90.0), math.radians(altdeg)
    sl = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    return np.clip(np.sin(alt)*np.sin(sl) + np.cos(alt)*np.cos(sl)*np.cos(az-asp), 0, 1)


def slope_pct(z, d):
    gy, gx = np.gradient(z, d, d)
    return 100.0 * np.hypot(gx, gy)


def main(ours_path, official_path, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ours_path) as src:
        z = src.read(1).astype(np.float64)
        nod = src.nodata if src.nodata is not None else -3.4028234663852886e38
        z[z == nod] = np.nan
        tr, crs = src.transform, src.crs
        res = tr.a

    with rasterio.open(official_path) as off:
        zo = np.full(z.shape, np.nan)
        reproject(off.read(1).astype(np.float64), zo,
                  src_transform=off.transform, src_crs=off.crs,
                  dst_transform=tr, dst_crs=crs,
                  src_nodata=off.nodata, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)

    # --- horizontal + vertical coregistration (Nuth & Kaab 2011) -----------
    # Solve dz ~ dx*gx + dy*gy + c on the official DEM's gradients; shifting
    # ours by (-dx, -dy, -c) removes the misregistration. Iterate to converge.
    from scipy.ndimage import shift as ndshift  # noqa: E402
    total_dx = total_dy = total_c = 0.0
    zs = z.copy()
    for _ in range(6):
        ok = ~np.isnan(zs) & ~np.isnan(zo)
        gy, gx = np.gradient(zo, res, res)
        good = ok & ~np.isnan(gx) & ~np.isnan(gy)
        d = zs[good] - zo[good]
        A = np.column_stack([gx[good], gy[good], np.ones(d.size)])
        (dx, dy, c), *_ = np.linalg.lstsq(A, d, rcond=None)
        total_dx += dx; total_dy += dy; total_c += c
        print(f"  coreg iter: shift ({dx:+.2f}, {dy:+.2f}) m, dz {c:+.2f} m")
        # the fit is in array axes (gy = d/d_row, gx = d/d_col), so the
        # correction is a straight array shift by (dy, dx) pixels
        zs = ndshift(z, (total_dy / res, total_dx / res), order=1,
                     mode="constant", cval=np.nan) - total_c
        if math.hypot(dx, dy) < 0.05:
            break

    ok = ~np.isnan(z) & ~np.isnan(zo)
    bias = float(np.median(z[ok] - zo[ok]))          # raw vertical bias
    okc = ~np.isnan(zs) & ~np.isnan(zo)
    dzc = zs[okc] - zo[okc]                          # after coregistration
    dzc = dzc - np.median(dzc)

    # separate long-wavelength tilt (GCP-free bundle adjustment) from
    # surface error: remove a best-fit plane from the residual
    rr, cc = np.where(okc)
    P = np.column_stack([rr*res/1000.0, cc*res/1000.0, np.ones(dzc.size)])
    coef, *_ = np.linalg.lstsq(P, dzc, rcond=None)
    tilt = math.hypot(coef[0], coef[1])              # m per km
    dzp = dzc - P @ coef
    so_all, sf_all = slope_pct(zs, res)[okc], slope_pct(zo, res)[okc]
    sok = ~np.isnan(so_all) & ~np.isnan(sf_all)  # gradient is NaN next to holes
    s_ours, s_off = so_all[sok], sf_all[sok]

    lines = [
        f"common valid cells: {ok.sum():,} "
        f"({100*ok.sum()/max((~np.isnan(z)).sum(),1):.0f}% of our DTM)",
        f"raw vertical bias (ours - official): {bias:+.2f} m "
        f"(datum ties differ)",
        f"coregistration (Nuth & Kaab 2011): horizontal shift "
        f"({total_dx:+.1f} E, {-total_dy:+.1f} N) m = "
        f"{math.hypot(total_dx, total_dy):.1f} m, vertical {total_c:+.2f} m",
        f"after coregistration:",
        f"  median |dz| {np.median(np.abs(dzc)):.2f} m",
        f"  RMS {np.sqrt(np.mean(dzc**2)):.2f} m",
        f"  68th pct |dz| {np.percentile(np.abs(dzc),68):.2f} m, "
        f"95th {np.percentile(np.abs(dzc),95):.2f} m",
        f"after also removing best-fit plane (tilt {tilt:.2f} m/km):",
        f"  median |dz| {np.median(np.abs(dzp)):.2f} m",
        f"  RMS {np.sqrt(np.mean(dzp**2)):.2f} m",
        f"  68th pct |dz| {np.percentile(np.abs(dzp),68):.2f} m, "
        f"95th {np.percentile(np.abs(dzp),95):.2f} m",
        f"slope ({res:.0f} m baseline):",
        f"  area > 20%:  ours {100*(s_ours>20).mean():.1f}%   "
        f"official {100*(s_off>20).mean():.1f}%",
        f"  median:      ours {np.median(s_ours):.1f}%   "
        f"official {np.median(s_off):.1f}%",
        f"  p95:         ours {np.percentile(s_ours,95):.1f}%   "
        f"official {np.percentile(s_off,95):.1f}%",
    ]
    text = "\n".join(lines)
    print(text)
    (outdir / "stats.txt").write_text(text + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    h, w = z.shape
    ext = [0, w*res/1000, 0, h*res/1000]
    dzmap = np.full(z.shape, np.nan)
    dzmap[okc] = zs[okc] - zo[okc]
    dzmap -= np.nanmedian(dzmap)

    fig, axes = plt.subplots(1, 3, figsize=(13, 8), dpi=150)
    for ax, data, title in ((axes[0], zo, "Official USGS DTM (DTEEC…U01)"),
                            (axes[1], z, "This pipeline (2 m stereo, 4 m grid)")):
        zz = np.where(np.isnan(data), np.nanmedian(data), data)
        ax.imshow(hillshade(zz, res), cmap="gray", extent=ext, vmin=0, vmax=1)
        ax.set_title(title, fontsize=10, loc="left", fontweight="bold")
        ax.set_xlabel("East (km)")
    axes[0].set_ylabel("North (km)")
    im = axes[2].imshow(dzmap, cmap="RdBu_r", extent=ext, vmin=-15, vmax=15)
    axes[2].set_title("Difference after coregistration", fontsize=10, loc="left",
                      fontweight="bold")
    axes[2].set_xlabel("East (km)")
    cb = fig.colorbar(im, ax=axes[2], shrink=0.55, pad=0.03)
    cb.set_label("ours − official (m)")
    fig.suptitle("Harmakhis Vallis validation: ESP_012579_1420 + ESP_012434_1420",
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(outdir / "comparison.png", bbox_inches="tight")
    print(f"wrote {outdir}/comparison.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
