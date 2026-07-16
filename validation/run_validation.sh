#!/usr/bin/env bash
# Validation run: reproduce the official USGS DTM
# DTEEC_012579_1420_012434_1420_U01 (Harmakhis Vallis, -37.7N 95.58E)
# with the exact chain used for the Dao Vallis juncture DTM
# (see ../work*/chain.log and ../stereo/*/ba-log-*, run-log-*).
set -euo pipefail
D=/home/louis/Desktop/MARS/depthmap
export ISISROOT=$D/tools/mamba/envs/isis8
export ISISDATA=$D/isisdata
export PATH=$ISISROOT/bin:$D/asp/sp/bin:$PATH
cd $D/validation

fetch() {  # resumable download with retries
  local url=$1 tries=0
  until wget -q -c "$url"; do
    tries=$((tries+1)); [ $tries -ge 8 ] && { echo "FETCH FAILED: $url"; exit 1; }
    sleep 10
  done
}

echo "=== [1/8] EDR download $(date -u +%H:%M:%S)"
mkdir -p edr
( cd edr
  for pair in ESP_012579_1420:ORB_012500_012599 ESP_012434_1420:ORB_012400_012499; do
    o=${pair%%:*}; orb=${pair##*:}
    for ccd in RED4 RED5; do for ch in 0 1; do
      fetch "https://hirise-pds.lpl.arizona.edu/PDS/EDR/ESP/${orb}/${o}/${o}_${ccd}_${ch}.IMG"
    done; done
  done )

echo "=== [2/8] official DTM download $(date -u +%H:%M:%S)"
mkdir -p official
( cd official
  fetch "https://www.uahirise.org/PDS/DTM/ESP/ORB_012500_012599/ESP_012579_1420_ESP_012434_1420/DTEEC_012579_1420_012434_1420_U01.IMG" )

echo "=== [3/8] hiedr2mosaic $(date -u +%H:%M:%S)"
for o in ESP_012579_1420 ESP_012434_1420; do
  mkdir -p work_$o
  if [ ! -s work_$o/${o}_RED.mos_hijitreged.norm.cub ]; then
    ( cd work_$o && hiedr2mosaic.py --web \
        ../edr/${o}_RED4_0.IMG ../edr/${o}_RED4_1.IMG \
        ../edr/${o}_RED5_0.IMG ../edr/${o}_RED5_1.IMG )
  fi
done

echo "=== [4/8] reduce to 1 m $(date -u +%H:%M:%S)"
mkdir -p stereo
cd stereo
[ -s left_1m.cub ] || reduce from=../work_ESP_012579_1420/ESP_012579_1420_RED.mos_hijitreged.norm.cub \
  to=left_1m.cub algorithm=average mode=scale sscale=2 lscale=2
[ -s right_1m.cub ] || reduce from=../work_ESP_012434_1420/ESP_012434_1420_RED.mos_hijitreged.norm.cub \
  to=right_1m.cub algorithm=average mode=scale sscale=2 lscale=2

echo "=== [5/8] seed stereo (uncontrolled) $(date -u +%H:%M:%S)"
[ -s runc/run-PC.tif ] || parallel_stereo \
  --alignment-method affineepipolar --stereo-algorithm asp_mgm \
  --subpixel-mode 9 --ip-per-tile 500 --individually-normalize \
  left_1m.cub right_1m.cub runc/run \
  --corr-seed-mode 1 --sgm-collar-size 256 --threads 16
# export dense matches from the seed disparity for the bundle adjustment
# (tri stage rerun, as in the juncture session)
[ -s runc/run-disp-left_1m__right_1m.match ] || parallel_stereo \
  --alignment-method affineepipolar --stereo-algorithm asp_mgm \
  --subpixel-mode 9 --ip-per-tile 500 --individually-normalize \
  --num-matches-from-disparity 20000 \
  left_1m.cub right_1m.cub runc/run \
  --corr-seed-mode 1 --sgm-collar-size 256 --threads 16 --entry-point 5

echo "=== [6/8] dense-match bundle adjustment $(date -u +%H:%M:%S)"
[ -s ba2/ba-left_1m.adjust ] || bundle_adjust left_1m.cub right_1m.cub -o ba2/ba \
  --match-files-prefix runc/run-disp \
  --num-iterations 200 --camera-weight 0 --tri-weight 0.1 \
  --remove-outliers-params "75.0 3.0 30 50"
[ -s ba2/ba-left_1m.adjust ] || { echo "BUNDLE ADJUSTMENT FAILED"; exit 1; }

echo "=== [7/8] reduce to 2 m + controlled stereo $(date -u +%H:%M:%S)"
# The juncture run's final stereo used cubes reduced again to 2 m/px, kept
# under the same filenames in red2/ so ba2's .adjust files match by basename.
mkdir -p red2
[ -s red2/left_1m.cub ]  || reduce from=left_1m.cub  to=red2/left_1m.cub \
  algorithm=average mode=scale sscale=2 lscale=2
[ -s red2/right_1m.cub ] || reduce from=right_1m.cub to=red2/right_1m.cub \
  algorithm=average mode=scale sscale=2 lscale=2
[ -s run2/run-PC.tif ] || parallel_stereo \
  --bundle-adjust-prefix ba2/ba --alignment-method affineepipolar \
  --stereo-algorithm asp_mgm --corr-kernel 9 9 --subpixel-mode 9 \
  --ip-per-tile 2000 --ip-detect-method 1 --epipolar-threshold 100 \
  --individually-normalize red2/left_1m.cub red2/right_1m.cub run2/run \
  --corr-seed-mode 1 --sgm-collar-size 256 --threads 16

echo "=== [8/8] point2dem 4 m $(date -u +%H:%M:%S)"
[ -s run2/run-DEM.tif ] || point2dem -r mars \
  --t_srs "+proj=sinu +lon_0=95.58 +R=3396190 +units=m +no_defs" \
  --tr 4.0 --errorimage run2/run-PC.tif

echo VALIDATION_RUN_DONE
