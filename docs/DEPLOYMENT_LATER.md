# Deferred deployment tasks

The owner explicitly deferred these steps on 25 October 2026. They do not block local source delivery or publication to GitHub. They remain required before describing Quarry as a publicly deployed service.

- Create and verify the Oracle Free Tier account personally, then provision only Always Free resources within the available allowance. Follow `ORACLE_DEPLOYMENT.md`; do not upgrade or substitute paid resources.
- Configure the free personal Gmail sender privately in ignored `.runtime/deployment-mail.env`. Enable eligible-account two-step verification, create an app password and confirm the free-plan setting locally. Keep credentials out of commits, issues and chat.
- Configure a public hostname, HTTPS origin and edge firewall on the actual host. Verify public certificates and real Internet email verification/reset delivery.
- Run native-host startup, persistent restart, worker recovery, capacity and backup/restore acceptance. Establish off-host backup retention and monitoring.

Local HTTPS and STARTTLS rehearsals use a private test CA and captured mail. They do not prove public certificate issuance or Internet mail delivery. No Oracle resource or paid service has been provisioned by the local delivery commands.
