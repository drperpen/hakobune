# Bundles

Phase 2. A bundle is the directory described in ADR-001 §6. It also holds the
installer itself as `hakobune.pyz`, a zipapp that needs only the target's
`python3` and `openssl`.

```
hakobune-<release>/
  manifest.json          release, components, sha256 and size of every other file
  manifest.json.sig      Ed25519 signature of manifest.json
  hakobune.pyz           the installer (standard library only, reproducible)
  images/<name>.tar      docker save archives, exactly the locked image IDs
  models/<name>/...      weights as served
  recipes/<name>/...     recipe files at the pinned commit
  notices/               principal licenses and notices, with README.md as the index
```

## Commands

```
bin/hakobune build --release 2026.11.0-dev.1      # test build
bin/hakobune build --release 2026.11.0            # release: needs every gate below
bin/hakobune keygen --out <offline path>/hakobune-signing.key
bin/hakobune sign bundles/hakobune-<release> --key <key>
bin/hakobune verify --bundle bundles/hakobune-<release> --pubkey <key>.pub
```

On the target, the same check runs from the bundle itself:
`python3 hakobune.pyz verify --bundle . --pubkey <trusted.pub>`.

## Release gates

A release version (`YYYY.MM.N`) is chosen by the operator (AGENTS.md).
`build` refuses a release unless:

- every component in `components.json` has `"review": "approved"`, which mirrors
  `docs/third-party.md`;
- no notice is still `pending`;
- the checkout has no uncommitted changes;
- `hakobune.lock` matches `components.json`.

A test build (`YYYY.MM.N-dev.N`) skips these gates but lists what is missing in
`manifest.json` (`release_blockers`) and in `notices/README.md`.

Bundles are immutable: building an existing release number is refused. `sign`
re-checks the bundle before signing, so a damaged bundle cannot receive a valid
signature. Verification refuses missing files, extra files, symbolic links and
any size or hash mismatch.

## Size and timing (PGX, 2026-11-02, release `2026.11.0-dev.1`)

| | |
| --- | --- |
| Files | 78 |
| Size | 180.0 GB (models 133.8 GB, images 46.3 GB, everything else under 1 MB) |
| Build | 3 s, using hardlinks from the store, so no extra disk |
| Full verification (`hakobune.pyz`, sha256 of everything) | 1 min 48 s |

Images are stored uncompressed. Weights do not compress, and `docker load`
reads plain tars. Compressing only the images could save some of their 46.3 GB on
a slow link. Revisit that in phase 6 if LAN pushes are too slow.

## Open decisions

1. **Signing key.** Where the real Ed25519 key lives. ADR-001 says offline on the
   operator's machine. PGX is online (it runs the public demo), so it should not
   hold the release key. The test bundle in `bundles/` is signed with a throwaway
   key that is not kept.
2. **Trust on the target.** Proposal for phase 3: the first `install` shows the
   bundle's key fingerprint and requires the operator to confirm it (or pass it
   with `--trust SHA256:…`). It then stores the public key in `/etc/hakobune/`, and
   every later upgrade must be signed by that key.
3. **Qwen license texts.** The NVIDIA Open Model License and the Qwen Community
   License 1.0 are pending notices. They are not in the Hugging Face repository and
   must be obtained, pinned and added before the first release.
