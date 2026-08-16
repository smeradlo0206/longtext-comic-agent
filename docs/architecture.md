# Architecture

## Principles

The system separates semantic judgment from deterministic state control. Agents read bounded context and produce schema-validated proposals. Normal services validate, version, persist, and commit canonical data.

## Components

- FastAPI exposes project, document import, chapter, chunk, and health endpoints.
- Pydantic schemas in `comic_agent/schemas` define all agent/service contracts.
- SQLAlchemy stores formal ids, status, version, relations, timestamps, and JSON payloads.
- PostgreSQL is the production fact source; SQLite is used only for unit tests.
- Redis, MinIO, and pgvector are reserved in infrastructure for workflow state, object storage, and later retrieval.
- Provider interfaces isolate all LLM and image model calls.

## Data Flow

TXT upload is parsed into `SourceDocumentV1`, `SourceChapterV1`, and `SourceChunkV1`. Chunks become the evidence anchor for proposals. Story proposals cannot become canonical without `CommitService` evidence validation.

## StoryBible Curation Boundary

The StoryBible Curator is proposal-only. It receives a `StoryBibleContextV1` and returns
a schema-valid `StoryBibleCuratorProposalV1` with a candidate `CommitPlanV1`, conflicts,
confidence, and evidence references. It neither owns repositories nor writes canonical
story data. Its default configured model is `deepseek-v4-pro`, accessed only through the
provider interface.

Provider output is only a draft. The curator then applies deterministic post-processing
before returning the candidate: it stamps state and relationship intervals with the
event orders the timeline agent supplied in the context (`event_orders`, consumed —
never derived), replaces any provider-chosen commit-plan content hash with a
deterministic SHA-256 content hash, and adds a blocking `LOW_CONFIDENCE` conflict when
the draft confidence is below the curator's threshold. The plan-identity fields
(`commit_plan_id`, `source_proposal_id`) are excluded from the content hash, so an
identical-content replay reuses the stored candidate plan instead of duplicating it.

StoryBible curation is scoped to an effective-from state library: the curator
consolidates the reviewed upstream narrative-analysis proposals (entity, event,
state-change) into profile, state, relationship, and world-rule updates. Every state
is effective from its anchoring event onward and persists across chapter imports, so
facts established in earlier chapters stay visible in later ones even when the new
text never mentions them. The parallel timeline agent owns event ordering; the
curator consumes it through `event_orders` only.

`ContextBuilder` is the agent read boundary. It creates bounded, project-scoped context
from selected source proposals and existing StoryBible resources; it does not expose a
whole-database read to agents. `StoryBibleRepository` keeps retrieval project-scoped,
including profile lookup, state-at-event lookup, and related state/relationship retrieval.
The API rejects path/body or nested-resource project mismatches before curation.

The deterministic snapshot boundary is `GET /projects/{project_id}/storybible/state-at`:
it folds every in-effect state interval at the requested timeline event order into one
merged view per profile (grouped into characters, locations, organizations) plus active
relationships and world rules. This is the join point where the storyboard agent later
combines StoryBible state with narrative-analysis and timeline output.

The proposed-to-canonical flow is:

```text
bounded project context
-> StoryBible Curator candidate proposal
-> evidence and invariant validation
-> reviewed CommitPlanV1
-> CommitService
-> idempotent canonical StoryBible resources
```

`CommitService` is the sole canonical write boundary. It validates `EvidenceRefV1`
traceability, project-owned profile references, and plan-wide plus already-canonical
identity/temporal invariants before applying updates through the repository. Canonical
updates and the plan's `COMMITTED` transition share one repository unit of work: any
later constraint or persistence failure rolls the entire promotion back. Migration
`0004_storybible_resources` persists canonical profiles, states, relationships, world
rules, and candidate commit plans.

## Startup Phase Boundary

This phase implements the source evidence chain, schema contracts, mock providers, API shell, database shell, docs, and tests. Full story compilation, image generation, QA repair loops, and frontend workflows are planned but not implemented.
