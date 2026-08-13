# Schema Contracts

V1 schemas live in `comic_agent/schemas`. Most phase-one schemas still use
`schema_version = "1.0"`; explicitly noted proposal-layer contracts, such as
Claim v1.1 and v1.2, may add versioned output compatibility rules.

2026-07-28 update: this is an additive phase-one schema change. It adds
`AgentRunV1`, `ProviderResultV1`, `MockProviderResultV1`, `AgentInputRefV1`, and
`AgentOutputRefV1` for Mock Agent auditability without changing existing V1 field
semantics, so no `schema_version` bump or data migration is required.

2026-08-09 Knowledge State extraction update: `knowledge_state_extraction`
returns `KnowledgeStateProposalBatchV1`; `states=[]` is a valid successful
batch, while every nonempty v1.1 state still requires `EvidenceRefV1`.
Subjects, targets, and temporal anchors may remain explicitly unresolved and
the schema does not verify that an optional Proposal id exists; linking and
review own that responsibility. Whole-document result payloads add compatible
`knowledge_states`, and older v1.0 results missing that field deserialize as an
empty list. 无需数据库迁移：新增字段仅出现在兼容的 Schema/JSON 聚合结果中，旧 v1.0 payload 继续可读。

KnowledgeState batch hardening: `KnowledgeStateProposalBatchV1` rejects both a
repeated `proposal_id` and a repeated full v1.1 semantic state in the same
batch. This is a malformed new-output validation tightening, not a rewrite of
historical Proposal ids. Conservative aggregation additionally retains distinct
candidates when target text, basis, resolution state, or temporal anchors differ;
it does not use fuzzy matching to decide whether two target texts mean the same
thing.

2026-08-09 Knowledge State attitude-target hardening: fresh v1.1
`KnowledgeStateProposalV1` outputs with `BELIEVES`, `SUSPECTS`, or
`DISBELIEVES` must target the content proposition as `WORLD_FACT` or `EVENT`;
they cannot target a `CLAIM` such as a rumor or statement. This is a
compatibility-impacting validation tightening for malformed new v1.1 drafts, not
a field addition, so the v1.1 schema version and legacy v1.0 read compatibility
remain unchanged. No database migration is required: proposal and whole-document
results remain JSON payloads and no canonical story data is rewritten.

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

2026-08-05 Entity/Claim batch output contract update: `entity_extraction` now
returns `EntityProposalBatchV1` and `claim_extraction` now returns
`ClaimProposalBatchV1` as stable outer proposals. The batch schemas add
non-empty `entities[]` / `claims[]` collections and reject duplicate item
`proposal_id` values. This changes the NarrativeAnalyst mode output contract but
does not change `EntityProposalV1` or `ClaimProposalV1` fields and does not
require a database migration. AgentRun and evidence audit APIs now enumerate all
proposal ids from `events[]`, `entities[]`, or `claims[]`.

2026-08-06 Claim semantic classification update: new `claim_extraction` outputs
use `ClaimProposalV1.schema_version = "1.1"` inside
`ClaimProposalBatchV1.schema_version = "1.1"`. V1.1 replaces the broad
`ASSERTION` output category with `FACTUAL_ASSERTION`, `BELIEF`, `HYPOTHESIS`,
`DENIAL`, `ACCUSATION`, `MEMORY`, `INTERPRETATION`, `PREDICTION`, and
`COMMITMENT`, and adds required `temporal_scope` values `PAST`, `PRESENT`,
`FUTURE`, or `ATEMPORAL`. Historical `schema_version = "1.0"` claim and claim
 batch payloads remain readable, including legacy `ASSERTION` with
 `temporal_scope = null`. V1.1 rejects `ASSERTION` and requires every batch item
 to also be v1.1. This is a proposal-layer output contract change and requires
 no database migration.

2026-08-06 Claim semantic-boundary update: fresh claim-extraction output now uses
`ClaimProposalV1.schema_version = "1.2"` inside
`ClaimProposalBatchV1.schema_version = "1.2"`. V1.2 adds `EVALUATION` for
source-grounded quality, strength, difficulty, or value judgements, and makes the
classification priority explicit: an uncertainty hedge is `HYPOTHESIS`; an
explicit unhedged mental stance is `BELIEF`; an evaluative judgement is
`EVALUATION`; a causal, motive, or meaning explanation is `INTERPRETATION`; only
then can a direct unhedged statement be `FACTUAL_ASSERTION`. Historical v1.0 and
v1.1 claim and batch payloads remain readable. V1.2 batches require all contained
claims to be v1.2, and `EVALUATION` is rejected for earlier versions. This is a
proposal-layer output contract change and requires no database migration.

