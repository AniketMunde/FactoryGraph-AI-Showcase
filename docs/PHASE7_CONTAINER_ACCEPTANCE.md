# Prepared container configuration

The repository includes CPU API/dashboard Dockerfiles and Compose configuration with
loopback-exposed application ports, separate secrets and an isolated database volume.
No source dataset or runtime bundle is embedded in the images.

Container build, Linux execution, bootstrap, permissions, resource limits and lifecycle
acceptance remain unverified. Treat the files as configuration to inspect, not a tested
deployment. Use authorized inputs and an isolated graph rather than another running
demonstration. The full product remains source-checkout based.
