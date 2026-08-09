# Task 5 Recovery Report — StoryBible Curation and Retrieval API

## Requirements checked

- `POST /projects/{project_id}/storybible/curate` accepts bounded `StoryBibleContextV1`, rejects path/body, nested-resource, source-chunk, and evidence project mismatches, and persists only a candidate commit plan.
- `POST /projects/{project_id}/storybible/commit-plans/{plan_id}` looks up the plan with the path project, requires `{"status": "APPROVED"}`, and delegates canonical promotion exclusively to `CommitService`.
- Retry of an approved commit is idempotent.
- Profile collection, profile item, and profile state resources are project-scoped. State lookup honors the optional `event_id` filter.
- The repository session is request-local and closed by the dependency generator.

## TDD evidence

The interrupted implementation already contained its production code and its new test file when recovery began, so a historical RED run could not be honestly reproduced without discarding or temporarily altering the inherited work. Static baseline inspection confirmed that `HEAD` did not register a StoryBible router. The inherited API tests were then run unchanged as the GREEN evidence:

```text
.venv\\Scripts\\python.exe -m pytest tests\\test_storybible_api.py -v
10 passed, 1 warning
```

The tests exercise candidate-only curation, explicit approval, idempotency, project isolation for context/commit/retrieval, and event-filtered states. No real model or network call was made: the API fixture replaces the app curator with `MockLLMProvider`.

## Files in scope

- `comic_agent/api/storybible.py` — bounded curate, approved commit, and project-scoped retrieval routes.
- `comic_agent/main.py` — StoryBible curator configuration and router registration.
- `comic_agent/repositories/storybible_repository.py` — stable, project-scoped profile listing.
- `tests/test_storybible_api.py` — API-boundary regression coverage.

## Verification

```text
.venv\\Scripts\\python.exe -m pytest tests\\test_storybible_api.py -v  # 10 passed
.venv\\Scripts\\python.exe -m pytest -q                               # 94 passed, 1 skipped
.venv\\Scripts\\python.exe -m ruff check [Task 5 files]               # all checks passed
.venv\\Scripts\\python.exe -m mypy comic_agent                        # success, no issues in 47 files
git diff --check                                                        # clean
```

## Self-review and concerns

- Canonical writes are reachable from this API only through `CommitService.commit_storybible_plan`; candidate-plan persistence is non-canonical and idempotent by project/content hash.
- `StoryBibleContextV1` remains the schema source for bounded input and `StoryBibleCuratorProposalV1` for agent output; no standalone API schemas were introduced.
- The full test run has one pre-existing deprecation warning from FastAPI/Starlette's `TestClient` use of `httpx`; it is unrelated to this task.
- No commit has been created yet: explicit approval is required before committing the scoped Task 5 changes.
