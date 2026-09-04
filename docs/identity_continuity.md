# Identity Continuity

## Problem

Passing line art independently to every panel produced different color interpretations. Passing
the entire prior panel reduced identity drift, but also copied old poses and could keep characters
standing after the source said they sat down. A shared seed had the same composition-locking bias.

## AUTO Anchor Flow

1. `LongTextComicCompiler` emits one `IdentityAnchorSpec` per selected character entity.
2. The queue worker loads FLUX.2 once and generates isolated portrait-oriented color anchors.
3. Each panel reference is resolved by `entity_id` and its source path is replaced by the generated
   anchor path. The number and ordering of Provider images do not change.
4. Panels use independent deterministic seeds. Character anchors stabilize identity, scene assets
   stabilize space, and current source evidence controls pose and action.
5. `plan.json` records anchor prompts and inputs. `result.json` records attempts, timings, and files.

`identity_anchor_mode=OFF` preserves historical workflow behavior. `AUTO` is explicit in production
requests because an automatically generated anchor should be inspected before expensive chapters.

## Remaining Boundary

An anchor is reference conditioning, not a trainable identity token. For strict production use,
approve anchors before panel execution, train a character LoRA where appropriate, and add a visual
QA Provider that can reject identity or cast-count violations and enqueue selective repairs.
