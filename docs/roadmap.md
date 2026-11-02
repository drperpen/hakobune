# Roadmap

| Phase | Deliverable | Where it runs |
| --- | --- | --- |
| **0. Scope** (done) | ADR-001, PGX baseline, third-party register, repository rules | Documentation |
| **1. Lockfile and artifact store** (next) | `hakobune.lock` pinning every image digest and every weight file's sha256; `hakobune fetch`/`collect` fills the gitignored store from registries or from PGX's local images and weights, and verifies it; provenance gaps closed | PGX, read-only |
| **2. Bundle build** | `hakobune build`, `sign`, `verify`; notices; measured size | PGX, writes only to the store |
| **3. Install** | Preflight; layout; secret generation; Compose project and systemd unit; PostgreSQL init and Hakoteca migrations; model readiness waits; health checks; idempotent re-runs; `uninstall` for rehearsals | Rehearsal GB10 |
| **4. Commission** | Site profile; hostname, TLS via Hakoteca Offline PKI, trusted proxy; first administrator; acceptance checks | Rehearsal GB10 |
| **5. Lifecycle** | `status`, `upgrade` (backup, then migrate), `rollback`, `backup`/`restore`, redacted diagnostic bundle | Rehearsal GB10 |
| **6. Delivery** | `hakobune push` over LAN (resumable rsync), USB SSD procedure, delta upgrades | Operator machine to rehearsal GB10 |
| **7. First customer demo** | Office install, on-site commission | Customer GB10 |
| **Later** | JIT support gate; remote upgrades through it | |

## Open items

1. **Qwen image redistribution.** Provenance is known: Salient Data's
   `qwen38-next-dgx-recipe` (see [baseline](baseline-pgx.md)). Still open: whether
   the NVIDIA Deep Learning Container License inside the image allows shipping it
   to customers, or whether we rebuild it from the recipe's dev path.
2. **Warm-up.** The Qwen container uses compile caches. Decide whether the bundle
   ships pre-built caches or the office install builds them once (first start can
   take a long time either way). The draft token map is shipped from the pinned
   recipe commit, not from a cache.
3. **Hakoteca docs.** `docs/models.md` in Hakoteca is stale (still lists 27B/2B).
   That is a Hakoteca change, made there.

## Decided

| Date | Decision |
| --- | --- |
| 2026-11-02 | ADR-001 accepted. |
| 2026-11-02 | Releases use calendar versions (`2026.11.0`); ADR-001 §12. |
| 2026-11-02 | Artifact store and bundles stay on PGX's local disk, one release kept, hardlinked; ADR-001 §13. |
| 2026-11-02 | Model provenance recorded: both weight sets are NVIDIA's published NVFP4 checkpoints; the Qwen image comes from Salient Data's recipe. |
| 2026-11-02 | Operator confirmed: embeddings stay on Nemotron-3-Embed-1B-NVFP4 in its own `vllm/vllm-openai:v0.28.0` image for the first release. Serving it from the Qwen image would save about 20 GB, but it would tie the embedding service to a patched nightly that NVIDIA has not validated for this model, and every Qwen recipe update would need an embedding re-check (or a re-index). We can revisit after the first release with a test on the rehearsal GB10. |
