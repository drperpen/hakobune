# Third-party register

Every component redistributed in a customer bundle needs a complete row before
that bundle ships. "Review" means the exact license text was read, redistribution
and commercial-use terms are understood, and the required notices are in the
bundle's `notices/`.

| Component | Exact source | License (as stated) | Redistribution questions | Review |
| --- | --- | --- | --- | --- |
| Qwen3.8-Flash-Next NVFP4 weights | `nvidia/Qwen3.8-Flash-Next-NVFP4` @ `fc694b54fb0174e0913e6adf86691ef85a4ead47` | NVIDIA Open Model License; additional: Qwen Community License 1.0 (per model card) | Read both texts; check Qwen Community License conditions for commercial use and any user-count thresholds; required attribution and naming | Pending |
| Nemotron-3-Embed-1B-NVFP4 weights | `nvidia/Nemotron-3-Embed-1B-NVFP4` @ `e58f16cdf28e3c57252bcaf65e9f60f357f717be` (NVIDIA's quantization, ModelOpt 0.45.0) | OpenMDW-1.1 (LICENSE file); NOTICE and THIRD_PARTY_NOTICES.md in the repository | Ship LICENSE, NOTICE and THIRD_PARTY_NOTICES.md unchanged | Pending |
| Qwen vLLM image | `ghcr.io/salient-data/qwen38-next-dgx@sha256:3d67df7b…`, the prod image of `salient-data/qwen38-next-dgx-recipe` @ `f309019d…` (build `2026-10-14-77154ca6`) | Recipe and patches Apache-2.0 (Salient Data; patch 0002 from tonyd2wild, Apache-2.0); vLLM Apache-2.0; NVIDIA software under the NVIDIA Deep Learning Container License (`/NGC-DL-CONTAINER-LICENSE` in the image) | NVIDIA Deep Learning Container License read 2026-11-02 (see below); shipping appears permitted as a derived container inside Hakoteca, with conditions. Carry the recipe's NOTICE and patch PROVENANCE.md | Pending operator decision |
| Embedding vLLM image | `vllm/vllm-openai@sha256:61fc8a89…` (`v0.28.0`) | vLLM Apache-2.0; bundled CUDA/NVIDIA libraries under NVIDIA terms | Same NVIDIA Deep Learning Container License, in the identical base layer (see below) | Pending operator decision |
| PostgreSQL image | `postgres@sha256:ae69c452…` | PostgreSQL License; Debian base packages | Notices | Pending |
| Hakoteca Core and Console gateway | Built from the Hako `v0.4.0` tag | Hakoteca's own; images already carry license records | Carry Hakoteca's notices through | Pending |

## NVIDIA Deep Learning Container License (v. September 14, 2021)

Both vLLM images contain `/NGC-DL-CONTAINER-LICENSE` in the same CUDA base layer
(`ddb9b4955d48…`), so rebuilding the Qwen image from source would not avoid it.
This is a reading, not legal advice; the operator decides.

- **Shipping is allowed for a derived container** that includes the whole NVIDIA
  container plus software with primary functionality (§1.c), as long as the
  product has material additional functionality (§2.a). It must not be shipped
  as a stand-alone product (§4.c). Hakoteca on top of vLLM meets this.
- **If the operator keeps ownership of the box** (leases it), §1.b may apply
  instead: deployment on infrastructure you own or lease, without distributing,
  provided users do not reach the NVIDIA APIs directly. vLLM binds to loopback
  and users reach only Hakoteca.
- **Conditions:**
  - Customer terms must be at least as protective as NVIDIA's: no reverse
    engineering, no redistribution, CUDA only on NVIDIA GPUs (§2.c, §4).
  - Keep NVIDIA's notices, and do not remove the license file from the images
    (§4.b). Hakobune does not modify images.
  - Ship the notice "This software contains source code provided by NVIDIA
    Corporation." (§2.b) and the license text in the bundle's `notices/`.
  - Notify NVIDIA of known misuse (§2.d).
  - Make no claim of NVIDIA endorsement (§4.d).
  - Not for Critical Applications such as medical, life-support or military
    systems (§4.h), with indemnity to NVIDIA if used that way (§4.i).
  - Governing law is Delaware; U.S. export rules apply (§13, §15).
- **To confirm:** NVIDIA invites questions at
  nvidia-compute-license-questions@nvidia.com (§19); a written confirmation for
  this appliance model would close the item.
