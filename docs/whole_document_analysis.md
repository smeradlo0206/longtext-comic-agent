# Whole-Document Narrative Analysis

## Normal Flow

1. Import a TXT document.
2. Select the imported document in the Narrative Analyst Console.
3. Choose one or more implemented modes: `event_extraction`,
   `entity_extraction`, or `claim_extraction`.
4. Start whole-document analysis and inspect progress, grouped proposal results,
   Evidence audit links, and linked AgentRuns.

Chunks remain an internal unit for context bounds and evidence locations. The
normal task API intentionally does not accept manually supplied chunk ids.
Manual chunk selection is retained under Advanced debug mode for diagnosis.

## Execution Model

The v0.1 task is persisted before execution. It uses deterministic overlapping
windows with `window_size=3`, `stride=2`, and fixed concurrency one. For five
chunks, the windows are `[0,1,2]` and `[2,3,4]`; a tail window is added whenever
needed to cover the final chunk.

Each mode/window is independently auditable with its selected chunk ids, status,
linked AgentRun id when present, and sanitized failure message. A failed window
does not block remaining windows. The final task state is `SUCCEEDED`,
`PARTIAL_FAILED`, or `FAILED`.

Use `GET /narrative-analysis-runs/{analysis_run_id}/windows` or the console's
**Window execution details** table to inspect every execution. Each record
contains only the mode, window index, chunk ids, status, AgentRun id, sanitized
error category and message, recommended action, attempt count, effective input
budget, prior failure category, and a fixed allowlist of provider diagnostics
such as `finish_reason`, content type, reasoning flag, and usage token counts.
Schema failures additionally report only the Pydantic error kind, field paths,
and expected output schema. It never returns source chunk text, quote text,
provider response content, or credentials.

The **Window execution details** table is intentionally wider than the normal
console content. It has its own horizontal viewport, visible scrollbar, and
left/right controls. Use the scrollbar, a horizontal swipe, or the controls to
inspect every audit column without compressing or hiding a failure field.

The worker makes at most one automatic retry for a recoverable failed attempt.
For `PROVIDER_LENGTH_BEFORE_FINAL_CONTENT`, it lowers only that window's input
budget from 1200 to 800 characters per chunk. For
`SCHEMA_VALIDATION_FAILED`, it retries once at the same budget after the Batch
JSON-only boundary has been enforced. Retry history remains on the window. A
failed retry remains failed; validation is never bypassed. Explicit resume still
selects only `PENDING` or `FAILED` windows and never reruns a successful window.

Provider transport retries are separate from the window retry. The provider
retries one transient `429` or `5xx` response once; it never automatically
retries `400`, `401`, `403`, or `404`. Window diagnostics retain only
`http_status_code` and `request_attempts`. Recommended operator actions are
status-specific: wait before resuming for `429`, wait briefly for `5xx`, check
model/request settings for `400`, local credential/access configuration for
`401`/`403`, and endpoint/model naming for `404`.

The worker is sequential and in-process. A service restart interrupts active
work, but persisted task and window state remains. Resume reruns only `PENDING`
or `FAILED` windows and never reruns successful windows.

## Aggregation

Results use typed Pydantic schemas and retain proposal, AgentRun ids, and
EvidenceRef values. Aggregation is intentionally conservative:

- Event proposals merge only when normalized event type, summary, and evidence
  all match.
- Entity proposals merge only when normalized canonical name and entity type
  match; their evidence references are retained.
- Claim proposals merge only when type, text, source type, and evidence all
  match.

No similarity-based merge creates a canonical fact. The task does not call
CommitService, write StoryBible, or write other canonical data.

## Dry-Run and Manual Real Evaluation

Whole-document analysis defaults to dry-run and therefore never calls a
provider. A real provider request needs both the explicit console checkbox and
server-side `ENABLE_REAL_LLM=true`. This setting is loaded by the API process;
after changing it locally, restart the API before using the console checkbox.
When the server gate is off, normal whole-document requests are rejected before
any windows are created, rather than creating a task whose windows cannot call a
provider. Keep real evaluation manual and use only sanitized task summaries for
records.

Do not commit or paste `.env`, API keys, full source text, quotes, raw provider
responses, `message.content`, local evaluation output, or database files.

## API

- `GET /projects/{project_id}/documents`
- `POST /projects/{project_id}/documents/{document_id}/narrative-analysis-runs`
- `GET /narrative-analysis-runs/{analysis_run_id}`
- `GET /narrative-analysis-runs/{analysis_run_id}/windows`
- `GET /narrative-analysis-runs/{analysis_run_id}/result`
- `POST /narrative-analysis-runs/{analysis_run_id}/resume`

The existing `POST /projects/{project_id}/agent-runs/narrative-analyst` remains
an internal/debug endpoint for explicit chunk selection.

## Manual Console Acceptance

Run these checks only with an authorized local TXT. Do not paste its contents,
quotes, API key, provider response, or `message.content` into notes or commits.

### 1. Start the local console

In one PowerShell terminal:

```powershell
cd D:\107
uv run uvicorn comic_agent.main:app --reload
```

In a second PowerShell terminal:

```powershell
cd D:\107
python -m http.server 8080 --directory web_console
```

Open `http://127.0.0.1:8080`. Create or choose a project, import the authorized
TXT, then click **Load documents** in Narrative Analyst Console. Select the
document and one or more modes. Do not enter chunk ids in the normal flow.

### 2. Dry-run acceptance

Leave **real LLM requested** unchecked and start a task with all three modes.
The expected outcome is:

- `SUCCEEDED` after every planned window completes;
- `concurrency=1`, `window_size=3`, and `stride=2` in progress metadata;
- for five chunks, two windows per selected mode, with the final chunk covered;
- zero provider calls, no AgentRun proposal results, and an empty aggregated
  Proposal List; and
- no API key, raw provider response, full chunk text, or `message.content` in
  the browser.

Open **Advanced debug: manual chunk selection** only when diagnosing a specific
window. The normal whole-document API does not accept `chunk_ids`.

### 3. Manual real-provider acceptance

This is a manual opt-in test. Configure only your local environment, then start
a fresh API process:

```powershell
cd D:\107
$env:ENABLE_REAL_LLM = 'true'
$env:LLM_MODEL = 'deepseek-v4-pro'
$env:LLM_RESPONSE_FORMAT = ''
$env:LLM_TIMEOUT_SECONDS = '360'
$env:LLM_MAX_OUTPUT_TOKENS = '3000'
uv run uvicorn comic_agent.main:app --reload
```

The API key remains in local configuration; do not place it in this command or
the console. In the browser, explicitly check **real LLM requested**, choose a
document and one mode, and start the task. The expected outcome is one AgentRun
per successful mode/window, then a typed aggregate result with proposal items,
AgentRun ids, Evidence chunk ids, and short quote previews. Add modes only after
the one-mode run is satisfactory.

For each proposal, use the AgentRun/Evidence views to confirm that the Evidence
chunk id belongs to the selected document and that the short quote supports the
proposal. Entity v1.1 reviews should confirm `CREATURE` versus `CHARACTER` and
that `creature_subtype` is source-supported or null.

### 4. Failure and resume acceptance

If a real window fails, allow the task to finish. It should be `PARTIAL_FAILED`
when at least one other window succeeds. Click **Resume failed windows** after
the provider is ready. Successful windows keep their existing AgentRun ids;
only pending or failed windows are retried. A service restart is equivalent to
an interruption: restart the API, refresh progress, and use the same resume
action.
