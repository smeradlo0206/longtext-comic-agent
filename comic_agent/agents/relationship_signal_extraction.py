"""Proposal-only Relationship Signal extraction agent."""

from pydantic import ValidationError

from comic_agent.agents.base import BaseAgent
from comic_agent.agents.source_evidence import (
    is_verifiable_or_uniquely_rebindable_evidence,
)
from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas import (
    RelationshipEvidenceBasis,
    RelationshipParticipantRefV1,
    RelationshipResolutionStatus,
    RelationshipSignalProposalBatchV1,
    RelationshipSignalProposalV1,
    SourceChunkV1,
)

RELATIONSHIP_SIGNAL_EXTRACTION_SYSTEM_PROMPT = """
You are RelationshipSignalExtractionAgent. Use only input_context.source_chunks and
input_context.source_chunk_ids. Return exactly one RelationshipSignalProposalBatchV1 JSON
object with schema_version="1.0" and a signals array. signals=[] is a successful result when
no reliable, auditable relationship signal exists. Return final JSON only: no markdown,
prose, reasoning, a single RelationshipSignalProposalV1, another mode's batch, canonical
relationship, StoryBible write, or provider-specific field.

This is a source-first relationship signal, never a confirmed or permanent relationship fact.
The selected SourceChunkV1 records are the complete evidence boundary. Do not use a database,
StoryBible, CommitService, full document, another Agent output, another window, provider history,
environment variables, local files, or external knowledge. Each EvidenceRefV1 quote_text must be
an exact verbatim substring of its selected chunk. When evidence is insufficient, return signals=[].

Ordinary co-presence, greeting, conversation, seeing someone, expression, silence, a single normal
exchange, one normal action, or sharing a place are not relationship signals. "????" may be a
LIMITED OBSERVED_ACTION PROTECTS signal; it never alone implies ALLIED_WITH, COOPERATES_WITH,
TRUSTS, friendship, or a change effect. A single threat, attack, or dispute can be THREATENS or
HOSTILE_TO only with explicit relationship-directed support; it never alone means RIVALS_WITH.
Never infer FORMATION, STRENGTHENING, WEAKENING, or TERMINATION from one rescue, command, or help.

Respect mode boundaries. Entity extraction identifies existence, not relationships.
Event extraction records what happened, such as a rescue or threat, not whether a relationship
exists. ClaimProposalV1 records an attributable assertion: "??????" is normally a Claim.
Emit a Relationship Signal only
when text explicitly points to a binary relation; use DIRECT_STATEMENT or REPORTED_STATEMENT with
source_speaker and never promote the statement to narrated truth or canonical fact. "???????"
may be a stated BETRAYS signal, but "??????" does not prove ? betrayed ?.
The traitor label is a Claim, not a binary BETRAYS relation: output signals=[] for that statement
unless the same selected source explicitly identifies both people and a betrayal action between
them.
KnowledgeStateProposalV1 records knowing, hearing, suspecting, believing, or disbelieving:
"???????" is SUSPECTS, not a Relationship Signal. StateChangeProposalV1 records
persistent target attributes: giving a sword may change its holder, but never alone creates
cooperation.

Use only Schema v1.0 relationship_domain, relationship_kind, directionality, signal_effect,
assertion_polarity, evidence_basis, and support_level values; do not invent free-text labels.
Kinship, spouse, romantic partner, disciple, membership, hierarchy, leadership, and dependency need
explicit source support. Never derive them from a title, age, shared action, favorable behavior, or
one command. TRUSTS, DISTRUSTS, COMMANDS, DEPENDS_ON, PROTECTS, THREATENS, DECEIVES, and BETRAYS
are directed. SIBLING_OF, SPOUSE_OF, COOPERATES_WITH, ALLIED_WITH, HOSTILE_TO, and RIVALS_WITH are
symmetric. Preserve source order of subject and counterpart; never swap them and never use one
participant twice.

Only NARRATED may use EXPLICIT. DIRECT_STATEMENT and REPORTED_STATEMENT require source_speaker and
never use EXPLICIT. OBSERVED_ACTION never uses EXPLICIT. Do not output INFERRED: it is reserved for
future human or offline tools, so a signal needing inference must return signals=[]. Statements,
rumors, reports, accusations, and denials must keep their source nature rather than become
narrated facts.

Use PRESENT unless current source text explicitly establishes a relationship beginning, change, or
end. FORMATION, STRENGTHENING, WEAKENING, and TERMINATION require auditable
temporal_anchor.anchor_text. Do not invent valid_from, valid_until, permanent duration, or event
ordering. no longer trusts means DISTRUSTS plus FORMATION: for "????????", use
relationship_domain=TRUST, relationship_kind=DISTRUSTS, signal_effect=FORMATION, and the explicit
"??" anchor. TRUST is the neutral domain name and does not mean positive trust. Relationship
denial uses DENIAL plus DENIED.

All participant, source_speaker, context_event, and temporal event references must be UNRESOLVED.
Every candidate Proposal ID and proposal_schema must be null; never invent an EntityProposalV1 or
EventProposalV1 ID, never upgrade a mention to RESOLVED, and never link names, aliases, titles,
pronouns, context, or common knowledge. An unresolved subject, counterpart, or source_speaker
mention_text must appear verbatim in a selected SourceChunk. Do not expand "?", "?", "??", or
"??" into an outside name. A context event is only local event context and cannot add a
relationship conclusion.

Every signal has independent non-empty EvidenceRefV1. Copy the shortest complete, auditable quote
verbatim and retain terminal punctuation when it belongs to the source. Default quote_start and
quote_end to null. Fill both only when Python half-open source_text[quote_start:quote_end] exactly
equals quote_text; quote_end is the exclusive end. Never guess, repair, normalize, or silently
correct offsets. Output every semantic signal at most once in source order; never automatically
merge.
""".strip()


