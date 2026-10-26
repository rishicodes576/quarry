# Hosted installation prerequisites

The source supports a local Docker deployment. A hosted installation requires operator-supplied infrastructure and configuration; these are installation requirements rather than enabled-by-default external services.

- Provide a Linux host with sufficient CPU, memory, disk and Docker/Compose support. Use only resources within the intended free allowance; do not enable paid upgrades or automatic resource substitutions.
- Configure the HTTPS origin, public hostname and edge firewall for that installation.
- Configure a verified outbound mail transport privately. Keep credentials in ignored operator configuration, never in source or browser responses.
- Run host startup, persistent restart, worker recovery, capacity and backup/restore acceptance. Establish off-host backup retention and monitoring.

Production configuration fails closed when required settings are missing. Local HTTPS and STARTTLS rehearsals use a private test CA and captured mail; they do not prove public certificate issuance or Internet delivery. Detailed installation recipes and environment settings are in the operations runbooks.
