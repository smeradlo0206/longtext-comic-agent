# GitHub Issue Drafts

## 1. Lock V1 Schema Export Contract
- Background: Schema is the cross-agent contract.
- Goal: Export JSON Schema for all V1 models.
- Input: `comic_agent/schemas`.
- Output: `schema_exports/*.json`.
- Not doing: New domain fields.
- Allowed directories: `comic_agent/schemas`, `scripts`, `tests`.
- Dependencies: none.
- Acceptance: export script exits 0.
- Tests: `uv run python scripts/export_json_schemas.py`, `uv run pytest tests/test_source_schemas.py`.
- Owner: A
- Labels: `area:schema`, `type:feature`, `priority:p0`, `week:1`
- Week: 1

## 2. Harden EvidenceRef Validation
- Background: Evidence drives fidelity.
- Goal: Validate quote ranges and nonblank text.
- Input: EvidenceRef requirements.
- Output: validation tests.
- Not doing: quote text matching.
- Allowed directories: `comic_agent/schemas`, `tests`.
- Dependencies: Issue 1.
- Acceptance: invalid ranges fail.
- Tests: `uv run pytest tests/test_source_schemas.py`.
- Owner: A
- Labels: `area:schema`, `type:feature`, `week:1`
- Week: 1

## 3. Implement TXT Chapter Detection
- Background: TXT import is MVP path.
- Goal: Detect Chinese and English chapter headings.
- Input: TXT text.
- Output: SourceChapter records.
- Not doing: EPUB/PDF.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Issue 1.
- Acceptance: Chinese/English/default chapter tests pass.
- Tests: `uv run pytest tests/test_document_parser.py`.
- Owner: B
- Labels: `area:backend`, `type:feature`, `week:1`
- Week: 1

## 4. Implement SourceChunk Idempotency
- Background: repeated imports must not duplicate facts.
- Goal: Deterministic document/chunk ids and DB unique constraints.
- Input: ParsedDocument.
- Output: ImportResult status.
- Not doing: cross-project dedup.
- Allowed directories: `comic_agent/repositories`, `comic_agent/database`, `tests`.
- Dependencies: Issue 3.
- Acceptance: importing same file twice creates one document.
- Tests: `uv run pytest tests/test_idempotent_import.py`.
- Owner: B
- Labels: `area:backend`, `type:feature`, `priority:p0`, `week:1`
- Week: 1

## 5. Create Project And Import API
- Background: demo needs HTTP workflow.
- Goal: Add `/projects` and import routes.
- Input: Project JSON and multipart TXT.
- Output: persisted source records.
- Not doing: auth.
- Allowed directories: `comic_agent/api`, `comic_agent/main.py`, `tests`.
- Dependencies: Issues 3-4.
- Acceptance: API test can create, upload, query.
- Tests: `uv run pytest tests/test_health.py`.
- Owner: B
- Labels: `area:backend`, `type:feature`, `week:1`
- Week: 1

## 6. Add Docker Compose Infrastructure
- Background: local infra must start consistently.
- Goal: Compose api/postgres/redis/minio.
- Input: `.env.example`.
- Output: valid Compose config.
- Not doing: production hardening.
- Allowed directories: root config files.
- Dependencies: none.
- Acceptance: `docker compose config` exits 0.
- Tests: `docker compose config`.
- Owner: B
- Labels: `area:backend`, `type:feature`, `week:1`
- Week: 1

## 7. Add Mock LLM Provider Modes
- Background: tests must avoid real LLMs.
- Goal: success/schema-error/timeout behavior.
- Input: configured response.
- Output: structured model or deterministic error.
- Not doing: network calls.
- Allowed directories: `comic_agent/providers`, `tests`.
- Dependencies: Issue 1.
- Acceptance: mock provider tests pass.
- Tests: `uv run pytest tests/test_mock_providers.py`.
- Owner: B
- Labels: `area:backend`, `type:feature`, `week:1`
- Week: 1

## 8. Add Mock Image Provider
- Background: visual pipeline needs a provider seam.
- Goal: deterministic generate/edit result.
- Input: provider-neutral request.
- Output: mock image URI.
- Not doing: real image generation.
- Allowed directories: `comic_agent/providers`, `tests`.
- Dependencies: none.
- Acceptance: no network call needed.
- Tests: `uv run pytest tests/test_mock_providers.py`.
- Owner: C
- Labels: `area:visual`, `type:feature`, `week:1`
- Week: 1

## 9. Write Fidelity Policy
- Background: novel mode must be strict.
- Goal: document CANON_STRICT rules.
- Input: product principles.
- Output: `docs/fidelity_policy.md`.
- Not doing: legal policy.
- Allowed directories: `docs`.
- Dependencies: none.
- Acceptance: all flags documented.
- Tests: docs review.
- Owner: A
- Labels: `type:docs`, `area:story`, `week:1`
- Week: 1

