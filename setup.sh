#!/usr/bin/env bash
# Toolchain setup for the HiRISE DTM pipeline.
#
# Reconstructed from the working environment (not re-tested from a clean
# machine — read before running). Installs everything under $PREFIX, no
# root needed. Budget: ~20 GB disk, most of it ISIS base data and the two
# unpacked toolchains.
set -euo pipefail

PREFIX=${PREFIX:-$HOME/hirise-tools}
ASP_TAR=StereoPipeline-3.7.0-2026-06-08-x86_64-Linux.tar.bz2
mkdir -p "$PREFIX" && cd "$PREFIX"

# --- micromamba (standalone conda) -------------------------------------------
if [ ! -x bin/micromamba ]; then
  mkdir -p bin
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xj -C . bin/micromamba
fi
export MAMBA_ROOT_PREFIX=$PREFIX/mamba

# --- ISIS 8.3.0 ---------------------------------------------------------------
bin/micromamba create -y -n isis8 -c usgs-astrogeology -c conda-forge isis=8.3.0
ISISENV=$MAMBA_ROOT_PREFIX/envs/isis8

# --- ISIS data area -----------------------------------------------------------
# Only what this chain needs: base (kernels + MOLA shape model, ~2.6 GB)
# and the MRO calibration files (~60 MB). Mission SPICE kernels are NOT
# downloaded — hiedr2mosaic.py runs spiceinit with WEB=True, which fetches
# them per-image from the USGS web service.
export ISISDATA=$PREFIX/isisdata
mkdir -p "$ISISDATA"
"$ISISENV/bin/downloadIsisData" base "$ISISDATA"
"$ISISENV/bin/downloadIsisData" mro  "$ISISDATA" --exclude "kernels/**"

# --- Ames Stereo Pipeline 3.7.0 ------------------------------------------------
if [ ! -d asp ]; then
  wget -c "https://github.com/NeoGeographyToolkit/StereoPipeline/releases/download/3.7.0/$ASP_TAR"
  mkdir -p asp && tar -xjf "$ASP_TAR" -C asp --strip-components=1
fi

cat <<EOF

Setup complete. Before running pipeline.sh, export:

  export ISISROOT=$ISISENV
  export ISISDATA=$ISISDATA
  export PATH=$ISISENV/bin:$PREFIX/asp/bin:\$PATH

EOF
