# Schema Contracts

All V1 schemas use `schema_version = "1.0"` and live in `comic_agent/schemas`.

2026-07-28 update: this is an additive phase-one schema change. It adds
`AgentRunV1`, `ProviderResultV1`, `MockProviderResultV1`, `AgentInputRefV1`, and
`AgentOutputRefV1` for Mock Agent auditability without changing existing V1 field
semantics, so no `schema_version` bump or data migration is required.

2026-07-28 P0 hardening update: this tightens V1 draft validation without adding
new top-level story concepts. `ProviderResultV1` now rejects contradictory
success/error states and successful empty outputs. `AgentRunV1` now rejects
successful runs without source inputs or auditable outputs and failed runs without
an error message. `EvidenceRefV1` remains a field-format schema; CommitService is
responsible for checking that `quote_text` and `quote_start`/`quote_end` match the
referenced `SourceChunkV1.text`. This is a compatibility-impacting validation
tightening for malformed draft records, but it does not require a database
migration because no persisted canonical story data exists in phase one.

2026-07-28 P1 initial narrative semantics update: this keeps
`schema_version = "1.0"` because the change is an additive V1 draft expansion for
proposal-layer semantics. It adds `ClaimProposalV1` and
`KnowledgeStateProposalV1` as candidate outputs only; neither is canonical story
data, and `verification_status = CONFIRMED` still does not bypass CommitService.
`EventProposalV1` now includes `actor_resolution_status` and
`unresolved_actor_ref_id` so agents can distinguish `KNOWN`, `UNKNOWN`,
`UNRESOLVED`, `NOT_APPLICABLE`, and transitional `UNSPECIFIED` actor cases
without inventing Character ids. `UNSPECIFIED` preserves compatibility with old
draft payloads and may be removed or tightened in a later schema revision.

Validation impact: explicit `KNOWN` requires non-empty `participant_ids`;
explicit `UNKNOWN`, `UNRESOLVED`, and `NOT_APPLICABLE` reject invented
participants; `UNRESOLVED` requires an `unresolved_actor_ref_id`; `UNSPECIFIED`
does not force `participant_ids` but rejects `unresolved_actor_ref_id`. The new
claim and knowledge proposals require EvidenceRef lists, confidence in `[0, 1]`,
valid enums, no extra fields, and non-blank claim text. Database migration
impact: none. This does not add canonical story tables, database persistence,
Claim merge, KnowledgeState lifecycle management, `NarrativePerspectiveV1`, or
CommitService conflict arbitration.

2026-08-05 EventExtractionAgent output contract update: `event_extraction` now
returns `EventProposalBatchV1` as its stable outer proposal. The batch contains
1 or more `EventProposalV1` records in `events[]`, and batch-level
`proposal_id` duplication is rejected by schema validation. This changes the
agent/workflow output contract for event extraction but does not change
`EventProposalV1` fields or require a database migration. Older AgentRun payloads
with a single `EventProposalV1` remain readable by evidence audit APIs.

| Schema | Purpose | Required Fields | Evidence | Readers | Proposal Producer | Canonical Commit |
| --- | --- | --- | --- | --- | --- | --- |
| BaseRecordV1 | Common record metadata. | id, project_id, revision, status, timestamps, created_by | N/A | Services | Services | CommitService |
| EvidenceRefV1 | Source traceability pointer. Pydantic validates field shape only; CommitService validates quote/range against SourceChunk text. | chunk_id | Optional range/quote | All story agents | All story agents | CommitService validates chunk existence and quote authenticity |
| ProjectSpecV1 | Project policy. | id, name, type, fidelity flags | N/A | All services | API/user | SourceRepository |
| SourceDocumentV1 | Source file metadata. | document_id, project_id, checksum, storage_uri | N/A | Importer, agents | DocumentParser | SourceRepository |
| SourceChapterV1 | Chapter boundary. | chapter_id, document_id, order | N/A | Agents, API | DocumentParser | SourceRepository |
| SourceChunkV1 | Evidence atom. | chunk_id, document_id, chapter_id, text, checksum | Self | All agents | DocumentParser | SourceRepository |
| EntityProposalV1 | Candidate entity. | proposal_id, type, name, evidence_refs, confidence | Required | Merge services | Entity agents | CommitService later |
| EventProposalV1 | Candidate event, including explicit actor-resolution state. | proposal_id, type, non-empty summary, non-empty evidence_refs, confidence | At least one reference required; persisted with CANDIDATE status | Temporal/state agents | Event agent | CommitService later |
| EventProposalBatchV1 | Stable event-extraction outer proposal containing source-ordered events. | batch_id, events | Required through each event | Timeline, temporal/state agents, review UI | Event agent | CommitService validates each event later |
| ClaimProposalV1 | Candidate assertion, denial, accusation, hypothesis, memory, interpretation, or prediction. | proposal_id, claim_type, claim_text, source_type, verification_status, evidence_refs, confidence, reality_layer | Required | CommitService, review, knowledge agents | Claim/knowledge agents | CommitService later |
| KnowledgeStateProposalV1 | Candidate character knowledge or belief state. | proposal_id, character_id, knowledge_target_id, epistemic_status, reality_layer, evidence_refs, confidence | Required | Dialogue, panel, review, knowledge agents | Knowledge agents | CommitService later |
| TemporalRelationProposalV1 | Candidate event relation. | proposal_id, source, target, relation, confidence | Required unless UNKNOWN | Temporal solver | Temporal agent | CommitService later |
| StateChangeProposalV1 | Candidate state mutation. | proposal_id, event_id, target, path, evidence_refs | Required | State compiler | State agent | CommitService later |
| AgentInputRefV1 | Bounded object passed into an AgentRun. | object_id, object_schema, role | In referenced object if applicable | Workflow, audit | Agent wrapper | N/A |
| AgentOutputRefV1 | Structured object produced by an AgentRun. | object_id, object_schema, role | In output object if applicable | Workflow, audit | Agent wrapper | N/A |
| CharacterStateV1 | Compiled character state. | state_id, character_id, reality_layer | Derived from changes | Story/visual agents | State compiler | CommitService later |
| SceneSpecV1 | Source-grounded scene. | scene_id, chapter_id, chunks, layer, purpose | Via chunks | Translation agents | Narrative translator | CommitService later |
| StoryBeatV1 | Adaptation beat. | beat_id, scene_id, chunks, meaning, visual_expression | Via chunks | Page/panel agents | Narrative translator | CommitService later |
| PanelSpecV1 | Provider-neutral panel plan. | panel_id, page_id, scene_id, chunks, shot fields | Via chunks | Prompt compiler | Panel director | CommitService later |
| QAResultV1 | Quality check result. | qa_result_id, target, scores, passed | Target-dependent | Repair planner | QA agents | QA service |
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

