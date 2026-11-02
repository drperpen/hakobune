# Third-party register

Every component redistributed in a customer bundle needs a complete row before
that bundle ships. "Review" means the exact license text was read, redistribution
and commercial-use terms are understood, and the required notices are in the
bundle's `notices/`.

| Component | Exact source | License (as stated) | Redistribution questions | Review |
| --- | --- | --- | --- | --- |
| Qwen3.8-Flash-Next NVFP4 weights | `nvidia/Qwen3.8-Flash-Next-NVFP4` @ `fc694b54fb0174e0913e6adf86691ef85a4ead47` | NVIDIA Open Model License; additional: Qwen Community License 1.0 (per model card) | Read both texts; check Qwen Community License conditions for commercial use and any user-count thresholds; required attribution and naming | Pending |
| Nemotron-3-Embed-1B-NVFP4 weights | `nvidia/Nemotron-3-Embed-1B-NVFP4` @ `e58f16cdf28e3c57252bcaf65e9f60f357f717be` (NVIDIA's quantization, ModelOpt 0.45.0) | OpenMDW-1.1 (LICENSE file); NOTICE and THIRD_PARTY_NOTICES.md in the repository | Ship LICENSE, NOTICE and THIRD_PARTY_NOTICES.md unchanged | Pending |
| Qwen vLLM image | `ghcr.io/salient-data/qwen38-next-dgx@sha256:3d67df7b…`, the prod image of `salient-data/qwen38-next-dgx-recipe` @ `f309019d…` (build `2026-10-14-77154ca6`) | Recipe and patches Apache-2.0 (Salient Data; patch 0002 from tonyd2wild, Apache-2.0); vLLM Apache-2.0; NVIDIA software under the NVIDIA Deep Learning Container License (`/NGC-DL-CONTAINER-LICENSE` in the image) | **Main question:** does that NVIDIA license let us redistribute the image to customers? If not, the alternative is to rebuild it ourselves from the recipe's dev path (same patches, pinned base), which still needs the CUDA base's terms checked. Carry the recipe's NOTICE and patch PROVENANCE.md | Pending |
| Embedding vLLM image | `vllm/vllm-openai@sha256:61fc8a89…` (`v0.28.0`) | vLLM Apache-2.0; bundled CUDA/NVIDIA libraries under NVIDIA terms | Confirm CUDA redistributable terms cover shipping the image | Pending |
| PostgreSQL image | `postgres@sha256:ae69c452…` | PostgreSQL License; Debian base packages | Notices | Pending |
| Hakoteca Core and Console gateway | Built from the Hakoteca `v0.2.3` tag | Hakoteca's own; images already carry license records | Carry Hakoteca's notices through | Pending |