2026-08-07 Entity taxonomy update: fresh `EntityProposalV1` and
`EntityProposalBatchV1` outputs use `schema_version = "1.1"`. V1.1 has the
closed entity taxonomy `CHARACTER`, `CREATURE`, `LOCATION`, `ORGANIZATION`,
`OBJECT`, `ABILITY`, and `CONCEPT`, plus optional `CreatureSubtype` values
`ANIMAL`, `MONSTER`, `SPIRIT_BEAST`, and `OTHER`. `creature_subtype` is allowed
only for `CREATURE`; a missing subtype is valid when the source cannot support a
classification. Historical v1.0 Entity and EntityBatch payloads remain readable
with their prior entity type values. V1.1 rejects legacy or unknown entity types.
This is a proposal-layer output contract change.

2026-08-07 Whole-document analysis update: `NarrativeAnalysisRunV1`,
`NarrativeAnalysisWindowV1`, and `NarrativeAnalysisResultV1` define typed,
auditable task, window, and conservative aggregation contracts. Results retain
their originating AgentRun ids and EvidenceRef values. Persistence adds the
`narrative_analysis_runs` and `narrative_analysis_windows` tables. This is an
additive database migration: no existing table, canonical data, or StoryBible
record is transformed.

2026-08-08 Whole-document window diagnostics and retry update:
`NarrativeAnalysisWindowV1` now writes `schema_version = "1.3"` and includes
optional `failure_category`, `recommended_action`, and
`provider_error_diagnostics`, plus `attempt_count`,
`effective_max_chars_per_chunk`, and `previous_failure_category`. Schema
validation diagnostics use only error kind, schema field paths, and expected
output schema. Provider diagnostics are restricted by the provider-summary
allowlist and never carry provider response content, source text, quote text,
or credentials. Historical v1.0, v1.1, and v1.2 window payloads remain readable;
missing retry fields default safely. Existing window records store their schema
payload in the current JSON column, so this additive audit-field change requires
no SQL migration or canonical-data transformation.

2026-08-09 whole-document reliability hardening: no proposal or workflow schema
changed. Provider diagnostics continue to expose only allowlisted values. The
provider may retry one transient `429` or `5xx` response. A multi-SourceChunk
window that fails with `PROVIDER_LENGTH_BEFORE_FINAL_CONTENT` is now recorded as
`SPLIT` and recovered as deterministic one-SourceChunk child windows, preserving
the complete text and audit boundary of each source chunk. A singleton window
retains one bounded input-budget retry; schema validation still retries once at
the same budget. This additive runtime status and recovery behavior requires no
database migration or canonical-data transformation; historical window payloads
remain readable.

2026-08-12 overlap ownership and State Change recovery hardening:
`NarrativeAnalysisWindowPlanV1` and `NarrativeAnalysisWindowV1` fresh payloads use
`schema_version="1.4"`. Every planned leaf deterministically owns the first source
chunks not already owned by an earlier leaf; `chunk_ids` remain the full context and
`owned_chunk_ids` are the only chunks whose proposals may enter whole-document
aggregation. Historical v1.0-v1.3 windows without ownership fields remain readable by
falling back to their context chunk ids. Length-failed parents retain `SPLIT` status and
create children only for parent-owned chunks, with parent/child lineage and a sanitized
split reason. Evidence ownership is determined by the first `new_value_evidence_indexes`
reference; no fuzzy merge or part-whole resolution is performed.

State Change schema recovery exposes only stable rule codes (for example,
`STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER`) and uses a fixed source-free correction
marker. Quantity values must be JSON numbers; the worker never coerces, drops, or repairs
invalid proposals. No raw provider response or source text is persisted in diagnostics.
These additive JSON payload fields require no database migration.