## 10. Create Component Matrix
- Background: four-person work split needs clarity.
- Goal: map components to schemas and owners.
- Input: six-week plan.
- Output: `docs/component_matrix.md`.
- Not doing: staffing assignments beyond A/B/C/D.
- Allowed directories: `docs`.
- Dependencies: none.
- Acceptance: required components listed.
- Tests: docs review.
- Owner: B
- Labels: `type:docs`, `area:workflow`, `week:1`
- Week: 1

## 11. Entity Proposal Agent Shell
- Background: Week 2 starts story extraction.
- Goal: define shell using BaseAgent and EntityProposalV1.
- Input: SourceChunk context.
- Output: EntityProposalV1.
- Not doing: real model prompt.
- Allowed directories: `comic_agent/agents`, `tests`.
- Dependencies: Week 1 schemas.
- Acceptance: mock entity proposal validates.
- Tests: targeted agent test.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:2`
- Week: 2

## 12. Event Proposal Agent Shell
- Background: events drive timeline and state.
- Goal: event agent shell with EvidenceRef.
- Input: SourceChunk context.
- Output: EventProposalV1.
- Not doing: canonical commit.
- Allowed directories: `comic_agent/agents`, `tests`.
- Dependencies: Week 1 schemas.
- Acceptance: mock event proposal validates.
- Tests: event agent test.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:2`
- Week: 2

## 13. Coreference Proposal Pass
- Background: aliases must merge safely.
- Goal: propose entity merge candidates.
- Input: EntityProposalV1 list.
- Output: merge proposal payload.
- Not doing: automatic destructive merge.
- Allowed directories: `comic_agent/agents`, `tests`.
- Dependencies: Issue 11.
- Acceptance: ambiguous references stay unresolved.
- Tests: coreference fixture test.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:2`
- Week: 2

## 14. Event Dedup Service
- Background: parallel extraction can duplicate events.
- Goal: deterministic dedup candidate grouping.
- Input: EventProposalV1 list.
- Output: grouped event ids.
- Not doing: semantic LLM merge.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Issue 12.
- Acceptance: exact duplicate grouped.
- Tests: dedup unit test.
- Owner: B
- Labels: `area:backend`, `area:story`, `type:feature`, `week:2`
- Week: 2

## 15. Temporal Relation Agent Shell
- Background: event order must be explicit.
- Goal: produce TemporalRelationProposalV1.
- Input: event pair context.
- Output: temporal proposal.
- Not doing: graph solve.
- Allowed directories: `comic_agent/agents`, `tests`.
- Dependencies: Issue 12.
- Acceptance: self-loop rejected.
- Tests: schema and agent tests.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:2`
- Week: 2

## 16. Temporal Solver MVP
- Background: proposals need deterministic consistency checks.
- Goal: build simple graph validator.
- Input: TemporalRelationProposalV1.
- Output: temporal graph diagnostics.
- Not doing: complex probabilistic solve.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Issue 15.
- Acceptance: contradictory cycles flagged.
- Tests: solver unit test.
- Owner: B
- Labels: `area:workflow`, `type:feature`, `week:2`
- Week: 2

