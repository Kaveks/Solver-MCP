# =============================================================================
# docker/lammps/Dockerfile — lammps-svc image (Layer 4)
#
# Thin wrapper over the official LAMMPS stable image. Long-lived execution target
# on the shared /work volume so the worker can invoke `lmp -in input.lammps`.
# Non-root, no network (network isolation set in docker-compose.yml).
#
# NOTE: the actual lmp invocation mechanism is implemented in docs/phase-2.3
# (LAMMPSConnector.run()). This image only needs to start and stay running.
#
# Base image: the official LAMMPS image. The plain `lammps/lammps:stable` tag does not
# exist on Docker Hub; `latest` is the pullable official image. A pinned stable tag should
# be set for reproducibility once the exact tag is confirmed (accepted image-tag risk).
# =============================================================================
FROM lammps/lammps:latest

USER 1000:1000

# Keep the container alive as an execution target.
CMD ["sleep", "infinity"]
