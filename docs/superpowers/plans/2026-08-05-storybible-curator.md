# StoryBible Curator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an evidence-backed StoryBible Curator that proposes, reviews, commits, and retrieves canonical person, organization, location, relationship, world-rule, and time-bound state resources.

**Architecture:** New Pydantic contracts in `comic_agent/schemas` define StoryBible resources and candidate curator output. A Curator reads only a bounded context and produces a `StoryBibleCuratorProposalV1` with a `CommitPlanV1`; validation and the extended `CommitService` perform idempotent canonical persistence. Repository queries and API routes expose only project-scoped resources for later agents.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx, pytest, Ruff, mypy.

## Global Constraints

- `comic_agent/schemas` Pydantic models are the only schema source of truth.
- Agents may output Proposal objects only; only `CommitService` writes canonical story data.
- Every canonical fact must retain valid `EvidenceRefV1` traceability.
- Agents receive bounded context only through `ContextBuilder` and repository query methods.
- Provider-specific fields are excluded from domain schemas; all external calls use provider interfaces.
- Writes must be idempotent, schema changes use `schema_version = "1.0"`, and migrations include downgrade support.
- Unit tests never call real LLM or image APIs; use local SQLite and mock providers.
- Keep API credentials in `.env`; `.env` remains Git-ignored and `.env.example` has no secret values.

---

## File Structure

- Create `comic_agent/schemas/storybible.py`: StoryBible resource, bounded context, curator proposal, conflict, update-union, and commit-plan schemas.
- Modify `comic_agent/schemas/__init__.py`: public exports for new contracts.
- Modify `scripts/export_json_schemas.py`: export every new public contract.
- Create `tests/test_storybible_schemas.py`: validation regression tests for all schema invariants.
- Modify `comic_agent/database/models.py`: SQLAlchemy models for canonical StoryBible records and candidate commit plans.
- Create `migrations/versions/0004_storybible_resources.py`: create/drop StoryBible tables and indexes.
- Create `comic_agent/repositories/storybible_repository.py`: project-scoped, bounded persistence and retrieval methods.
- Create `comic_agent/services/storybible_validator.py`: deterministic evidence, identity, state-interval, and duplicate validation.
- Modify `comic_agent/services/commit_service.py`: idempotent approval/commit gateway for `CommitPlanV1`.
- Modify `comic_agent/services/context_builder.py`: bounded StoryBible context construction.
- Create `comic_agent/agents/storybible_curator.py`: provider-backed proposal-only Curator.
- Create `comic_agent/providers/openai_compatible.py`: OpenAI-compatible, configured provider implementation.
- Modify `comic_agent/config.py`: base URL, API key, model name, and timeout settings loaded from `.env`.
- Create `.env.example`: non-secret provider configuration template.
- Create `comic_agent/api/storybible.py`: Curator submission, commit, and resource retrieval routes.
- Modify `comic_agent/main.py`: register StoryBible routes.
- Create `tests/test_storybible_repository.py`, `tests/test_storybible_curator.py`, `tests/test_storybible_api.py`, and `tests/test_openai_compatible_provider.py`.

### Task 1: Define StoryBible Contracts and JSON-Schema Export

**Files:**
- Create: `comic_agent/schemas/storybible.py`
- Modify: `comic_agent/schemas/__init__.py`
- Modify: `scripts/export_json_schemas.py`
- Test: `tests/test_storybible_schemas.py`

**Interfaces:**
- Consumes: `EvidenceRefV1`, `EventProposalV1`, `EntityProposalV1`, `StateChangeProposalV1`, and `TemporalRelationProposalV1`.
- Produces: `StoryBibleContextV1`, `StoryEntityProfileV1`, `StoryEntityStateV1`, `StoryRelationshipV1`, `WorldRuleV1`, `ProfileUpdateProposalV1`, `StateUpdateProposalV1`, `RelationshipUpdateProposalV1`, `WorldRuleUpdateProposalV1`, `StoryBibleUpdateV1`, `ConflictV1`, `CommitPlanV1`, and `StoryBibleCuratorProposalV1`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_profile_rejects_unsupported_entity_kind() -> None:
    with pytest.raises(ValidationError):
        StoryEntityProfileV1(profile_id="p-1", project_id="project-1", entity_kind="PROP", canonical_name="Umbrella", evidence_refs=[])


