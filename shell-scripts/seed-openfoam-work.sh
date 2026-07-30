#!/usr/bin/env bash
# shell-scripts/seed-openfoam-work.sh
#
# Idempotent provisioning of the OpenFOAM reference mesh on the shared /work volume.
# This is openfoam-svc's CMD, so it runs on every container start.
#
# Why at startup (and not at image build)
# ─────────────────────────────────────────────────────────────────────
# /work is a Docker named volume. It is empty on a fresh checkout and after
# `make down-clean`, and it mounts OVER the image's /work content — so a mesh baked
# into the image at build time would be hidden by the empty volume. The CFD connector
# expects a polyMesh at /work/mesh/constant/polyMesh (case_builder resolves
# polymesh_ref against /work); if it is missing, every CFD job fails at the build
# stage. This script closes that provisioning gap deterministically: the container
# that owns blockMesh inspects the real volume on startup and regenerates the mesh
# only when it is absent.
#
# What it does
# ─────────────────────────────────────────────────────────────────────
#   - If /work/mesh/constant/polyMesh exists: skip (already provisioned).
#   - Otherwise: stage the baked reference blockMeshDict + a minimal controlDict into
#     /work/mesh/system, source the OpenFOAM environment, and run blockMesh.
#   - Either way: exec `sleep infinity` so the container stays alive as the execution
#     target the worker invokes simpleFoam inside.
#
# A provisioning failure is non-fatal: it is logged loudly and the container stays up
# (killing it would take down the execution target). The connector still reports a
# clear build-stage error if the mesh is missing.
#
# Environment
# ─────────────────────────────────────────────────────────────────────
#   WORK_DIR         Root of the shared work volume.  Default: /work
#   OPENFOAM_BASHRC  OpenFOAM env script to source.   Default: /opt/openfoam10/etc/bashrc
#   SEED_DICT        Baked reference blockMeshDict.    Default: /opt/seed/blockMeshDict

# Note: deliberately no `-u` — the OpenFOAM bashrc references unset variables.
set -eo pipefail

WORK_DIR="${WORK_DIR:-/work}"
OPENFOAM_BASHRC="${OPENFOAM_BASHRC:-/opt/openfoam10/etc/bashrc}"
SEED_DICT="${SEED_DICT:-/opt/seed/blockMeshDict}"

MESH_DIR="${WORK_DIR}/mesh"
POLYMESH_DIR="${MESH_DIR}/constant/polyMesh"

if [ -d "${POLYMESH_DIR}" ]; then
    echo "[seed-openfoam] polyMesh already present at ${POLYMESH_DIR} — skipping provisioning."
else
    echo "[seed-openfoam] polyMesh missing — provisioning the reference mesh at ${MESH_DIR}."
    mkdir -p "${MESH_DIR}/system" "${MESH_DIR}/constant"
    cp "${SEED_DICT}" "${MESH_DIR}/system/blockMeshDict"

    # Minimal controlDict so blockMesh can run (matches the former manual seed target).
    cat > "${MESH_DIR}/system/controlDict" <<'EOF'
FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }
application   simpleFoam;
startTime     0;
endTime       1;
deltaT        1;
writeInterval 1;
EOF

    # shellcheck disable=SC1090
    if source "${OPENFOAM_BASHRC}" && blockMesh -case "${MESH_DIR}"; then
        echo "[seed-openfoam] mesh provisioned at ${POLYMESH_DIR}."
        echo "[seed-openfoam] CFD jobs with polymesh_ref=mesh/constant/polyMesh can now run."
    else
        echo "[seed-openfoam] WARNING: blockMesh failed — /work has no usable mesh." >&2
        echo "[seed-openfoam] CFD will fail at the build stage until this is resolved." >&2
    fi
fi

echo "[seed-openfoam] openfoam-svc ready — staying alive as the execution target."
exec sleep infinity
