# Hakobune contributor rules

## What belongs in git

- Manifests, lockfiles, installer code, tests and documentation only.
- Never commit model weights, image tarballs, bundles, the artifact store, secrets,
  signing keys, customer names, hostnames, addresses, certificates or other site data.
  `.gitignore` covers the usual paths. If a file is larger than a few MB, stop and
  ask why it is here.
- Site profiles live in a separate private location (see ADR-001), never in this
  repository.

## Machines and authority

- **PGX** is the build and reference machine. It runs the
  Hakoteca dev installation **and the public client instance**
  (`console.hakoteca.co.jp`). On PGX, Hakobune may only read: inspect containers,
  images and files, hash weights, export images with `docker save`, build bundles
  into the artifact store. Never install, start, stop, restart, recreate or
  reconfigure any PGX container, service, database or firewall from Hakobune.
  The Hakoteca repository's `AGENTS.md` still governs PGX.
- **Rehearsal GB10** is the only target where destructive install, uninstall,
  wipe and upgrade tests are allowed. Before any destructive step, verify the host
  identity (hostname, machine ID) matches the rehearsal machine.
- **Customer GB10s** are changed only by the operator, by an explicit action, never
  by tests.

## Installer rules

- The installer runs on a stock DGX OS box with only what that OS ships (bash,
  Python 3 standard library, OpenSSL, Docker, NVIDIA Container Toolkit). No pip,
  npm or network access at install time.
- Every step is idempotent and safe to re-run. Preflight refuses an unsupported host
  and explains why.
- Secrets are generated on the target and stored mode 0600. Never print, log or put
  them in a bundle, a manifest or command arguments.
- Back up the database before any migration on a machine holding real data.

## Hako release contract

Hako (the product, repository `hakoteca-hako`, `~/projects/hakoteca` on PGX) defines
what Hakobune may rely on in its ADR-024 "Deployment by Hakobune". The dependency is
one-way: Hakobune consumes Hako release images and never edits Hako; anything
Hakobune needs from Hako is a Hako change made there.

- Read Hako's contract from `/usr/share/hakoteca/release.json` in the locked
  `hakoteca-core` image (`src/hakobune/hako.py`; Hako 0.4.0 or later). Do not
  hard-code Hako settings, migration revisions or commands that the manifest
  provides.
- Set up the database with `python -m hakoteca_core.security.postgres_roles` from
  the Core image, in the order the manifest's `database_setup` gives.
- Render `HAKOTECA_APPLIANCE_RELEASE=<release>` and
  `HAKOTECA_ADMIN_GUIDE_EXTRA_DIR` (the installed `admin-guide/`, read-only) into
  Core's environment.
- `admin-guide/` holds the customer-facing appliance pages, in Hako's guide format.
  Hako's guide links to six fixed names (`hako.REQUIRED_PAGES`); a release bundle
  needs all of them. Pages are customer-facing: no hostnames, addresses, customer
  names or secrets, and they describe only commands that exist. A change to an
  installer command updates its page in the same commit.

## Third-party content

Every redistributed image, model and binary needs an entry in
`docs/third-party.md` with exact source, revision/digest, license and review
status before it can go into a customer bundle.

## Versions

The operator approves every Hakobune release version and every pinned component
change. Suggest changes; do not bump on your own.
