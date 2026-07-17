# Acceptance Criteria

## Weekly Criteria

### Week 1

- JSON Schema export works.
- Invalid enums and out-of-range confidence are rejected.
- Canonical story facts require EvidenceRef support.
- TXT import preserves source order.
- Repeated import is idempotent.
- Any SourceChunk can be located by chapter and source offsets.
- Docker Compose config is valid.
- Tests pass.

### Week 2

- Entity, event, temporal, reality-layer, and state proposals are evidence-backed.
- Merge/dedup services produce deterministic audit records.
- Character state can be queried by chapter/event.

### Week 3

- StoryBible and VisualBible are reviewable and freezeable.
- Character visual variants map to story time.
- Style assumptions are separated from source facts.

### Week 4

- Single panel/page generation works through provider interfaces.
- QA agents produce structured QAResult records.
- RepairPlan can trigger bounded local repair.

### Week 5

- One full chapter and one campus article workflow can run.
- Queue, checkpoint, and local recompute behaviors are observable.

### Week 6

- 100,000-character pressure test runs.
- Ablation results and final demo artifacts are ready.

## Component Criteria

Every component in `component_matrix.md` must define inputs, outputs, owner, tests, and failure behavior before implementation.
