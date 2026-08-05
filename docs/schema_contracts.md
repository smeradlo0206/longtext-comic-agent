# Schema Contracts

All V1 schemas use `schema_version = "1.0"` and live in `comic_agent/schemas`.

| Schema | Purpose | Required Fields | Evidence | Readers | Proposal Producer | Canonical Commit |
| --- | --- | --- | --- | --- | --- | --- |
| BaseRecordV1 | Common record metadata. | id, project_id, revision, status, timestamps, created_by | N/A | Services | Services | CommitService |
| EvidenceRefV1 | Source traceability pointer. | chunk_id | Optional range/quote; supplied values must match the referenced chunk | All story agents | All story agents | CommitService validates |
| ProjectSpecV1 | Project policy. | id, name, type, fidelity flags | N/A | All services | API/user | SourceRepository |
| SourceDocumentV1 | Source file metadata. | document_id, project_id, checksum, storage_uri | N/A | Importer, agents | DocumentParser | SourceRepository |
| SourceChapterV1 | Chapter boundary. | chapter_id, document_id, order | N/A | Agents, API | DocumentParser | SourceRepository |
| SourceChunkV1 | Evidence atom. | chunk_id, document_id, chapter_id, text, checksum | Self | All agents | DocumentParser | SourceRepository |
| EntityProposalV1 | Candidate entity. | proposal_id, type, name, evidence_refs, confidence | Required | Merge services | Entity agents | CommitService later |
| EventProposalV1 | Candidate event. | proposal_id, type, non-empty summary, non-empty evidence_refs, confidence | At least one reference required; persisted with CANDIDATE status | Temporal/state agents | Event agent | CommitService later |
| TemporalRelationProposalV1 | Candidate event relation. | proposal_id, source, target, relation, confidence | Required unless UNKNOWN | Temporal solver | Temporal agent | CommitService later |
| StateChangeProposalV1 | Candidate state mutation. | proposal_id, event_id, target, path, evidence_refs | Required | State compiler | State agent | CommitService later |
| CharacterStateV1 | Compiled character state. | state_id, character_id, reality_layer | Derived from changes | Story/visual agents | State compiler | CommitService later |
| SceneSpecV1 | Source-grounded scene. | scene_id, chapter_id, chunks, layer, purpose | Via chunks | Translation agents | Narrative translator | CommitService later |
| StoryBeatV1 | Adaptation beat. | beat_id, scene_id, chunks, meaning, visual_expression | Via chunks | Page/panel agents | Narrative translator | CommitService later |
| PanelSpecV1 | Provider-neutral panel plan. | panel_id, page_id, scene_id, chunks, shot fields | Via chunks | Prompt compiler | Panel director | CommitService later |
| QAResultV1 | Quality check result. | qa_result_id, target, scores, passed | Target-dependent | Repair planner | QA agents | QA service |
| RepairPlanV1 | Repair instruction. | repair_plan_id, target_id, type, instruction | Target-dependent | Repair executor | Repair planner | Repair service |
| AgentRunV1 | Immutable record of one agent execution. | run id, project, input chunk, agent, status | Links one input chunk to an optional output proposal | API, audit services | Agent runner | N/A |

Field types are implemented directly in Pydantic. The JSON Schema export script is the authoritative machine-readable contract.

## StoryBible Task 1 Compatibility and Migration Note

Task 1 additively introduces the public `schema_version = "1.0"` StoryBible contracts:
`StoryBibleContextV1`, `StoryEntityProfileV1`, `StoryEntityStateV1`,
`StoryRelationshipV1`, `WorldRuleV1`, the four StoryBible update proposal types,
`StoryBibleUpdateV1`, `ConflictV1`, `CommitPlanV1`, and
`StoryBibleCuratorProposalV1`. Existing V1 schemas and fields are unchanged, so this is a
backward-compatible schema addition.

Task 1 defines and exports Pydantic and JSON Schema contracts only. It makes no database
schema change and requires no database migration. StoryBible persistence tables and their
migration are deferred to the persistence task.
