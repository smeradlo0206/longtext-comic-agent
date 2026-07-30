# Phase 1 Workflow Status

This page is the lightweight website-facing status record for the phase-one mock
agent audit loop. It summarizes what is implemented, what remains out of scope,
and the latest sanitized local evaluation result. It does not include source
novel text, long quotes, databases, temporary files, or generated artifacts.

## Current Stage

Phase 1 Mock Agent Audit Loop plus a default-disabled real Event agent skeleton.

## Completed

- TXT import.
- Chapter parsing.
- SourceChunk persistence.
- EvidenceRef source validation.
- Initial Event / Claim / KnowledgeState Proposal schema.
- ContextBuilder bounded context.
- MockEventWorkflow.
- AgentRun persistence.
- Idempotent import and run checks.
- Local real-excerpt evaluation script with sanitized output.
- Default-disabled OpenAI-compatible LLM provider adapter.
- Minimal EventExtractionAgent producing `EventProposalV1` only.
- RealEventWorkflow audit wrapper with EvidenceRef validation.
- Dry-run smoke script for real LLM readiness checks.

## Not Completed

- Production real LLM extraction quality.
- Claim / KnowledgeState workflow integration.
- Canonical CommitService write for story facts.
- StoryBible.
- Merge and conflict resolution.
- Image generation.
- Frontend visualization beyond this documentation page.

## Agent Run Audit Loop

```text
SourceChunk
  -> ContextBuilder bounded context
  -> MockEventAgent through MockLLMProvider
  -> EventProposalV1
  -> CommitService EvidenceRef validation
  -> AgentRunV1 with ProviderResultV1
  -> AgentRunRepository persistence
```

The workflow records both successful and failed runs. Failed provider output,
provider timeouts, and EvidenceRef mismatches are preserved as failed
`AgentRunV1` records instead of writing canonical story data.

## Schema V1 Capability Matrix

| Capability | Status | Notes |
| --- | --- | --- |
| SourceDocument / SourceChapter / SourceChunk | Complete for TXT-only phase one | UTF-8 TXT import and stable chunk ids are covered by tests. |
| EvidenceRef validation | Complete for phase one | CommitService validates chunk existence, quote text, and quote ranges. |
| EventProposalV1 | Complete for phase-one proposal output | Includes explicit actor-resolution status. |
| ClaimProposalV1 | Schema available | Workflow integration is not implemented yet. |
| KnowledgeStateProposalV1 | Schema available | Lifecycle and workflow integration are not implemented yet. |
| ContextBuilder | Complete for bounded SourceChunk context | Uses explicit chunk ids and max chunk limits. |
| MockEventWorkflow | Complete for mock audit loop | Uses MockLLMProvider only. |
| EventExtractionAgent | Skeleton available | Can call an injected provider and produce `EventProposalV1`; default real provider use is disabled. |
| RealEventWorkflow | Skeleton available | Requires `ENABLE_REAL_LLM=true` and explicit script opt-in before any real call. |
| AgentRunRepository | Complete for phase-one audit persistence | Saves full `AgentRunV1` payload idempotently. |

## Real LLM Readiness

Real model calls are off by default. Local configuration is described in
[Real LLM Setup](real_llm_setup.md). The readiness smoke script records only
sanitized metadata, such as counts, ids, character ranges, hashes, and whether a
provider call was attempted. It must not publish source text, long quotes, or API
keys.

```text
SourceChunk
  -> ContextBuilder bounded context
  -> EventExtractionAgent
  -> OpenAICompatibleLLMProvider only when explicitly enabled
  -> EventProposalV1
  -> CommitService EvidenceRef validation
  -> AgentRunV1 with ProviderResultV1
  -> AgentRunRepository persistence
```

## Latest Automated Test Result

Local verification snapshot from 2026-07-30:

| Check | Result |
| --- | --- |
| `uv run ruff check comic_agent tests scripts` | Passed |
| `uv run mypy comic_agent` | Passed |
| `uv run pytest` | 162 passed, 1 dependency deprecation warning |
| `uv run python scripts/export_json_schemas.py` | Passed |

## Sanitized Real Excerpt Evaluation

The local evaluation used a Project Gutenberg public-domain text:

- text_source_type: public_domain
- source_url: `https://www.gutenberg.org/ebooks/11`
- title: Alice's Adventures in Wonderland
- author: Lewis Carroll
- license_status: Public domain in the USA via Project Gutenberg
- selected excerpt range: first two normalized chapter sections

No source text, full chapter, or long quote is published here. Evidence is
represented only by ids, character ranges, and hashes.

| Metric | Result |
| --- | --- |
| total_chars | 22512 |
| chapters_count | 2 |
| chunks_count | 56 |
| selected_chunks_count | 3 |
| evidence_validation_passed | true |
| agent_run_saved | true |
| import_idempotent | true |
| run_idempotent | true |
| failed_case_recorded | true |

Selected chunk metadata:

| chunk_id | char_start | char_end | chunk_hash |
| --- | ---: | ---: | --- |
| `chunk_26aae95e92efc01a` | 33 | 335 | `600bdab65955e200fa617c761f571acf77d941c4bf400bc55e345e93c241bf0a` |
| `chunk_565f1991442dc8fa` | 337 | 626 | `c8dd7c004e99d9e6fcd240ace4654075555d206003cc4f8fae3c0d97e50e31db` |
| `chunk_cb9ad39b1651c57e` | 628 | 1367 | `95fda77292270b350163f38f43ae27d6e88b482f47c707c01bd06861efd9e3f2` |

## Local Evaluation Boundary

- Full local text is expected at `local_eval/novel_excerpt.txt`.
- Local evaluation output is written to `output/evaluations/`.
- `local_eval/`, `output/`, `tmp/`, databases, caches, and `schema_exports/` are
  ignored and must not be committed.
- The script `scripts/evaluate_phase1_real_excerpt.py` is safe to commit because
  it contains no novel text and emits sanitized summaries only.
