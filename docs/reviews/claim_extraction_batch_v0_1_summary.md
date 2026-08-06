# ClaimExtractionAgent Batch V0.1 Summary

Last updated: 2026-08-06

## Contract

`claim_extraction` now returns `ClaimProposalBatchV1`. Fresh outputs use
`schema_version="1.2"` at both the batch and claim item level.

```text
ClaimProposalBatchV1
batch_id
claims[]: ClaimProposalV1
```

The number of claims is based on distinct salient claims supported by the
selected `SourceChunkV1` records, not chunk count. One chunk can produce multiple
claims, and three chunks can produce one claim when only one distinct salient
claim is present.

Each claim must have independent `EvidenceRefV1`. The agent must not write
StoryBible data, invent speakers or verification state, or treat ordinary
actions, events, or entity names as claims.

V1.2 claim types are:

```text
FACTUAL_ASSERTION
BELIEF
HYPOTHESIS
DENIAL
ACCUSATION
MEMORY
EVALUATION
INTERPRETATION
PREDICTION
COMMITMENT
```

Every v1.2 claim must include `temporal_scope`: `PAST`, `PRESENT`, `FUTURE`, or
`ATEMPORAL`. `FACTUAL_ASSERTION` cannot be a fallback: use `HYPOTHESIS` for a
hedged inference, `BELIEF` for an explicit non-tentative mental stance,
`EVALUATION` for quality/strength/difficulty/value judgement, and
`INTERPRETATION` for a causal, motive, or meaning explanation. Legacy `ASSERTION`
remains readable only for historical `schema_version="1.0"` payloads, and v1.1
payloads remain readable.

## Sanitized Summary Fields

Automated smoke/API summaries may include:

```text
batch_id
claims_count
claim_proposal_ids
claim_evidence_results
quote_matched
char_range_matched
evidence_validation_passed
```

`claim_evidence_results` includes sanitized `claim_type`, `source_type`, and
`temporal_scope`. It must not include `claim_text` or `quote_text`.

They must not include source text, `quote_text`, `claim_text`, raw provider
responses, `message.content`, or API keys.

## Manual Eval Plan

Recommended current extraction model: `deepseek-chat`.

Manual real LLM eval is user-run only:

```text
C: Entity Batch + Claim Batch, 1/2/3 chunks
E: Claim Batch, 1/2/3 chunks, plus KnowledgeState prep notes
```

Record sanitized summary fields only. Do not paste `.env`, API keys, real source
text, long quotes, `claim_text`, raw provider responses, or `message.content`.

## Quality Checklist

```text
claims_cover_major_claims
claim_count_reasonable
no_duplicate_claims
claim_is_attributable_proposition
claim_type_matches_decision_table
factual_assertions_are_unhedged
belief_and_hypothesis_distinguished
evaluation_and_interpretation_distinguished
claim_temporal_scope_correct
prediction_commitment_distinguished
every_claim_has_supporting_evidence
no_duplicate_or_invented_claims
overall_pass
manual_issue
```
