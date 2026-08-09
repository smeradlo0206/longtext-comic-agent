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

`ContextBuilder` is the agent read boundary. It creates bounded, project-scoped context
from selected source proposals and existing StoryBible resources; it does not expose a
whole-database read to agents. `StoryBibleRepository` keeps retrieval project-scoped,
including profile lookup, state-at-event lookup, and related state/relationship retrieval.
The API rejects path/body or nested-resource project mismatches before curation.

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
traceability and commit-plan invariants before applying updates through the repository.
Migration `0004_storybible_resources` persists canonical profiles, states, relationships,
world rules, and candidate commit plans.

## Startup Phase Boundary

This phase implements the source evidence chain, schema contracts, mock providers, API shell, database shell, docs, and tests. Full story compilation, image generation, QA repair loops, and frontend workflows are planned but not implemented.