| Schema | Purpose | Required Fields | Evidence | Readers | Proposal Producer | Canonical Commit |
| --- | --- | --- | --- | --- | --- | --- |
| BaseRecordV1 | Common record metadata. | id, project_id, revision, status, timestamps, created_by | N/A | Services | Services | CommitService |
| EvidenceRefV1 | Source traceability pointer. Pydantic validates field shape only; CommitService validates quote/range against SourceChunk text. | chunk_id | Optional range/quote | All story agents | All story agents | CommitService validates chunk existence and quote authenticity |
| ProjectSpecV1 | Project policy. | id, name, type, fidelity flags | N/A | All services | API/user | SourceRepository |
| SourceDocumentV1 | Source file metadata. | document_id, project_id, checksum, storage_uri | N/A | Importer, agents | DocumentParser | SourceRepository |
| SourceChapterV1 | Chapter boundary. | chapter_id, document_id, order | N/A | Agents, API | DocumentParser | SourceRepository |
| SourceChunkV1 | Evidence atom. | chunk_id, document_id, chapter_id, text, checksum | Self | All agents | DocumentParser | SourceRepository |
| EntityProposalV1 | Candidate reusable narrative entity. Fresh outputs use v1.1 closed taxonomy and permit creature_subtype only for CREATURE; v1.0 remains readable. | proposal_id, type, name, evidence_refs, confidence | Required | Merge services | Entity agents | CommitService later |
| EntityProposalBatchV1 | Stable entity-extraction outer proposal containing source-ordered distinct entities. Fresh outputs use v1.1 and require v1.1 items. | batch_id, entities | Required through each entity | Merge services, review UI | Entity agent | CommitService validates each entity later |
| EventProposalV1 | Candidate event, including explicit actor-resolution state. | proposal_id, type, summary, evidence_refs, confidence | Required | Temporal/state agents | Event agent | CommitService later |
| EventProposalBatchV1 | Stable event-extraction outer proposal containing source-ordered events. | batch_id, events | Required through each event | Timeline, temporal/state agents, review UI | Event agent | CommitService validates each event later |
| ClaimProposalV1 | Candidate factual assertion, belief, hypothesis, denial, accusation, memory, evaluation, interpretation, prediction, or commitment. New outputs use schema_version 1.2; schema_version 1.0/1.1 payloads remain readable. | proposal_id, claim_type, claim_text, temporal_scope for v1.2, source_type, verification_status, evidence_refs, confidence, reality_layer | Required | CommitService, review, knowledge agents | Claim/knowledge agents | CommitService later |
| ClaimProposalBatchV1 | Stable claim-extraction outer proposal containing source-ordered distinct claims. New outputs use schema_version 1.2 and require all claims to be v1.2. | batch_id, claims | Required through each claim | Review UI, knowledge agents | Claim agent | CommitService validates each claim later |
| KnowledgeStateProposalV1 | Candidate character knowledge or belief state. | proposal_id, character_id, knowledge_target_id, epistemic_status, reality_layer, evidence_refs, confidence | Required | Dialogue, panel, review, knowledge agents | Knowledge agents | CommitService later |
| TemporalRelationProposalV1 | Candidate event relation. | proposal_id, source, target, relation, confidence | Required unless UNKNOWN | Temporal solver | Temporal agent | CommitService later |
| StateChangeProposalV1 | Source-first candidate state mutation; v1.3 adds controlled appearance paths while v1.0/v1.1/v1.2 remain readable. | proposal_id, event, target, path, values, evidence_refs | Required | State compiler later | State-change agent | CommitService later |
| StateChangeProposalBatchV1 | Empty-or-more source-window State Change candidates; fresh output is v1.3. | batch_id, changes | Required through each change | Review/linker later | State-change agent | CommitService later |
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
| NarrativeAnalysisRunV1 | Persisted whole-document Narrative Analyst task. | analysis_run_id, project_id, document_id, modes, status, window ids | Via AgentRuns and result | API, console, audit | Narrative analysis service | N/A |
| NarrativeAnalysisWindowV1 | One independently retryable mode/window execution; v1.4 adds context/owned chunk boundaries and split lineage. | analysis_window_id, mode, window_index, chunk ids, owned chunk ids, status | Via linked AgentRun | API, console, audit | Narrative analysis worker | N/A |
| NarrativeAnalysisResultV1 | Typed conservative aggregation of proposal candidates. Fresh v1.4 adds `relationship_signals`; v1.0-v1.3 remain readable with missing lists defaulted. | analysis_run_id, events, entities, claims | Preserves EvidenceRef and AgentRun ids | API, console, review | Aggregation service | N/A |
| ProviderResultV1 | One provider call result. Success requires raw_output or structured_output and forbids error_message; failure requires error_message. | provider_result_id, provider_name, provider_type, output_schema, success | Structured output carries evidence if any | AgentRun, audit | Provider adapter | N/A |
| MockProviderResultV1 | Mock provider result specialization using ProviderResultV1 consistency rules. | provider_result_id, output_schema, success | Structured output carries evidence if any | Tests, AgentRun, audit | Mock provider | N/A |

Field types are implemented directly in Pydantic. The JSON Schema export script is the authoritative machine-readable contract.

## Knowledge State Schema Contract v1.1

Claim is a proposition asserted by a character or narrator; it does not by itself
mean any character knows or believes it. Knowledge State records a source-backed
character epistemic position toward a proposition or fact. `UNAWARE` requires
explicit source wording and is never inferred from silence.

Historical v1.0 Knowledge State payloads remain readable, including unversioned
payloads carrying legacy `character_id` and `knowledge_target_id`. New writes use
v1.1 `subject`, `target`, `epistemic_basis`, and optional temporal anchors. A
resolved reference requires a candidate Proposal id of the matching schema;
unresolved references retain source text and null ids. Schema validation checks
shape and type only: proving that a referenced Proposal exists is linker/review
responsibility. Resolved and unresolved candidates never merge automatically.

