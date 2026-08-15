"""Proposal-only State Change extraction agent."""

from pydantic import ValidationError

from comic_agent.agents.base import BaseAgent
from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas import SourceChunkV1, StateChangeProposalBatchV1

STATE_CHANGE_EXTRACTION_SYSTEM_PROMPT = """
You are StateChangeExtractionAgent. Use only input_context.source_chunks and
input_context.source_chunk_ids. Return exactly one StateChangeProposalBatchV1 JSON
object with schema_version="1.3" and a changes array. changes=[] is the required
successful result when no reliable, auditable State Change exists. Do not return a
single StateChangeProposalV1 or another mode's batch. Return final JSON only.

Extract only a source-supported event that causes an auditable state change to a
persistent target. event is the cause or context; target is the character, object,
location, or organization whose state changed. Do not repeat the event itself as the
target. Do not output knowledge, belief, suspicion, unawareness, trust, hostility,
alliance, betrayal, relationship signals, or an action with no explicit state result.
The selected source_chunks are the complete evidence boundary for this run: do not
borrow facts, prior states, names, or old values from another window, an unselected
chunk, a database, a StoryBible, or common sense. If the selected context does not
state the prior value, use old_value=null.
Within each permitted SourceChunk, scan every sentence in source order and retain all
independent, auditable changes: injury worsening followed by bandaging improvement,
each character movement, breakage then repair then re-damage, door open/close/open,
each possession transfer, quantity changes, completed appearance changes, a final
rockery collapse, and a wall crack followed later by collapse when time, reaction, or
another independent consequence separates the stages. Do not stop after the first
change and do not drop later changes merely because they share one SourceChunk.

Use only target_kind values CHARACTER, OBJECT, LOCATION, or ORGANIZATION. target
mention_text is the smallest auditable object name, never a complete event, sentence,
claim, rumor, or speech. This agent has no approved candidate Proposal inputs. Every
event and target reference must be UNRESOLVED: event_proposal_id, entity_proposal_id,
and proposal_schema must be null. Do not invent event_proposal_id or entity_proposal_id.
Never output RESOLVED, legacy event_id, legacy target_entity_id, canonical IDs, database
commands, StoryBible data, or automatic links.

Use only these v1.3 attribute_path values and obey the target-kind matrix:
- health.injury, life_status, and role.status: CHARACTER only.
- location: CHARACTER or OBJECT only.
- possession.holder and quantity: OBJECT only.
- physical.condition and accessibility: OBJECT or LOCATION only.
- availability: OBJECT or ORGANIZATION only.
- appearance.clothing and appearance.hairstyle: CHARACTER only.
Only extract an explicitly completed appearance conversion. “换上灰衣”, “脱下斗篷”,
“解开发绳，长发披下”, and “重新束起头发” can support appearance state changes when
their evidence directly supports the new value. Do not extract a plan, command,
hypothesis, static appearance description, brief expression such as “脸色苍白” or
“脸色一变”, lighting effect, wind-blown clothing such as “衣角被风吹起”, or momentary
messy hair. Do not add appearance.face_color, emotion, posture,
ability, or knowledge paths.
Do not use free-form paths such as changed, status_change, or descriptive sentences.
Part-whole target resolution is intentionally out of scope: “木箱” and “箱盖” are
separate OBJECT mentions unless a future approved contract explicitly links them.

old_value=null means the source does not state the prior value. Never use unknown
placeholders such as "未知", "不明", "N/A", or "待确认". new_value must be a source-supported,
non-empty JSON scalar, never an object, list, quote, event summary, explanation, or
speculation. Do not infer old_value, new_value, causality, ownership, or possession from
common sense. A non-null old_value is allowed only when that prior value is explicitly
stated in the selected context or is the immediately preceding auditable change in
the same context. Example: “林舟被箭射伤。” -> CHARACTER 林舟, health.injury, old_value=null,
new_value="受伤". Example: “矿洞入口被永久封死。” -> LOCATION or OBJECT 矿洞入口,
accessibility, old_value=null, new_value="封死". “林舟看见一把钥匙。” is changes=[] unless
the source explicitly establishes a possession or other state change.
Use the smallest concrete result that preserves meaning. Do not hide a specific result
behind a generic value: “左臂渗出血珠” must not become only “受伤”; use a concrete,
path-compatible result such as “左臂伤口渗血”. When the same context states a chain,
carry the prior value forward in source order: 木箱完好 -> 箱角裂开 -> 箱板重新合拢 ->
焦黑并塌下一角; 铁门合上 -> 开启 -> 关上 -> 打开; 伤势渗血 -> 血色止住; 卷轴阿葵 ->
周砚 -> 沈策 -> 陆衡; 药瓶 6 -> 4; and a separated wall 细裂 -> 坍下. Never infer
these old values across windows, from omitted context, a database, or canonical state.

persistent=true only when the source explicitly supports persistence; persistent=true is
allowed only when the source explicitly supports a continuing, permanent, from-now-on,
long-term, or stable result, or equivalent persistence meaning. The source must say the
change will continue, is permanent, holds from now on, or remains always/long-term,
or an equivalent persistence meaning. Collapse, close, recover, be injured, arrive,
obtain, or put results alone do
not constitute persistence evidence. Even when common sense suggests the result lasts,
use persistent=false and persistence_evidence_indexes=[] unless the source explicitly
supports persistence. persistent=false means no explicit persistence support, not proven
temporary. Do not silently correct a provider's persistent value.

event_summary only describes the minimal cause or local context for the current change.
Do not mix another target's state result into it, do not concatenate multiple state
results, and do not invent a causal relation just to complete the summary. The target,
attribute_path, new_value, and evidence determine the actual change.
Event and State Change may both be represented: the event is the instantaneous cause,
while the State Change is the auditable result available to later narration. If one
uninterrupted action produces “裂纹” and immediately “崩塌”, output only the final（最终）、
narratively useful “崩塌” state unless the source clearly separates the two stages with
time, reaction, or an independent consequence. Do not merge or rewrite across windows.

For an UNRESOLVED target, mention_text must be an exact name or pronoun that appears in
one of the permitted source chunks. Do not turn "他" or "她" into an invented person
name, and do not use a name absent from all permitted chunks. The runtime boundary check
will reject an unresolved mention_text absent from the selected source chunks.

Every change must independently carry non-empty evidence_refs. Each quote_text must be
copied verbatim from the selected input SourceChunk and support the change. Each change
must have non-empty new_value_evidence_indexes pointing only to valid indexes in its own
evidence_refs. When persistent=true, persistence_evidence_indexes must be non-empty and
point to explicit persistence evidence in that same change. When persistent=false,
persistence_evidence_indexes must be []. Default quote_start and quote_end to null. Only
fill both when the Python half-open interval source_text[quote_start:quote_end] exactly
equals quote_text; quote_end is the exclusive end. Preserve terminal punctuation when it
is necessary to the exact source quote. Never borrow evidence from another change.

Return changes=[] for pure speech, presence, observation, plan, promise, condition,
hypothesis, wish, or prediction; for an event without an explicit target state result;
for mental or relationship changes; or when no verbatim evidence supports new_value.
“挥拳击中木板，木屑落下” still requires changes=[]: action intensity or falling
wood chips does not prove that the board was cracked, broken, or damaged. Emit a
physical-condition change only when the source explicitly states the target result
(裂开、断裂、破碎、损坏、倒塌, or an equivalent explicit result).

Each change needs a unique proposal_id. Do not emit exact semantic duplicates. Do not use
fuzzy matching, similarity, LLM merging, cross-window judgment, or automatic repairs.
One source quote may support different State Changes, but each change carries its own
EvidenceRefV1. Sort by source chunk order and then source appearance. Output proposal
data only: no markdown, explanations, reasoning, raw provider content, canonical state,
or anything except final JSON.
""".strip()


