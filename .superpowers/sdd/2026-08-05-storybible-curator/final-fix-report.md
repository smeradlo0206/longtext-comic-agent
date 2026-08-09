# StoryBible Curator Final Fix Report

Date: 2026-08-09

## Scope

This fix wave addressed the five final-review findings against the complete StoryBible
Curator branch. It preserved the architecture constraints that Pydantic models in
`comic_agent/schemas` are the contract source of truth, agents emit proposals only,
`CommitService` is the canonical promotion boundary, and tests make no real provider
calls.

## Root-cause investigation and pattern analysis

1. **Non-atomic plan promotion.** `CommitService.commit_storybible_plan` invoked
   `save_candidate_plan`, each `apply_canonical_update`, and `save_committed_plan` in
   sequence. Every repository helper independently called `Session.commit()`. Therefore
   the first canonical update became durable before a later update or plan-status write
   could fail. The repository had strong single-resource race recovery, but no plan-level
   unit of work.
2. **Canonical data absent from validation.** `StoryBibleValidator.validate_commit_plan`
   initialized its identity-owner and temporal-state maps as empty for every invocation.
   It correctly detected collisions among updates in one plan, but it never received
   profiles or states already canonical for the project. A second plan could therefore
   reuse a canonical name/alias or add an incompatible overlapping state.
3. **Unvalidated profile references.** Repository preflight checked global ownership only
   for resource ids directly updated by the plan. It did not resolve
   `StoryEntityStateV1.profile_id` or either `StoryRelationshipV1` endpoint. Because the
   StoryBible tables do not declare foreign keys, missing and cross-project references
   reached canonical storage.
4. **Contract/storage length mismatch.** The new StoryBible Pydantic fields accepted
   unbounded strings, while migration `0004_storybible_resources` and SQLAlchemy models
   store identifiers in `VARCHAR(128)` and canonical names in `VARCHAR(255)`. SQLite did
   not expose the mismatch because it does not enforce VARCHAR lengths.
5. **Union export gap.** The exporter iterated only concrete `BaseModel` subclasses.
   `StoryBibleUpdateV1` is an `Annotated` union, so it could not be added to that list and
   had no generated public JSON Schema file.

The common pattern was incomplete boundary composition: individual helpers and
within-object validation were correct in isolation, but plan-wide guarantees require one
transaction and canonical project context at the commit boundary.

## RED evidence

The following regressions were written before production changes and failed for the
expected missing behavior:

- Seven focused commit regressions failed: deterministic second-write rollback,
  existing-canonical identity collision, existing-canonical overlapping state conflict,
  missing/cross-project state owner, and missing/cross-project relationship endpoint.
- The injected persistence failure left the SQLAlchemy session pending rollback under the
  old code, demonstrating that the service neither rolled back nor restored a usable
  session after the later flush failed.
- Four focused schema/export regressions failed: 128-character identifier bounds,
  255-character canonical-name bounds (profile and world rule), and the absent
  `StoryBibleUpdateV1.json` artifact.

RED command substitution note: the plan's `uv run ...` form could not run because `uv`
is not installed in this environment. All commands used the worktree's existing Python
3.12 virtual environment (`.venv/Scripts/python.exe`) with the same locked dependencies.

## Implementation and GREEN evidence

- Added `StoryBibleRepository.commit_unit_of_work()`. Repository helpers flush rather
  than commit while the unit is active; exactly one final commit persists every canonical
  update and the plan's `COMMITTED` transition. Any exception rolls the session back.
  Standalone repository operations retain their existing commit and race-recovery
  semantics.
- `CommitService` now performs effective-plan preflight, canonical snapshot validation,
  all update applications, and the committed-plan transition in that shared unit of work.
- Added project-scoped `list_states` retrieval for deterministic service validation.
  `StoryBibleValidator` seeds identity owners and flattened temporal facts from canonical
  profiles/states. A higher revision of the same state id remains an allowed replacement;
  a different state id with a conflicting overlapping fact is rejected.
