# Product Scope

## Goal

Build a high-fidelity long-text comic generation system for long original novels, campus news, promotional copy, and notices. The system must preserve source facts, keep every story fact traceable to source evidence, and use agents only for proposals.

## Six-Week MVP

- Import and structure a 100,000-character novel.
- Query character state and temporal relations for any chapter.
- Generate a 12-20 page continuous comic for one 3,000-5,000 character chapter.
- Generate a 4-8 panel comic for one campus news article or notice.
- Support QA, local repair, checkpoint recovery, and cost accounting.

## Novel Mode

Novel mode defaults to `CANON_STRICT`. It permits medium translation such as panel compression and dialogue splitting, but does not permit new events, new dialogue, character changes, or event reordering.

## Campus News And Notice Mode

Campus mode uses fact-grounded adaptation. It may simplify presentation for clarity, but must not invent people, activities, times, locations, or institutional claims.

## Not In Scope

The startup phase does not implement real LLM calls, real image API calls, complete story compilation agents, model training, complete frontend, or full 100,000-character processing.

## Human Freeze Points

- StoryBible freeze: humans review and approve canonical entities, events, temporal graph, and state rules.
- VisualBible freeze: humans review and approve style, character variants, recurring locations, props, and visual constraints.

## Final Competition Demo

The demo should show source import, traceable evidence, StoryBible/VisualBible review, chapter comic generation, multi-agent QA, local repair, and campus-news 4-8 panel generation.
