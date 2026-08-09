# Development Log

## 2026-07-28: Phase 1 Source-to-Proposal Closed Loop

Implemented the first demonstrable workflow without a real LLM or image provider:

```text
UTF-8 TXT upload
-> chapter and SourceChunk parsing
-> selected SourceChunk
-> MockEventAgent
-> EventProposal validation
-> EvidenceRef source validation
-> CANDIDATE proposal persistence
-> AgentRun audit record
```

### Delivered

- `EventProposalV1` now requires a non-empty summary and at least one evidence reference.
- `CommitService` verifies that referenced chunks exist, quote ranges stay in bounds, and quote text matches source text.
- `MockEventAgent` accepts one `SourceChunkV1` and creates a deterministic `MOCK_EVENT` with an exact full-chunk quote.
- API endpoints provide Mock extraction plus candidate-proposal and agent-run queries.
- Candidate proposals are persisted with `CANDIDATE` status and remain separate from canonical story data.
- Repeated Mock extraction for one chunk reuses its proposal but creates a new `AgentRun` audit entry.
- Added migrations for `event_proposals` and AgentRun input/output links.

### Verification

- `python -m pytest`: 29 passed.
- `python -m ruff check .`: passed.
- `python -m mypy comic_agent`: passed.
- JSON Schema export and Alembic migrations were validated with temporary SQLite databases.

### Deliberate Phase Boundary

The Mock Agent does not understand text or call an LLM. It validates the typed proposal and evidence-traceability pipeline only. Canonical story-event commits remain intentionally unimplemented.

## 2026-08-05: StoryBible Curator Contract and Persistence

Delivered the StoryBible curation path with versioned Pydantic and exported JSON Schema
contracts for bounded curator context, candidate proposals, conflicts, commit plans, and
the canonical profile, state, relationship, and world-rule resources. All canonical facts
remain evidence-backed through `EvidenceRefV1`.

- `StoryBibleCurator` uses `deepseek-v4-pro` by default and produces
  `StoryBibleCuratorProposalV1` candidates only; it has no canonical-write capability.
- `ContextBuilder` supplies bounded context rather than database-wide agent reads, while
  `StoryBibleRepository` exposes project-scoped StoryBible retrieval.
- `CommitService` is the canonical boundary: it validates evidence and plan invariants,
  then performs idempotent canonical persistence only for a reviewed commit plan.
- Alembic migration `0004_storybible_resources` adds canonical StoryBible resource tables
  and candidate commit-plan persistence.
- Regression coverage includes schema validation, proposal-only curation, project
  isolation, bounded context, retrieval, commit validation, idempotency, API behavior,
  provider request shaping, and migration compatibility.

### 2026-08-09 Final consistency hardening

- StoryBible plan promotion now uses one unit of work for every canonical update and the
  candidate plan's `COMMITTED` transition; a later database failure restores the prior
  candidate state and rolls back earlier canonical flushes.
- Commit validation now includes project canonical profiles/states, rejecting identity
  collisions and incompatible overlapping state facts introduced by separate plans.
- State owners and both relationship endpoints must resolve to a profile owned by the
  plan project or created in that same plan.
- StoryBible V1 identifiers and names now enforce the 128/255-character persistence
  limits, and `StoryBibleUpdateV1` is included in JSON Schema export.
- Migration note: this pre-release V1 contract hardening requires no new Alembic revision
  because migration `0004_storybible_resources` already carries those storage lengths;
  no database shape or payload representation changed.

### Test Policy

Normal unit and regression tests use deterministic fakes or `httpx.MockTransport`; they
must not make real provider or image-model requests. An explicitly user-requested live
connectivity smoke test exists separately and is skipped unless
`RUN_LIVE_LLM_SMOKE_TEST=1`; it requires live-provider configuration and is not run in the
default suite. This preserves offline, repeatable regression tests while allowing an
intentional opt-in connectivity check.