- Repository preflight resolves every state owner and relationship endpoint against
  project-owned canonical profiles or profile updates in the same plan, distinguishing
  nonexistent from cross-project references before any durable write.
- Added Pydantic `StringConstraints` for StoryBible identifiers (128) and canonical/name
  strings (255), matching existing persistence columns. The initial unreleased V1 remains
  `schema_version = "1.0"`; documentation records that no new database migration is
  needed because migration `0004` already has the matching storage limits.
- Exported `StoryBibleUpdateV1` through a Pydantic `TypeAdapter` and verified its four-way
  JSON Schema union by executing the exporter in an isolated temporary directory.
- Focused GREEN: 7/7 new commit/ownership regressions passed and 4/4 new schema/export
  regressions passed.

## Final verification

- Full pytest: **110 passed, 1 skipped**. The skipped case is the explicitly opt-in live
  provider connectivity smoke test; no external/provider call was made. One pre-existing
  Starlette/httpx deprecation warning was emitted.
- Ruff: **passed** (`ruff check .`).
- mypy: **passed** (`mypy comic_agent`, 47 source files).
- JSON Schema export: **passed**; `schema_exports/StoryBibleUpdateV1.json` exists.
- Fresh Alembic smoke: a new isolated SQLite database upgraded from base through
  `0004_storybible_resources (head)` and was removed afterward.
- `git diff --check`: **passed**; only line-ending conversion notices were reported by
  Git on this Windows worktree.

## Concerns and compatibility notes

- Identifier/name validation tightens the accepted initial V1 input domain to values the
  existing database schema can store portably. This is documented as pre-release V1
  hardening rather than a new versioned contract or database migration.
- Canonical identity and temporal conflict detection is an application-level invariant
  evaluated inside the plan transaction. The current scope adds no normalized alias/fact
  tables or new database uniqueness constraints.
- The only verification warning is the pre-existing Starlette `TestClient` deprecation
  notice regarding httpx; it is unrelated to this fix wave.

## Residual P1 follow-up: committed retry after canonical replacement

### Root cause

The initial atomic/canonical-context fix still ran canonical snapshot validation for an
exact plan whose stored candidate row was already `COMMITTED`. This made historical plan
payloads compete with facts introduced later. The reproduced identity sequence was:

1. commit profile A as `Alice` at revision 1;
2. rename A to `Alicia` at revision 2;
3. commit profile B as `Alice`;
4. retry the exact revision-1 plan.

Step 4 incorrectly raised a duplicate-identity error even though revision gating made the
retry a no-op. The same ordering defect applied to replaced temporal state followed by
reuse of the replacement value in another state.

### RED/GREEN evidence

- RED: `test_retry_committed_plan_ignores_canonical_identity_changes_after_its_commit`
  failed at canonical snapshot validation with `duplicate StoryBible identity belongs to
  multiple profiles`.
- Existing/new guard characterizations for an altered payload and a wrong-project replay
  passed before the change, establishing the security/idempotency behavior that the fix
  had to preserve.
- GREEN: the repository now returns a stored plan early only when its row is already
  `COMMITTED`, its project and content hash match, and its complete serialized payload is
  identical. `CommitService` checks this before canonical snapshot validation and repeats
  the check inside the unit of work to close a concurrent status-transition window.
- GREEN focused: four tests passed covering identity replacement/reuse retry, temporal
  replacement/reuse retry, altered-payload rejection, and wrong-project rejection.

### Follow-up verification

- Full pytest: **114 passed, 1 skipped** (the explicit opt-in live-provider smoke test).
- Ruff: **passed**.
- mypy: **passed** for 47 source files.
- `git diff --check`: **passed** with only Windows line-ending notices.
- No provider or external network call was made.

No new compatibility or migration concern was introduced; this change only restores
idempotent behavior for already-committed, exactly matching plan retries.