class RelationshipSignalExtractionAgent(BaseAgent[RelationshipSignalProposalBatchV1]):
    """Extract source-bounded Relationship Signal proposal batches through a provider."""

    spec = AgentSpec(
        agent_id="relationship-signal-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="RelationshipSignalProposalBatchV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> RelationshipSignalProposalBatchV1:
        """Extract one source-only Relationship Signal batch from bounded context."""

        source_text_by_chunk_id = _source_text_by_chunk_id(input_context)
        batch = self._provider.structured_generate(
            {
                "system_prompt": RELATIONSHIP_SIGNAL_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Use input_context.source_chunk_ids and source_chunks only. "
                    "Return one RelationshipSignalProposalBatchV1."
                ),
                "input_context": input_context,
            },
            RelationshipSignalProposalBatchV1,
        )
        if not isinstance(batch, RelationshipSignalProposalBatchV1):
            raise ValueError(
                "RelationshipSignalExtractionAgent provider must return "
                "RelationshipSignalProposalBatchV1"
            )
        source_text = "\n".join(source_text_by_chunk_id.values())
        for signal in batch.signals:
            _reject_traitor_label_as_betrayal(signal)
            _require_unresolved_participant(signal.subject, "subject")
            _require_unresolved_participant(signal.counterpart, "counterpart")
            if signal.subject.mention_text not in source_text:
                raise ValueError(
                    "RelationshipSignalExtractionAgent unresolved subject mention_text must "
                    "appear in a source_chunk_ids-selected input SourceChunk"
                )
            if signal.counterpart.mention_text not in source_text:
                raise ValueError(
                    "RelationshipSignalExtractionAgent unresolved counterpart mention_text "
                    "must appear in a source_chunk_ids-selected input SourceChunk"
                )
            if signal.source_speaker is not None:
                _require_unresolved_participant(signal.source_speaker, "source_speaker")
                if signal.source_speaker.mention_text not in source_text:
                    raise ValueError(
                        "RelationshipSignalExtractionAgent unresolved source_speaker "
                        "mention_text must appear in a source_chunk_ids-selected input "
                        "SourceChunk"
                    )
            if signal.context_event is not None:
                _require_unresolved_event_reference(
                    signal.context_event.resolution_status,
                    signal.context_event.event_proposal_id,
                    signal.context_event.proposal_schema,
                    "context_event",
                )
            _require_unresolved_event_reference(
                signal.temporal_anchor.resolution_status,
                signal.temporal_anchor.event_proposal_id,
                signal.temporal_anchor.proposal_schema,
                "temporal_anchor",
            )
            if signal.evidence_basis == RelationshipEvidenceBasis.INFERRED:
                raise ValueError(
                    "RelationshipSignalExtractionAgent does not allow INFERRED evidence_basis"
                )
            for evidence in signal.evidence_refs:
                source = source_text_by_chunk_id.get(evidence.chunk_id)
                if not is_verifiable_or_uniquely_rebindable_evidence(
                    evidence, source_text_by_chunk_id
                ):
                    if source is None:
                        raise ValueError(
                            "RelationshipSignalExtractionAgent evidence must reference a "
                            "source_chunk_ids-selected input SourceChunk"
                        )
                    raise ValueError(
                        "RelationshipSignalExtractionAgent evidence quote_text must be "
                        "verbatim input SourceChunk text"
                    )
        return batch


