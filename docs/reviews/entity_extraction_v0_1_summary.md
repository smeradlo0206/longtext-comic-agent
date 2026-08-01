# EntityExtractionAgent V0.1 Summary

Last updated: 2026-08-01

## Scope

`EntityExtractionAgent` v0.1 is the second Narrative Analyst mode. It is a
bounded proposal-only agent:

- reads selected `SourceChunkV1` context from caller-provided `input_context`;
- calls external models only through the `LLMProvider` interface;
- outputs only `EntityProposalV1`;
- requires at least one `EvidenceRefV1`;
- does not write canonical StoryBible data;
- does not implement workflow, API, or web console entrypoints.

## Current Implementation

Implemented:

- `comic_agent/agents/entity_extraction.py`;
- `ENTITY_EXTRACTION_SYSTEM_PROMPT`;
- `EntityExtractionAgent.spec`;
- `EntityExtractionAgent.run(input_context) -> EntityProposalV1`;
- fake provider tests in `tests/test_entity_extraction_agent.py`.

The prompt asks for exactly one source-grounded entity and requires conservative
handling of names, aliases, entity type, and evidence quotes.

## Test Status

Automatic tests use a fake provider only. They cover:

- provider call wiring;
- `EntityProposalV1` return validation;
- prompt boundaries and forbidden output types;
- bounded proposal-only `AgentSpec`.

No real LLM evaluation has been executed for this mode yet.

## Pending Manual Real Eval

Recommended manual sequence:

1. 1 chunk real eval.
2. 2 chunk real eval.
3. 3 chunk real eval.

Each run should record only sanitized status fields such as schema validity,
evidence validity, quote match, entity type quality, canonical name quality, and
overall pass/fail.

## Safety Boundary

Do not paste or commit:

- `.env`;
- API keys or key fragments;
- real source text or long quotes;
- raw provider responses;
- `message.content`;
- local evaluation outputs;
- database files.
