# Upstream Integration

## Source

- Repository: `https://github.com/smeradlo0206/longtext-comic-agent.git`
- Imported commit: `ebb62a61ae71d56a47ac4c8c0c064447a399cef9`
- Archive SHA-256: `9226210d2a7d659fc03d39481865b968b8081107b2cece86a7c6ace132daae24`
- Import date: 2026-08-22

The Git smart transfer was unavailable in the server environment, so the exact public commit was
resolved through the GitHub API and imported from GitHub's official codeload archive. The archive
was unpacked under a local audit directory and kept unchanged as an audit copy.

## Baseline

Before integration, the untouched upstream snapshot completed:

```text
762 passed, 1 skipped, 6 warnings
```

The upstream architecture explicitly limited the implemented phase to the source evidence chain,
schema contracts, mock providers, API/database shells, and tests. Full story compilation, image
generation, QA repair loops, and frontend workflows were planned but not implemented.

## Local Changes

1. Imported the complete upstream application, migrations, API, web console, docs, and tests.
2. Moved all existing FLUX.2 Pydantic contracts into `comic_agent/schemas/image_workflow.py`.
3. Added proposal-only extractive long-text storyboard planning with exact `EvidenceRefV1` offsets.
4. Added provider-neutral `PageSpecV1` and production manifests.
5. Implemented `LocalFlux2ImageProvider` and retained `flux2_agent` as a compatibility CLI/module.
6. Added idempotent production persistence and migration `0009_comic_production_runs`.
7. Added API compile/status/retry/cancel routes and the `comic-agent` end-to-end CLI.
8. Added independent-panel generation, cross-page continuity graphs, and deterministic 3x2 composition.
9. Added optional automatic color identity anchors. The worker creates each anchor before panels
   without reloading the model, then replaces every matching character input by entity id.
10. In AUTO mode each panel uses an independent seed plus fixed identity/scene references. This
    prevents a previous full frame from freezing old poses while retaining cross-cast identity.

## Known Boundary

The offline extractive planner is intentionally conservative. It provides a functioning and
traceable long-text pipeline without an LLM credential, but it does not perform high-level scene
compression or literary shot selection. `LLM_PROPOSAL` remains fail-closed until a storyboard
Provider is explicitly configured and tested.

FLUX.2 Klein does not expose per-reference weights or a durable character identity token. AUTO
anchors substantially reduce cross-cast drift, but production adaptations still need human anchor
approval or character LoRAs plus visual QA when exact facial identity is mandatory.
