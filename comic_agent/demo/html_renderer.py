"""Render a complete Demo artifact as one offline-safe HTML file."""

# HTML/CSS template lines intentionally remain intact for readable emitted markup.
# ruff: noqa: E501

import html
import json
from pathlib import Path
from typing import Any


def _h(value: object) -> str:
    return html.escape(str(value), quote=True)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence(items: list[dict[str, Any]]) -> str:
    quotes = [_h(item.get("quote_text")) for item in items if item.get("quote_text")]
    return "" if not quotes else f'<p class="evidence">Evidence: {" · ".join(quotes)}</p>'


class DemoHtmlRenderer:
    """Build a responsive, self-contained presentation without external assets."""

    def render(self, artifact_dir: Path) -> Path:
        summary = _load(artifact_dir / "summary.json")
        narrative = _load(artifact_dir / "narrative.json")
        timeline = _load(artifact_dir / "timeline.json")
        storybible = _load(artifact_dir / "storybible.json")
        scenes = _load(artifact_dir / "comic_plan.json")
        panels = _load(artifact_dir / "panels.json")
        entities = storybible.get("bundle", {}).get("entities", [])
        characters = [item for item in entities if item.get("entity_kind") == "PERSON"]
        states = storybible.get("bundle", {}).get("state_changes", [])
        events = narrative.get("events", [])
        event_by_id = {item.get("proposal_id"): item for item in events}
        panels_by_scene: dict[str, list[dict[str, Any]]] = {}
        for panel in panels:
            panels_by_scene.setdefault(str(panel.get("scene_id")), []).append(panel)

        input_name = Path(str(summary.get("input", "input.txt"))).name
        run_id = artifact_dir.name
        body = self._document(
            summary=summary,
            input_name=input_name,
            run_id=run_id,
            characters=characters,
            states=states,
            events=events,
            event_by_id=event_by_id,
            timeline=timeline,
            scenes=scenes,
            panels=panels,
            panels_by_scene=panels_by_scene,
        )
        output = artifact_dir / "demo.html"
        output.write_text(body, encoding="utf-8")
        return output

    def _document(self, **data: Any) -> str:
        summary = data["summary"]
        characters, events = data["characters"], data["events"]
        scenes, panels = data["scenes"], data["panels"]
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LongText → Comic Demo</title><style>{self._css()}</style></head>
<body><nav><a href="#overview">Overview</a><a href="#characters">Characters</a><a href="#timeline">Timeline</a><a href="#storyboard">Storyboard</a></nav>
<main><header id="overview"><p class="eyebrow">OFFLINE DEMO ARTIFACT</p><h1>LongText <span>→</span> Comic Demo</h1>
<p class="lede">A traceable journey from source narrative to comic storyboard.</p>
<div class="stats"><b>{len(characters)}<small>Characters</small></b><b>{len(events)}<small>Events</small></b><b>{len(scenes)}<small>Scenes</small></b><b>{len(panels)}<small>Panels</small></b></div>
<div class="meta"><span>Input <strong>{_h(data["input_name"])}</strong></span><span>Run ID <strong>{_h(data["run_id"])}</strong></span><span>Provider Mode <strong>{_h(summary.get("provider_mode", "unknown"))}</strong></span></div></header>
{self._provenance(summary)}
<section id="characters"><div class="section-head"><p>CAST</p><h2>Characters</h2></div><div class="character-grid">{self._characters(characters, data["states"])}</div></section>
<section id="events"><div class="section-head"><p>NARRATIVE</p><h2>Story Events</h2></div><div class="events">{self._events(events)}</div></section>
<section id="timeline"><div class="section-head"><p>SEQUENCE</p><h2>Timeline</h2></div>{self._timeline(data["timeline"], data["event_by_id"])}</section>
<section id="storyboard"><div class="section-head"><p>COMIC PLAN</p><h2>Scenes &amp; Panels</h2></div>{self._scenes(scenes, data["panels_by_scene"], data["event_by_id"])}</section>
</main><footer>Generated from a local Demo artifact · No backend required</footer>
<script>document.querySelectorAll('.scene-title').forEach(b=>b.addEventListener('click',()=>b.closest('.scene').classList.toggle('collapsed')));</script></body></html>"""

    @staticmethod
    def _provenance(summary: dict[str, Any]) -> str:
        items = [
            ("Narrative", summary.get("narrative_source")),
            ("Timeline", summary.get("timeline_source")),
            ("StoryBible", summary.get("storybible_source")),
            ("Comic Planning", summary.get("comic_plan_status")),
        ]
        cards = "".join(
            f'<div><span>{_h(label)}</span><strong class="badge {_h(value or "unknown")}">{_h(value or "UNKNOWN")}</strong></div>'
            for label, value in items
        )
        note = ""
        if summary.get("timeline_source") == "DEMO_FALLBACK":
            note = (
                "<details><summary>Timeline provenance details</summary><p>Real provider attempted. "
                "The response did not satisfy the production schema contract, so the demo "
                "continued with a deterministic timeline derived from the real Narrative analysis.</p></details>"
            )
        return f'<section class="provenance"><div class="section-head"><p>EXECUTION</p><h2>Execution Provenance</h2></div><div class="provenance-grid">{cards}</div>{note}</section>'

    @staticmethod
    def _characters(characters: list[dict[str, Any]], states: list[dict[str, Any]]) -> str:
        cards = []
        for character in characters:
            current = [
                item.get("state")
                for item in states
                if item.get("profile_id") == character.get("profile_id")
            ]
            aliases = character.get("aliases") or []
            details = f"<p><b>Aliases</b> {', '.join(map(_h, aliases))}</p>" if aliases else ""
            if current:
                details += f"<p><b>Current state</b> {_h(current[-1])}</p>"
            cards.append(
                f'<article class="character"><div class="avatar">{_h(str(character.get("canonical_name", "?"))[:1])}</div><h3>{_h(character.get("canonical_name", "Unknown"))}</h3><p class="muted">{_h(character.get("entity_kind", ""))}</p>{details}{_evidence(character.get("evidence_refs", []))}</article>'
            )
        return "".join(cards) or '<p class="empty">No characters extracted.</p>'

    @staticmethod
    def _events(events: list[dict[str, Any]]) -> str:
        rendered = []
        for index, event in enumerate(events, 1):
            actors = [
                item.get("mention_text")
                for item in event.get("participant_mentions", [])
                if item.get("mention_text")
            ]
            location = (event.get("location_mention") or {}).get("mention_text")
            metadata = "".join(
                filter(
                    None,
                    [
                        f"<span>Actors: {_h(' / '.join(actors))}</span>" if actors else "",
                        f"<span>Location: {_h(location)}</span>" if location else "",
                    ],
                )
            )
            rendered.append(
                f'<article class="event"><div class="number">{index:02d}</div><div><h3>{_h(event.get("summary", "Untitled event"))}</h3><p class="muted">{_h(event.get("event_type", ""))}</p><div class="chips">{metadata}</div>{_evidence(event.get("evidence_refs", []))}</div></article>'
            )
        return "".join(rendered)

    @staticmethod
    def _timeline(timeline: dict[str, Any], event_by_id: dict[str, dict[str, Any]]) -> str:
        relations = {
            (item.get("source_event_id"), item.get("target_event_id")): item.get("relation")
            for item in timeline.get("temporal_relations", [])
        }
        ids = timeline.get("event_ids", [])
        parts = []
        for index, event_id in enumerate(ids):
            event = event_by_id.get(event_id, {})
            parts.append(
                f'<div class="time-node"><i></i><small>{index + 1:02d}</small><strong>{_h(event.get("summary", event_id))}</strong></div>'
            )
            if index + 1 < len(ids):
                label = relations.get((event_id, ids[index + 1]), "SOURCE ORDER")
                parts.append(f'<div class="connector"><span>{_h(label)}</span></div>')
        return f'<div class="timeline">{"".join(parts)}</div>'

    def _scenes(
        self,
        scenes: list[dict[str, Any]],
        panels_by_scene: dict[str, list[dict[str, Any]]],
        event_by_id: dict[str, dict[str, Any]],
    ) -> str:
        output = []
        for index, scene in enumerate(scenes, 1):
            event_ids = scene.get("related_event_ids", [])
            event_text = " · ".join(
                event_by_id.get(item, {}).get("summary", item) for item in event_ids
            )
            facts = [
                ("Location", scene.get("location")),
                ("Story time", scene.get("time")),
                ("Characters", " / ".join(scene.get("character_ids", []))),
            ]
            fact_html = "".join(
                f"<span><b>{_h(label)}</b>{_h(value)}</span>" for label, value in facts if value
            )
            panel_html = "".join(
                self._panel(panel, number)
                for number, panel in enumerate(
                    panels_by_scene.get(str(scene.get("scene_id")), []), 1
                )
            )
            output.append(
                f'<article class="scene"><button class="scene-title"><span>SCENE {index:02d}</span><strong>{_h(event_text or scene.get("title", "Scene"))}</strong><i>⌄</i></button><div class="scene-body"><div class="scene-facts">{fact_html}</div><p>{_h(scene.get("summary", ""))}</p><div class="panel-grid">{panel_html}</div></div></article>'
            )
        return "".join(output)

    @staticmethod
    def _panel(panel: dict[str, Any], number: int) -> str:
        visual = panel.get("narrative_beat") or panel.get("caption") or "Visual generation pending"
        actions = ", ".join(
            f"{key}: {value}" for key, value in panel.get("character_actions", {}).items()
        )
        dialogue = (
            " / ".join(panel.get("dialogue", [])) or panel.get("caption") or panel.get("narration")
        )
        return f'<article class="panel"><div class="panel-image"><span>PANEL {number:02d}</span><b>Visual generation pending</b><p>{_h(visual)}</p></div><div class="panel-copy"><p><b>Visual</b>{_h(panel.get("shot_type", ""))} · {_h(panel.get("camera_angle", ""))} · {_h(panel.get("composition", ""))}</p>{f"<p><b>Action</b>{_h(actions)}</p>" if actions else ""}{f"<p><b>Dialogue / Caption</b>{_h(dialogue)}</p>" if dialogue else ""}</div></article>'

    @staticmethod
    def _css() -> str:
        return """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f4f1ea;color:#20201e;font:16px/1.55 Inter,Segoe UI,Arial,sans-serif}nav{position:sticky;top:0;z-index:9;display:flex;gap:28px;justify-content:center;padding:14px;background:#fffdf9eF;border-bottom:1px solid #ded9ce;backdrop-filter:blur(10px)}nav a{color:#4b4943;text-decoration:none;font-weight:700}main{max-width:1180px;margin:auto;padding:48px 24px}header{padding:56px;border:1px solid #d8d1c4;border-radius:24px;background:#fffdf9;box-shadow:0 18px 50px #3d352815}.eyebrow,.section-head p{margin:0;color:#a2442f;font-size:.75rem;letter-spacing:.16em;font-weight:800}h1{font-size:clamp(2.5rem,6vw,5.4rem);line-height:1;margin:14px 0}h1 span{color:#a2442f}.lede{font-size:1.15rem;color:#666159}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:38px 0}.stats b{padding:20px;border-radius:14px;background:#272724;color:#fff;font-size:1.8rem}.stats small{display:block;color:#cfc8bb;font-size:.75rem;font-weight:500}.meta{display:flex;flex-wrap:wrap;gap:18px;color:#777168}.meta span{padding-right:18px;border-right:1px solid #ddd5c8}.meta strong{display:block;color:#262522}section{scroll-margin-top:70px;margin:70px 0}.section-head h2{margin:4px 0 24px;font-size:2rem}.provenance{padding:32px;border-radius:20px;background:#272724;color:white}.provenance-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.provenance-grid div{padding:18px;background:#ffffff0c;border:1px solid #ffffff20;border-radius:12px}.provenance-grid span{display:block;color:#bdb8ae;font-size:.8rem}.badge{display:inline-block;margin-top:8px;color:#fff}.badge.REAL_PROVIDER{color:#8ed19d}.badge.DEMO_FALLBACK{color:#f1c178}.provenance details{margin-top:18px;color:#d8d2c7}.character-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.character,.event,.scene,.panel{background:#fffdf9;border:1px solid #ddd6ca;border-radius:18px}.character{padding:24px}.avatar{display:grid;place-items:center;width:54px;height:54px;border-radius:50%;background:#a2442f;color:#fff;font-size:1.4rem;font-weight:800}.character h3{margin:14px 0 0;font-size:1.35rem}.muted{color:#777168}.evidence{font-size:.78rem;color:#80796e;border-top:1px solid #eee7dc;padding-top:10px}.event{display:grid;grid-template-columns:64px 1fr;gap:16px;padding:22px;margin:12px 0}.number{font:800 1.5rem Georgia;color:#a2442f}.event h3{margin:0}.chips{display:flex;flex-wrap:wrap;gap:8px}.chips span,.scene-facts span{padding:6px 10px;border-radius:99px;background:#eee8dd;font-size:.78rem}.timeline{display:flex;align-items:stretch;overflow:auto;padding:24px 4px}.time-node{min-width:190px;padding:18px;border-radius:14px;background:#fffdf9;border:1px solid #dcd5c9}.time-node small{display:block;color:#a2442f}.time-node strong{display:block;margin-top:8px}.connector{display:grid;place-items:center;min-width:78px;color:#8b8175}.connector:after{content:'→';font-size:1.7rem}.connector span{font-size:.6rem;position:absolute;margin-top:-34px}.scene{margin:18px 0;overflow:hidden}.scene-title{width:100%;border:0;background:#fffdf9;padding:22px;display:grid;grid-template-columns:100px 1fr 30px;text-align:left;cursor:pointer}.scene-title span{color:#a2442f;font-weight:800}.scene-title strong{font-size:1.05rem}.scene-body{padding:0 22px 24px}.collapsed .scene-body{display:none}.scene-facts{display:flex;flex-wrap:wrap;gap:8px}.scene-facts b,.panel-copy b{display:block;color:#8a4838;font-size:.7rem;text-transform:uppercase}.panel-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;margin-top:20px}.panel{overflow:hidden}.panel-image{min-height:250px;padding:22px;display:flex;flex-direction:column;justify-content:center;background:#e7e1d6;color:#48443d;text-align:center}.panel-image span{align-self:flex-start;font-size:.7rem;font-weight:800}.panel-image b{font:700 1.25rem Georgia}.panel-image p{font-size:.85rem}.panel-copy{padding:18px}.panel-copy p{margin:8px 0}footer{text-align:center;padding:38px;color:#7c766c}.empty{color:#777}@media(max-width:760px){nav{gap:14px;font-size:.8rem}main{padding:28px 14px}header{padding:30px}.stats{grid-template-columns:repeat(2,1fr)}.provenance-grid,.character-grid,.panel-grid{grid-template-columns:1fr}.scene-title{grid-template-columns:78px 1fr 20px}.timeline{flex-direction:column}.connector{min-height:60px}.connector:after{content:'↓'}.connector span{margin:0 0 0 72px}.meta span{border:0}}"""
