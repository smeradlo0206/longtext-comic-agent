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

## Campus Profile to Timeline boundary

The optional `campus_content_profile` Narrative mode emits only an evidence-backed candidate
`CampusContentProfileProposalV1` from supplied factual Claim proposals. It cannot create comic
beats, panels, images, StoryBible facts, or Timeline output. After Gate 2, the pure
`NarrativeTimelineInputAdapter` can explicitly convert an APPROVED bundle containing that Profile
into bounded `TimelineAnalysisInputV1` records. It validates bundle/profile/run identity and
SourceChunk evidence without Provider calls, repository scans, or writes. This is not a complete
manuscript-to-comic pipeline and requires no database migration.

## Startup Phase Boundary

This phase implements the source evidence chain, schema contracts, mock providers, API shell, database shell, docs, and tests. Full story compilation, image generation, QA repair loops, and frontend workflows are planned but not implemented.

## Narrative Analyst and automatic Gate 2

Narrative Analyst runs are persisted as bounded, resumable mode/window work. Each worker
uses only Gate 1 APPROVED source chunks and records AgentRun provenance, typed Proposal
outputs, and deterministic aggregation. Agents never write canonical StoryBible data.

After all leaf windows succeed, `NarrativeAnalysisReviewCoordinator` builds a caller-supplied
Gate 2 context and invokes deterministic `ReviewGate2Service`. Gate 2 persists an auditable
result and route (`APPROVED`, `REJECTED`, `NEEDS_HUMAN_REVIEW`, `FAILED`, or `NOT_READY`)
without mutating the run, Proposal, AgentRun, or Timeline artifacts. Only a fresh APPROVED
route exposes its typed approved Proposal bundle through the read-only API.
Stage B recovery is bounded and append-only. A recovery attempt is reserved by a persistent
idempotency key, consumes root/proposal/window budgets, and may rerun only the original mode,
leaf window, and Gate 1-approved source scope. Reservation, resume, and process restart are
safe to re-enter: one key yields at most one Provider call and one fresh AgentRun/Proposal
batch. Recovery writes only the non-canonical recovery-attempt audit table (Alembic migration
`0006_narrative_analysis_recovery_attempts`, after Timeline migration `0005`) and never writes
StoryBible or invokes CommitService.

### Structured Provider execution

Before a real source-bearing Narrative call, the configured provider/model may be probed with
only a fixed readiness request and a fixed Pydantic schema. The persisted capability profile
selects `STRICT_JSON_SCHEMA`, `JSON_OBJECT`, or `UNAVAILABLE`; it never stores an endpoint,
credential, prompt, source text, or raw response. `JSON_OBJECT_ONLY` remains the compatible
default, while `AUTO` prefers an explicitly proven strict schema path and `REQUIRE_STRICT`
stops before source text when strict support is unavailable. Provider usage and finish reason
are persisted only when reported; absent usage remains unavailable rather than becoming zero.

One `SCHEMA_VALIDATION_FAILED` attempt receives one source-preserving, rule-code-only format
repair. A second failure may split only the failed approved scope, first at SourceChunk boundaries
and then into non-overlapping slices of one approved SourceChunk. Budgets, lineage and
idempotency are persisted. When recovery cannot proceed, the window and root run become
`NEEDS_HUMAN_ACTION`; no aggregate, Gate 2, Timeline, StoryBible, or canonical write follows.
