"""End-to-end StoryBible state-flow demo with a scripted provider.

Simulates the real pipeline inputs — narrative-analysis proposals (entities, events,
claims, state changes) plus the timeline agent's temporal relations — then runs the
full chain: curate -> approve -> commit -> world-state snapshots at several story
moments. No real LLM or network call is made; the provider returns a handcrafted
draft of the shape the configured model is asked to produce.

Run from the repository root with the project virtualenv:

    python scripts/demo_storybible_state_flow.py
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.database.models import SourceChunkModel
from comic_agent.main import create_app
from comic_agent.schemas.source import SourceChunkV1

PROJECT = "project-1"

CHUNKS = {
    "c1": "林夏裹着黑金外套走进北境城,腰侧悬着一柄青锋剑。城内屋舍完好,悬空回廊灯火通明。",
    "c2": "苏烟在城门口等候,两人结伴同行。此界灵气充盈,得灵气者方可施法。",
    "c5": "林夏换上一袭素白长裙,青锋剑交到苏烟手中。北境城遭火焚,只剩断壁残垣,浓烟不散。",
}


def ev(chunk_id: str, quote: str) -> dict[str, str]:
    return {"chunk_id": chunk_id, "quote_text": quote}


def build_context() -> dict[str, Any]:
    """The upstream output: narrative-analysis proposals + timeline relations."""

    def entity(
        pid: str, kind: str, name: str, aliases: list[str], chunk_id: str, quote: str
    ) -> dict[str, Any]:
        return {
            "proposal_id": pid,
            "entity_type": kind,
            "canonical_name": name,
            "aliases": aliases,
            "evidence_refs": [ev(chunk_id, quote)],
            "confidence": 0.95,
        }
    return {
        "project_id": PROJECT,
        "source_chunk_ids": ["c1", "c2", "c5"],
        "entity_proposals": [
            entity("ent-linxia", "CHARACTER", "林夏", ["小夏"], "c1", "林夏"),
            entity("ent-suyan", "CHARACTER", "苏烟", [], "c2", "苏烟"),
            entity("ent-beijing", "LOCATION", "北境城", [], "c1", "北境城"),
            entity("ent-sword", "OBJECT", "青锋剑", [], "c1", "青锋剑"),
        ],
        "event_proposals": [
            {
                "proposal_id": f"{PROJECT}:ev-enter",
                "event_type": "ARRIVAL",
                "summary": "林夏进城",
                "participant_ids": ["ent-linxia"],
                "location_id": "ent-beijing",
                "evidence_refs": [ev("c1", "林夏")],
                "confidence": 0.95,
                "reality_layer": "PRIMARY",
            },
            {
                "proposal_id": f"{PROJECT}:ev-meet",
                "event_type": "MEETING",
                "summary": "苏烟与林夏结伴",
                "participant_ids": ["ent-linxia", "ent-suyan"],
                "location_id": "ent-beijing",
                "evidence_refs": [ev("c2", "结伴同行")],
                "confidence": 0.95,
                "reality_layer": "PRIMARY",
            },
            {
                "proposal_id": f"{PROJECT}:ev-change",
                "event_type": "CHANGE",
                "summary": "林夏换装并赠剑",
                "participant_ids": ["ent-linxia", "ent-suyan"],
                "location_id": "ent-beijing",
                "evidence_refs": [ev("c5", "素白长裙")],
                "confidence": 0.95,
                "reality_layer": "PRIMARY",
            },
            {
                "proposal_id": f"{PROJECT}:ev-burn",
                "event_type": "DISASTER",
                "summary": "北境城遭火焚",
                "participant_ids": [],
                "location_id": "ent-beijing",
                "evidence_refs": [ev("c5", "只剩断壁残垣")],
                "confidence": 0.95,
                "reality_layer": "PRIMARY",
            },
        ],
        "claim_proposals": [
            {
                "claim_id": "claim-qi",
                "subject_id": "ent-beijing",
                "predicate": "setting",
                "object_value": "灵气充盈,得灵气者方可施法",
                "asserted_by_entity_id": None,
                "evidence_refs": [ev("c2", "灵气充盈,得灵气者方可施法")],
                "confidence": 0.95,
                "reality_layer": "PRIMARY",
            }
        ],
        "state_change_proposals": [
            {
                "proposal_id": "sc-1",
                "event_id": f"{PROJECT}:ev-enter",
                "target_entity_id": "ent-linxia",
                "attribute_path": "appearance.clothing",
                "old_value": None,
                "new_value": "黑金外套",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c1", "裹着黑金外套")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "sc-2",
                "event_id": f"{PROJECT}:ev-enter",
                "target_entity_id": "ent-linxia",
                "attribute_path": "possession.holder",
                "old_value": None,
                "new_value": "青锋剑",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c1", "悬着一柄青锋剑")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "sc-3",
                "event_id": f"{PROJECT}:ev-change",
                "target_entity_id": "ent-linxia",
                "attribute_path": "appearance.clothing",
                "old_value": "黑金外套",
                "new_value": "素白长裙",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c5", "素白长裙")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "sc-4",
                "event_id": f"{PROJECT}:ev-change",
                "target_entity_id": "ent-suyan",
                "attribute_path": "possession.holder",
                "old_value": None,
                "new_value": "青锋剑",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c5", "青锋剑交到苏烟手中")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "sc-5",
                "event_id": f"{PROJECT}:ev-enter",
                "target_entity_id": "ent-beijing",
                "attribute_path": "physical.condition",
                "old_value": None,
                "new_value": "完好",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c1", "屋舍完好")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "sc-6",
                "event_id": f"{PROJECT}:ev-burn",
                "target_entity_id": "ent-beijing",
                "attribute_path": "physical.condition",
                "old_value": "完好",
                "new_value": "废墟",
                "persistent": True,
                "reality_layer": "PRIMARY",
                "evidence_refs": [ev("c5", "只剩断壁残垣")],
                "confidence": 0.95,
            },
        ],
        "temporal_relation_proposals": [
            {
                "proposal_id": "rel-1",
                "source_event_id": f"{PROJECT}:ev-enter",
                "target_event_id": f"{PROJECT}:ev-meet",
                "relation": "BEFORE",
                "evidence_refs": [ev("c2", "结伴同行")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "rel-2",
                "source_event_id": f"{PROJECT}:ev-meet",
                "target_event_id": f"{PROJECT}:ev-change",
                "relation": "BEFORE",
                "evidence_refs": [ev("c5", "素白长裙")],
                "confidence": 0.95,
            },
            {
                "proposal_id": "rel-3",
                "source_event_id": f"{PROJECT}:ev-change",
                "target_event_id": f"{PROJECT}:ev-burn",
                "relation": "BEFORE",
                "evidence_refs": [ev("c5", "只剩断壁残垣")],
                "confidence": 0.95,
            },
        ],
    }


def build_draft() -> dict[str, Any]:
    """A handcrafted provider response of the shape the curator asks the model for."""

    def profile(
        profile_id: str,
        name: str,
        aliases: list[str],
        quote: tuple[str, str],
    ) -> dict[str, Any]:
        return {
            "update_id": f"{PROJECT}:upd-prof-{profile_id}",
            "project_id": PROJECT,
            "profile": {
                "profile_id": f"{PROJECT}:prof-{profile_id}",
                "project_id": PROJECT,
                "entity_kind": "PERSON" if profile_id != "beijing" else "LOCATION",
                "canonical_name": name,
                "aliases": aliases,
                "evidence_refs": [ev(*quote)],
            },
            "evidence_refs": [ev(*quote)],
        }

    def state(
        state_id: str,
        profile_id: str,
        attribute_path: str,
        value: str,
        from_event: str,
        until_event: str | None,
        quote: tuple[str, str],
    ) -> dict[str, Any]:
        state_payload: dict[str, Any] = {
            "state_id": f"{PROJECT}:st-{state_id}",
            "project_id": PROJECT,
            "profile_id": f"{PROJECT}:prof-{profile_id}",
            "state": {attribute_path: value},
            "triggering_event_id": f"{PROJECT}:{from_event}",
            "valid_from_event_id": f"{PROJECT}:{from_event}",
            "evidence_refs": [ev(*quote)],
        }
        if until_event is not None:
            state_payload["valid_until_event_id"] = f"{PROJECT}:{until_event}"
        return {
            "update_id": f"{PROJECT}:upd-st-{state_id}",
            "project_id": PROJECT,
            "state": state_payload,
            "evidence_refs": [ev(*quote)],
        }

    return {
        "proposal_id": f"{PROJECT}:curator-demo",
        "project_id": PROJECT,
        "status": "CANONICAL",
        "commit_plan": {
            "commit_plan_id": f"{PROJECT}:plan-demo",
            "project_id": PROJECT,
            "source_proposal_id": f"{PROJECT}:curator-demo",
            "updates": [
                profile("linxia", "林夏", ["小夏"], ("c1", "林夏")),
                profile("suyan", "苏烟", [], ("c2", "苏烟")),
                profile("beijing", "北境城", [], ("c1", "北境城")),
                state(
                    "cloth1",
                    "linxia",
                    "appearance.clothing",
                    "黑金外套",
                    "ev-enter",
                    "ev-change",
                    ("c1", "裹着黑金外套"),
                ),
                state(
                    "sword-linxia",
                    "linxia",
                    "possession.holder",
                    "青锋剑",
                    "ev-enter",
                    "ev-change",
                    ("c1", "悬着一柄青锋剑"),
                ),
                state(
                    "cloth2",
                    "linxia",
                    "appearance.clothing",
                    "素白长裙",
                    "ev-change",
                    None,
                    ("c5", "素白长裙"),
                ),
                state(
                    "sword-suyan",
                    "suyan",
                    "possession.holder",
                    "青锋剑",
                    "ev-change",
                    None,
                    ("c5", "青锋剑交到苏烟手中"),
                ),
                state(
                    "city-ok",
                    "beijing",
                    "physical.condition",
                    "完好",
                    "ev-enter",
                    "ev-burn",
                    ("c1", "屋舍完好"),
                ),
                state(
                    "city-ruin",
                    "beijing",
                    "physical.condition",
                    "废墟",
                    "ev-burn",
                    None,
                    ("c5", "只剩断壁残垣"),
                ),
                {
                    "update_id": f"{PROJECT}:upd-rel-ally",
                    "project_id": PROJECT,
                    "relationship": {
                        "relationship_id": f"{PROJECT}:rel-ally",
                        "project_id": PROJECT,
                        "source_profile_id": f"{PROJECT}:prof-linxia",
                        "target_profile_id": f"{PROJECT}:prof-suyan",
                        "relationship_type": "ALLY",
                        "valid_from_event_id": f"{PROJECT}:ev-meet",
                        "evidence_refs": [ev("c2", "结伴同行")],
                    },
                    "evidence_refs": [ev("c2", "结伴同行")],
                },
                {
                    "update_id": f"{PROJECT}:upd-rule-qi",
                    "project_id": PROJECT,
                    "world_rule": {
                        "rule_id": f"{PROJECT}:rule-qi",
                        "project_id": PROJECT,
                        "name": "灵气施法",
                        "statement": "此界灵气充盈,得灵气者方可施法。",
                        "evidence_refs": [ev("c2", "灵气充盈,得灵气者方可施法")],
                    },
                    "evidence_refs": [ev("c2", "灵气充盈,得灵气者方可施法")],
                },
            ],
            "evidence_refs": [ev("c1", "林夏")],
        },
        "conflicts": [
            {
                "conflict_id": f"{PROJECT}:conf-alias",
                "project_id": PROJECT,
                "category": "IDENTITY",
                "summary": "别名'小夏'仅出现一次,需人工确认归属。",
                "affected_update_ids": [f"{PROJECT}:upd-prof-linxia"],
                "evidence_refs": [ev("c1", "林夏")],
                "blocking": False,
            }
        ],
        "evidence_refs": [ev("c1", "林夏")],
        "confidence": 0.9,
    }


class ScriptedProvider:
    """Deterministic stand-in for the LLM provider (offline demo)."""

    def __init__(self, draft: dict[str, Any]) -> None:
        self._draft = draft

    def structured_generate(self, request: dict[str, object], output_model: type[Any]) -> Any:
        return output_model.model_validate(self._draft)


def print_snapshot(label: str, snapshot: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    for character in snapshot["characters"]:
        print(f"  [人物] {character['canonical_name']}: {character['state']}")
    for location in snapshot["locations"]:
        print(f"  [地点] {location['canonical_name']}: {location['state']}")
    for relationship in snapshot["relationships"]:
        print(
            f"  [关系] {relationship['source_profile_id']} "
            f"-{relationship['relationship_type']}-> {relationship['target_profile_id']}"
        )
    for rule in snapshot["world_rules"]:
        print(f"  [规则] {rule['name']}: {rule['statement']}")
    if snapshot["unresolved_state_ids"]:
        print(f"  [顺序未知的状态] {snapshot['unresolved_state_ids']}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        app = create_app(database_url=f"sqlite+pysqlite:///{Path(tmp_dir) / 'demo.db'}")
        session: Session = app.state.session_factory()
        try:
            for index, (chunk_id, text) in enumerate(CHUNKS.items()):
                chunk = SourceChunkV1(
                    chunk_id=chunk_id,
                    document_id="doc-1",
                    chapter_id="chapter-1" if chunk_id != "c5" else "chapter-5",
                    project_id=PROJECT,
                    order=index,
                    text=text,
                    checksum=f"checksum-{chunk_id}",
                )
                session.add(
                    SourceChunkModel(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        chapter_id=chunk.chapter_id,
                        project_id=chunk.project_id,
                        order=chunk.order,
                        text=chunk.text,
                        source_page=chunk.source_page,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        checksum=chunk.checksum,
                        payload=chunk.model_dump(mode="json"),
                    )
                )
            session.commit()
        finally:
            session.close()

        app.state.storybible_curator = StoryBibleCurator(ScriptedProvider(build_draft()))

        with TestClient(app) as client:
            print("输入上下文(叙事解析提案 + 时间线关系):")
            print(json.dumps(build_context(), ensure_ascii=False, indent=2))

            curate_response = client.post(
                f"/projects/{PROJECT}/storybible/curate",
                json=build_context(),
            )
            print(f"\n策展 POST /curate -> {curate_response.status_code}")
            if curate_response.status_code != 200:
                print(f"  错误详情: {curate_response.json()['detail']}")
                raise SystemExit(1)
            proposal = curate_response.json()
            print(f"  status={proposal['status']}  confidence={proposal['confidence']}")
            print(f"  content_hash={proposal['commit_plan']['content_hash'][:16]}...")
            print(f"  冲突数={len(proposal['conflicts'])}")
            stamped = {
                update["state"]["state_id"]: (
                    update["state"]["valid_from_order"],
                    update["state"]["valid_until_order"],
                )
                for update in proposal["commit_plan"]["updates"]
                if "state" in update
            }
            print("  状态被盖上的时间戳(state_id -> (from_order, until_order)):")
            for state_id, orders in stamped.items():
                print(f"    {state_id}: {orders}")

            commit_response = client.post(
                f"/projects/{PROJECT}/storybible/commit-plans/{PROJECT}:plan-demo",
                json={"status": "APPROVED"},
            )
            print(f"\n审批 POST /commit-plans -> {commit_response.status_code}")

            for event_order, label in [
                (0, "时刻 0(第1章:林夏刚进城)"),
                (1, "时刻 1(第1章:与苏烟结伴)"),
                (2, "时刻 2(第5章:换装赠剑之后)"),
                (3, "时刻 3(第5章:北境城焚毁之后)"),
                (40, "时刻 40(很久以后——第5章之后的章节没再提过任何状态)"),
            ]:
                snapshot_response = client.get(
                    f"/projects/{PROJECT}/storybible/state-at",
                    params={"event_order": event_order},
                )
                print_snapshot(label, snapshot_response.json())

        app.state.engine.dispose()


if __name__ == "__main__":
    main()
