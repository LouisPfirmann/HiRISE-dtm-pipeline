#!/usr/bin/env bash
# HiRISE stereo DTM pipeline — Juncture of branches of Dao Vallis
# Pair: PSP_003468_1430 (23.3 deg roll) + PSP_003956_1430 (8.7 deg roll)
#
# This is the RECORD of the commands actually run (reconstructed from the
# ISIS/ASP session logs), not a turnkey installer. Tool setup is on you:
#   ISIS 8.3.0        https://github.com/DOI-USGS/ISIS3 (conda/micromamba)
#   ASP 3.7.0         https://stereopipeline.readthedocs.io
# plus an ISISDATA area for the MRO mission kernels (spiceinit runs with
# WEB=True, so only the base calibration files are needed locally).
#
# Wall-clock on a 16-thread laptop (32 GB RAM): a few hours.
# Scratch space: ~8 GB. Final products: ~20 MB.
set -euo pipefail

# --- environment (adapt paths) ----------------------------------------------
export ISISROOT=$HOME/mamba/envs/isis8      # ISIS 8.3.0 env
export ISISDATA=$HOME/isisdata
export PATH=$ISISROOT/bin:$HOME/asp/bin:$PATH   # ASP 3.7.0 (build 4d34ce366)

# --- 1. raw EDRs (RED4+RED5 CCDs only: the 2.3 km-wide central strip) --------
# Full-observation DTMs need all 10 RED CCDs; RED4+RED5 keeps compute and
# download manageable and covers the terrain of interest (13 km along-track).
mkdir -p edr && ( cd edr
  for f in RED4_0 RED4_1 RED5_0 RED5_1; do
    wget -c https://hirise-pds.lpl.arizona.edu/PDS/EDR/PSP/ORB_003400_003499/PSP_003468_1430/PSP_003468_1430_${f}.IMG
    wget -c https://hirise-pds.lpl.arizona.edu/PDS/EDR/PSP/ORB_003900_003999/PSP_003956_1430/PSP_003956_1430_${f}.IMG
  done )

# --- 2. EDR -> calibrated, CCD-mosaicked cube, one per observation -----------
# hiedr2mosaic.py chains: hi2isis -> hical -> histitch -> spiceinit(WEB) ->
# spicefit -> noproj -> hijitreg -> handmos -> cubenorm.
# WART: on this pair hijitreg found no valid offsets between RED4 and RED5
# (contrast is that low) and fell back to zero CCD offsets. Harmless here:
# the noproj'd CCDs are already coregistered to well under a pixel.
for o in PSP_003468_1430 PSP_003956_1430; do
  mkdir -p work_$o && ( cd work_$o
    hiedr2mosaic.py --web ../edr/${o}_RED4_0.IMG ../edr/${o}_RED4_1.IMG \
                          ../edr/${o}_RED5_0.IMG ../edr/${o}_RED5_1.IMG )
done

# --- 3. reduce 0.5 m -> 1 m --------------------------------------------------
mkdir -p stereo && cd stereo
reduce from=../work_PSP_003468_1430/PSP_003468_1430_RED.mos_hijitreged.norm.cub \
       to=left_1m.cub  algorithm=average mode=scale sscale=2 lscale=2
reduce from=../work_PSP_003956_1430/PSP_003956_1430_RED.mos_hijitreged.norm.cub \
       to=right_1m.cub algorithm=average mode=scale sscale=2 lscale=2

# --- 4. seed stereo, uncontrolled -------------------------------------------
# Purpose: not a DTM — its dense disparity becomes the match file for the
# bundle adjustment in step 5. (A conventional sparse-IP bundle_adjust was
# tried first and produced too few matches on this low-contrast pair.)
parallel_stereo --alignment-method affineepipolar --stereo-algorithm asp_mgm \
  --subpixel-mode 9 --ip-per-tile 500 --individually-normalize \
  left_1m.cub right_1m.cub runc/run \
  --corr-seed-mode 1 --sgm-collar-size 256 --threads 16

# --- 5. dense-match bundle adjustment ----------------------------------------
# Median reprojection error after this: 0.3-0.7 px.
bundle_adjust left_1m.cub right_1m.cub -o ba2/ba \
  --match-files-prefix runc/run-disp \
  --num-iterations 200 --camera-weight 0 --tri-weight 0.1 \
  --remove-outliers-params "75.0 3.0 30 50"

# --- 6. reduce 1 m -> 2 m for the production stereo ---------------------------
# A controlled 1 m stereo attempt had large correlation dropouts on the
# textureless dust (I/F contrast ~0.01). Dropping to 2 m with a 9x9 census
# kernel recovered ~70-80% coverage of the overlap. Filenames are kept so
# ba2's .adjust files still match by cube basename.
mkdir -p red2
reduce from=left_1m.cub  to=red2/left_1m.cub  algorithm=average mode=scale sscale=2 lscale=2
reduce from=right_1m.cub to=red2/right_1m.cub algorithm=average mode=scale sscale=2 lscale=2

# --- 7. controlled stereo (MGM, 2 m, 9x9 census) ------------------------------
parallel_stereo --bundle-adjust-prefix ba2/ba --alignment-method affineepipolar \
  --stereo-algorithm asp_mgm --corr-kernel 9 9 --subpixel-mode 9 \
  --ip-per-tile 2000 --ip-detect-method 1 --epipolar-threshold 100 \
  --individually-normalize red2/left_1m.cub red2/right_1m.cub run2/run \
  --corr-seed-mode 1 --sgm-collar-size 256 --threads 16

# --- 8. point cloud -> 4 m/px DTM ---------------------------------------------
# Median ray-intersection error (run-IntersectionErr.tif): 0.5 m.
point2dem -r mars --t_srs "+proj=sinu +lon_0=90.27 +R=3396190 +units=m +no_defs" \
  --tr 4.0 --errorimage run2/run-PC.tif

# --- 9. vertical datum: sphere -> MOLA areoid ---------------------------------
# point2dem heights are relative to the 3,396.19 km sphere; the USGS
# MOLA-HRSC blend is relative to the MOLA areoid. Tie by the median offset
# against the blend over the DTM footprint (+6,226 m for this site) so
# elevations are comparable with MOLA products.
uv run ../datum_tie.py run2/run-DEM.tif hirise_dtm_juncture.tif
