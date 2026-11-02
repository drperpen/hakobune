# ADR-001: Scope and boundaries

Date: 2026-11-02 (Asia/Tokyo)
Status: Accepted (operator, 2026-11-02)

## Context

Hakoteca will run on customer premises on an NVIDIA DGX Spark (GB10) that the
operator provides, ideally with no internet access. Today the only working
installation is PGX, assembled by hand: model containers run outside Hakoteca
deployment and their arguments are recorded only in Hakoteca's docs. A customer
installation must be reproducible, offline and upgradable without the operator
rebuilding it by hand each time.

Known facts that shape the design (details in [baseline](../baseline-pgx.md)):

- Every customer gets the same hardware (GB10, arm64) and the same model set.
- The full payload is about **170 GB**, mostly the 124 GB Qwen weights. A first
  install over a customer's internet link is impractical.
- The operator runs every install for now. The first demo is on site; later work
  may be remote.
- A second GB10 will be available for rehearsals.

## Decisions

### 1. Separate repository; Hakoteca stays the product
Hakobune consumes Hakoteca **release images** (`hakoteca/core:<version>`,
`hakoteca/console-gateway:<version>`, built by Hakoteca's
`scripts/build-public-images.py`) and migrations inside them. It never builds
Hakoteca from source and never edits the Hakoteca repository. If Hakobune needs
something from Hakoteca (for example a health or bootstrap command), that is a
Hakoteca change made there.

### 2. One hardware and OS profile
Target: NVIDIA DGX Spark, GB10, arm64, DGX OS 7.x (Ubuntu 24.04), NVIDIA driver
580.x, Docker and NVIDIA Container Toolkit as shipped with DGX OS. Preflight checks
each of these and refuses anything else. Hakobune does not install or reimage the
OS; the box starts from NVIDIA's first-boot setup.

### 3. One model set
| Role | Model | Served as |
| --- | --- | --- |
| Fast, router and expert | Qwen3.8-Flash-Next NVFP4 | `hakoteca-model` (port 8000) |
| Knowledge embeddings | Nemotron-3-Embed-1B-NVFP4 | `nemotron-embed` (port 8001) |

No other models are packaged. Changing a model is a new Hakobune release, and a
changed embedding model requires re-indexing Knowledge.

### 4. Everything runs as containers
On the box: vLLM (Qwen), vLLM (embeddings), PostgreSQL 17, Hakoteca Core and the
Console gateway, as one Docker Compose project under a systemd unit. No Python,
Node or other runtime is installed on the host for Hakoteca. Services bind to
loopback except the HTTPS gateway.

### 5. Install in the office, commission on site
Because the operator provides the box, installation has two stages:

- **`install`** (in the office, over LAN or a direct disk): loads images and
  weights, creates the layout, starts the stack with a placeholder identity, and
  passes health checks. This moves the 170 GB before the box leaves the office.
- **`commission`** (on site): applies the site profile (hostname, address,
  TLS certificate from Hakoteca's Offline PKI, trusted proxy, time zone), creates
  the first administrator through Hakoteca's existing hidden-prompt CLI, and runs
  acceptance checks. No large transfer is needed.

`upgrade` later moves only what changed; most releases change only the Core and
gateway images (about 300 MB).

### 6. Bundle format
A bundle is a directory, `hakobune-<release>/`:

```
manifest.json        release, component versions, image digests, per-file sha256
manifest.json.sig    Ed25519 signature of manifest.json
images/<name>.tar    docker save, one file per image
models/<name>/...    weights exactly as served
recipes/...          non-weight runtime files (for example draft token maps)
notices/...          licenses and notices for every component
```

Integrity is the signed manifest plus a sha256 for every file. rsync and file
copies naturally skip unchanged files, which provides upgrade deltas without a
custom format. Signing uses Ed25519 through OpenSSL, which DGX OS already ships;
the private key stays offline on the operator's machine.

### 7. Installer implementation
One Python 3 command, `hakobune`, using only the standard library, shipped inside
the bundle (a zipapp). It runs on the target with the OS's `python3`, `openssl`
and `docker`. The same program runs on the operator's machine for `fetch`,
`build`, `sign` and `push`. Development may use extra tools (tests, linters), but
nothing beyond the standard library is required at install time.

### 8. Layout on the target
| Path | Contents |
| --- | --- |
| `/opt/hakobune/releases/<release>/` | Installed bundle; `current` symlink |
| `/var/lib/hakoteca/models/` | Weights (read-only to the model containers) |
| `/var/lib/hakoteca/postgres/` | Database data |
| `/var/lib/hakoteca/knowledge/` | Knowledge storage |
| `/var/lib/hakoteca/backups/` | Pre-upgrade database backups |
| `/etc/hakoteca/` | Rendered configuration; secrets mode 0600 |

A dedicated `hakoteca` system account owns the application data.

### 9. Secrets and site data
Database passwords, the Hakoteca key file and API keys between Core and vLLM are
generated on the target at install time and never leave it. Site profiles
(customer name, hostnames, addresses, certificate requests) live in a private
location outside this repository, not on GitHub.

### 10. Delivery modes
1. **Direct disk** (USB SSD): copy the bundle, run `hakobune install` locally. Used
   for the first demo.
2. **LAN push** from the operator's machine: `hakobune push` uses resumable rsync
   over SSH, then runs the same command on the target.
3. **Remote upgrade** through the future JIT support gate: same push, deltas only.

### 11. Where tests run
PGX is a read-only reference and build machine for Hakobune (see `AGENTS.md`).
Install, wipe and upgrade tests run only on the rehearsal GB10.

### 12. Release versions
Hakobune releases use calendar versions, `YYYY.MM.N` (for example `2026.11.0`),
independent of Hakoteca's version. The manifest records each component's own
version. The operator approves every release version.

### 13. Artifact store and bundles
For now the artifact store and built bundles live on PGX's local disk, in this
checkout's gitignored `store/` and `bundles/`, and only one release is kept.
A store plus one bundle is about 340 GB if copied, against 449 GB free, so the
bundle build hardlinks files from the store (same file system) instead of copying
them. The store copies weights from `~/ai_models`; it never hardlinks PGX's live
files. Revisit (NAS or external SSD) before keeping a second release.

## Out of scope for now

The JIT support gate (planned later as a Hakobune component), OS installation or
reimaging, other GPUs or multiple nodes, customer-run installation, automatic
updates.

## Consequences

- PGX's hand-built model containers become pinned, declarative configuration. PGX
  itself is not migrated to Hakobune by this decision.
- Each Hakobune release needs a completed third-party review of every component
  before it reaches a customer.
- Each kept release needs about 170 GB on the operator's machine; with hardlinks
  the store and a bundle built from it share that space.
