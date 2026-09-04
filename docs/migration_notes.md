# Migration Notes

## Comic Planning / local FLUX.2 integration

### Schema compatibility

- Added the upstream `ComicPlanningInputV1`, `ScenePlanV1`, and `PanelPlanV1` contracts at schema
  version `1.0`; existing comic-production and image-workflow payloads remain compatible.
- `ComicPlanStoryboardAdapter` converts evidence-backed `PanelPlanV1` records into the existing
  proposal-only storyboard handoff. Provider fields remain confined to `PromptSpecV1` and the
  image workflow contracts.

### Database compatibility

- No database migration is required. Planned runs use the existing idempotent comic-production
  repository and queue records.

### CLI compatibility

- Added `comic-agent run-planned`; existing `run`, `status`, and `worker` commands are unchanged.
- Planned character identifiers must have matching selected character assets before image work is
  enqueued.

## Upstream sync a89cb84

### Database compatibility

- Imported upstream StoryBible production migration `0009_storybible_production_runs` and review
  migration `0010_storybible_review_runs` without rewriting their published revision ids.
- Added `0011_merge_storybible_comic_heads` to join the upstream StoryBible branch with the local
  `0009_comic_production_runs` branch. The merge migration changes only the Alembic graph and does
  not create, alter, or drop tables.

## 0.3.0

### Identity-anchor compatibility

- `StoryboardRequest` and `WorkflowJob` now default to schema version `2.2` and continue to accept
  historical `2.0` and `2.1` payloads.
- Added `IdentityAnchorSpec` and `PlannedIdentityAnchor`. A `2.2` workflow may normalize each
  character reference once and reuse the generated color anchor across all panel cast groupings.
- Runtime image result files now report schema version `2.2` and include auditable identity-anchor
  attempts and output paths.
- `ComicProductionRequestV1.identity_anchor_mode` defaults to `OFF` for compatibility. `AUTO`
  enables color anchors and independent panel seeds; no database migration is required.
- Package metadata, FastAPI OpenAPI metadata, and the `flux2_agent` compatibility package now share
  `comic_agent.__version__` as the single `0.3.0` version source.
- Duplicate registrations of the existing AgentRun read routes were removed from the document and
  timeline routers. Public paths and the authoritative sanitized handlers are unchanged.

## 0.2.0

### Schema compatibility

- Added `PageSpecV1`, `ComicProductionRequestV1`, `ComicPanelProposalV1`,
  `ComicStoryboardProposalV1`, `ComicProductionManifestV1`, `ComicProductionRunV1`, and
  `ComicPageArtifactV1` at schema version `1.0`.
- `StoryboardRequest` and `WorkflowJob` defaulted to schema version `2.1` while accepting historical
  `2.0` payloads. The source text limit became 120,000 characters and a job may contain up
  to 120 independent panels, supporting 20 pages at 6 panels per page.
- Image workflow and queue Pydantic models moved to the canonical `comic_agent/schemas` package.
  `flux2_agent.models` remains a compatibility re-export.
- Runtime image result files reported schema version `2.1`.
- A root `Shot` may have no static references. This enables evidence-grounded text-only environment
  panels instead of injecting an unrelated character image merely to satisfy schema validation.

### Database compatibility

- Alembic migration `0009_comic_production_runs` adds the non-canonical production run table.
- The unique `(project_id, document_id, request_hash)` key makes repeated compile requests
  idempotent.
- No existing canonical StoryBible tables or evidence contracts are modified.

### Storage compatibility

- Runtime queue state remains under `queue/` and generated artifacts remain under `runs/`.
- The project never creates or writes a directory named `output`.