class StateChangeExtractionAgent(BaseAgent[StateChangeProposalBatchV1]):
    """Extract bounded v1.3 State Change proposal batches through an LLM provider."""

    spec = AgentSpec(
        agent_id="state-change-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="StateChangeProposalBatchV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> StateChangeProposalBatchV1:
        """Extract one bounded State Change batch from supplied SourceChunk context."""

        source_text_by_chunk_id = _source_text_by_chunk_id(input_context)
        batch = self._provider.structured_generate(
            {
                "system_prompt": STATE_CHANGE_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Use input_context.source_chunk_ids and source_chunks only. "
                    "Return one StateChangeProposalBatchV1."
                ),
                "input_context": input_context,
            },
            StateChangeProposalBatchV1,
        )
        for change in batch.changes:
            if (
                change.event is None
                or change.target is None
                or change.event.resolution_status != "UNRESOLVED"
                or change.target.resolution_status != "UNRESOLVED"
            ):
                raise ValueError(
                    "StateChangeExtractionAgent source-only output requires UNRESOLVED "
                    "event and target references"
                )
            if change.target.mention_text not in "\n".join(source_text_by_chunk_id.values()):
                raise ValueError(
                    "StateChangeExtractionAgent unresolved target mention_text must appear "
                    "in a source_chunk_ids-selected input SourceChunk"
                )
            for evidence in change.evidence_refs:
                source_text = source_text_by_chunk_id.get(evidence.chunk_id)
                if source_text is None:
                    raise ValueError(
                        "StateChangeExtractionAgent evidence must reference a "
                        "source_chunk_ids-selected input SourceChunk"
                    )
                if evidence.quote_text is None or evidence.quote_text not in source_text:
                    raise ValueError(
                        "StateChangeExtractionAgent evidence quote_text must be verbatim input "
                        "SourceChunk text"
                    )
                if (
                    evidence.quote_start is not None
                    and evidence.quote_end is not None
                    and (
                        source_text[evidence.quote_start : evidence.quote_end]
                        != evidence.quote_text
                    )
                ):
                    raise ValueError(
                        "StateChangeExtractionAgent evidence offsets must exactly match quote_text"
                    )
        return batch


