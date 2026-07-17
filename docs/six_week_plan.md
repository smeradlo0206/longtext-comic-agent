# Six Week Plan

## Week 1: Schema, Import, Database, Engineering Foundation

- Goal: create schemas, source import, DB skeleton, API skeleton, CI.
- A: define core story schemas and evidence policy.
- B: implement FastAPI, SQLAlchemy, Docker Compose, import MVP.
- C: define provider-neutral visual contracts.
- D: define QA and repair schemas plus golden fixtures.
- Dependencies: none.
- Deliverables: current repository scaffold.
- Acceptance: Week 1 criteria pass.
- Risk: dependency setup delays; fallback to SQLite tests and generated issue scripts.

## Week 2: Story Compilation Agents, Temporal Graph, Character State

- A: entity/event/time/state proposal agents.
- B: merge, dedup, temporal solver, state compiler shells.
- C: early visual implications from state.
- D: fidelity QA cases for extraction.
- Dependencies: Week 1 schemas and chunks.
- Deliverables: queryable story graph prototype.
- Acceptance: chapter-level proposals with evidence.
- Risk: ambiguity; fallback to unresolved proposal states.

## Week 3: StoryBible, VisualBible, Visual Assets

- A: StoryBible synthesis and freeze workflow.
- B: versioning and approval gates.
- C: StyleBible, character variants, asset registry.
- D: review checklists and consistency tests.
- Dependencies: Week 2 canonical story data.
- Deliverables: frozen StoryBible and VisualBible samples.
- Acceptance: human review can approve/reject.
- Risk: style scope creep; fallback to limited style presets.

## Week 4: Panel, Page, Image Generation, QA And Repair Loop

- A: narrative-to-beat rules.
- B: workflow orchestration and cost records.
- C: PageSpec, PanelSpec, PromptSpec, provider integration.
- D: multidimensional QA and RepairPlan.
- Dependencies: Week 3 frozen bibles.
- Deliverables: one-page generation loop with mocks/selected provider.
- Acceptance: failed panel can be repaired locally.
- Risk: provider instability; fallback to mocks and recorded fixtures.

## Week 5: Full Chapter, Campus Mode, Queue, Checkpoint, Local Recompute

- A: chapter adaptation fidelity rules.
- B: queue, checkpoint, dependency recompute.
- C: campus templates and layout variants.
- D: chapter QA and regression suite.
- Dependencies: Week 4 loop.
- Deliverables: full chapter and campus article demo.
- Acceptance: restart and local recompute work.
- Risk: runtime cost; fallback to shorter chapter.

## Week 6: Stress Test, Ablation, Demo And Defense

- A: 100,000-character annotation audit.
- B: performance, cost, reliability reports.
- C: final visual polish and export.
- D: ablation and evaluation report.
- Dependencies: all prior weeks.
- Deliverables: final demo, slides, metrics.
- Acceptance: demo path is rehearsed and reproducible.
- Risk: integration drift; fallback to scripted demo with saved artifacts.
