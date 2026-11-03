---
title: What the Hako appliance contains
audience: [system-admin]
covers:
  - docs/adr/ADR-001-scope-and-boundaries.md
  - components.json
  - src/hakobune/hako.py
reviewed: 2026-11-03
---

# What the Hako appliance contains

A Hako appliance is one NVIDIA DGX Spark computer that runs everything Hako needs.
Hakoteca prepares it with its installer, Hakobune, and delivers it ready to use.
After installation the appliance needs no internet access: the language models,
the database and Hako itself all run on the machine.

## What runs on the appliance?

| Service | What it does |
| --- | --- |
| Hako Console gateway | Serves the web interface over HTTPS. It is the only service that listens on the network. |
| Hako Core | Sign-in, permissions, conversations, Knowledge, tools and calls to the models. Listens only on the machine itself. |
| PostgreSQL 17 | The Hako database. Listens only on the machine itself. |
| Chat model | Qwen3.8-Flash-Next (NVIDIA NVFP4 version), used for fast answers, routing and expert answers. |
| Embedding model | Nemotron-3-Embed-1B (NVIDIA NVFP4 version), used to search Knowledge. |

All of them run as containers that start automatically when the appliance starts.
The models are part of the appliance: Hako calls only these local models and has no
cloud fallback.

## Which versions does my appliance run?

The appliance has two version numbers, both shown at the bottom of the Settings
navigation for system administrators:

- **Hakoteca Hako** followed by the Hako version, for example 0.4.0.
- **Hakobune** followed by the appliance release, a date-based number such as
  2026.11.0. One appliance release fixes the versions of every part listed above,
  including the models.

Give both numbers when you contact Hakoteca support.

## Who changes the appliance?

Hakoteca installs and upgrades the appliance. Each appliance release is checked
and signed by Hakoteca before it is installed. Changing a model is a new appliance
release, and a change of the embedding model means that Knowledge is indexed
again.

Everyday administration (accounts, Roles, Knowledge, tools and connections)
happens in **Settings**, as described in the rest of this guide.

## Where is my data?

Everything Hako stores stays on the appliance: the database, the private copies
of indexed documents and the key that protects stored passwords. Original
documents in folder and SMB sources stay where they are; Hako only reads them.
See [Backups, upgrades and recovery](upgrade-backup-recovery.md) for what must be
kept safe.
