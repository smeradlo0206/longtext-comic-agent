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
| TemporalRelationProposalV1 | Candidate event relation. | proposal_id, source, target, relation, confidence | Required unless UNKNOWN | Temporal solver | Temporal agent | CommitService later |
| StateChangeProposalV1 | Candidate state mutation. | proposal_id, event_id, target, path, evidence_refs | Required | State compiler | State agent | CommitService later |
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

### 2026-08-09 V1 contract hardening and migration note

The StoryBible contracts remain at `schema_version = "1.0"` because this correction is
part of the initial, unreleased V1 feature branch required by the implementation plan.
The accepted input domain is tightened only for identifiers longer than 128 characters
and names longer than 255 characters, values the existing `0004_storybible_resources`
columns could not portably store. No Alembic data migration is required: migration
`0004` already defines the matching database lengths, and no column or stored-payload
shape changed.

### StoryBible curation completion note (pre-release V1)

The StoryBible contracts stay at `schema_version = "1.0"`; this wave completes the
curator behavior without changing stored resource shapes, so no new Alembic revision
is required.

- `CommitPlanV1.content_hash` is now optional on input. The curator and the curation
  API always replace it with a deterministic SHA-256 hash of the plan content,
  excluding the plan-identity fields (`content_hash`, `commit_plan_id`,
  `source_proposal_id`). Candidate plans therefore persist a server-owned idempotency
  key: replaying identical updates reuses the stored candidate instead of creating a
  duplicate, and a provider-chosen key can no longer collide or be forged. The
  `(project_id, content_hash)` unique constraint from `0004_storybible_resources` is
  unchanged.
- The curator deterministically derives story orders from the confirmed
  `TemporalRelationProposalV1` BEFORE/AFTER chains in `StoryBibleContextV1` and fills
  missing `valid_from_order` / `valid_until_order` on state and relationship updates
  before the candidate plan is returned. `valid_until_order` uses the until event's
  order minus one so consecutively anchored states do not overlap on the shared
  boundary. Cyclic or unordered events keep their order fields unset.
- Drafts whose `confidence` is below the curator's `confidence_threshold` (0.7) are
  returned with an added blocking `LOW_CONFIDENCE` conflict; they remain CANDIDATE and
  still require explicit approval before any canonical write.
- The curator's output contract now instructs and validates all four update kinds
  (profile, state, relationship, world rule) plus structured `ConflictV1` entries, so
  the model can emit the full design-mandated output instead of only profile and state
  updates.
- Bounded context caps were separated: source chunks stay at 3, while the reviewed
  upstream proposal lists (entity, event, state-change, temporal-relation) may carry
  up to 20 records each so the curator sees a whole analysis batch instead of three
  arbitrarily truncated proposals.
