# EntityExtractionAgent Batch V0.1 Summary

Last updated: 2026-08-05

## Contract

`entity_extraction` now returns `EntityProposalBatchV1`.

```text
EntityProposalBatchV1
batch_id
entities[]: EntityProposalV1
```

The number of entities is based on distinct significant entities supported by
the selected `SourceChunkV1` records, not chunk count. One chunk can produce
multiple entities, and three chunks can produce one entity when only one
distinct significant entity is present.

Each entity must have independent `EvidenceRefV1`. The agent must not write
StoryBible data or invent names, aliases, types, relationships, locations,
objects, abilities, factions, or facts.

## Sanitized Summary Fields

Automated smoke/API summaries may include:

```text
batch_id
entities_count
entity_proposal_ids
entity_evidence_results
quote_matched
char_range_matched
evidence_validation_passed
```

They must not include source text, `quote_text`, aliases, raw provider responses,
`message.content`, or API keys.

## Manual Eval Plan

Recommended current extraction model: `deepseek-chat`.

Manual real LLM eval is user-run only:

```text
B: Entity Batch, 1/2/3 chunks
C: Entity Batch + Claim Batch, 1/2/3 chunks
```

Record sanitized summary fields only. Do not paste `.env`, API keys, real source
text, long quotes, aliases, raw provider responses, or `message.content`.

## Quality Checklist

```text
entities_cover_major_entities
entity_count_reasonable
no_duplicate_entities
entity_types_correct
names_and_aliases_not_invented
every_entity_has_supporting_evidence
overall_pass
manual_issue
```
