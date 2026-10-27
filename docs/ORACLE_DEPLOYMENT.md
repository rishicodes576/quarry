# Free Oracle deployment acceptance

Status on 27 October 2026: no Oracle host, public hostname or native-host acceptance is established. The private dedicated free sender passed live certificate-verified Gmail SMTP authentication and one authorized same-account inbox-delivery test from the Docker application network. Public signup/recovery and the deployed application outbox still require acceptance. See `evaluation/results/smtp-delivery.json`. Local production-mode TLS/STARTTLS and ARM64-emulated model checks have separate evidence.

## Owner prerequisites

Create and verify your own [Oracle account](https://signup.cloud.oracle.com/). Keep it on Free Tier. Oracle requires identity/payment verification and can place temporary card authorization holds; virtual/single-use/prepaid cards are not accepted. Do not upgrade to a paid account or choose trial-credit resources. [Oracle FAQ](https://www.oracle.com/cloud/free/faq/)

In the home region, select an Always Free eligible Ubuntu ARM64 image and `VM.Standard.A1.Flex`. Allocate at most **2 OCPUs / 12 GB RAM in total across the tenancy**. A 150 GB boot disk leaves room for source builds only if existing boot/block volumes keep the combined total within **200 GB**. Check existing allocations first. Capacity availability is a separate prerequisite; a paid shape is not a fallback. [Current resource allowances](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

Create an SSH key locally and retain the private half outside the repository. Verify the server host-key fingerprint through the console before connecting. Allow TCP 22 only from the administrator's IP; allow public TCP 80/443. Keep PostgreSQL, Qdrant, S3, parser, API and mail-sink ports private. This deployment uses the VM and existing Compose services; it does not require a cloud load balancer or a paid database.

For a free web hostname, the owner can register a [DuckDNS subdomain](https://www.duckdns.org/about.jsp) and point it at the VM's public address. Keep its update token private. DNS must resolve correctly before Caddy requests its public certificate. A changed public address requires a DNS update.

## Verification email without buying a domain

An eligible personal Gmail account can use an app password for this SMTP-only integration. Enable two-step verification and create a separate app password locally; never put your normal Google password in Quarry. Some account policies do not offer app passwords. [Google's eligibility and revocation instructions](https://support.google.com/accounts/answer/185833)

Set the SMTP sender and username to that same Gmail address, with `smtp.gmail.com`, port `587`, and STARTTLS. This uses Gmail's authenticated sender rather than pretending to send from the web hostname. [Google SMTP protocol documentation](https://developers.google.com/workspace/gmail/imap/imap-smtp)

Gmail has finite sending limits; Google documents errors beyond 500 daily messages, and other restrictions can apply. This is an option for a small portfolio deployment, not an unlimited mail service or a delivery SLA. SMTP failures retain the existing bounded outbox retry/dead-job behavior; inspect failed mail jobs before assuming a signup message arrived. No paid mail fallback is configured. [Gmail limits](https://support.google.com/mail/answer/22839)

## Install on the owned host

Follow the [official Ubuntu Docker Engine installation](https://docs.docker.com/engine/install/ubuntu/) for ARM64, including Buildx and the Compose plugin. Install Python 3 and allow only trusted administrators access to Docker. Check `docker info` and `docker compose version`; Compose must support the overlays' `!override` tag (2.24.4 or newer).

Transfer the reviewed source ZIP over SSH after checking its delivery manifest. Extract into the administrator's home directory. The following commands run on that server inside `quarry/`; they have not been executed against an Oracle host in this release:

```bash
python3 -c "from scripts.manage import configure; configure()"
chmod 600 .env
```

Edit the ignored `.env` privately. Retain its newly generated private-service secrets. Replace the example hostname/address and configure these values before starting services:

```dotenv
QUARRY_ENV=production
QUARRY_APP_ORIGIN=https://YOUR_OWNED_HOSTNAME
QUARRY_PUBLIC_HOST=YOUR_OWNED_HOSTNAME
QUARRY_ACME_EMAIL=YOUR_OPERATOR_EMAIL
QUARRY_COOKIE_SECURE=true
QUARRY_DEMO_SEED=false
QUARRY_SIGNUP_MODE=public
QUARRY_SMTP_HOST=smtp.gmail.com
QUARRY_SMTP_PORT=587
QUARRY_SMTP_STARTTLS=true
QUARRY_SMTP_USER=YOUR_GMAIL_ADDRESS
QUARRY_SMTP_PASSWORD=YOUR_LOCALLY_CONFIGURED_APP_PASSWORD
QUARRY_MAIL_FROM=YOUR_GMAIL_ADDRESS
QUARRY_ALLOW_PAID_PROVIDERS=false
OPENAI_API_KEY=
```

Never commit this file or paste it into chat. Live generation is optional: leave the Groq key empty for local extractive operation, or configure an owner-attested Free Plan key privately. Do not copy development sessions or demo credentials to the public host.

Use the production overlay consistently on this host:

```bash
docker compose -f compose.yaml -f infra/production.compose.yaml config --quiet
docker compose -f compose.yaml -f infra/production.compose.yaml build api web objectstore gateway postgres qdrant searxng
docker compose -f compose.yaml -f infra/production.compose.yaml up --no-build --detach --wait --wait-timeout 900
```

The build selects each image family once; parser/initialization/workers reuse the backend image. The production overlay excludes Mailpit, disables demo access, and enables the public TLS edge. Do not use the default local `manage.py up` to restart a production stack: it selects the loopback development gateway. For an ordinary server reboot, enable the Docker daemon at boot; the configured persistent services have restart policies. Initialization/migrations are explicit deployment steps.

## Acceptance before claiming deployment complete

From a second device, open the actual HTTPS hostname and verify a publicly trusted certificate. Check that demo access is absent and private ports are unreachable. Register an owner-controlled test address, receive its real verification message, redeem it once, then test login, logout, reset, upload, cited research and export. A healthy internal HTTP endpoint does not establish public TLS or mail delivery.

Restart the stack with volumes preserved and repeat authenticated access. Exercise worker recovery, inspect resource/queue metrics, and perform a restore into an isolated project before moving any real data. Recheck the pinned images on the native architecture. Configure encrypted off-host backups through a separately reviewed free destination; the same-host restore is not off-host disaster recovery. Record the hostname, host architecture, tested image IDs, timestamps and actual outcomes in a new acceptance report. Leave unavailable checks explicitly incomplete.

This is a single-host deployment. The local replica experiment does not establish native ARM capacity, multi-zone failover or always-available free cloud capacity. Public deployment remains blocked by the owner account prerequisite until those actual acceptance steps pass.