def _source_text_by_chunk_id(input_context: dict[str, object]) -> dict[str, str]:
    """Return the bounded source text available to this source-only Agent."""

    source_chunk_ids = input_context.get("source_chunk_ids")
    if not isinstance(source_chunk_ids, list) or not all(
        isinstance(source_chunk_id, str) for source_chunk_id in source_chunk_ids
    ):
        raise ValueError(
            "StateChangeExtractionAgent requires string source_chunk_ids"
        )
    if len(source_chunk_ids) != len(set(source_chunk_ids)):
        raise ValueError(
            "StateChangeExtractionAgent source_chunk_ids must be unique"
        )

    source_chunks = input_context.get("source_chunks")
    if not isinstance(source_chunks, list):
        raise ValueError("StateChangeExtractionAgent requires SourceChunkV1 source_chunks")
    source_text_by_chunk_id: dict[str, str] = {}
    for source_chunk in source_chunks:
        chunk_id: str
        text: str
        if isinstance(source_chunk, SourceChunkV1):
            chunk_id = source_chunk.chunk_id
            text = source_chunk.text
        elif isinstance(source_chunk, dict):
            try:
                validated_chunk = SourceChunkV1.model_validate(source_chunk)
            except ValidationError as exc:
                raise ValueError(
                    "StateChangeExtractionAgent requires valid SourceChunkV1 source_chunks"
                ) from exc
            chunk_id = validated_chunk.chunk_id
            text = validated_chunk.text
        else:
            raise ValueError("StateChangeExtractionAgent requires SourceChunkV1 source_chunks")
        source_text_by_chunk_id[chunk_id] = text
    if (
        len(source_text_by_chunk_id) != len(source_chunks)
        or set(source_text_by_chunk_id) != set(source_chunk_ids)
    ):
        raise ValueError(
            "StateChangeExtractionAgent source_chunk_ids must exactly match supplied "
            "SourceChunkV1 values"
        )
    return {
        source_chunk_id: source_text_by_chunk_id[source_chunk_id]
        for source_chunk_id in source_chunk_ids
    }
