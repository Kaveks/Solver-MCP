# =============================================================================
# docker/openfoam/Dockerfile — openfoam-svc image (Layer 4)
#
# Thin wrapper over the official OpenFOAM 10 image. The container is a long-lived
# execution target: it stays alive on the shared /work volume so the worker can
# invoke simpleFoam against a case directory. It runs non-root with no network
# (network isolation is set in docker-compose.yml).
#
# NOTE: the actual simpleFoam invocation mechanism is implemented in
# docs/phase-1.5 (OpenFOAMConnector.run()). This image only needs to start and
# stay running for docs/phase-1.1 Step 1.1.
#
# Base image: OpenFOAM Foundation v10 (the openfoam.org build). The plain
# `openfoam/openfoam10` tag does not exist on Docker Hub; the published Foundation v10
# image is `openfoam10-paraview56`. Our case_builder uses OF Foundation v10 file
# conventions (momentumTransport, etc.), so the Foundation image — not the ESI/opencfd
# build — is required.
# =============================================================================
FROM openfoam/openfoam10-paraview56:latest

# Provisioning assets, installed as root before dropping privileges. The reference
# blockMeshDict (the same mesh the Phase 1 regression gate uses, so its patch names
# inlet/outlet/walls match case_builder) and the idempotent seed script that stages the
# polyMesh onto the shared /work volume on startup when it is missing. The mesh itself
# cannot be baked into the image: /work is a named volume that mounts over the image's
# content and is empty after `make down-clean` — so provisioning must happen at runtime.
USER root
COPY tests/regression/openfoam/blockMeshDict /opt/seed/blockMeshDict
COPY shell-scripts/seed-openfoam-work.sh /opt/seed/seed-openfoam-work.sh
RUN chmod +x /opt/seed/seed-openfoam-work.sh \
    && chown -R 1000:1000 /opt/seed \
    # Own the /work mountpoint as uid 1000 so a fresh named volume (which inherits the
    # first mounter's mountpoint ownership) is writable by the non-root user. openfoam-svc
    # often mounts /work before the worker, so this must match the worker image's /work.
    && mkdir -p /work \
    && chown 1000:1000 /work

# Run as a non-root UID (matches the worker's UID so both can read/write /work).
USER 1000:1000

# Reset the base image ENTRYPOINT. The Foundation image uses
# ENTRYPOINT ["/bin/sh","-c","/entry.sh"], which prints a banner and ignores CMD, so the
# container would exit immediately. The seed script sources the OpenFOAM environment
# itself (OPENFOAM_BASHRC) and ends in `exec sleep infinity`, keeping the container alive
# as the execution target the worker invokes simpleFoam inside.
ENTRYPOINT []

# Provision the reference mesh if absent, then stay alive as the execution target.
CMD ["/opt/seed/seed-openfoam-work.sh"]
