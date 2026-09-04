# Schema Contracts

All V1 schemas use `schema_version = "1.0"` and live in `comic_agent/schemas`.

| Schema | Purpose | Required Fields | Evidence | Readers | Proposal Producer | Canonical Commit |
| --- | --- | --- | --- | --- | --- | --- |
| BaseRecordV1 | Common record metadata. | id, project_id, revision, status, timestamps, created_by | N/A | Services | Services | CommitService |
| EvidenceRefV1 | Source traceability pointer. | chunk_id | Optional range/quote; supplied values must match the referenced chunk | All story agents | All story agents | CommitService validates |
| ProjectSpecV1 | Project policy. | id, name, type, fidelity flags | N/A | All services | API/user | SourceRepository |
| SourceDocumentV1 | Source file metadata. | document_id, project_id, checksum, storage_uri | N/A | Importer, agents | DocumentParser | SourceRepository |
| SourceChapterV1 | Chapter boundary. | chapter_id, document_id, order | N/A | Agents, API | DocumentParser | SourceRepository |
| SourceChunkV1 | Evidence atom. | chunk_id, document_id, chapter_id, text, checksum | Self | All agents | DocumentParser | SourceRepository |
| EntityProposalV1 | Candidate entity. | proposal_id, type, name, evidence_refs, confidence | Required | Merge services | Entity agents | CommitService later |
| EventProposalV1 | Candidate event. | proposal_id, type, non-empty summary, non-empty evidence_refs, confidence | At least one reference required; persisted with CANDIDATE status | Temporal/state agents | Event agent | CommitService later |
| ClaimProposalV1 | Candidate assertion, separate from confirmed events. | claim_id, subject, predicate, value, evidence_refs, confidence | At least one reference required | Timeline/StoryBible agents | Claim agent | CommitService later |
| CampusContentProfileProposalV1 | Candidate campus-publication adaptation profile. | project_id, content type, audience, factual claim ids, tone, page budget, evidence | Required | Gate 2 and explicit Timeline adapter | Campus Profile Agent | Never in this phase |
| ComicBeatProposalV1 | Candidate future comic narrative beat, not a panel. | profile id, beat index, purpose, fact ids, visual constraints, evidence | Required | Future Gate 3 only | Not produced in this phase | Never in this phase |
| TemporalRelationProposalV1 | Candidate event relation. | proposal_id, source, target, relation, confidence | Required unless UNKNOWN | Temporal solver | Temporal agent | CommitService later |
| TimelineAnalysisInputV1 | Whole-text timeline analysis input. | project_id plus event, claim, or state-change proposals | At least one input evidence reference | Timeline agent | Context builder | N/A |
| TimelineAnalysisProposalV1 | Candidate time relations, conflicts, and duplicates. | proposal_id, project_id, evidence_refs, confidence | Never canonical; derived evidence only | StoryBible review | Timeline agent | CommitService later |
| StateChangeProposalV1 | Candidate state mutation. | proposal_id, event_id, target, path, evidence_refs | Required | State compiler | State agent | CommitService later |
| CharacterStateV1 | Compiled character state. | state_id, character_id, reality_layer | Derived from changes | Story/visual agents | State compiler | CommitService later |
| SceneSpecV1 | Source-grounded scene. | scene_id, chapter_id, chunks, layer, purpose | Via chunks | Translation agents | Narrative translator | CommitService later |
| StoryBeatV1 | Adaptation beat. | beat_id, scene_id, chunks, meaning, visual_expression | Via chunks | Page/panel agents | Narrative translator | CommitService later |
| PanelSpecV1 | Provider-neutral panel plan. | panel_id, page_id, scene_id, chunks, shot fields | Via chunks | Prompt compiler | Panel director | CommitService later |
| QAResultV1 | Quality check result. | qa_result_id, target, scores, passed | Target-dependent | Repair planner | QA agents | QA service |
| PanelTextQAProposalV1 | Proposal-only pre-render comparison of PanelPlan facts against trusted source text. | proposal_id, project_id, checked panel ids, evidence, passed | Required input evidence allowlist | Image production gate | PanelTextQAAgent | Never |
| RepairPlanV1 | Repair instruction. | repair_plan_id, target_id, type, instruction | Target-dependent | Repair executor | Repair planner | Repair service |
| AgentRunV1 | Immutable record of one agent execution. | run id, project, input chunk, agent, status | Links one input chunk to an optional output proposal | API, audit services | Agent runner | N/A |