`HEARD` status requires `HEARD` basis, while a `HEARD` basis may support another
status such as `BELIEVES` or `SUSPECTS`. Temporal anchors preserve source text or
candidate Event linkage but never infer event order or state termination; when the
source provides no explicit start or end anchor, `valid_from` and `valid_until` are
null rather than synthetic unresolved anchors. A direct assertion by itself is a
Claim, not proof that its speaker `BELIEVES` it.

For v1.1, `target_kind` classifies the cognitive target itself: `EVENT` is a
concrete occurrence, discovery, change, or action; `WORLD_FACT` is a proposition
about a world/person/place/object/relationship/fact state; `CLAIM` is a
statement, report, rumor, declaration, accusation, or promise as the target.
The source of a statement and `epistemic_status` do not determine this field:
`HEARD` does not imply `CLAIM`. New `target_text` values use the smallest
complete, auditable core proposition, retaining only meaning-changing
qualifiers. A speech frame belongs in a `CLAIM` target only when the speech act
itself is the cognitive target.

Whole-document aggregation still uses only the complete resolution-aware
semantic key, including subject, target text, target kind, target linkage,
status, basis, reality layer, and temporal anchors. A Console-only deterministic
possible-duplicate hint may compare a safely normalized display form (Unicode
normalization, outer quote/whitespace/terminal-punctuation removal, and only
the listed outer wrappers `传言`/`传闻`/`说法`/`消息`). That comparison does not
enter the schema key, write canonical data, change Proposal ids, or merge
candidates. Unresolved links remain unresolved.

No database migration is required: new fields only appear in compatible
Schema/JSON aggregation results, existing whole-document results use JSON
payloads, v1.0 payloads remain readable, and missing new fields receive
compatibility defaults.

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

## Knowledge State offline evaluation contract v1.1

`KnowledgeStateEvaluationCaseV1` v1.1 is a fixture-only, versioned schema for offline
semantic regression evaluation. A case contains one to three synthetic or redacted
`SourceChunkV1` values, exact expected states, non-empty forbidden partial matchers,
and a strict policy. It reuses the production Knowledge State enums and proposal
schema; it does not define a second state model.

An expectation has one primary `evidence_quote` and may declare a finite
`allowed_evidence_quotes` list of additional, literal source quotes for that same
state. Evidence is accepted only when it is exactly one of those configured values;
it is never shortened, punctuation-normalized, fuzzily matched, or repaired.

The evaluator is deterministic and read-only. It compares Unicode-normalized,
trimmed, whitespace-collapsed text; evidence quotes must occur in the fixture source
and supplied offsets, when present, must match exactly. Each actual state can satisfy
at most one expected state. It never uses an LLM, database, embeddings, fuzzy matching,
or automatic merge. In particular, `山中有鬼` and `山中有鬼的传言` remain different
texts for evaluation.

An empty proposal batch passes only a fixture with no expected states and no forbidden
match. Failure reports distinguish missing, forbidden, extra, target, evidence,
temporal, and resolved-reference errors. Fixture source is synthetic or redacted and
is not canonical story data.

Schema compatibility impact: v1.1 adds the optional, finite exact-evidence allowlist
to evaluation expectations. Historical v1.0 cases remain readable but reject that new
field; fresh bundled cases use v1.1. Existing Knowledge State and whole-document
payloads remain readable. No database migration is required: evaluation cases are
bundled JSON fixtures and evaluation results are transient API/Console payloads.

### Real-run failure and recovery contract

The explicit real-run endpoint returns a typed `SUCCEEDED` outcome containing a
validated `KnowledgeStateProposalBatchV1` and evaluation result, or a typed `FAILED`
outcome. Failure categories are restricted to schema validation, timeout, network,
HTTP, configuration, and unknown provider failure. Diagnostics are an allowlist of
schema field paths, expected output schema, timeout metadata, request attempts, and
HTTP status; raw response content, reasoning, prompts, source text, and credentials
are never returned.

Only `PROVIDER_SCHEMA_VALIDATION` receives one recovery retry with
`output_recovery=schema_validation`. Timeout, network, HTTP, and configuration
failures never trigger recovery. A second schema failure remains an explicit run
failure and is included in the batch report as `run_failed_case_count`; it is never
represented as an empty or passing Batch.

`KnowledgeStateEvaluationReportV1` is an additive v1.1 transient report over one
or more already-structured evaluation batches. It records deterministic aggregate
pass rates, category summaries, status and target-kind correctness, exact-evidence
rates, forbidden matches, unresolved-reference errors, and failure-type counts.
It never invokes a Provider or accepts raw Provider content. Semantic duplicate
states are rejected by `KnowledgeStateProposalBatchV1` before an aggregate report
can be formed. No production Knowledge State payload, database table, canonical
story record, or migration is changed.

