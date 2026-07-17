# Component Matrix

| Component | Type | Input Schema | Output Schema | Dependency | Owner | Acceptance | Week |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Document Importer | Program | TXT | SourceDocument/Chapter/Chunk | Storage | B | Idempotent import | 1 |
| Entity Extraction Agent | Agent | SourceChunk | EntityProposal | Document Importer | A | Evidence-backed proposals | 2 |
| Coreference Agent | Agent | EntityProposal | EntityProposal | Entity Extraction | A | Merge suggestions only | 2 |
| Event Extraction Agent | Agent | SourceChunk | EventProposal | Document Importer | A | Evidence-backed events | 2 |
| Temporal Relation Agent | Agent | EventProposal | TemporalRelationProposal | Event Extraction | A | No self loops | 2 |
| Reality Layer Agent | Agent | SourceChunk | SceneSpec | Document Importer | A | DREAM/PRIMARY separated | 2 |
| State Change Agent | Agent | EventProposal | StateChangeProposal | Event Extraction | A | Evidence-backed changes | 2 |
| Entity Merge | Program | EntityProposal | Canonical Entity | Coreference | B | Deterministic merge log | 2 |
| Event Dedup | Program | EventProposal | Canonical Event | Event Extraction | B | Duplicate-safe | 2 |
| Temporal Solver | Program | TemporalRelationProposal | Temporal Graph | Temporal Agent | B | Consistent graph | 2 |
| State Compiler | Program | StateChangeProposal | CharacterState | Temporal Solver | B | Queryable state | 2 |
| StoryBible Generation | Program/Agent | Canonical story data | StoryBible | State Compiler | A | Human freeze ready | 3 |
| Style Planning Agent | Agent | ProjectSpec | StyleBible | Product policy | C | Reviewable style rules | 3 |
| Character Visual Agent | Agent | CharacterState | CharacterVisualVariant | StyleBible | C | Variant timeline | 3 |
| Narrative Translation Agent | Agent | SceneSpec | StoryBeat | StoryBible | A | No new story info | 4 |
| Page Planning Agent | Agent | StoryBeat | PageSpec | Narrative Translation | C | Page count bounds | 4 |
| Panel Director Agent | Agent | PageSpec | PanelSpec | Page Planning | C | Provider-neutral panels | 4 |
| Visual Asset Retriever | Program | PanelSpec | Asset refs | VisualBible | C | Deterministic lookup | 4 |
| Prompt Compiler | Program | PanelSpec | PromptSpec | Asset Retriever | C | Provider fields isolated | 4 |
| Model Router | Program | PromptSpec | Provider request | Prompt Compiler | B | Cost policy applied | 4 |
| Image Provider | Provider | Provider request | Image result | Model Router | C | Mockable interface | 4 |
| Original Fidelity QA | Agent | Panel/Page | QAResult | Image Provider | D | Hard fails on unsupported facts | 4 |
| Image/Text QA | Agent | Panel/Page | QAResult | Image Provider | D | Text matches beat | 4 |
| Character Continuity QA | Agent | Panel/Page | QAResult | CharacterState | D | Variant consistency | 4 |
| World State QA | Agent | Panel/Page | QAResult | State Compiler | D | World facts consistent | 4 |
| Visual Quality QA | Agent | Image result | QAResult | Image Provider | D | Quality threshold | 4 |
| Repair Planning Agent | Agent | QAResult | RepairPlan | QA Agents | D | Bounded repair plan | 4 |
| Page Layout Engine | Program | Panel images | Page image | PanelSpec | C | Exportable page | 4 |
| Dependency Recompute Service | Program | DependencyEdge | Workflow tasks | Workflow runs | B | Local recompute works | 5 |
