# Timeline Gold Set

This directory benchmarks TimelineAgent reasoning quality, not API availability.

The only evaluated relations are `BEFORE`, `AFTER`, `SIMULTANEOUS`, `OVERLAPS`,
and `UNKNOWN`. `UNKNOWN` is a correct safety label when the supplied evidence does
not establish a reliable story-time relation. Text, chapter, and chunk order are
not story-time facts.

Each JSONL record embeds production `EventProposalV1` payloads and source chunks.
Its evidence is checked through `CommitService` before TimelineAgent runs.

Current production conflict labels cover only contradictory claims and state changes
that reference a missing event. Duplicate labels use the production exact-key rule:
event type, normalized summary, participants, location, and reality layer.
Duplicate checks use independent claim pairs so they do not make the temporal pair
simultaneously carry an ambiguous duplicate-event label.

Run locally without network:

```powershell
python scripts\eval_timeline.py --mode rules
```

Run the explicit real-provider baseline:

```powershell
python scripts\eval_timeline.py --mode llm
python scripts\eval_timeline.py --mode all
```

Long LLM runs print per-case progress and ETA. Network-only retries are opt-in, and a
partially completed artifact directory can be resumed without rerunning successful cases:

```powershell
python scripts\eval_timeline.py --mode llm --network-retries 1
python scripts\eval_timeline.py --mode all --resume artifacts\timeline_eval\RUN_ID
```

Per-class accuracy is recall for that Gold class. The unsupported temporal assertion
rate is the fraction of Gold `UNKNOWN` cases predicted as a non-`UNKNOWN` relation.
Reports distinguish successful-case accuracy, attempted-case accuracy, execution success
rate, and network/provider/evidence failure categories.
