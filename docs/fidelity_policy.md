# Fidelity Policy

Novel projects default to `CANON_STRICT`:

- `allow_new_events = false`
- `allow_new_dialogue = false`
- `allow_character_change = false`
- `allow_event_reordering = false`
- `allow_visual_compression = true`
- `allow_dialogue_splitting = true`
- `require_source_traceability = true`

## Medium Translation

Allowed translation includes panel compression, camera choice, visualizing implied posture, splitting long dialogue across balloons, and converting narration into captions when every story fact remains traceable.

## Tampering

Tampering includes adding events, deleting key events, changing motives, inventing dialogue, changing relationships, reordering cause/effect, or visually asserting unsupported facts as canon.

## Psychological Description

Inner states may be shown through expression, posture, lighting, or captions only when grounded in source text. Ambiguous inner states must remain ambiguous.

## Ambiguous Characters And Unreliable Narration

Ambiguous mentions stay as unresolved proposals until evidence supports merging. Unreliable narration is recorded with reality/credibility metadata rather than converted into unquestioned primary fact.

## Dreams And Hypotheses

Dreams, imagined scenes, hypotheticals, flashbacks, and inserts must carry a `RealityLayer` and must not update primary-world state unless the source explicitly says they do.

## Dialogue

Key dialogue should be preserved word-for-word. Splitting across balloons is allowed; rewriting meaning is not.

## Unsupported Visual Facts

Visual details without direct source support must be marked as adaptation assumptions or style defaults and must not become canonical story facts.
