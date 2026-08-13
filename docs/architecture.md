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
traceability, project-owned profile references, and plan-wide plus already-canonical
identity/temporal invariants before applying updates through the repository. Canonical
updates and the plan's `COMMITTED` transition share one repository unit of work: any
later constraint or persistence failure rolls the entire promotion back. Migration
`0004_storybible_resources` persists canonical profiles, states, relationships, world
rules, and candidate commit plans.

## Review Gate 1 Contract Boundary

The future source-quality path is `Import & Chunking -> Review Gate 1 -> Orchestrator /
ContextBuilder -> Narrative Analyst`. Gate 1 receives a bounded in-memory source snapshot and
the parsed document/chapter/chunk records. It checks deterministic encoding, checksum, scope,
order, range, duplicate, whitespace, and chunk usability rules. It does not interpret story
meaning, call a Provider, repair input, or write canonical data.

Only `ApprovedSourceChunkBundleV1.chunk_ids` may be routed downstream after an APPROVED result.
The bundle contains no text, storage URI, provider payload, or StoryBible data. This repository
currently implements only the Schema/JSON contract; Gate 1 service, Agent, API, Console,
Orchestrator wiring, automatic repair, and human-review persistence are not implemented.

## Review Gate 2 Contract Boundary

The future review path is `Narrative Analyst Proposal output -> Review Gate 2 -> Continuity
Timeline -> StoryBible Curator -> Review Gate 4 -> CommitService`. Review Gate 2 receives only
the bounded Proposal envelopes, AgentRun provenance, Evidence references, and allowed
SourceChunk ids defined by `ReviewGate2InputV1`. It produces auditable decision, issue, and
reference-resolution records plus an approved Proposal bundle only after complete review.

The currently implemented component is the Pydantic/JSON Schema contract only. No Review Agent,
automatic linker, database persistence, API endpoint, Console view, Timeline, StoryBible Curator,
or canonical write path is introduced. The contract explicitly forbids fuzzy/LLM reference
resolution and canonical writes; unresolved references remain unresolved unless a future bounded
review process records a valid decision.

## Startup Phase Boundary

This phase implements the source evidence chain, schema contracts, mock providers, API shell, database shell, docs, and tests. Full story compilation, image generation, QA repair loops, and frontend workflows are planned but not implemented.
