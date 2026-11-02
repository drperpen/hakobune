# Lockfile and artifact store

Phase 1. Three files describe a release's contents:

| File | In git | Written by | Says |
| --- | --- | --- | --- |
| `components.json` | yes | a person | which images, models and recipe files ship, by pinned ref, Hugging Face revision or git commit |
| `hakobune.lock` | yes | `hakobune lock` | the exact bytes: image IDs, and the size and sha256 of every model and recipe file |
| `hakobune.local.json` | no (gitignored) | the operator | where this machine keeps the sources (copy `hakobune.local.example.json`) |

Neither committed file names a machine, a path or a site. `tests/test_hygiene.py`
fails if one does.

## Commands

```
bin/hakobune lock            # resolve components.json into hakobune.lock
bin/hakobune lock --check    # fail if the lock is stale; writes nothing
bin/hakobune collect         # fill store/ from local images, weights and recipes
bin/hakobune verify          # re-hash all of store/ against the lock
bin/hakobune status          # what store/ holds, without hashing
```

`collect` and `verify` take `--only NAME` (repeatable). Every command can be
re-run: `collect` skips files it has already verified, using the file's size,
mtime and inode recorded in `store/state.json`. `verify` always re-hashes
everything.

A pin change is a change to `components.json` followed by `hakobune lock`. The
operator approves it by reviewing the lock diff (AGENTS.md).

## Where each hash comes from

The lock records what upstream published, not just what this machine happens
to hold:

- **Model weights.** The file list and hashes come from the Hugging Face metadata
  that `hf download` leaves in `<model>/.cache/huggingface/`. That is the
  revision's tree (`trees/<revision>.json`) when present, otherwise the
  per-file download records, whose commit must equal the pinned revision. Large
  (LFS) files take the sha256 the hub published, and `collect` hashes every byte
  against it while copying. Small files are hashed at `lock` time and must match
  the hub's git blob ID. `.gitattributes` is left out. A model without this
  metadata is refused as a provenance gap.
- **Recipe files** are read with `git show <commit>:<path>` from the pinned
  commit, never from the working tree.
- **Images.** A registry image must resolve from its pinned digest. A local build
  (the Hakoteca images) must match the image ID pinned in `components.json`,
  because its tag is mutable. The lock records the image ID, which survives
  `docker save`/`docker load`.

## Store layout

```
store/images/<name>.tar          docker save --platform linux/arm64 of the locked image
store/models/<name>/<path>       weights as served
store/recipes/<name>/<path>      recipe files at the pinned commit
store/state.json                 what has been verified (a cache; safe to delete)
```

Each file is written under `.partial`, checked against the lock, made read-only
and then renamed, so a file under its final name is always good. An image archive
is checked offline: its config blob must hash to the locked image ID, the
config's `diff_ids` must equal the archive's layers in order, and every blob must
hash to its name. This links every byte `docker load` will read back to the lock.

## Safety on PGX

- The Docker wrapper runs only `docker image inspect` and `docker save` and
  refuses anything else (`tests/test_store.py`).
- Sources are read with `O_DIRECT`, so copying 133 GB does not evict from the
  page cache the pages that the live Qwen server streams from the same files.
  Pages Hakobune writes are dropped once they are on disk. Pages of source files
  are never dropped.
- `collect` refuses to start without enough free disk for the missing files plus
  a 10 GB margin.
