# microstack — rules

- **R1**: `api` and `worker` MUST run the same version.
- **R2**: `backup` runs only during the maintenance window; otherwise it is declared inactive.
- **R3**: every running process MUST correspond to a declared service (no orphans).