2026-08-10 evaluation reliability update: narrated mental-state labels without an
explicit acquisition or self-expression mechanism use `epistemic_basis = UNKNOWN`;
`INFERRED` requires a stated concrete basis, and `STATED` requires the character's own
speech or writing. Bundled fixtures now follow the agent's shortest exact-verbatim
evidence rule. `KnowledgeStateEvaluationRunFailureV1` v1.1 adds optional, allowlisted
`schema_error_rule_codes` so the single schema-recovery retry can correct a known
contract violation without exposing source text or raw provider output. v1.0 failures
remain readable. This is evaluation-only JSON contract hardening; it changes neither
production Knowledge State payloads nor database tables, so no database migration is
required.

### Knowledge State extraction semantic clarifications

Evidence offsets are optional exact anchors. The extraction prompt defaults
`quote_start` and `quote_end` to `null`; when supplied, both must satisfy Python's
half-open rule `source_text[start:end] == quote_text`, with `end` as the exclusive
position after the final character. The evaluator does not repair, broaden, or fuzzy
match an invalid offset.

The shortest complete verbatim evidence quote retains the source sentence's terminal
punctuation when it belongs to that sentence. Removing only a final punctuation mark is
not a permitted shortening: the evaluator continues to compare the selected fixture
quote exactly and does not normalize punctuation.

`target_kind=EVENT` is reserved for concrete occurrences, actions, discoveries, and
changes, including leaving, arriving, dying, happening, opening, and closing.
`WORLD_FACT` remains the type for static world, person, place, object, relationship,
and fact-state propositions. A target's kind is independent of `HEARD`, `SUSPECTS`,
`BELIEVES`, `DISBELIEVES`, or `UNAWARE`.

Narrative wording such as “觉得” or “怀疑” defaults to `SUSPECTS + UNKNOWN` when no
explicit acquisition basis is given. `INFERRED` requires a concrete stated basis and
`STATED` requires the character's speech or writing. These are prompt and evaluation
fixture clarifications only; production v1.0/v1.1 payloads remain readable and no
database migration is required.

## State Change Schema Contract v1.1

`StateChangeProposalV1` is a Proposal-only record for a source-supported persistent
state mutation caused by an event. It is not a canonical StoryBible write, a duplicate
Event, a Knowledge State, or a relationship signal. Fresh v1.1 output uses
`StateChangeEventRefV1` and `StateChangeTargetRefV1`: both carry auditable source
text and may remain `UNRESOLVED` with null candidate IDs. A resolved event link requires
`event_proposal_id` plus `proposal_schema="EventProposalV1"`; a resolved target link
requires `entity_proposal_id` plus `proposal_schema="EntityProposalV1"`. Schema
validation checks only this shape and type pairing; linker/review later verifies that a
candidate exists. It never upgrades an unresolved reference.

Historical explicit v1.0 State Change payloads remain readable with `event_id` and
`target_entity_id`. A payload without `schema_version` that carries either legacy field
is read as v1.0. New construction defaults to v1.1, which requires the source-first
`event` and `target` objects and rejects both legacy IDs. Legacy IDs are never converted
or guessed into resolved candidate links.

`StateChangeProposalBatchV1` is always v1.1 and permits `changes=[]` when a source
window has no auditable state change. Its non-empty items must all be v1.1. It rejects
repeated proposal IDs and exact semantic duplicates using event/target source text,
resolution status, candidate IDs, attribute path, old/new values, persistence, and
reality layer. It performs no fuzzy matching, normalization, embedding, LLM decision,
or silent merge; differing targets, resolution states, values, persistence, or layers
remain distinct candidates.

No database migration is required. State Change remains a compatible Proposal/JSON
payload and not canonical StoryBible data. The Schema itself does not write StoryBible,
CommitService, or canonical state; the implemented Agent/workflow/worker/aggregation/API
and Console integration remains Proposal-only and is documented below.

### State Change Proposal contract v1.2

State Change v1.2 preserves readable v1.0 legacy IDs and v1.1 source-first payloads.
Historical v1.2 targets must be a
persistent `CHARACTER`, `OBJECT`, `LOCATION`, or `ORGANIZATION`; an event, claim,
knowledge state, or relationship signal is not a State Change target. Controlled paths
are `health.injury`, `life_status`, `location`, `possession.holder`,
`physical.condition`, `accessibility`, `availability`, `quantity`, and `role.status`.
The Schema enforces the target/path matrix: health, life, and role apply to characters;
location applies to characters or objects; possession and quantity to objects; physical
condition and accessibility to objects or locations; availability to objects or
organizations.

