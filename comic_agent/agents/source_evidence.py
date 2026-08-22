"""Bounded source-evidence helpers shared by source-only proposal agents."""

from collections.abc import Mapping

from comic_agent.schemas.base import EvidenceRefV1


def is_verifiable_or_uniquely_rebindable_evidence(
    evidence: EvidenceRefV1,
    source_text_by_chunk_id: Mapping[str, str],
) -> bool:
    """Accept direct evidence or one exact, uniquely rebindable selected quote.

    The caller does not alter the evidence reference.  The workflow's centralized
    normalizer performs the actual audited rebind after the proposal is returned.
    """

    quote_text = evidence.quote_text
    if not isinstance(quote_text, str) or not quote_text:
        return False

    referenced_source = source_text_by_chunk_id.get(evidence.chunk_id)
    if referenced_source is not None and quote_text in referenced_source:
        return True

    return sum(quote_text in source for source in source_text_by_chunk_id.values()) == 1
