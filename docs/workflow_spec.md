# Workflow Spec

## Development-Time Flow

Schema definition -> Agent contracts -> Database and workflow design.

Schema changes are synchronization points. Agent contracts may evolve in parallel after schema approval. Database and workflow changes must follow schema compatibility review.

## Runtime Flow

File import -> chapters and SourceChunks -> per-chapter parallel extraction -> whole-book entity merge -> event dedup -> temporal graph -> state compilation -> StoryBible audit/freeze -> VisualBible generation/freeze -> chapter narrative translation -> page planning -> panel generation -> world-state resolution -> visual asset retrieval -> image generation -> multidimensional QA -> repair loop -> page composition -> chapter QA -> full-book QA -> export.

## Parallel Steps

Per-chapter extraction, QA checks, visual asset retrieval, and independent panel generation can run in parallel after their dependencies are ready.

## Synchronization Points

Schema approval, whole-book entity merge, event dedup, temporal graph solve, StoryBible freeze, VisualBible freeze, chapter QA, and full-book QA are synchronization points.

## Serial Steps

Import before extraction, entity merge before canonical character state, StoryBible before VisualBible, PanelSpec before PromptSpec, and QA before repair execution must remain serial.

## Failure Returns

- Schema validation failure returns to the producing agent/service.
- Evidence failure returns to extraction.
- Temporal contradiction returns to temporal relation proposals.
- Visual QA failure returns to repair planning or panel generation.
- Chapter QA failure returns to the smallest failed panel/page node.

## Idempotent Nodes

File import, chunk creation, proposal submission, provider request recording, QA result recording, repair attempts, and dependency recompute must be idempotent.
