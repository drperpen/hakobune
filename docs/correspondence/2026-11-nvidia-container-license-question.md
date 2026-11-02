# Letter to NVIDIA: Deep Learning Container License question

Status: draft, not sent. Fill in the bracketed fields before sending.

To: nvidia-compute-license-questions@nvidia.com
Subject: Distribution of CUDA-based vLLM containers inside an on-premises DGX Spark appliance

---

Dear NVIDIA licensing team,

We are [company legal name], the developer of Hakoteca, a private AI workspace
for businesses in Japan. We would like to confirm that the way we plan to deliver
Hakoteca complies with the NVIDIA Deep Learning Container License (version of
September 14, 2021), which ships as `/NGC-DL-CONTAINER-LICENSE` in the
containers we use.

**How we deliver Hakoteca**

- Each customer receives an NVIDIA DGX Spark (GB10) running DGX OS, installed and
  configured by us, and placed on the customer's premises.
  [Choose one: The customer buys the DGX Spark from us. / We keep ownership of the
  DGX Spark and provide it to the customer under a lease or service agreement.]
- The system runs fully offline. We transfer the container images to it as
  `docker save` archives during installation. We do not publish the images
  anywhere, and the customer receives no separate copy of them.
- Two of the containers serve models with vLLM:
  1. the official `vllm/vllm-openai` image (v0.28.0) published by the vLLM project;
  2. an image from a community recipe that adds Apache-2.0 patches to vLLM on top
     of a vLLM nightly image.

  Both are built on NVIDIA's CUDA base image and contain the license unchanged.
  We do not modify any NVIDIA component, and we keep every NVIDIA notice and the
  license file in place.
- The vLLM services listen only on the machine's loopback interface. Users never
  reach vLLM or any NVIDIA API directly. They use Hakoteca's own application
  (chat, document knowledge base, administration), which is the product's primary
  functionality and calls the models internally.
- The system runs only on the DGX Spark's NVIDIA GPU.

**Our questions**

1. If the customer buys the DGX Spark, may we deliver these containers as part of
   Hakoteca under Sections 1.c and 2 (a derived container with material
   additional functionality, not a stand-alone product)?
2. If we keep ownership of the DGX Spark and lease it to the customer, does
   Section 1.b (deployment on infrastructure we own or lease, without
   distribution) apply instead?
3. Does it matter that one image was built by a third party (the community recipe)
   rather than by us, given that the NVIDIA components in it are unmodified?
4. For Section 2.c, is it enough that our customer agreement includes terms at
   least as protective as the license? Those terms would cover no reverse
   engineering, no redistribution, use only on NVIDIA GPUs and no use in
   Critical Applications. We would also include the license text and the notice
   "This software contains source code provided by NVIDIA Corporation." in the
   documentation we deliver. Is there a recommended flow-down wording?
5. Is anything else required of us, such as registration or a separate
   agreement, for this kind of commercial on-premises appliance?

We would be grateful for a written answer that we can keep with our compliance
records. If a different program or agreement fits this use better, please let us
know.

Kind regards,

[Name]
[Title], [company legal name]
[Email] · [Phone]
[Postal address]