For v1.2, `old_value=null` means only that the source did not state a prior value.
Unknown placeholders such as `未知`, `不明`, `N/A`, and `待确认` are invalid. `new_value`
is a non-null, non-speculative JSON scalar with a deterministic path-compatible type;
it is never a quote, event summary, list, object, or inferred explanation. Every v1.2
Proposal has non-empty `new_value_evidence_indexes` pointing into its own
`evidence_refs`. `persistent=true` requires non-empty
`persistence_evidence_indexes`; `persistent=false` requires an empty list and means
only “no explicit persistence support,” not “proven temporary.” The Schema validates
index shape and bounds, not what a quote means.

The extraction Prompt tightens the semantic boundary: `persistent=true` requires explicit
continuing, permanent, from-now-on, long-term, stable, or equivalent source language.
Results such as collapse, close, recover, injury, arrival, obtaining, or putting are not
persistence evidence by themselves. For unresolved targets, `mention_text` must appear
verbatim as a name or pronoun in one of the permitted source chunks; the Agent rejects an
absent mention without changing the Proposal or inferring a name. `event_summary` is only
the minimal cause/local context and must not include another target's state result.

Historical v1.1 and v1.2 Batches remain readable when explicitly declared. Historical
v1.2 Batches permit `changes=[]` and accept only v1.2 items. Exact duplicate detection includes target
category and excludes Evidence order/indexes and confidence; it never performs fuzzy
merging. No old payload is automatically migrated or guessed into v1.2 values,
persistence, or resolved references.

### State Change Narrative Analysis integration

`state_change_extraction` is an implemented Proposal-only Narrative Analyst mode. It runs
over bounded SourceChunk windows and returns `StateChangeProposalBatchV1`; `changes=[]` is
a successful result. `NarrativeAnalysisResultV1` fresh output is v1.3 and adds
`state_changes`. Versionless historical results without `knowledge_states` and
`state_changes` remain v1.0-readable with both lists defaulted to `[]`; versionless
results with `knowledge_states` but no `state_changes` remain v1.1-readable with
`state_changes=[]`.

State Change aggregation merges only an exact semantic key: event summary/resolution/link,
target text/kind/resolution/link, attribute path, type-sensitive old and new values,
persistent flag, and reality layer. It never links unresolved references, performs fuzzy
matching, writes canonical state, or decides facts. The Console presents these candidates
in a dedicated audit table with values, persistence evidence indexes, and Evidence audit
entry points.

无需数据库迁移：新增字段只存在于兼容的 Schema/JSON 聚合结果中；历史 v1.0/v1.1
payload 继续可读。State Change remains Proposal/JSON data only: no StoryBible,
CommitService, or database state-table write is introduced.

### State Change Schema Contract v1.3

Fresh `StateChangeProposalV1` and `StateChangeProposalBatchV1` payloads default to
`schema_version="1.3"`. Explicit v1.0, v1.1, and v1.2 payloads remain readable and are
not rewritten or upgraded. Fresh batches still use `changes=[]` for an empty result and
accept only v1.3 items; unresolved event/target references keep candidate ids and schema
null.

The controlled paths `appearance.clothing` and `appearance.hairstyle` are CHARACTER-only.
Their `new_value` and non-null `old_value` are concise non-empty strings; object, array,
empty, unknown-placeholder, and speculative values remain invalid. Completed changes such
as “换上灰衣” and “解开发绳，长发披下” are admissible; plans, commands, static looks,
wind or light effects, brief expressions, and momentary disorder are not. Event is the
instantaneous cause and State Change is the resulting reusable state, so both may be
represented. In an uninterrupted “裂纹→崩塌” action, only the final result is preferred;
separate time/reaction stages may produce separate changes.

`persistent=false` means only that the source provides no explicit permanent, long-term,
from-now-on, continuing, or stable support; it does not mean the state immediately ends.
Evidence, unresolved-link, exact duplicate, and Proposal-only boundaries remain unchanged.
No fuzzy merge, automatic resolved link, canonical write, or semantic repair is introduced.
Part-whole target resolution is intentionally out of scope: “木箱” and “箱盖” remain
independent OBJECT mentions unless a future approved Schema explicitly models their relation.
`NarrativeAnalysisResultV1` fresh output follows compatible v1.4 and includes
`relationship_signals`; historical result payloads still read with missing lists defaulted to `[]`.

无需数据库迁移：v1.3 只扩展兼容的 Proposal/JSON Schema 与聚合结果，不写入 canonical
StoryBible 或数据库状态表。

### Relationship Signal Schema Contract v1.0

`RelationshipSignalProposalV1` 与 `RelationshipSignalProposalBatchV1` 是新的
Proposal-only、source-first 合同。它们表达当前 SourceChunk 中带证据、方向、语境和
时间边界的二元关系信号，不等于 Claim、Knowledge State、Event 或 canonical
relationship。参与者只允许 `CHARACTER` 与 `ORGANIZATION`；不支持自由三元关系，也不
从多人同行或普通相遇推断两两关系。

