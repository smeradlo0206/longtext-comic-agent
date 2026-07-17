# Domain Glossary

| Term | Definition | Positive Example | Negative Example |
| --- | --- | --- | --- |
| SourceChunk | Small ordered source text unit with checksum and char range. | Paragraph 7 in Chapter 2. | A summary written by an agent. |
| EvidenceRef | Pointer from a fact to a SourceChunk and optional quote range. | `chunk-1`, chars 4-12. | "The model remembers this." |
| Entity | Canonical thing in the story world. | Lin Xia, old library, blue umbrella. | A pronoun mention alone. |
| Character | Person-like Entity whose state can change. | Lin Xia. | The school gate as a place. |
| Event | Story-world occurrence. | Chen Ye gives Lin Xia an umbrella. | The sentence that describes the event. |
| NarrativeMention | Textual mention of an entity/event. | "she" referring to Lin Xia. | The canonical Lin Xia entity. |
| Scene | Coherent story unit with location, time, and participants. | Playground after rain. | One camera shot. |
| StoryBeat | Adaptation unit carrying a scene meaning into pages/panels. | "Lin Xia hesitates before accepting help." | Raw source paragraph. |
| TemporalRelation | Relation between events. | Event A BEFORE Event B. | Chapter order without event ids. |
| RealityLayer | Layer such as primary, dream, imagined, flashback. | Dream sequence marked DREAM. | Treating a fantasy as primary fact. |
| StateChange | Event-caused mutation. | Umbrella moves from Chen Ye to Lin Xia. | Lin Xia's whole inventory timeline. |
| CharacterState | Compiled state over an interval. | Lin Xia holds umbrella after event E. | One isolated quote. |
| KnowledgeState | What a character knows at story time. | Lin Xia knows the map exists. | Reader-only exposition. |
| StyleBible | Frozen style rules. | Black-and-white campus manga style. | A single prompt. |
| CharacterVisualVariant | Visual state for a character at a time. | Raincoat Lin Xia, Chapter 1. | Generic "girl" prompt. |
| PageSpec | Provider-neutral page plan. | Page 3 has four panels. | Image model prompt. |
| PanelSpec | Provider-neutral panel requirements. | Must show umbrella handoff. | `model_name=gpt-image`. |
| Proposal | Agent output awaiting validation/commit. | EventProposalV1. | Canonical database row. |
| Canonical Data | Approved formal project fact. | Committed Event record. | Agent draft. |
| QAResult | Structured quality check result. | Character continuity pass/fail. | Free-form reviewer note only. |
| RepairPlan | Bounded instruction for fixing a failed target. | Redraw panel region x/y/w/h. | "Make it better." |
| DependencyEdge | Recompute relationship. | Panel depends on CharacterState. | Informal task note. |

## Key Distinctions

- Event vs NarrativeMention: Event is what happened in the story world; NarrativeMention is how text refers to it.
- StateChange vs CharacterState: StateChange is a mutation; CharacterState is the compiled result over time.
- Scene vs StoryBeat: Scene is source-grounded structure; StoryBeat is adaptation planning.
- PanelSpec vs PromptSpec: PanelSpec is provider-neutral; PromptSpec may contain provider-specific prompt fields.
- Proposal vs Canonical Data: Proposal is submitted by agents; Canonical Data is written only through commit rules.