Field types are implemented directly in Pydantic. The JSON Schema export script is the authoritative machine-readable contract.

## StoryBible Contracts and Compatibility

The StoryBible is an additive set of public `schema_version = "1.0"` contracts. Its
canonical resource types are `StoryEntityProfileV1`, `StoryEntityStateV1`,
`StoryRelationshipV1`, and `WorldRuleV1`. Every canonical resource carries
project ownership, revision, canonical status, and one or more `EvidenceRefV1` values.
States and relationships additionally record a valid story-time interval.

`ProfileUpdateProposalV1`, `StateUpdateProposalV1`,
`RelationshipUpdateProposalV1`, and `WorldRuleUpdateProposalV1` are the candidate
updates collected by `StoryBibleUpdateV1`. `ConflictV1` records reviewable conflicts;
`CommitPlanV1` is the reviewed, evidence-backed plan eligible for promotion; and
`StoryBibleCuratorProposalV1` is the candidate-only curator result. `StoryBibleContextV1`
is the bounded input contract for that curator.

`StoryBibleContextV1` now writes schema version `1.1` and accepts historical `1.0` payloads.
The trusted `source_chunk_ids` ceiling increases from three to eight so a short whole document
split into several evidence chunks is not rejected before curation. Contexts above eight chunks
still fail before a Provider call and are never truncated. This changes only the existing JSON
payload contract; no database migration is required.

StoryBible identifiers are limited to 128 characters and canonical/alias names to 255
characters. These Pydantic constraints match the `VARCHAR(128)` and `VARCHAR(255)`
persistence boundaries so invalid provider output is rejected before a database write.
`StoryBibleUpdateV1` is exported as its own JSON Schema union alongside the concrete
update models.

`CommitService` is the only canonical owner: it validates evidence and plan-wide
invariants, persists the candidate plan, applies valid updates idempotently through the
repository, and marks the plan committed. Agents emit proposals only and cannot write
canonical StoryBible facts directly.

StoryBible output normalization resolves a quote-only `EvidenceRefV1` to the first exact
occurrence inside its explicitly named trusted source chunk. This is deterministic even when the
same exact quote appears more than once; missing, altered, cross-project, or out-of-scope quotes
remain rejected. Provider-supplied spans are still checked byte-for-byte against source text.

Commit validation is seeded with the project's existing canonical profiles and states.
This prevents later plans from introducing duplicate identities or incompatible
overlapping state values. State and relationship profile references must resolve either
to a project-owned canonical profile or to a profile created in the same plan. All
canonical writes and the committed-plan status transition occur in one transaction.

The contracts remain backward-compatible additions to existing V1 schemas. The
corresponding persistence migration is `0004_storybible_resources`; it adds the
canonical StoryBible resource tables and candidate commit-plan storage. The Pydantic
models in `comic_agent/schemas` remain the only schema source of truth, and the JSON
Schema export script produces the machine-readable contracts.

### 2026-08-09 V1 contract hardening and migration note

The StoryBible contracts remain at `schema_version = "1.0"` because this correction is
part of the initial, unreleased V1 feature branch required by the implementation plan.
The accepted input domain is tightened only for identifiers longer than 128 characters
and names longer than 255 characters, values the existing `0004_storybible_resources`
columns could not portably store. No Alembic data migration is required: migration
`0004` already defines the matching database lengths, and no column or stored-payload
shape changed.

