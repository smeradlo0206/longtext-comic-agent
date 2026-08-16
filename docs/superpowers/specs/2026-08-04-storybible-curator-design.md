# StoryBible Curator Design

## Purpose

Build the StoryBible Curator as a bounded intelligent-agent module. It turns reviewed,
evidence-backed narrative proposals and confirmed temporal relations into auditable update
proposals for the story setting library. The setting library contains people, organizations,
locations, their aliases and profiles, and their time-bound states.

The curator does not write canonical story facts. It only produces proposals and a
`CommitPlan`; `CommitService` remains the sole canonical write boundary.

## Scope

### Included

- Curate people, organizations, and locations from reviewed entity and event proposals.
- Produce profile updates, relationship updates, world-rule updates, and state updates.
- Use confirmed temporal relations to order state changes.
- Detect evidence gaps, incompatible updates, duplicate identities, and overlapping state
  intervals as reviewable conflicts.
- Persist canonical StoryBible resources only after an approved commit plan.
- Provide bounded retrieval of resources for later agents through `ContextBuilder`.

### Excluded

- Import/chunk review, narrative extraction, and temporal-relation generation.
- Review Gate 4 UI or human approval workflow.
- Storyboard planning, prompt compilation, image generation, and QA.
- Direct use of a real model in unit tests.

## Model Policy

- Default curator model: `deepseek-v4-pro`, selected for structured extraction and
  consolidation.
- Conflict-review model: `qwen3.6-reasoner` (or a configured reasoning model), used only
  for isolated ambiguous or contradictory cases.
- All calls go through the existing `LLMProvider` interface. API credentials live only in
  `.env`, which is ignored by Git; `.env.example` contains variable names but never values.

## Contracts

### Inputs

The curator accepts a bounded context package containing:

- reviewed `EntityProposalV1`, `EventProposalV1`, and `StateChangeProposalV1` records;
- confirmed `TemporalRelationProposalV1` records;
- existing canonical StoryBible resources relevant to those records.

Each input fact must retain at least one `EvidenceRefV1`. The curator receives bounded
context only; it never reads the entire database.

### Outputs

The curator returns a `StoryBibleCuratorProposalV1` containing:

- person, organization, and location profile update proposals;
- state update proposals with an effective event/time reference;
- relationship and world-rule update proposals;
- structured conflicts or evidence issues; and
- a `CommitPlanV1` that enumerates the proposed additions and changes.

No provider-specific fields appear in domain schemas. The curator may emit only proposal
objects.

## Data Model and Persistence

New schema models are the single source of truth and are versioned as `1.0`:

- `StoryEntityProfileV1`: canonical identity record for PERSON, ORGANIZATION, or LOCATION,
  with aliases, attributes, evidence, revision, and status.
- `StoryEntityStateV1`: state snapshot/interval for a profile, linked to a triggering event
  or temporal anchor and evidence.
- `StoryRelationshipV1`: typed relationship between two profiles, with temporal validity and
  evidence.
- `WorldRuleV1`: source-supported setting rule.
- `StoryBibleCuratorProposalV1`, `ConflictV1`, and `CommitPlanV1`: candidate output and
  commit-review contracts.

Database tables store canonical profiles, states, relationships, world rules, and immutable
candidate commit plans. Existing proposal tables continue to store candidates and are never
reclassified as canonical data by an agent.

## Processing Flow

1. `ContextBuilder` assembles only relevant reviewed proposals, timeline relationships, and
   existing matching resources.
2. The curator validates input evidence and builds a structured model request.
3. The default LLM provider returns a schema-validated curator proposal.
4. Deterministic validation checks evidence references, identity keys, temporal ordering,
   overlapping states, and duplicate updates.
5. A conflict result blocks the affected commit-plan entry and is returned for human review.
6. An approved `CommitPlanV1` is passed to `CommitService`, which validates again and
   idempotently persists canonical resources.
7. Later agents request profiles/states through bounded repository queries and
   `ContextBuilder`, not by direct database reads.

## Error Handling and Idempotency

- Missing or mismatched evidence rejects the affected proposal.
- Contradictory facts produce conflicts; neither fact silently overwrites the other.
- Repeating the same approved commit plan is a no-op, identified by a stable content key.
- Provider timeouts, malformed structured responses, and low-confidence outputs return a
  failed/needs-review result with no canonical write.

## Verification

Unit tests use mock providers and temporary SQLite databases. They cover profile creation,
organization/location curation, temporal state retrieval, evidence failure, conflict
detection, idempotent commit, and bounded context retrieval. The complete repository must
pass Ruff, mypy, and pytest.

## Compatibility and Migration

The change adds new V1 schemas and tables; existing source-import and mock-event APIs stay
compatible. Schema version and migration notes must accompany the implementation.

## Boundary Revision: Story-Time Ordering Owned by the Timeline Agent

Original scope listed "use confirmed temporal relations to order state changes" as a
curator responsibility. That responsibility was later moved to a parallel timeline
agent: the StoryBible Curator anchors states and relationships to events by event id
(`triggering_event_id` / `valid_from_event_id` / `valid_until_event_id`) and CONSUMES
the timeline agent's pairwise `temporal_relation_proposals` output only to stamp
`valid_from_order` / `valid_until_order`. It never extracts event order from text, and
all-UNKNOWN timeline output stamps nothing. States are effective from their from-event
onward and persist across chapter imports; a deterministic `state-at` snapshot folds
every in-effect interval into one merged world view for downstream consumers, which
join StoryBible state with narrative-analysis and timeline output by event id.
