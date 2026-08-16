# Whole-Document Narrative Analysis

## Knowledge State aggregation compatibility

Whole-document result payloads may include `knowledge_states`. Older v1.0 result
payloads that omit the field deserialize with `knowledge_states=[]`. Aggregation
does not resolve text references: different resolved/unresolved states, status,
basis, reality layer, target, subject, or temporal anchors remain separate.
It also keeps candidates separate when their target text differs, even if their
proposal ids happen to match across windows. Review UI must pair a Proposal id
with AgentRun context; a proposal id is batch-scoped rather than a global
canonical identifier. Empty batches remain successful windows.

`KNOWS + OBSERVED` is limited to an explicitly observed, recognized, discovered,
or confirmed concrete fact. Presence, an uninspected object, a rumor, or narrator
knowledge does not establish a character's knowledge of hidden content.

Knowledge State `target_kind` means the semantic type of the cognitive target,
not the speaking source or the subject's epistemic status. Use `EVENT` only for
a concrete occurrence/discovery/change/action, `WORLD_FACT` for a proposition
or fact state, and `CLAIM` only for a statement/report/rumor/declaration/
accusation/promise as the target. `HEARD` therefore does not imply `CLAIM`.
`target_text` uses the smallest complete, auditable core proposition: for a
world-fact target, `山中有鬼的传言` is normalized to `山中有鬼`; the statement or
rumor frame is retained only when it is itself the `CLAIM` target.

## Normal Flow

1. Import a TXT document.
2. Select the imported document in the Narrative Analyst Console.
3. Choose one or more implemented modes: `event_extraction`,
   `entity_extraction`, `claim_extraction`, `knowledge_state_extraction`, or
   `state_change_extraction`.
4. Start whole-document analysis and inspect progress, grouped proposal results,
   Evidence audit links, and linked AgentRuns.

Chunks remain an internal unit for context bounds and evidence locations. The
normal task API intentionally does not accept manually supplied chunk ids.
Manual chunk selection is retained under Advanced debug mode for diagnosis.

## Execution Model

The v0.1 task is persisted before execution. It uses deterministic overlapping
windows with `window_size=3`, `stride=2`, and fixed concurrency one. For five
chunks, the context windows are `[0,1,2]` and `[2,3,4]`; a tail window is added whenever
needed to cover the final chunk. Ownership is assigned deterministically in source
order: the first leaf owns `[0,1,2]`, while the second reads `[2,3,4]` but owns only
`[3,4]`. `chunk_ids` are context; `owned_chunk_ids` are the only source chunks whose
proposals may enter whole-document aggregation. Every chunk has exactly one initial
owner, and overlap is never an additional output owner.

Each mode/window is independently auditable with its selected chunk ids, status,
linked AgentRun id when present, and sanitized failure message. A failed window
does not block remaining windows. The final task state is `SUCCEEDED`,
`PARTIAL_FAILED`, or `FAILED`.

Use `GET /narrative-analysis-runs/{analysis_run_id}/windows` or the console's
**Window execution details** table to inspect every execution. Each record
contains only the mode, context chunk ids, owned chunk ids, parent/child lineage,
split reason, status, AgentRun id, sanitized
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
For `PROVIDER_LENGTH_BEFORE_FINAL_CONTENT` on a multi-SourceChunk window, it
first records the failed parent and deterministically splits it into one child
window per parent-owned SourceChunk. Each child may read the parent context but
owns only its one source chunk; it receives complete text (no character slicing
across a chunk boundary) and is processed independently. The parent is marked
`SPLIT` with lineage and reason; deterministic child IDs make this recovery
idempotent, and a resume never reruns successful children. A
single-SourceChunk length failure retains the existing one retry, lowering only
that window's input budget from 1200 to 800 characters per chunk. For
`SCHEMA_VALIDATION_FAILED`, it retries once at the same budget after the Batch
JSON-only boundary has been enforced. State Change retries may include only safe
rule codes such as `STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER`; quantity old/new
values must be JSON numbers and the provider receives a fixed source-free marker.
The worker never coerces values, drops valid siblings, or persists raw output.
Retry history remains on the window. A
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
- Knowledge-state proposals merge only when their complete resolution-aware
  subject, target, status, basis, reality-layer, and temporal-anchor semantics
  match. An empty batch is a successful window and contributes no candidates.