def test_commit_plan_requires_at_least_one_update() -> None:
    with pytest.raises(ValidationError):
        CommitPlanV1(commit_plan_id="plan-1", project_id="project-1", source_proposal_id="curator-1", updates=[])
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run pytest tests/test_storybible_schemas.py -v`

Expected: FAIL because `comic_agent.schemas.storybible` does not exist.

- [ ] **Step 3: Implement strict V1 contracts**

```python
class StoryEntityKind(StrEnum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"


class CommitPlanV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    commit_plan_id: str
    project_id: str
    source_proposal_id: str
    content_hash: str
    updates: list[StoryBibleUpdateV1] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
```

Give every profile, state, relationship, and world rule an id, project id, revision/status metadata, typed evidence refs, and validators that reject invalid temporal intervals or blank names. Export them through `comic_agent.schemas` and add them to `SCHEMAS`.

- [ ] **Step 4: Run focused tests and JSON-schema export**

Run: `uv run pytest tests/test_storybible_schemas.py -v; uv run python scripts/export_json_schemas.py`

Expected: PASS; `schema_exports/StoryBibleCuratorProposalV1.json` and `schema_exports/CommitPlanV1.json` are generated locally and ignored by Git.

- [ ] **Step 5: Commit the contracts**

```bash
git add comic_agent/schemas/storybible.py comic_agent/schemas/__init__.py scripts/export_json_schemas.py tests/test_storybible_schemas.py
git commit -m "feat: define StoryBible curator contracts"
```

### Task 2: Persist Canonical Resources and Candidate Commit Plans

**Files:**
- Modify: `comic_agent/database/models.py`
- Create: `migrations/versions/0004_storybible_resources.py`
- Create: `comic_agent/repositories/storybible_repository.py`
- Test: `tests/test_storybible_repository.py`

**Interfaces:**
- Consumes: canonical `StoryEntityProfileV1`, `StoryEntityStateV1`, `StoryRelationshipV1`, `WorldRuleV1`, and candidate `CommitPlanV1`.
- Produces: `StoryBibleRepository.save_candidate_plan`, `get_profile`, `find_profiles`, `list_states_at_event`, `list_related_resources`, and idempotent `apply_canonical_update` methods.

- [ ] **Step 1: Write failing repository tests**

```python
def test_find_profiles_scopes_alias_search_to_one_project(storybible_repository) -> None:
    storybible_repository.apply_canonical_update(profile(project_id="project-a", aliases=["Xia"]), plan_id="plan-a")
    storybible_repository.apply_canonical_update(profile(profile_id="p-2", project_id="project-b", aliases=["Xia"]), plan_id="plan-b")
    assert [item.profile_id for item in storybible_repository.find_profiles("project-a", "xia")] == ["p-1"]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run pytest tests/test_storybible_repository.py -v`

Expected: FAIL because `StoryBibleRepository` does not exist.

- [ ] **Step 3: Add models, migration, and repository**

```python
class StoryEntityProfileModel(Base):
    __tablename__ = "story_entity_profiles"
    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

def find_profiles(self, project_id: str, query: str) -> list[StoryEntityProfileV1]:
    rows = self._session.scalars(select(StoryEntityProfileModel).where(StoryEntityProfileModel.project_id == project_id)).all()
    return [profile for profile in map(self._profile_from_row, rows) if query.casefold() in {profile.canonical_name.casefold(), *(alias.casefold() for alias in profile.aliases)}]
```

Create profile, state, relationship, world-rule, and candidate-commit-plan tables with project indexes. The migration’s downgrade drops indexes before tables. Store plan content hashes and enforce a unique `(project_id, content_hash)` pair. Canonical writes update only when the stored revision is lower; equal plans return existing data.

- [ ] **Step 4: Run repository tests and migration smoke test**

Run: `uv run pytest tests/test_storybible_repository.py -v; uv run alembic upgrade head`

Expected: PASS; Alembic creates the five StoryBible tables without altering source tables.

- [ ] **Step 5: Commit persistence support**

```bash
git add comic_agent/database/models.py comic_agent/repositories/storybible_repository.py migrations/versions/0004_storybible_resources.py tests/test_storybible_repository.py
git commit -m "feat: persist StoryBible resources"
```

### Task 3: Enforce Curator Invariants and Canonical Commit Boundary

**Files:**
- Create: `comic_agent/services/storybible_validator.py`
- Modify: `comic_agent/services/commit_service.py`
- Modify: `comic_agent/services/context_builder.py`
- Test: `tests/test_storybible_commit_service.py`

**Interfaces:**
- Consumes: a `StoryBibleCuratorProposalV1`, `CommitPlanV1`, `StoryBibleRepository`, and a bounded list of source chunks.
- Produces: `StoryBibleValidator.validate_proposal`, `ContextBuilder.storybible_context`, and `CommitService.commit_storybible_plan(plan, repository)`.

- [ ] **Step 1: Write failing validation/commit tests**

```python
def test_commit_rejects_state_with_evidence_from_another_project(repository) -> None:
    plan = plan_with_state(evidence_refs=[EvidenceRefV1(chunk_id="project-b-chunk")])
    with pytest.raises(ValueError, match="project"):
        CommitService(repository).commit_storybible_plan(plan, repository)


def test_repeated_approved_plan_is_idempotent(repository) -> None:
    first = CommitService(repository).commit_storybible_plan(valid_plan(), repository)
    second = CommitService(repository).commit_storybible_plan(valid_plan(), repository)
    assert second == first
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_storybible_commit_service.py -v`

Expected: FAIL because the new commit method does not exist.

- [ ] **Step 3: Implement deterministic validation and commit**

```python
def commit_storybible_plan(self, plan: CommitPlanV1, repository: StoryBibleRepository) -> CommitPlanV1:
    StoryBibleValidator(self._evidence_lookup).validate_commit_plan(plan)
    existing = repository.get_plan_by_content_hash(plan.project_id, plan.content_hash)
    if existing is not None:
        return existing
    for update in plan.updates:
        repository.apply_canonical_update(update, plan.commit_plan_id)
    return repository.save_committed_plan(plan)
```

Reject missing evidence, cross-project evidence, an update that contains two incompatible values for the same entity/state/time anchor, and a state interval whose end precedes its start. `storybible_context` limits the request to caller-selected ids plus at most three adjacent states/relationships per profile.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_storybible_commit_service.py -v`

Expected: PASS; invalid plans leave all canonical table counts unchanged.

- [ ] **Step 5: Commit validation and commit boundary**

```bash
git add comic_agent/services/storybible_validator.py comic_agent/services/commit_service.py comic_agent/services/context_builder.py tests/test_storybible_commit_service.py
git commit -m "feat: validate and commit StoryBible plans"
```

### Task 4: Implement Provider-backed Proposal-only Curator

**Files:**
- Create: `comic_agent/agents/storybible_curator.py`
- Create: `comic_agent/providers/openai_compatible.py`
- Modify: `comic_agent/config.py`
- Create: `.env.example`
- Test: `tests/test_storybible_curator.py`
- Test: `tests/test_openai_compatible_provider.py`

**Interfaces:**
- Consumes: `StoryBibleContextV1`, `LLMProvider`, and `StoryBibleCuratorProposalV1` as the provider output schema.
- Produces: `StoryBibleCurator.run(context: StoryBibleContextV1) -> StoryBibleCuratorProposalV1` and `OpenAICompatibleProvider.structured_generate(request, output_model)`.

- [ ] **Step 1: Write failing curator/provider tests**

```python
def test_curator_returns_only_a_schema_valid_candidate(mock_provider) -> None:
    curator = StoryBibleCurator(mock_provider)
    proposal = curator.run(valid_context())
    assert proposal.commit_plan.project_id == "project-1"
    assert proposal.status == "CANDIDATE"


def test_openai_provider_never_sends_key_in_request_body(httpx_mock) -> None:
    provider = OpenAICompatibleProvider(base_url="https://api.example/v1", api_key="secret", model="deepseek-v4-pro")
    provider.structured_generate({"messages": [{"role": "user", "content": "x"}]}, OutputModel)
    assert httpx_mock.get_request().headers["Authorization"] == "Bearer secret"
    assert "secret" not in httpx_mock.get_request().content.decode()
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_storybible_curator.py tests/test_openai_compatible_provider.py -v`

Expected: FAIL because the Curator and configured provider do not exist.

- [ ] **Step 3: Implement the Curator and OpenAI-compatible provider**

```python
class StoryBibleCurator:
    spec = AgentSpec(agent_id="storybible-curator", version="1.0", reads=["StoryBibleContextV1"], output_schema="StoryBibleCuratorProposalV1", tools=[], can_write_canonical_data=False, requires_evidence=True, max_context_chunks=3, confidence_threshold=0.7)

    def run(self, context: StoryBibleContextV1) -> StoryBibleCuratorProposalV1:
        response = self._provider.structured_generate(self._request(context), StoryBibleCuratorProposalV1)
        return response.model_copy(update={"status": RecordStatus.CANDIDATE})
```

The provider posts to `{LLM_BASE_URL}/chat/completions`, sets `Authorization: Bearer <key>` only as a request header, asks for JSON object output, extracts `choices[0].message.content`, and validates it through the requested Pydantic model. `Settings` uses `LLM_BASE_URL`, `LLM_API_KEY`, `STORYBIBLE_MODEL=deepseek-v4-pro`, and `LLM_TIMEOUT_SECONDS=60`; no source file contains a real key.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_storybible_curator.py tests/test_openai_compatible_provider.py -v`

Expected: PASS; tests use mocked transport/provider only.

- [ ] **Step 5: Commit the Agent and configuration**

```bash
git add comic_agent/agents/storybible_curator.py comic_agent/providers/openai_compatible.py comic_agent/config.py .env.example tests/test_storybible_curator.py tests/test_openai_compatible_provider.py
git commit -m "feat: add StoryBible Curator agent"
```

### Task 5: Expose Bounded Curation and Resource Retrieval APIs

**Files:**
- Create: `comic_agent/api/storybible.py`
- Modify: `comic_agent/main.py`
- Test: `tests/test_storybible_api.py`

**Interfaces:**
- Consumes: `POST /projects/{project_id}/storybible/curate` with a bounded `StoryBibleContextV1` payload and `POST /projects/{project_id}/storybible/commit-plans/{plan_id}` with approval data.
- Produces: candidate curator proposal, idempotent committed plan, `GET /projects/{project_id}/storybible/profiles`, `GET /projects/{project_id}/storybible/profiles/{profile_id}`, and `GET /projects/{project_id}/storybible/profiles/{profile_id}/states?event_id=` resources.

- [ ] **Step 1: Write failing API tests**

```python
def test_profile_endpoint_does_not_cross_project_boundaries(client) -> None:
    response = client.get("/projects/project-a/storybible/profiles/profile-b")
    assert response.status_code == 404


def test_commit_endpoint_is_idempotent(client) -> None:
    first = client.post("/projects/project-1/storybible/commit-plans/plan-1")
    second = client.post("/projects/project-1/storybible/commit-plans/plan-1")
    assert first.json() == second.json()
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_storybible_api.py -v`

Expected: FAIL with 404 because no StoryBible router is registered.

- [ ] **Step 3: Implement authenticated-by-project API boundaries**

```python
@router.get("/projects/{project_id}/storybible/profiles/{profile_id}", response_model=StoryEntityProfileV1)
def get_profile(project_id: str, profile_id: str, repository: StoryBibleRepositoryDep) -> StoryEntityProfileV1:
    profile = repository.get_profile(project_id, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="StoryBible profile not found")
    return profile
```

Use a repository dependency that closes its session after each request. Curation endpoint creates candidates only; commit endpoint first verifies project ownership and explicit approval status, then calls `CommitService`. Retrieval endpoints never expose another project’s resource.

- [ ] **Step 4: Run API tests**

Run: `uv run pytest tests/test_storybible_api.py -v`

Expected: PASS; candidate curation causes no canonical writes until the commit endpoint runs.

- [ ] **Step 5: Commit the API**

```bash
git add comic_agent/api/storybible.py comic_agent/main.py tests/test_storybible_api.py
git commit -m "feat: expose StoryBible resources"
```

### Task 6: Run Full Regression and Document the New Contract

**Files:**
- Modify: `docs/schema_contracts.md`
- Modify: `docs/architecture.md`
- Modify: `docs/development_log.md`
- Test: all existing and new tests

**Interfaces:**
- Consumes: completed implementation and migration.
- Produces: current architecture and schema documentation, plus verified project quality gates.

- [ ] **Step 1: Write documentation assertions as a checklist**

```text
Schema contracts list the StoryBible types and CommitService as canonical owner.
Architecture says Curator is proposal-only and ContextBuilder bounds reads.
Development log names the migration, tests, and no-real-model testing policy.
```

- [ ] **Step 2: Run the complete quality suite before doc edits**

Run: `uv run pytest; uv run ruff check .; uv run mypy comic_agent; uv run python scripts/export_json_schemas.py`

Expected: all commands PASS; schema exports are generated but remain ignored.

- [ ] **Step 3: Update documentation**

Add the StoryBible contracts, proposed-to-canonical flow, migration `0004_storybible_resources`, and resource retrieval boundary to the three documentation files. State explicitly that Curator uses `deepseek-v4-pro` by default and no test makes a real provider request.

- [ ] **Step 4: Run the complete quality suite after documentation**

Run: `uv run pytest; uv run ruff check .; uv run mypy comic_agent; uv run alembic upgrade head`

Expected: all commands PASS; Alembic is at revision `0004_storybible_resources`.

- [ ] **Step 5: Commit verified documentation**

```bash
git add docs/schema_contracts.md docs/architecture.md docs/development_log.md
git commit -m "docs: document StoryBible Curator workflow"
```