StoryBible identifiers are limited to 128 characters and canonical/alias names to 255
characters. These Pydantic constraints match the `VARCHAR(128)` and `VARCHAR(255)`
persistence boundaries so invalid provider output is rejected before a database write.
`StoryBibleUpdateV1` is exported as its own JSON Schema union alongside the concrete
update models.

`CommitService` is the only canonical owner: it validates evidence and plan-wide
invariants, persists the candidate plan, applies valid updates idempotently through the
repository, and marks the plan committed. Agents emit proposals only and cannot write
canonical StoryBible facts directly.

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

| AgentRunV1 | One auditable agent execution. Successful runs require source input chunks and at least one output proposal or provider result; failed runs require error_message. | agent_run_id, project_id, agent_name, input_chunk_ids, output_schema, status | Output Proposal carries evidence | Workflow, audit, QA | Agent wrapper | N/A |
| ProviderResultV1 | One provider call result. Success requires raw_output or structured_output and forbids error_message; failure requires error_message. | provider_result_id, provider_name, provider_type, output_schema, success | Structured output carries evidence if any | AgentRun, audit | Provider adapter | N/A |
| MockProviderResultV1 | Mock provider result specialization using ProviderResultV1 consistency rules. | provider_result_id, output_schema, success | Structured output carries evidence if any | Tests, AgentRun, audit | Mock provider | N/A |

Field types are implemented directly in Pydantic. The JSON Schema export script is the authoritative machine-readable contract.

## P0 Evidence Authenticity

`EvidenceRefV1` can be constructed with only `chunk_id`, with `quote_text`, with
`quote_start`/`quote_end`, or with both range and quote. Pydantic only checks that
range fields are a valid pair and that `quote_text` is not blank. CommitService
performs repository-aware checks:

- `chunk_id` only: referenced chunk must exist.
- `quote_text` only: quote must appear in `SourceChunkV1.text`.
- range only: range must satisfy `0 <= quote_start < quote_end <= len(text)`.
- range plus quote: `text[quote_start:quote_end]` must equal `quote_text`.

Project-level cross-use of chunks is not yet enforced by the evidence schema
because phase-one proposals do not carry a project id. Services that validate
project context must do so before or inside CommitService in a later hardening
pass.

## P0 Workflow Consistency

Provider results and agent runs are audit records, not canonical story facts.
They still must be internally coherent:

- A successful provider result must include `raw_output` or `structured_output`.
- A successful provider result must not include `error_message`.
- A failed provider result must include `error_message`.
- A successful agent run must include at least one `input_chunk_id`.
- A successful agent run must include `output_proposal_ids`, `provider_result_id`,
  or inline `provider_result`.
- A failed agent run may have no outputs, but it must include `error_message`.

This update introduces `ClaimProposalV1` and `KnowledgeStateProposalV1` only as
proposal schemas. It still does not introduce canonical `ClaimV1`,
`KnowledgeStateV1`, `ObjectStateV1`, `FactLockV1`, `CausalRelationV1`, or a
complete StoryBible.