### 2026-08-15 TimelineAgent V2 compatibility and migration note

`TimelineAnalysisInputV1`, `TimelineAnalysisProposalV1`, and
`TemporalRelationProposalV1` now default to `schema_version = "1.1"` while accepting
the prior `"1.0"` payloads. V2 adds the optional input `mode` (`RULES_ONLY` remains the
default) and an optional short `reasoning_summary` on a temporal-relation candidate.
LLM mode emits only reviewable candidate relations, never canonical StoryBible data.

### Campus content Profile and approved Timeline adapter

`CampusContentProfileProposalV1` and `ComicBeatProposalV1` are new exported v1.0 Proposal
contracts. A Profile has a 1–24 page budget and unique factual `ClaimProposalV1.claim_id` values.
ComicBeat is only a future narrative-beat contract: it is neither a panel nor an image/provider prompt.

`NarrativeAnalysisResultV1` v1.5 adds compatible `campus_content_profiles`; v1.0–v1.4 remain
readable with that list empty. `TimelineAnalysisInputV1` v1.2 records the approved bundle, review
run, and Profile ids when built by the explicit adapter; v1.0/v1.1 inputs remain readable. The
adapter accepts only an APPROVED Gate 2 bundle, validates bounded SourceChunk evidence, retains
Profile-required factual Claims, and never accepts a raw aggregate, calls a Provider, writes
canonical data, or automatically runs Timeline. No database migration is required. This phase does
not implement SceneContext, beat generation, panels, images, materials, Gate 3/4, or full conversion.

### Narrative Analyst automatic Gate 2

`NarrativeAnalysisRunV1`, `NarrativeAnalysisWindowV1`, and the six typed Proposal families
are the source-of-truth contracts for bounded whole-document analysis. Gate 1-approved
chunk ids and AgentRun provenance are explicit review context; no service expands that scope
(`NarrativeAnalysisWindowV1` v1.9 adds backward-compatible persisted INITIAL,
LENGTH_RECOVERY, SCHEMA_REPAIR, SPLIT_CHILD, and TERMINAL budget phases, plus separate
length/schema repair counters and source-free terminal reasons. It uses the existing JSON
payload and requires no database migration.)
or resolves references implicitly.
`EventProposalBatchV1` v1.1 keeps v1.0 readable and permits `events=[]` only for a bounded
scope with no independently auditable event. This prevents a Provider from inventing an Event
solely to satisfy a non-empty array rule; an empty batch remains non-canonical and still passes
through the normal aggregate and Gate 2 boundary.
`ProviderCapabilityProfileV1` v1.1 adds an optional, source-free capability record for each
concrete Narrative Proposal batch Schema; v1.0 capability payloads remain readable and fall
back to their existing provider/model-wide selected mode.
`ReviewGate2ResultV1` and
`NarrativeAnalysisReviewRouteV1` persist the fresh automatic decision. APPROVED carries the
typed `ApprovedProposalBundleV1`; REJECTED carries only sanitized issue summaries;
NEEDS_HUMAN_REVIEW carries held Proposal ids; FAILED carries sanitized execution diagnostics;
NOT_READY carries no review artifact. Historical run and Proposal payload versions remain
readable. `NarrativeAnalysisRunV1` v1.7 adds source-free `pipeline_phase` and
`pipeline_safe_issue_codes` fields for asynchronous Console polling. Existing v1.0-v1.6
run payloads remain readable with `QUEUED` and an empty issue-code list. No database
migration is required because these fields remain in the existing JSON payload container.
Stage B `RecoveryAttemptV1` is an append-only, non-canonical audit contract. Its directive
locks the original mode, leaf window, approved source scope, and AgentRun provenance; its
budget records root/proposal/window counts, tokens, and time. A persistent idempotency key
allows at most one reserved/running recovery execution across re-entry,
resume, or restart. Fresh Gate 2 artifacts are never written over the original REJECTED run,
and only a fresh APPROVED recovery route may be returned by the recovery bundle endpoint.
`RecoveryDirectiveV1` v1.2 additionally records the reserved number of Provider calls for
that fixed scope: one verbatim-evidence correction and, only after a structural failure, one
same-scope JSON-format correction. Earlier v1.0-v1.1 directives remain readable and default
to one call. This remains JSON-payload compatibility only; no database migration is required.

