# Hakobune

Hakobune (箱舟, "ark") packages a complete, offline Hakoteca installation for an
NVIDIA DGX Spark (GB10) and installs, commissions and upgrades it. It brings the
model serving (vLLM), the model weights, Hakoteca Core and Console, PostgreSQL and
everything else the box needs. Once installed, the box needs no internet access.

Hakoteca is the product. Hakobune is how it ships: it pins exact versions of each
part, builds a signed bundle from them, and runs that bundle on a GB10.

## Status

Phase 0 done (ADR-001 accepted 2026-11-02); phase 1 (lockfile and artifact store) next. See:

- [ADR-001: scope and boundaries](docs/adr/ADR-001-scope-and-boundaries.md)
- [PGX reference baseline](docs/baseline-pgx.md), the working installation the
  first release reproduces
- [Roadmap](docs/roadmap.md)
- [Third-party register](docs/third-party.md)

## What this repository never contains

Model weights, container image tarballs, built bundles, secrets, signing keys or
customer site data. Those live in the gitignored local artifact store or in
private locations described in [ADR-001](docs/adr/ADR-001-scope-and-boundaries.md).
