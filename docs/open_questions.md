# Open Questions

| Question | Recommended Temporary Choice | Impact |
| --- | --- | --- |
| Should EPUB be supported? | Defer; TXT first, DOCX interface reserved. | Keeps parser scope small. |
| Page reading direction? | Store project-level `reading_direction`; default LTR. | Allows later RTL/manga support. |
| First version color or black-and-white? | Do not decide; VisualBible freeze decides. | Avoids hardcoding style. |
| Image API provider? | Keep `ImageProvider` abstract. | Provider can change without PanelSpec change. |
| Budget ceiling? | Optional `budget_limit`; no hard enforcement yet. | Cost policy can be added later. |
| Maximum characters/entities? | Record as runtime limits later. | Avoids premature DB constraints. |
| Is faithful compression allowed? | Allow visual compression only in CANON_STRICT. | Keeps plot facts intact. |
| Multi-world timelines? | Use `RealityLayer`; defer complex world ids. | Migratable minimal design. |
| Campus real-person reference policy? | Require team/legal decision before using reference images. | Avoids privacy misuse. |