- State-change proposals merge only when event and target text, kinds, resolutions,
  candidate links, attribute path, type-sensitive old/new values, persistence, and
  reality layer all match. `changes=[]` is a successful window and contributes no
  candidates. No fuzzy merge, automatic entity/event resolution, or fact adjudication
  is performed.

The Console can flag a deterministic, narrow **可能重复** review hint for two
otherwise comparable Knowledge State candidates whose safely normalized core
target matches but whose target kind or original expression differs. It only
normalizes Unicode, outer quotes, whitespace, terminal punctuation, and the
outer wrappers `传言`/`传闻`/`说法`/`消息`. The hint preserves every candidate and
its Proposal id, AgentRun/evidence audit context, resolution state, and review
decision. It never performs fuzzy matching, embedding/LLM comparison,
canonicalization, automatic linking, resolution upgrade, deletion, rewriting,
or merge.

No similarity-based merge creates a canonical fact. The task does not call
CommitService, write StoryBible, or write other canonical data.

`NarrativeAnalysisResultV1` fresh output is v1.4 and includes `state_changes` and
`relationship_signals` alongside `knowledge_states`. Historical v1.0/v1.1/v1.2/v1.3 JSON
result payloads remain readable; missing new lists default to `[]`. 无需数据库迁移：新增字段只存在于兼容的 JSON 聚合结果中。
The State Change Console audit table is separate from the Knowledge State table and shows
event/target resolution, attribute path, old/new values, persistence evidence indexes,
AgentRun context, and Evidence audit access.

State Change v1.3 adds the CHARACTER-only `appearance.clothing` and
`appearance.hairstyle` paths. Event remains the instantaneous cause while State Change is
the resulting reusable state; `persistent=false` means no explicit continuing/permanent
support, not that the state immediately ends. No canonical write, automatic resolution,
fuzzy merge, or semantic repair is performed.

Relationship Signal Schema Contract v1.0 is an implemented proposal-only
`relationship_signal_extraction` mode. It supports binary CHARACTER /
ORGANIZATION participants, controlled relationship kind/domain/directionality, source
basis, polarity, support level, optional speaker/context event, temporal anchors and
EvidenceRef. It runs through the existing bounded workflow, worker recovery/resume, deterministic
window ownership/split lineage, exact aggregation, API and dedicated Console audit table. The first
EvidenceRef determines leaf ownership; no fuzzy deduplication is used. Unresolved
references remain null-linked and the schema performs no database lookup or fuzzy linking.
This additive JSON aggregation field requires no database migration. Relationship Signal remains
Proposal-only and never writes a canonical relationship, StoryBible, or CommitService record.

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

## Offline Knowledge State evaluation is separate from whole-document analysis

The Console's **Knowledge State 评测** section is not a whole-document workflow and
does not read imported chapters, aggregate results, AgentRuns, or provider payloads.
It lists only bundled synthetic/redacted fixtures, accepts a manually supplied typed
batch, and runs deterministic comparison locally on the API service. Loading the
section never calls a Provider. A real-LLM fixture execution remains an explicitly
checked, server-gated option and is not part of regression tests.

This separation keeps whole-document aggregation conservative: semantic candidates
are only merged by the existing complete key. Offline evaluation adds no canonical
state, no database tables, and no migration requirement.

The separate evaluation section can collect the newest structured Batch for each
case in browser memory and submit those batches to the read-only batch-report
endpoint. `KnowledgeStateEvaluationReportV1` is a cross-case quality summary, not
a whole-document result and not an AgentRun. Generating or exporting it never
calls a Provider and does not persist the report.

When a real fixture run cannot produce a valid Knowledge State Batch, whole-document
analysis is unaffected: the evaluation Console records a sanitized run failure,
keeps its `case_id`, and includes it in the report. It does not fabricate an empty
Batch, write a canonical fact, or silently remove the case from totals.

## Automatic Review Gate 2 routing boundary