def _reject_traitor_label_as_betrayal(signal: RelationshipSignalProposalV1) -> None:
    """Keep an unsupported traitor label in Claim extraction rather than relationship output."""

    if str(signal.relationship_kind) != "BETRAYS":
        return
    if not any(
        evidence.quote_text is not None and "??" in evidence.quote_text
        for evidence in signal.evidence_refs
    ):
        raise ValueError(
            "RelationshipSignalExtractionAgent traitor label without an explicit betrayal action "
            "is a Claim, not a binary BETRAYS relation"
        )


def _require_unresolved_participant(
    participant: RelationshipParticipantRefV1,
    label: str,
) -> None:
    """Reject candidate entity links because this Agent receives no candidate inputs."""

    resolution_status = participant.resolution_status
    entity_proposal_id = participant.entity_proposal_id
    proposal_schema = participant.proposal_schema
    if (
        resolution_status != RelationshipResolutionStatus.UNRESOLVED
        or entity_proposal_id is not None
        or proposal_schema is not None
    ):
        raise ValueError(
            "RelationshipSignalExtractionAgent source-only output requires UNRESOLVED "
            f"{label} references with null candidate IDs and schemas"
        )


def _require_unresolved_event_reference(
    resolution_status: RelationshipResolutionStatus,
    event_proposal_id: str | None,
    proposal_schema: str | None,
    label: str,
) -> None:
    """Reject candidate Event links because this Agent receives no candidate inputs."""

    if (
        resolution_status != RelationshipResolutionStatus.UNRESOLVED
        or event_proposal_id is not None
        or proposal_schema is not None
    ):
        raise ValueError(
            "RelationshipSignalExtractionAgent source-only output requires UNRESOLVED "
            f"{label} references with null candidate IDs and schemas"
        )


def _source_text_by_chunk_id(input_context: dict[str, object]) -> dict[str, str]:
    source_chunk_ids = input_context.get("source_chunk_ids")
    if not isinstance(source_chunk_ids, list) or not all(
        isinstance(chunk_id, str) for chunk_id in source_chunk_ids
    ):
        raise ValueError("RelationshipSignalExtractionAgent requires string source_chunk_ids")
    if len(source_chunk_ids) != len(set(source_chunk_ids)):
        raise ValueError("RelationshipSignalExtractionAgent source_chunk_ids must be unique")

    source_chunks = input_context.get("source_chunks")
    if not isinstance(source_chunks, list):
        raise ValueError("RelationshipSignalExtractionAgent requires SourceChunkV1 source_chunks")
    source_text_by_chunk_id: dict[str, str] = {}
    for source_chunk in source_chunks:
        if isinstance(source_chunk, SourceChunkV1):
            validated_chunk = source_chunk
        elif isinstance(source_chunk, dict):
            try:
                validated_chunk = SourceChunkV1.model_validate(source_chunk)
            except ValidationError as exc:
                raise ValueError(
                    "RelationshipSignalExtractionAgent requires valid SourceChunkV1 source_chunks"
                ) from exc
        else:
            raise ValueError(
                "RelationshipSignalExtractionAgent requires SourceChunkV1 source_chunks"
            )
        source_text_by_chunk_id[validated_chunk.chunk_id] = validated_chunk.text
    if (
        len(source_text_by_chunk_id) != len(source_chunks)
        or set(source_text_by_chunk_id) != set(source_chunk_ids)
    ):
        raise ValueError(
            "RelationshipSignalExtractionAgent source_chunk_ids must exactly match supplied "
            "SourceChunkV1 values"
        )
    return {chunk_id: source_text_by_chunk_id[chunk_id] for chunk_id in source_chunk_ids}