Stage B recovery uses Alembic migration `0006_narrative_analysis_recovery_attempts`,
downstream of Timeline migration `0005_timeline_analysis_proposals`. Its persistent
idempotency key is strengthened in application code to include evidence text, prompt,
agent version, and provider model before any LLM call.

### 2026-08-22 Parallel Narrative reference compatibility and migration note

`ProposalMentionRefV1` is a new exported, source-first reference contract. Event v1.1
adds `participant_mentions` and `location_mention`; Claim v1.3 adds `source_reference`
and `target_event_reference`. The original `participant_ids`, `location_id`, `source_id`,
and `target_event_id` remain hard internal Proposal links only. Historical Event v1.0 and
Claim v1.0–v1.2 payloads remain readable.

Because the six Narrative modes execute independently, a provider-local name such as
`Lin` cannot be assumed to equal an EntityProposal id selected by another mode. During
aggregation, legacy values that do not name an aggregate Proposal become unresolved
mention references; source AgentRun payloads are not overwritten. Gate 2 performs only
exact unique, reality-compatible linking and records its decision. Ambiguous or unmatched
mentions stay nonblocking and unresolved; no fuzzy matching, LLM linking, or canonical
write occurs. The Timeline adapter materializes only Gate 2 `RESOLVED` entity links in
its separate input copy. This is an additive JSON-payload change and needs no database
migration.

### 2026-08-22 Timeline execution diagnostics compatibility and migration note

`TimelineGate3RunV1` v1.1 adds optional, source-free `failure_category` and
`safe_issue_codes` fields for a Timeline Provider execution failure. v1.0 payloads remain
readable, and no Alembic migration is needed because the run is stored in its existing JSON
payload. For downstream status only, the Pipeline selects the newest fresh Gate 2 APPROVED
recovery route with a bundle; a later separate rejected or failed recovery attempt does not
hide that approved bundle's Timeline run. The original root Gate 2 route remains unchanged
for audit, and no route can bypass Gate 2, Gate 3, or write canonical data.

### 2026-08-22 Timeline pair inference hardening and migration note

`TimelinePairInferenceV1` v1.0 is the Provider-facing contract for one ordered event pair.
It contains only the temporal relation, indexes into an input EvidenceRef allowlist,
confidence, and a short summary. Proposal ids, event ids, EvidenceRef values, quotes, and
offsets are materialized deterministically by `TimelineAgent`; the Provider cannot invent
them. One schema-only repair is allowed with source-free field paths and rule codes.

`TimelineGate3RunV1` now writes v1.2 and may contain typed
`TimelineProviderDiagnosticsV1`; historical v1.0/v1.1 JSON payloads remain readable. No
database migration is required because the new optional fields remain in the existing run
payload. Gate 3 and downstream access remain blocked after any terminal Timeline failure.

### 2026-09-02 Timeline pair relation compatibility and migration note

`TimelinePairInferenceV1.schema_version` advances to `1.1` while continuing to read `1.0`.
Its Provider-facing `relation` enum now contains only the five relations implemented by
TimelineAgent V2 (`BEFORE`, `AFTER`, `OVERLAPS`, `SIMULTANEOUS`, and `UNKNOWN`). Older `1.0`
responses using those values remain readable. `DURING` and `CONTAINS` were never accepted by
TimelineAgent V2 and are now rejected at the Provider schema boundary, where the existing bounded
repair can handle them. No database migration is required because Timeline inference responses are
not stored in a dedicated table and Timeline run payloads already use JSON storage.
