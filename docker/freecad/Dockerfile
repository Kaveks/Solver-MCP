# =============================================================================
# docker/freecad/Dockerfile — freecad-svc image (Layer 4)
#
# Prototype: the FreeCAD connector is a STUB (docs/phase-3.4) that returns a structured
# NOT_IMPLEMENTED response — no real FreeCAD is invoked until Phase 4 (docs/phase-4.2).
# So this container only needs to exist, run non-root, and stay alive on the shared /work
# volume. A minimal base keeps the stack lean; the real headless FreeCAD image is built in
# Phase 4 when the connector is implemented.
#
# (The intended `freecad/freecad:0.21` base does not exist on Docker Hub; rather than pull a
# large third-party FreeCAD image for a stub, the Prototype uses a minimal placeholder.)
# =============================================================================
FROM python:3.12-slim

# Run as a non-root UID (no user account needed for sleep).
USER 1000:1000

# Keep the container alive as a placeholder execution target.
CMD ["sleep", "infinity"]