After a whole-document Narrative Analyst run is `SUCCEEDED`, all leaf windows are successful,
and its aggregate result is persisted, `NarrativeAnalysisReviewCoordinator` builds one
`ReviewGate2InputV1` from the six aggregate lists: Event, Entity, Claim, Knowledge State, State
Change, and Relationship Signal. It preserves original Proposal values, mode/schema, AgentRun
ids, aggregated EvidenceRef values, project/document/analysis-run identity, and only the
Gate 1-approved SourceChunks actually used by the run. It does not scan a database for context,
use raw provider responses, text similarity, embedding, or automatic canonical links.

The typed `ReviewGate2ResultV1` and `NarrativeAnalysisReviewRouteV1` are persisted inside the
existing analysis-run JSON payload. Empty input produces a valid empty APPROVED bundle. An
APPROVED route alone exposes the readonly `ApprovedProposalBundleV1` endpoint; rejected routes
keep only safe diagnostics, human-review routes keep held Proposal ids, and failed reviews expose
no bundle. Gate 2 failures do not change the completed Narrative Analyst status. Resume/re-entry
does not rerun a persisted valid Gate 2 audit. There is no Review Agent, semantic LLM reviewer,
automatic remediation, total-control state machine, Timeline, StoryBible Curator, or CommitService.
Stage B recovery is separate and bounded: it may rerun only the original
mode and leaf window with the same ordered Gate 1-approved SourceChunk scope, policy budget, and
AgentRun provenance. Each rerun is reviewed by fresh Gate 2; it never overwrites old Proposal,
AgentRun, or Gate 2 artifacts, writes canonical StoryBible data, or calls CommitService. Recovery
attempts are non-canonical audits in `narrative_analysis_recovery_attempts`, created by Alembic
migration `0006_narrative_analysis_recovery_attempts` after the Timeline migration.
The automatic coordinator invokes Gate 2 with a SourceChunk and AgentRun context bounded and
complete for that review only. Duplicate context chunk ids, context chunks outside the declared
allowed scope, and AgentRun-analysis mappings outside the known AgentRun set fail the entire
review with a sanitized execution issue and no bundle. Missing context for Evidence that is still
within the allowed scope remains a Proposal-level `EVIDENCE_CHUNK_NOT_FOUND` rejection; Gate 2
does not read repositories or databases to fill it. The input builder does not accept a separate
AgentRun parameter, and repeated identical input/context/policy calls are deterministic except for
UTC audit timestamps.

## Automatic import to analysis

The normal console path is TXT import → Gate 1 review → chapter selection → one-click
Narrative Analyst. Omitted modes default to all six implemented extraction modes, while
the coordinator computes the exact approved chunk intersection server-side. Rejected or
human-review imports cannot start analysis; this flow remains proposal-only.

## Future Review Gate 1 source-quality boundary

After TXT import and chunking, a future worker may build `ReviewGate1InputV1` from the parsed
SourceDocument, SourceChapter, SourceChunk records and an in-memory normalized-text snapshot.
The input intentionally accepts quality anomalies so a deterministic Gate 1 service can report
duplicate ids/orders, scope mismatches, checksum/range errors, whitespace-only chunks, chapter
gaps, and overlaps without losing the audit record. It must not include Provider output or expose
the normalized text in a Result/Bundle/log.

Gate 1 counts newline runs only after CRLF/CR to LF normalization. Under policy v1.1,
four newline characters are warning-only layout whitespace while five or more require
human review; these are fixed policy literals. Explicit v1.0 policies retain the
historical four-newline review boundary.

Only an APPROVED `ApprovedSourceChunkBundleV1` may be handed to Orchestrator/ContextBuilder;
REJECTED, pending, or failed Gate 1 results halt whole-document analysis. Gate 1 does not perform
semantic review, fuzzy text deduplication, automatic repair, LLM calls, canonical writes, or
database persistence. The synchronous `ReviewGate1Service.review()` now executes this
deterministic review and returns source-free metrics plus bounded routing advice. TXT import now
invokes it automatically; only APPROVED results persist. The chapter coordinator authorizes
downstream analysis without automatic repair or human-review persistence. No database migration
is required.