## 17. State Change Agent Shell
- Background: character state depends on events.
- Goal: produce StateChangeProposalV1.
- Input: EventProposalV1 and chunks.
- Output: state change proposal.
- Not doing: full compiler.
- Allowed directories: `comic_agent/agents`, `tests`.
- Dependencies: Issue 12.
- Acceptance: target path and evidence required.
- Tests: state proposal test.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:2`
- Week: 2

## 18. Character State Compiler MVP
- Background: users need state queries.
- Goal: apply persistent state changes in temporal order.
- Input: StateChangeProposalV1.
- Output: CharacterStateV1.
- Not doing: ambiguous conflict resolution.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Issues 16-17.
- Acceptance: state query by event works.
- Tests: compiler unit test.
- Owner: B
- Labels: `area:backend`, `area:story`, `type:feature`, `week:2`
- Week: 2

## 19. StoryBible Freeze Workflow
- Background: humans must approve story canon.
- Goal: add review/freeze status shell.
- Input: canonical story data.
- Output: frozen StoryBible artifact.
- Not doing: UI.
- Allowed directories: `comic_agent/workflows`, `docs`, `tests`.
- Dependencies: Week 2.
- Acceptance: freeze prevents further automatic mutation.
- Tests: workflow unit test.
- Owner: A
- Labels: `area:workflow`, `area:story`, `type:feature`, `week:3`
- Week: 3

## 20. StyleBible Schema Extension
- Background: visual planning needs style contracts.
- Goal: add minimal StyleBible schema.
- Input: project style choices.
- Output: StyleBibleV1.
- Not doing: provider prompts.
- Allowed directories: `comic_agent/schemas`, `docs`, `tests`.
- Dependencies: schema review.
- Acceptance: JSON Schema export includes StyleBible.
- Tests: schema export and validation.
- Owner: C
- Labels: `area:schema`, `area:visual`, `type:feature`, `week:3`
- Week: 3

## 21. Character Visual Variant Schema
- Background: character continuity needs visual states.
- Goal: define variant schema tied to CharacterState.
- Input: CharacterStateV1.
- Output: CharacterVisualVariantV1.
- Not doing: image generation.
- Allowed directories: `comic_agent/schemas`, `tests`.
- Dependencies: Issue 20.
- Acceptance: variants reference source state.
- Tests: schema validation.
- Owner: C
- Labels: `area:schema`, `area:visual`, `type:feature`, `week:3`
- Week: 3

## 22. StoryBeat Translation Rules
- Background: scenes need adaptation units.
- Goal: create conservative translation service shell.
- Input: SceneSpecV1 and chunks.
- Output: StoryBeatV1.
- Not doing: creative rewriting.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: StoryBible freeze.
- Acceptance: CANON_STRICT defaults `new_story_information=false`.
- Tests: story beat unit test.
- Owner: A
- Labels: `area:story`, `type:feature`, `week:4`
- Week: 4

## 23. PageSpec Schema And Planner Shell
- Background: pages organize panels.
- Goal: add PageSpec and simple planner contract.
- Input: StoryBeatV1.
- Output: PageSpecV1.
- Not doing: final layout engine.
- Allowed directories: `comic_agent/schemas`, `comic_agent/agents`, `tests`.
- Dependencies: Issue 22.
- Acceptance: page bounds validated.
- Tests: schema/planner test.
- Owner: C
- Labels: `area:visual`, `area:schema`, `type:feature`, `week:4`
- Week: 4

## 24. Prompt Compiler Isolation
- Background: provider fields must stay out of PanelSpec.
- Goal: compile PromptSpec from PanelSpec.
- Input: PanelSpecV1.
- Output: PromptSpecV1.
- Not doing: model routing.
- Allowed directories: `comic_agent/services`, `comic_agent/schemas`, `tests`.
- Dependencies: Issue 23.
- Acceptance: provider data appears only in PromptSpec.
- Tests: prompt compiler test.
- Owner: C
- Labels: `area:visual`, `type:feature`, `week:4`
- Week: 4

## 25. QAResult And RepairPlan Workflow
- Background: repair must be structured.
- Goal: connect QAResult failures to bounded RepairPlan.
- Input: QAResultV1.
- Output: RepairPlanV1.
- Not doing: real redraw.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Week 4 panel generation.
- Acceptance: hard failure creates repair plan with max attempts.
- Tests: repair planner test.
- Owner: D
- Labels: `area:qa`, `type:feature`, `week:4`
- Week: 4

## 26. Campus News 4-8 Panel Mode
- Background: MVP includes campus/news mode.
- Goal: produce compact factual panel plan.
- Input: CAMPUS_NEWS ProjectSpec and article chunks.
- Output: 4-8 PanelSpec records.
- Not doing: real image generation.
- Allowed directories: `comic_agent/services`, `tests`, `docs`.
- Dependencies: Week 4 panel planner.
- Acceptance: no unsupported real-person visual facts.
- Tests: campus mode test.
- Owner: C
- Labels: `area:visual`, `area:story`, `type:feature`, `week:5`
- Week: 5

## 27. Dependency Recompute Service
- Background: local repair requires dependency tracking.
- Goal: model dependency edges and affected nodes.
- Input: changed node id.
- Output: recompute task list.
- Not doing: distributed queue.
- Allowed directories: `comic_agent/services`, `tests`.
- Dependencies: Week 4 workflow.
- Acceptance: panel change recomputes dependent page QA.
- Tests: recompute unit test.
- Owner: B
- Labels: `area:workflow`, `type:feature`, `week:5`
- Week: 5

## 28. 100k Import Pressure Fixture
- Background: Week 6 needs scale evidence.
- Goal: generate synthetic long TXT fixture and import timing test.
- Input: synthetic text generator.
- Output: pressure report.
- Not doing: copyrighted text.
- Allowed directories: `tests`, `scripts`, `docs`.
- Dependencies: import MVP.
- Acceptance: import completes within agreed budget.
- Tests: pressure test command.
- Owner: D
- Labels: `area:qa`, `type:feature`, `week:6`
- Week: 6