`RelationshipKind` 使用受控 kind/domain/directionality 矩阵：亲属与情感 kind 包括
`PARENT_OF`、`CHILD_OF`、`SIBLING_OF`、`SPOUSE_OF`、`ROMANTIC_PARTNER_OF`、`RELATIVE_OF`；
归属/层级包括 `MEMBER_OF`、`LEADS`、`COMMANDS`、`REPORTS_TO`、`MASTER_OF`、`DISCIPLE_OF`；
态度与依附包括 `TRUSTS`、`DISTRUSTS`、`DEPENDS_ON`；合作/冲突包括
`COOPERATES_WITH`、`ALLIED_WITH`、`HOSTILE_TO`、`RIVALS_WITH`、`PROTECTS`、`THREATENS`；
欺骗/背叛包括 `DECEIVES`、`BETRAYS`。对称 kind 在 Batch 去重时按无序参与者对比较，
但不改写 subject/counterpart 的原文顺序；有向关系的反向候选保持独立。

`evidence_basis` 严格区分 `NARRATED`、`DIRECT_STATEMENT`、`OBSERVED_ACTION`、
`REPORTED_STATEMENT` 与仅供人工/离线工具使用的 `INFERRED`。直接陈述和转述必须带
source speaker，且不能使用 `EXPLICIT`；旁白和观察行为禁止虚构 speaker；`INFERRED`
至少需要两条 EvidenceRef、只能是 `LIMITED`，且不能表达关系形成、增强、削弱或终止。
`DENIAL` 必须搭配 `assertion_polarity=DENIED`，其他 effect 必须为 `AFFIRMED`。
变化型 effect 必须有非空 temporal anchor text；Schema 不推断事件顺序，也不裁决证据
内容。亲属关系不允许 `TERMINATION`。

所有 participant、context event、temporal event 引用均为候选 Proposal 引用：
`UNRESOLVED` 时 ID/schema 必须为 null，`RESOLVED` 时分别只能是
`EntityProposalV1` / `EventProposalV1`。Schema 不查询数据库、不验证 Proposal 是否真实
存在、不自动链接称呼、不写入 StoryBible 或 CommitService。Batch 只做完整语义键的
精确去重，不做文本归一化、模糊匹配、embedding 或 LLM 裁决；evidence 顺序和 confidence
差异不能使完全相同语义逃过校验。

Relationship Signal Proposal/Batch v1.0 remains unchanged. `relationship_signal_extraction` is
implemented across the bounded workflow, whole-document worker, resume/split ownership flow, exact
aggregation, API and Console audit. `NarrativeAnalysisResultV1` v1.4 adds compatible
`relationship_signals`; v1.0-v1.3 results remain readable and default that list to `[]`. Its exact
aggregation key includes both participant references (unordered only for symmetric signals), kind/
domain/direction/effect/polarity/basis/support, speaker, context event, temporal anchor and reality
layer. It never uses fuzzy matching, entity linking, fact adjudication, or canonical writes.

无需数据库迁移：`relationship_signals` 只存在于兼容 JSON 聚合结果。Relationship Signal remains
Proposal-only and does not create canonical relationships or write StoryBible/CommitService data.

### Review Gate 2 Schema Contract v1.0

Review Gate 2 v1.0 is a proposal-review contract, not a review Agent, linker, canonical
writer, or automatic decision service. `ReviewGate2InputV1` carries a bounded analysis run,
the six Narrative Analyst Proposal types with their AgentRun/Evidence provenance, an explicit
allowed SourceChunk scope, and a fixed `ReviewGate2PolicyV1`. Empty proposal input is valid.
The policy permanently requires Evidence and complete review before downstream use, permits
only exact reference matching, and forbids fuzzy matching, LLM reference resolution, and
canonical writes.

`ReviewableProposalEnvelopeV1` accepts exactly Event, Entity, Claim, Knowledge State, State
Change, and Relationship Signal Proposals. Its declared mode and schema must match the actual
Proposal type, AgentRun ids are non-empty and unique, and aggregated Evidence is non-empty.
The envelope preserves the original Proposal: it neither upgrades unresolved references nor
rewrites Proposal ids, fields, Evidence, reality layers, or semantics.

Review decisions record independent schema/provenance/evidence/mode-boundary statuses,
per-Evidence review, reference-resolution decisions, and sanitized issues. `APPROVED` permits
only passed/not-applicable checks, passed Evidence, no blocking or review-required issues, and
no required unresolved/ambiguous/rejected reference. `REJECTED` requires a failed check and a
blocking issue. `NEEDS_HUMAN_REVIEW` requires an unresolved review condition and a
review-required issue, without a blocking issue. Deterministic decisions cannot supersede a
prior decision; human decisions must identify the superseded decision and provide a non-empty
review note. Issues are auditable metadata only and must not contain raw provider payloads or
source content.

