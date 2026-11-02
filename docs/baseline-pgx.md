# PGX reference baseline

Observed read-only on PGX on 2026-11-02 (Asia/Tokyo) from `docker inspect`,
`docker image inspect` and the mounted files. This is the configuration the first
Hakobune release reproduces. Secrets present in container environments are not
recorded here.

## Host

| Item | Value |
| --- | --- |
| Hardware | NVIDIA DGX Spark, GB10, arm64 |
| OS | DGX OS 7.2.3 (build 2025-10-04), Ubuntu 24.04.5 LTS |
| NVIDIA driver | 580.178.04 |
| Docker Engine | 29.6.2 |
| NVIDIA Container Toolkit | 1.20.1 |
| Root disk | 916 GB (449 GB free when observed) |

## Model services

### Qwen3.8-Flash-Next NVFP4 (`qwen38-flash-next`)

| Item | Value |
| --- | --- |
| Image | `ghcr.io/salient-data/qwen38-next-dgx@sha256:3d67df7b7b7d25a5da64f62c0f87f6109062584261fe77157f6d37de178d10b2` (local ID `sha256:320ab0f7…`, 24.4 GB). It is the "prod" image of Salient Data's community recipe [`salient-data/qwen38-next-dgx-recipe`](https://github.com/salient-data/qwen38-next-dgx-recipe) (Apache-2.0), build `2026-10-14-77154ca6`, recipe commit `f309019de10d55774a579d42f71be67b2636ce8e` (checked out read-only at `~/ai_models/qwen38-next-dgx-recipe`). That build is `vllm/vllm-openai@sha256:a7deff2c…` (vLLM nightly `77154ca6116ae34cbfe314beef1016bde9b63989`, CUDA 13.0.2) plus 14 vLLM patches. The recipe's `recipe/pins.env` pins this exact digest and image ID, and the image is signed with `recipe/cosign.pub`. |
| Weights | Hugging Face snapshot `fc694b54fb0174e0913e6adf86691ef85a4ead47`, 132.7 GB (124 GiB): ten `model-0000N-of-00010.safetensors` shards plus `model-fp8-mtp-ple.safetensors` (53.7 GB), tokenizer and config files. Repository `nvidia/Qwen3.8-Flash-Next-NVFP4` (NVIDIA's ModelOpt quantization of `Qwen/Qwen3.8-Flash-Next`), the revision pinned by the recipe's `MODEL_ID`/`MODEL_REVISION`. |
| Mounts | weights read-only at `/hfrepo`; recipe cache `~/.cache/qwen38-next-dgx-recipe` (8.1 MB) read-write at `/root/.cache`. The cache holds the draft token map `draft-token-maps/d22ff523….json` that the speculative config requires, plus vLLM/FlashInfer compile caches. The same map is versioned in the recipe at `recipe/draft-token-maps/`; both copies hash to their name. |
| Runtime | host network, `ipc=host`, 32 GiB shm, restart `unless-stopped`, GPU all |
| Served names | `hakoteca-model`, `qwen3.8-flash-next`, on `127.0.0.1:8000` |
| Key arguments | `--trust-remote-code --quantization modelopt --max-model-len 262144 --max-num-seqs 12 --gpu-memory-utilization 0.80 --max-num-batched-tokens 4096 --kv-cache-dtype fp8_e4m3 --kv-cache-dtype-skip-layers 48 --mamba-ssm-cache-dtype bfloat16 --enable-prefix-caching --use-replayssm --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml`, default chat template `enable_thinking=false`, engram `host_file_gather`, compilation `mode 0 / FULL_DECODE_ONLY`, FlashInfer autotune off, speculative MTP with 6 tokens and the draft token map above |
| Environment (non-secret) | `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `VLLM_USE_V2_MODEL_RUNNER=1`, `VLLM_ENGINE_READY_TIMEOUT_S=3600`, `VLLM_PLE_FILE_GATHER_WORKERS=64`, `QWEN38_FP8_DENSE=gdn,attn,shared,mtp,lm_head`, `QWEN4EXP_DRAFT_VOCAB=0`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |

### Nemotron-3-Embed-1B-NVFP4 (`nemotron-3-embed-1b-vllm`)

| Item | Value |
| --- | --- |
| Image | `vllm/vllm-openai@sha256:61fc8a896b0a4fbbbdc063bc4b0dbc25ce98e02b5050c24aeb7830ac02039b14` (`v0.28.0`, 20.6 GB) |
| Weights | `~/ai_models/Nemotron-3-Embed-1B-NVFP4`, 997 MB, single `model.safetensors`. Downloaded from NVIDIA's own repository `nvidia/Nemotron-3-Embed-1B-NVFP4`, revision `e58f16cdf28e3c57252bcaf65e9f60f357f717be` (from the Hugging Face download metadata). NVIDIA quantized it from `nvidia/Nemotron-3-Embed-1B-BF16` with ModelOpt 0.45.0. The `/tmp/…` path in `quantization_metadata.json` is NVIDIA's build path, not a local quantization. `model.safetensors` sha256 `f2753954c89055eb679a45b7dfea27a3e05c04ecbdb1f4e6c086180fe8c32bc7` matches the hub's LFS hash. |
| Runtime | host network, `ipc=host`, restart `unless-stopped`, mounted read-only at `/model` |
| vLLM version note | The model card validates vLLM 0.22.1 and 0.25.0 and warns that 0.23.x and 0.24.x have known issues. PGX runs 0.28.0, which is not on that list but passed Hakoteca's embedding acceptance. |
| Served name | `nemotron-embed` on `127.0.0.1:8001`, `--runner pooling --max-model-len 8192 --gpu-memory-utilization 0.05 --dtype auto --trust-remote-code` |
| Authentication | `VLLM_API_KEY` set (value not recorded); Core must be given the same key |

## Hakoteca and supporting images

| Image | Reference | Size |
| --- | --- | --- |
| Core | `hakoteca/core:0.2.3`, ID `sha256:712079b1348d…` (local build, no registry digest) | 241 MB |
| Console gateway | `hakoteca/console-gateway:0.2.3`, ID `sha256:ff376c2b1d62…` | 64 MB |
| PostgreSQL | `postgres@sha256:ae69c452f483507a6b99fb654cf93aad7fe156ffd2c56247707eef4e36d3c12b` (`postgres:17`) | 477 MB |

Both Hakoteca images are built by Hakoteca's `scripts/build-public-images.py` from
the `v0.2.3` tag; the public instance stack is described in Hakoteca's
`deployment/public/`.

## Bundle size estimate

| Part | Size |
| --- | --- |
| Qwen weights | 132.7 GB (124 GiB) |
| Qwen vLLM image | 24.4 GB (uncompressed) |
| Embedding vLLM image | 20.6 GB (uncompressed) |
| Embedding weights | 1 GB |
| Core, gateway, PostgreSQL | 0.8 GB |
| **Total** | **about 180 GB** (decimal; 171 GiB) |

The two vLLM images share only 6 of their layers (the Qwen image has 42, the
embedding image 32), so the 20 GB is real. Separate `docker save` files would
not deduplicate the shared layers anyway. Using one vLLM image for both models would cut about 20 GB
(see roadmap open items).

## Gaps found

- `docs/models.md` in the Hakoteca repository still describes the retired 27B and
  2B models; `docs/current-state.md` has the current single Flash-Next service.
- ~~The Qwen image's origin and the Qwen weights' repository ID were not
  recorded.~~ Resolved 2026-11-02 (see above).
- ~~The embedding quantization was thought to be local.~~ It is NVIDIA's
  published NVFP4 checkpoint; resolved 2026-11-02.
- The Qwen container mounts a writable cache that holds a file the configuration
  depends on (the draft token map). The bundle must ship that file explicitly, not
  rely on a cache.