`ReferenceResolutionDecisionV1` is restricted to Entity, Event, or Claim Proposal candidates
in the current review scope. It records `RESOLVED`, `UNRESOLVED`, `AMBIGUOUS`, or `REJECTED`
without performing a lookup. Resolved decisions select exactly one listed candidate with a
non-`NONE` basis; unresolved decisions contain neither a candidate nor selection; ambiguous
decisions retain at least two candidates and a review-required issue; rejected decisions carry
a blocking issue. The Schema validates shapes, required issue categories, and exact declared
types only; it does not prove that a Proposal exists or automatically resolve a mention.

`ReviewGate2ResultV1` is complete only when all decisions are final and its
`ApprovedProposalBundleV1` exactly corresponds to the approved decisions. The bundle may be
empty when no Proposal is approved; a partially reviewed result has no bundle; a failed result
has a blocking `EXECUTION` issue and no bundle. It remains an audit JSON artifact for future
Timeline and StoryBible Curator consumers. This contract has no Review Agent, linker, API,
Console, Timeline, StoryBible Curator, CommitService, database table, or migration.

Schema compatibility impact: this adds independent v1.0 Review Gate 2 payloads only. Existing
Event, Entity, Claim, Knowledge State, State Change, Relationship Signal, Narrative Analysis,
and historical payload versions remain unchanged and readable. No historical Proposal is
rewritten, linked, or upgraded.

无需数据库迁移：Review Gate 2 新增字段仅存在于兼容的 Pydantic/JSON 审计合同中；当前未持久化
Review Gate 2 结果，未来如需持久化应单独设计数据库模型与迁移。

### Review Gate 1 Schema Contract v1.0

Review Gate 1 位于 Import & Chunking 完成之后、Orchestrator/ContextBuilder 之前，审核的是
SourceDocumentV1、SourceChapterV1、SourceChunkV1 的导入与切片质量，不判断叙事语义、不产生
事实，也不调用 LLM。`ReviewGate1InputV1` 携带已解码的 `SourceTextAuditSnapshotV1`、章节、
chunk 和固定 Policy 快照。Input 只验证结构、标识符和策略 Literal；重复 ID/order、范围重叠、
checksum 不一致、scope 错误等待审异常必须能够进入 Input，由 Result 形成审计结论，而不是
在输入层丢失。

Gate 1 的确定性边界包括：规范化文本 checksum 和 chunk checksum/range 校验、replacement
character、NUL/禁止控制字符、空文档/纯空白、章节/chunk scope、零起连续 order、重复/重叠
range、空章节、章节 chunk 边界以及 1200 字符长度策略。`char_end` 是 Python 半开区间的
exclusive end。标题行和空白分隔区可以造成合法 gap；不要求 chunk 覆盖全文，但有效 chunk
range 不得重叠或重复。相同文本/相同 checksum 且范围不同仅是可能重复提示，不自动删除或合并。
Gate 1 不修复乱码、offset、排序或 chunk 内容。

“乱码”检查只覆盖已严格 UTF-8 解码并规范化文本中的确定性损坏信号，例如 `\\uFFFD`、NUL
和禁止控制字符，不能证明自然语言质量或原始字节绝无问题。Issue 只保存受控 code/category/
check、对象输入索引、field path 和无换行的短 sanitized message，不保存 normalized_text、
全文、storage_uri 或 Provider 原始响应。

`ReviewGate1ResultV1` 只有确定性审核完成后才可 APPROVED：所有 chunk 为 USABLE、无 BLOCKING/
REVIEW_REQUIRED issue，并带有按源 order 排列的 `ApprovedSourceChunkBundleV1.chunk_ids`。
REJECTED 必须有 BLOCKING issue 且无 Bundle；NEEDS_HUMAN_REVIEW 必须有 REVIEW_REQUIRED issue
且暂停整份 Bundle；FAILED 必须是 REJECTED 并带 EXECUTION/BLOCKING issue。Bundle 只能交给
未来 Orchestrator/ContextBuilder，不能交给 StoryBible、CommitService 或任何 canonical 写入路径。

Gate 1 与 Gate 2 分工不同：Gate 1 检查输入文本/切片是否可安全供 Agent 使用；Gate 2 检查六类
Proposal 的 Schema、Evidence、来源与 mode 边界。两者均不自动链接、不做模糊匹配、不写
StoryBible。

Schema compatibility impact：新增独立的 Review Gate 1 v1.0 Pydantic/JSON payload，不修改
SourceDocumentV1、SourceChapterV1、SourceChunkV1 及其历史读取兼容性；当前不实现 Gate 1
service、Agent、API、Console 或自动路由。

无需数据库迁移：Gate 1 结果目前仅作为兼容的 Pydantic/JSON 审计合同；没有新增数据库表，
未来持久化需另行设计迁移。
