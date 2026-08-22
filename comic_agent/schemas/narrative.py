"""Narrative extraction proposal schemas."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer, RecordStatus, StrictBaseModel


class TemporalRelation(StrEnum):
    """Supported temporal relation labels."""

    BEFORE = "BEFORE"
    AFTER = "AFTER"
    DURING = "DURING"
    CONTAINS = "CONTAINS"
    OVERLAPS = "OVERLAPS"
    SIMULTANEOUS = "SIMULTANEOUS"
    UNKNOWN = "UNKNOWN"


class ActorResolutionStatus(StrEnum):
    """How EventProposalV1 resolves event participants or actors."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSPECIFIED = "UNSPECIFIED"


class ClaimType(StrEnum):
    """Supported claim proposal kinds."""

    ASSERTION = "ASSERTION"
    FACTUAL_ASSERTION = "FACTUAL_ASSERTION"
    BELIEF = "BELIEF"
    DENIAL = "DENIAL"
    ACCUSATION = "ACCUSATION"
    HYPOTHESIS = "HYPOTHESIS"
    MEMORY = "MEMORY"
    EVALUATION = "EVALUATION"
    INTERPRETATION = "INTERPRETATION"
    PREDICTION = "PREDICTION"
    COMMITMENT = "COMMITMENT"


class ClaimTemporalScope(StrEnum):
    """Temporal scope of the claim proposition."""

    PAST = "PAST"
    PRESENT = "PRESENT"
    FUTURE = "FUTURE"
    ATEMPORAL = "ATEMPORAL"


class VerificationStatus(StrEnum):
    """Proposal-layer verification status for claims."""

    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNRESOLVED = "UNRESOLVED"


class ClaimSourceType(StrEnum):
    """Source family for a claim proposal."""

    CHARACTER = "CHARACTER"
    MESSAGE = "MESSAGE"
    NARRATOR = "NARRATOR"
    SYSTEM_LABEL = "SYSTEM_LABEL"
    AGENT = "AGENT"
    UNKNOWN = "UNKNOWN"


class EntityType(StrEnum):
    """Entity taxonomy used by EntityProposalV1 v1.1 output."""

    CHARACTER = "CHARACTER"
    CREATURE = "CREATURE"
    LOCATION = "LOCATION"
    ORGANIZATION = "ORGANIZATION"
    OBJECT = "OBJECT"
    ABILITY = "ABILITY"
    CONCEPT = "CONCEPT"


class StateChangeTargetKind(StrEnum):
    """Persistent target categories admitted by State Change v1.3."""

    CHARACTER = "CHARACTER"
    OBJECT = "OBJECT"
    LOCATION = "LOCATION"
    ORGANIZATION = "ORGANIZATION"


class StateChangeAttributePath(StrEnum):
    """Auditable State Change dimensions admitted by v1.3."""

    HEALTH_INJURY = "health.injury"
    LIFE_STATUS = "life_status"
    LOCATION = "location"
    POSSESSION_HOLDER = "possession.holder"
    PHYSICAL_CONDITION = "physical.condition"
    ACCESSIBILITY = "accessibility"
    AVAILABILITY = "availability"
    QUANTITY = "quantity"
    ROLE_STATUS = "role.status"
    APPEARANCE_CLOTHING = "appearance.clothing"
    APPEARANCE_HAIRSTYLE = "appearance.hairstyle"


class RelationshipParticipantKind(StrEnum):
    """Participant categories admitted by the binary relationship contract."""

    CHARACTER = "CHARACTER"
    ORGANIZATION = "ORGANIZATION"


class RelationshipDirectionality(StrEnum):
    """Whether a relationship signal has an ordered or unordered pair."""

    DIRECTED = "DIRECTED"
    SYMMETRIC = "SYMMETRIC"


class RelationshipDomain(StrEnum):
    """Controlled relationship semantic domains."""

    KINSHIP = "KINSHIP"
    ROMANTIC = "ROMANTIC"
    AFFILIATION = "AFFILIATION"
    HIERARCHY = "HIERARCHY"
    DEPENDENCY = "DEPENDENCY"
    TRUST = "TRUST"
    COOPERATION = "COOPERATION"
    HOSTILITY = "HOSTILITY"
    RIVALRY = "RIVALRY"
    PROTECTION = "PROTECTION"
    DECEPTION = "DECEPTION"


class RelationshipKind(StrEnum):
    """Closed relationship kinds; free-form relationship labels are forbidden."""

    PARENT_OF = "PARENT_OF"
    CHILD_OF = "CHILD_OF"
    SIBLING_OF = "SIBLING_OF"
    SPOUSE_OF = "SPOUSE_OF"
    ROMANTIC_PARTNER_OF = "ROMANTIC_PARTNER_OF"
    RELATIVE_OF = "RELATIVE_OF"
    MEMBER_OF = "MEMBER_OF"
    LEADS = "LEADS"
    COMMANDS = "COMMANDS"
    REPORTS_TO = "REPORTS_TO"
    MASTER_OF = "MASTER_OF"
    DISCIPLE_OF = "DISCIPLE_OF"
    TRUSTS = "TRUSTS"
    DISTRUSTS = "DISTRUSTS"
    DEPENDS_ON = "DEPENDS_ON"
    COOPERATES_WITH = "COOPERATES_WITH"
    ALLIED_WITH = "ALLIED_WITH"
    HOSTILE_TO = "HOSTILE_TO"
    RIVALS_WITH = "RIVALS_WITH"
    PROTECTS = "PROTECTS"
    THREATENS = "THREATENS"
    DECEIVES = "DECEIVES"
    BETRAYS = "BETRAYS"


class RelationshipSignalEffect(StrEnum):
    """How the source signal bears on a relationship, not a truth verdict."""

    PRESENT = "PRESENT"
    FORMATION = "FORMATION"
    STRENGTHENING = "STRENGTHENING"
    WEAKENING = "WEAKENING"
    TERMINATION = "TERMINATION"
    DENIAL = "DENIAL"
    UNKNOWN = "UNKNOWN"


class RelationshipEvidenceBasis(StrEnum):
    """How the relationship signal is presented by the source."""

    NARRATED = "NARRATED"
    DIRECT_STATEMENT = "DIRECT_STATEMENT"
    OBSERVED_ACTION = "OBSERVED_ACTION"
    REPORTED_STATEMENT = "REPORTED_STATEMENT"
    INFERRED = "INFERRED"


class RelationshipAssertionPolarity(StrEnum):
    """Polarity of the source assertion, distinct from relationship attitude."""

    AFFIRMED = "AFFIRMED"
    DENIED = "DENIED"


class RelationshipSupportLevel(StrEnum):
    """Audit strength of the signal without making a canonical fact claim."""

    EXPLICIT = "EXPLICIT"
    STRONG = "STRONG"
    LIMITED = "LIMITED"


class CreatureSubtype(StrEnum):
    """Optional, source-grounded refinement for creature entities."""

    ANIMAL = "ANIMAL"
    MONSTER = "MONSTER"
    SPIRIT_BEAST = "SPIRIT_BEAST"
    OTHER = "OTHER"


LEGACY_CLAIM_TYPE_VALUES = {
    "ASSERTION",
    "DENIAL",
    "ACCUSATION",
    "HYPOTHESIS",
    "MEMORY",
    "INTERPRETATION",
    "PREDICTION",
}


def _looks_like_legacy_claim_payload(value: Any) -> bool:
    """Detect old claim JSON that omitted schema_version before Claim v1.1."""

    if not isinstance(value, dict) or "schema_version" in value:
        return False
    claim_type = value.get("claim_type")
    if isinstance(claim_type, ClaimType):
        claim_type = claim_type.value
    return value.get("temporal_scope") is None and claim_type in LEGACY_CLAIM_TYPE_VALUES


class EpistemicStatus(StrEnum):
    """A source-supported character epistemic state, never a truth verdict."""

    UNAWARE = "UNAWARE"
    HEARD = "HEARD"
    SUSPECTS = "SUSPECTS"
    BELIEVES = "BELIEVES"
    DISBELIEVES = "DISBELIEVES"
    KNOWS = "KNOWS"


class KnowledgeReferenceResolutionStatus(StrEnum):
    """Whether a proposal-layer knowledge reference has been linked."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


# Relationship signals use the same source-first resolution semantics as Knowledge
# State references; this alias avoids a second enum with identical meaning.
RelationshipResolutionStatus = KnowledgeReferenceResolutionStatus


class ProposalMentionRefV1(StrictBaseModel):
    """A source mention that may be deterministically linked after parallel extraction.

    It deliberately separates a copied source label from an internal Proposal id.
    Parallel agents cannot know another mode's provider-local ids, so unresolved
    mentions are valid candidate data rather than malformed hard references.
    """

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    mention_text: str = Field(min_length=1, description="Non-blank source mention.")
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether proposal_id is an explicit candidate Proposal link."
    )
    proposal_id: str | None = Field(
        default=None, description="Candidate Proposal id; never canonical data."
    )
    proposal_schema: Literal["EntityProposalV1", "EventProposalV1", "ClaimProposalV1"] | None = (
        Field(default=None, description="Candidate Proposal schema when resolved.")
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "ProposalMentionRefV1":
        if not self.mention_text.strip():
            raise ValueError("proposal mention_text cannot be blank")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.RESOLVED:
            if not self.proposal_id or not self.proposal_schema:
                raise ValueError(
                    "RESOLVED proposal mention requires proposal_id and proposal_schema"
                )
        elif self.proposal_id is not None or self.proposal_schema is not None:
            raise ValueError(
                "UNRESOLVED proposal mention requires proposal_id and proposal_schema null"
            )
        return self


class KnowledgeTargetKind(StrEnum):
    """The kind of proposition or fact toward which a state is directed."""

    CLAIM = "CLAIM"
    EVENT = "EVENT"
    ENTITY_FACT = "ENTITY_FACT"
    WORLD_FACT = "WORLD_FACT"
    UNKNOWN = "UNKNOWN"


class EpistemicBasis(StrEnum):
    """How source text says a state was obtained or expressed, not whether it is true."""

    OBSERVED = "OBSERVED"
    HEARD = "HEARD"
    INFERRED = "INFERRED"
    REMEMBERED = "REMEMBERED"
    STATED = "STATED"
    UNKNOWN = "UNKNOWN"


class KnowledgeSubjectRefV1(StrictBaseModel):
    """Source-grounded subject mention with optional Entity proposal linkage."""

    mention_text: str = Field(min_length=1, description="Non-blank source subject mention.")
    entity_proposal_id: str | None = Field(
        default=None, description="Candidate EntityProposalV1 id; never a canonical id."
    )
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether entity_proposal_id is linked."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "KnowledgeSubjectRefV1":
        if not self.mention_text.strip():
            raise ValueError("mention_text cannot be blank")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.RESOLVED:
            if not self.entity_proposal_id or not self.entity_proposal_id.strip():
                raise ValueError("RESOLVED subject requires entity_proposal_id")
        elif self.entity_proposal_id is not None:
            raise ValueError("UNRESOLVED subject requires entity_proposal_id to be null")
        return self


class KnowledgeTargetRefV1(StrictBaseModel):
    """Source-grounded target text with optional candidate Proposal linkage."""

    target_kind: KnowledgeTargetKind = Field(
        description=(
            "Semantic type of the cognitive target itself: EVENT is a concrete occurrence, "
            "WORLD_FACT is a proposition or fact state, and CLAIM is a statement/report/rumor "
            "as the target. It is not determined by the speaking source; however, BELIEVES, "
            "SUSPECTS, and DISBELIEVES must use WORLD_FACT or EVENT because they concern "
            "the truth content, not a CLAIM speech act."
        )
    )
    target_text: str = Field(min_length=1, description="Non-blank auditable proposition or fact.")
    proposal_id: str | None = Field(default=None, description="Candidate Proposal id only.")
    proposal_schema: str | None = Field(
        default=None, description="Proposal schema matching target_kind when resolved."
    )
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether the target Proposal link is resolved."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "KnowledgeTargetRefV1":
        if not self.target_text.strip():
            raise ValueError("target_text cannot be blank")
        if self.target_kind == KnowledgeTargetKind.UNKNOWN:
            if self.resolution_status == KnowledgeReferenceResolutionStatus.RESOLVED:
                raise ValueError("UNKNOWN target_kind cannot be RESOLVED")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.UNRESOLVED:
            if self.proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED target requires proposal_id and proposal_schema to be null"
                )
            return self
        if not self.proposal_id or not self.proposal_id.strip() or not self.proposal_schema:
            raise ValueError("RESOLVED target requires proposal_id and proposal_schema")
        allowed_schema = {
            KnowledgeTargetKind.CLAIM: "ClaimProposalV1",
            KnowledgeTargetKind.EVENT: "EventProposalV1",
            KnowledgeTargetKind.ENTITY_FACT: "EntityProposalV1",
        }.get(self.target_kind)
        if allowed_schema is None or self.proposal_schema != allowed_schema:
            raise ValueError("target_kind and proposal_schema must match a candidate Proposal type")
        return self


class KnowledgeTemporalAnchorV1(StrictBaseModel):
    """Optional source event/text anchor without inferred event ordering."""

    anchor_text: str | None = Field(
        default=None, description="Optional auditable source anchor text."
    )
    event_proposal_id: str | None = Field(
        default=None, description="Candidate EventProposalV1 id only."
    )
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether event_proposal_id is linked."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "KnowledgeTemporalAnchorV1":
        if self.anchor_text is not None and not self.anchor_text.strip():
            raise ValueError("anchor_text cannot be blank")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.RESOLVED:
            if not self.anchor_text or not self.event_proposal_id:
                raise ValueError(
                    "RESOLVED temporal anchor requires anchor_text and event_proposal_id"
                )
        elif self.event_proposal_id is not None:
            raise ValueError("UNRESOLVED temporal anchor requires event_proposal_id to be null")
        return self


class RelationshipParticipantRefV1(StrictBaseModel):
    """Source-grounded binary relationship participant with optional candidate link."""

    mention_text: str = Field(min_length=1, description="Non-blank source participant mention.")
    participant_kind: RelationshipParticipantKind = Field(
        description="Only CHARACTER or ORGANIZATION participants are admitted."
    )
    resolution_status: RelationshipResolutionStatus = Field(
        description="Whether the participant has a candidate EntityProposal link."
    )
    entity_proposal_id: str | None = Field(
        default=None, description="Candidate EntityProposalV1 id; never a canonical id."
    )
    proposal_schema: str | None = Field(
        default=None, description="Must be EntityProposalV1 when resolved."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "RelationshipParticipantRefV1":
        if not self.mention_text.strip():
            raise ValueError("relationship participant mention_text cannot be blank")
        if self.resolution_status == RelationshipResolutionStatus.UNRESOLVED:
            if self.entity_proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED relationship participant requires entity_proposal_id "
                    "and proposal_schema to be null"
                )
            return self
        if not self.entity_proposal_id or not self.entity_proposal_id.strip():
            raise ValueError("RESOLVED relationship participant requires entity_proposal_id")
        if self.proposal_schema != "EntityProposalV1":
            raise ValueError(
                "RESOLVED relationship participant proposal_schema must be EntityProposalV1"
            )
        return self


class RelationshipSourceSpeakerRefV1(RelationshipParticipantRefV1):
    """Participant-shaped source speaker; it is only legal for statement bases."""


class RelationshipTemporalAnchorV1(StrictBaseModel):
    """Optional source/time anchor with no inferred event ordering."""

    valid_from: str | None = Field(default=None, description="Optional source time start anchor.")
    valid_until: str | None = Field(default=None, description="Optional source time end anchor.")
    anchor_text: str | None = Field(
        default=None, description="Optional copied source text used as the temporal anchor."
    )
    resolution_status: RelationshipResolutionStatus = Field(
        description="Whether the optional event anchor is linked."
    )
    event_proposal_id: str | None = Field(
        default=None, description="Candidate EventProposalV1 id only."
    )
    proposal_schema: str | None = Field(
        default=None, description="Must be EventProposalV1 when resolved."
    )

    @model_validator(mode="after")
    def validate_anchor(self) -> "RelationshipTemporalAnchorV1":
        for field_name in ("valid_from", "valid_until", "anchor_text"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"relationship temporal {field_name} cannot be blank")
        if self.resolution_status == RelationshipResolutionStatus.UNRESOLVED:
            if self.event_proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED relationship temporal anchor requires event_proposal_id "
                    "and proposal_schema to be null"
                )
            return self
        if not self.event_proposal_id or not self.event_proposal_id.strip():
            raise ValueError("RESOLVED relationship temporal anchor requires event_proposal_id")
        if self.proposal_schema != "EventProposalV1":
            raise ValueError(
                "RESOLVED relationship temporal anchor proposal_schema must be EventProposalV1"
            )
        return self


class RelationshipContextEventRefV1(StrictBaseModel):
    """Optional local event context; it is not itself a relationship conclusion."""

    event_summary: str = Field(min_length=1, description="Minimal local event context.")
    resolution_status: RelationshipResolutionStatus = Field(
        description="Whether the context event has a candidate link."
    )
    event_proposal_id: str | None = Field(
        default=None, description="Candidate EventProposalV1 id only."
    )
    proposal_schema: str | None = Field(
        default=None, description="Must be EventProposalV1 when resolved."
    )

    @model_validator(mode="after")
    def validate_context_event(self) -> "RelationshipContextEventRefV1":
        if not self.event_summary.strip():
            raise ValueError("context event_summary cannot be blank")
        if self.resolution_status == RelationshipResolutionStatus.UNRESOLVED:
            if self.event_proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED context event requires event_proposal_id and proposal_schema "
                    "to be null"
                )
            return self
        if not self.event_proposal_id or not self.event_proposal_id.strip():
            raise ValueError("RESOLVED context event requires event_proposal_id")
        if self.proposal_schema != "EventProposalV1":
            raise ValueError("RESOLVED context event proposal_schema must be EventProposalV1")
        return self


class EntityProposalV1(StrictBaseModel):
    """Candidate entity discovered from source text."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    entity_type: EntityType | str = Field(description="Entity type.")
    creature_subtype: CreatureSubtype | None = Field(
        default=None,
        description="Optional source-grounded subtype for CREATURE entities only.",
    )
    canonical_name: str = Field(description="Proposed canonical name.")
    aliases: list[str] = Field(default_factory=list, description="Known aliases.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")

    @model_validator(mode="after")
    def validate_entity_taxonomy(self) -> "EntityProposalV1":
        """Apply the closed v1.1 taxonomy while retaining legacy v1.0 reads."""

        if self.schema_version == "1.1":
            try:
                self.entity_type = EntityType(self.entity_type)
            except ValueError as exc:
                raise ValueError(
                    "v1.1 entity_type must use the supported EntityType taxonomy"
                ) from exc
        if self.creature_subtype is not None and self.entity_type != EntityType.CREATURE:
            raise ValueError("creature_subtype requires entity_type CREATURE")
        return self


class EntityProposalBatchV1(StrictBaseModel):
    """Candidate story entities discovered from one bounded source context."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    batch_id: str = Field(description="Batch proposal id.")
    entities: list[EntityProposalV1] = Field(
        min_length=1,
        description="Candidate entity proposals in source order where possible.",
    )

    @model_validator(mode="before")
    @classmethod
    def default_legacy_entity_items(cls, value: Any) -> Any:
        """Read explicit v1.0 batches whose nested entities omitted a version."""

        if not isinstance(value, dict) or value.get("schema_version") != "1.0":
            return value
        entities = value.get("entities")
        if not isinstance(entities, list):
            return value
        return {
            **value,
            "entities": [
                {**entity, "schema_version": "1.0"}
                if isinstance(entity, dict) and "schema_version" not in entity
                else entity
                for entity in entities
            ],
        }

    @model_validator(mode="after")
    def validate_unique_entity_ids(self) -> "EntityProposalBatchV1":
        """Keep batch outputs addressable by unique proposal id."""

        proposal_ids = [entity.proposal_id for entity in self.entities]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("entities must have unique proposal_id values")
        if any(entity.schema_version != self.schema_version for entity in self.entities):
            raise ValueError(
                f"v{self.schema_version} entity batches require v{self.schema_version} entities"
            )
        return self


class EventProposalV1(StrictBaseModel):
    """Candidate story event discovered from source text."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    event_type: str = Field(description="Event type label.")
    summary: str = Field(min_length=1, description="Faithful event summary.")
    participant_ids: list[str] = Field(default_factory=list, description="Participant entity ids.")
    participant_mentions: list[ProposalMentionRefV1] = Field(
        default_factory=list,
        description="Source participant mentions; unresolved values are not Proposal ids.",
    )
    actor_resolution_status: ActorResolutionStatus = Field(
        default=ActorResolutionStatus.UNSPECIFIED,
        description="How participant_ids should be interpreted for actor resolution.",
    )
    unresolved_actor_ref_id: str | None = Field(
        default=None,
        description="Optional future UnresolvedReference id for an unresolved actor mention.",
    )
    location_id: str | None = Field(default=None, description="Location entity id if known.")
    location_mention: ProposalMentionRefV1 | None = Field(
        default=None,
        description="Source location mention when an EntityProposal id is not available.",
    )
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="At least one source evidence reference is required.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")

    @model_validator(mode="after")
    def validate_actor_resolution(self) -> "EventProposalV1":
        """Keep actor resolution explicit without inventing character ids."""

        if self.schema_version == "1.0" and (
            self.participant_mentions or self.location_mention is not None
        ):
            raise ValueError("EventProposalV1 v1.0 cannot include mention references")
        if self.location_id is not None and self.location_mention is not None:
            raise ValueError("event location_id and location_mention are mutually exclusive")
        status = self.actor_resolution_status
        if status == ActorResolutionStatus.KNOWN:
            if not self.participant_ids and not self.participant_mentions:
                raise ValueError(
                    "KNOWN actor resolution requires participants or participant_mentions"
                )
            if self.unresolved_actor_ref_id is not None:
                raise ValueError("KNOWN actor resolution cannot include unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.UNKNOWN:
            if self.participant_ids or self.participant_mentions:
                raise ValueError("UNKNOWN actor resolution requires empty participants")
            if self.unresolved_actor_ref_id is not None:
                raise ValueError("UNKNOWN actor resolution cannot include unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.UNRESOLVED:
            if self.participant_ids or self.participant_mentions:
                raise ValueError("UNRESOLVED actor resolution requires empty participants")
            if self.unresolved_actor_ref_id is None:
                raise ValueError("UNRESOLVED actor resolution requires unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.NOT_APPLICABLE:
            if self.participant_ids or self.participant_mentions:
                raise ValueError("NOT_APPLICABLE actor resolution requires empty participants")
            if self.unresolved_actor_ref_id is not None:
                raise ValueError(
                    "NOT_APPLICABLE actor resolution cannot include unresolved_actor_ref_id"
                )
        elif self.unresolved_actor_ref_id is not None:
            raise ValueError("UNSPECIFIED actor resolution cannot include unresolved_actor_ref_id")
        return self


class EventProposalBatchV1(StrictBaseModel):
    """Candidate story events discovered from one bounded source context."""

    schema_version: Literal["1.0", "1.1"] = Field(
        default="1.1",
        description=(
            "Schema version. v1.0 remains readable; v1.1 permits an auditable empty "
            "batch when a bounded scope contains no independently supportable event."
        ),
    )
    batch_id: str = Field(description="Batch proposal id.")
    events: list[EventProposalV1] = Field(
        default_factory=list,
        description=(
            "Candidate event proposals in source order where possible. May be empty only "
            "when this bounded scope has no independently auditable event."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_versioned_mentions(cls, value: Any) -> Any:
        """Lift only impossible v1.0 mention payloads to their v1.1 contract.

        Some JSON-object Providers select the legacy default even while emitting
        v1.1-only mention fields. The fields themselves prove the intended
        version, so this is a compatibility normalization rather than a fact or
        evidence repair.
        """

        if not isinstance(value, dict):
            return value
        events = value.get("events")
        if not isinstance(events, list):
            return value

        def needs_v11(item: object) -> bool:
            return isinstance(item, dict) and (
                bool(item.get("participant_mentions"))
                or item.get("location_mention") is not None
            )

        if not any(needs_v11(item) for item in events):
            return value
        return {
            **value,
            "schema_version": "1.1",
            "events": [
                {**item, "schema_version": "1.1"} if isinstance(item, dict) else item
                for item in events
            ],
        }

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> "EventProposalBatchV1":
        """Keep batch outputs addressable by unique proposal id."""

        proposal_ids = [event.proposal_id for event in self.events]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("events must have unique proposal_id values")
        if self.schema_version == "1.0" and any(
            event.schema_version != "1.0" for event in self.events
        ):
            raise ValueError("v1.0 event batches cannot contain v1.1 event records")
        return self


class ClaimProposalV1(StrictBaseModel):
    """Candidate claim, statement, evaluation, denial, memory, or interpretation."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = Field(
        default="1.2",
        description="Schema version.",
    )
    proposal_id: str = Field(description="Proposal id.")
    # Legacy v1.0 identifiers retained for Timeline compatibility.
    claim_id: str | None = Field(default=None, description="Legacy claim id alias.")
    subject_id: str | None = Field(default=None, description="Legacy subject id.")
    predicate: str | None = Field(default=None, description="Legacy claim predicate.")
    object_value: str | None = Field(default=None, description="Legacy claim object value.")
    asserted_by_entity_id: str | None = Field(
        default=None, description="Legacy asserting entity id."
    )
    claim_type: ClaimType = Field(description="Claim type.")
    claim_text: str = Field(description="Exact or faithful claim text.")
    temporal_scope: ClaimTemporalScope | None = Field(
        default=None,
        description="Temporal scope of the claim proposition; required for v1.1 and newer.",
    )
    source_type: ClaimSourceType = Field(description="Claim source family.")
    source_id: str | None = Field(default=None, description="Optional source object id.")
    target_event_id: str | None = Field(default=None, description="Optional target event id.")
    source_reference: ProposalMentionRefV1 | None = Field(
        default=None,
        description="Source mention when a linked Proposal id is not available.",
    )
    target_event_reference: ProposalMentionRefV1 | None = Field(
        default=None,
        description="Event mention when a linked EventProposal id is not available.",
    )
    verification_status: VerificationStatus = Field(
        description="Proposal-layer verification status."
    )
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")

    @model_validator(mode="before")
    @classmethod
    def default_legacy_payload_version(cls, value: Any) -> Any:
        """Read old claim payloads that omitted schema_version as v1.0."""

        if isinstance(value, dict) and "proposal_id" not in value and "claim_id" in value:
            legacy = dict(value)
            claim_id = str(legacy.pop("claim_id"))
            predicate = str(legacy.get("predicate", "claim"))
            object_value = str(legacy.get("object_value", ""))
            legacy.update(
                {
                    "proposal_id": claim_id,
                    "claim_id": claim_id,
                    "claim_type": "FACTUAL_ASSERTION",
                    "claim_text": f"{predicate}: {object_value}".strip(),
                    "source_type": "UNKNOWN",
                    "verification_status": "UNVERIFIED",
                    "temporal_scope": "PRESENT",
                    "schema_version": "1.0",
                }
            )
            return legacy
        if _looks_like_legacy_claim_payload(value):
            return {**value, "schema_version": "1.0"}
        return value

    @field_validator("claim_text")
    @classmethod
    def claim_text_not_blank(cls, value: str) -> str:
        """Reject empty claim text."""

        if value.strip() == "":
            raise ValueError("claim_text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ClaimProposalV1":
        """Validate versioned claim semantics and source identity."""

        if self.schema_version in {"1.1", "1.2", "1.3"}:
            if self.claim_type == ClaimType.ASSERTION:
                raise ValueError("ASSERTION is only supported for schema_version=1.0")
            if self.temporal_scope is None:
                raise ValueError("schema_version=1.1 and newer require temporal_scope")
        if self.schema_version not in {"1.2", "1.3"} and self.claim_type == ClaimType.EVALUATION:
            raise ValueError("EVALUATION is only supported for schema_version=1.2 and newer")
        if self.schema_version != "1.3" and (
            self.source_reference is not None or self.target_event_reference is not None
        ):
            raise ValueError("ClaimProposalV1 v1.0-v1.2 cannot include mention references")
        if self.source_id is not None and self.source_reference is not None:
            raise ValueError("claim source_id and source_reference are mutually exclusive")
        if self.target_event_id is not None and self.target_event_reference is not None:
            raise ValueError(
                "claim target_event_id and target_event_reference are mutually exclusive"
            )
        if self.source_type == ClaimSourceType.UNKNOWN and (
            self.source_id is not None or self.source_reference is not None
        ):
            raise ValueError("UNKNOWN claim source cannot include a source reference")
        return self


class ClaimProposalBatchV1(StrictBaseModel):
    """Candidate story claims discovered from one bounded source context."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = Field(
        default="1.2",
        description="Schema version.",
    )
    batch_id: str = Field(description="Batch proposal id.")
    claims: list[ClaimProposalV1] = Field(
        min_length=1,
        description="Candidate claim proposals in source order where possible.",
    )

    @model_validator(mode="before")
    @classmethod
    def default_legacy_batch_version(cls, value: Any) -> Any:
        """Read old claim batch payloads that omitted schema_version as v1.0."""

        if not isinstance(value, dict) or "schema_version" in value:
            return value
        claims = value.get("claims")
        if not isinstance(claims, list) or not claims:
            return value
        claim_versions: list[str | None] = []
        for claim in claims:
            if isinstance(claim, ClaimProposalV1):
                claim_versions.append(claim.schema_version)
            elif isinstance(claim, dict):
                claim_versions.append(
                    "1.0"
                    if _looks_like_legacy_claim_payload(claim)
                    else claim.get("schema_version")
                )
            else:
                claim_versions.append(None)
        if set(claim_versions) == {"1.0"}:
            return {**value, "schema_version": "1.0"}
        return value

    @model_validator(mode="after")
    def validate_unique_claim_ids(self) -> "ClaimProposalBatchV1":
        """Keep batch outputs addressable and version-consistent."""

        proposal_ids = [claim.proposal_id for claim in self.claims]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("claims must have unique proposal_id values")
        claim_versions = {claim.schema_version for claim in self.claims}
        if self.schema_version in {"1.1", "1.2", "1.3"} and claim_versions != {self.schema_version}:
            raise ValueError(
                f"schema_version={self.schema_version} batch requires all claims to be "
                f"v{self.schema_version}"
            )
        if self.schema_version == "1.0" and claim_versions != {"1.0"}:
            raise ValueError("schema_version=1.0 batch requires all claims to be v1.0")
        return self


class CampusContentType(StrEnum):
    """Supported campus-publication source categories."""

    CAMPUS_NEWS = "campus_news"
    EVENT_PROMOTION = "event_promotion"
    RECRUITMENT = "recruitment"
    PUBLIC_SERVICE = "public_service"


class CampusAudience(StrEnum):
    """Intended audience categories for a campus publication candidate."""

    STUDENT = "student"
    PARENT = "parent"
    TEACHER = "teacher"
    PUBLIC = "public"


class CampusComicTone(StrEnum):
    """Restricted presentation tones; these are not image-provider settings."""

    FORMAL = "formal"
    LIVELY = "lively"
    YOUTHFUL = "youthful"


class ComicBeatPurpose(StrEnum):
    """Narrative purpose of a future comic beat candidate."""

    INTRO = "INTRO"
    CONTEXT = "CONTEXT"
    ACTIVITY = "ACTIVITY"
    HIGHLIGHT = "HIGHLIGHT"
    CALL_TO_ACTION = "CALL_TO_ACTION"


class CampusContentProfileProposalV1(StrictBaseModel):
    """Candidate campus-content adaptation profile; it is never canonical data."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(min_length=1, description="Candidate proposal id.")
    project_id: str = Field(min_length=1, description="Owning project id.")
    status: RecordStatus = Field(default=RecordStatus.CANDIDATE)
    content_type: CampusContentType
    audience: list[CampusAudience] = Field(min_length=1)
    must_preserve_fact_ids: list[str] = Field(
        min_length=1,
        description="Evidence-backed factual ClaimProposalV1.claim_id values only.",
    )
    tone: CampusComicTone
    page_budget: int = Field(ge=1, le=24, description="First-phase page budget.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_candidate_only(self) -> "CampusContentProfileProposalV1":
        if self.status != RecordStatus.CANDIDATE:
            raise ValueError("CampusContentProfileProposalV1 status must be CANDIDATE")
        return self

    @field_validator("proposal_id", "project_id")
    @classmethod
    def validate_nonblank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value

    @field_validator("audience")
    @classmethod
    def validate_unique_audience(cls, value: list[CampusAudience]) -> list[CampusAudience]:
        if len(value) != len(set(value)):
            raise ValueError("audience must contain unique values")
        return value

    @field_validator("must_preserve_fact_ids")
    @classmethod
    def validate_fact_ids(cls, value: list[str]) -> list[str]:
        if any(not fact_id.strip() for fact_id in value):
            raise ValueError("must_preserve_fact_ids items must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("must_preserve_fact_ids must contain unique values")
        return value


class ComicBeatProposalV1(StrictBaseModel):
    """Future comic narrative-beat candidate; it is not a panel or provider prompt."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    status: RecordStatus = Field(default=RecordStatus.CANDIDATE)
    content_profile_id: str = Field(min_length=1)
    beat_index: int = Field(ge=1)
    purpose: ComicBeatPurpose
    source_fact_ids: list[str] = Field(min_length=1)
    event_ids: list[str] = Field(default_factory=list)
    visual_intent: str = Field(min_length=1, max_length=240)
    narration_hint: str | None = Field(default=None, min_length=1, max_length=240)
    must_show: list[str] = Field(default_factory=list)
    must_not_show: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("proposal_id", "project_id", "content_profile_id", "visual_intent")
    @classmethod
    def validate_beat_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ComicBeatProposalV1 text fields must not be blank")
        return value

    @field_validator("source_fact_ids", "event_ids", "must_show", "must_not_show")
    @classmethod
    def validate_unique_nonblank_values(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("ComicBeatProposalV1 list items must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("ComicBeatProposalV1 list values must be unique")
        return value

    @model_validator(mode="after")
    def validate_visible_constraints_do_not_conflict(self) -> "ComicBeatProposalV1":
        if self.status != RecordStatus.CANDIDATE:
            raise ValueError("ComicBeatProposalV1 status must be CANDIDATE")
        if set(self.must_show) & set(self.must_not_show):
            raise ValueError("must_show and must_not_show must not overlap")
        return self


class KnowledgeStateProposalV1(StrictBaseModel):
    """Candidate character knowledge or belief state."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    character_id: str | None = Field(default=None, description="Legacy v1.0 character id.")
    knowledge_target_id: str | None = Field(default=None, description="Legacy v1.0 target id.")
    subject: KnowledgeSubjectRefV1 | None = Field(
        default=None, description="v1.1 subject reference."
    )
    target: KnowledgeTargetRefV1 | None = Field(default=None, description="v1.1 target reference.")
    epistemic_status: EpistemicStatus = Field(description="Knowledge or belief status.")
    epistemic_basis: EpistemicBasis | None = Field(
        default=None, description="v1.1 acquisition basis."
    )
    source_claim_id: str | None = Field(default=None, description="Legacy v1.0 source claim id.")
    supporting_claim_proposal_id: str | None = Field(
        default=None, description="Optional candidate ClaimProposalV1 id for v1.1."
    )
    valid_from_event_id: str | None = Field(
        default=None, description="Legacy v1.0 event id from which the state becomes valid."
    )
    valid_from: KnowledgeTemporalAnchorV1 | None = Field(
        default=None, description="v1.1 start anchor."
    )
    valid_until: KnowledgeTemporalAnchorV1 | None = Field(
        default=None, description="v1.1 end anchor."
    )
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")

    @model_validator(mode="before")
    @classmethod
    def infer_unversioned_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "schema_version" in value:
            return value
        if "character_id" in value or "knowledge_target_id" in value:
            return {**value, "schema_version": "1.0"}
        return value

    @model_validator(mode="after")
    def validate_versioned_contract(self) -> "KnowledgeStateProposalV1":
        legacy_fields = (
            self.character_id,
            self.knowledge_target_id,
            self.source_claim_id,
            self.valid_from_event_id,
        )
        if self.schema_version == "1.0":
            if not self.character_id or not self.knowledge_target_id:
                raise ValueError("v1.0 requires character_id and knowledge_target_id")
            return self
        if any(value is not None for value in legacy_fields):
            raise ValueError(
                "v1.1 cannot include legacy character_id, knowledge_target_id, "
                "source_claim_id, or valid_from_event_id"
            )
        if self.subject is None or self.target is None or self.epistemic_basis is None:
            raise ValueError("v1.1 requires subject, target, and epistemic_basis")
        if (
            self.epistemic_status == EpistemicStatus.HEARD
            and self.epistemic_basis != EpistemicBasis.HEARD
        ):
            raise ValueError("HEARD epistemic_status requires HEARD epistemic_basis")
        if (
            self.epistemic_status
            in {
                EpistemicStatus.BELIEVES,
                EpistemicStatus.SUSPECTS,
                EpistemicStatus.DISBELIEVES,
            }
            and self.target.target_kind
            not in {KnowledgeTargetKind.WORLD_FACT, KnowledgeTargetKind.EVENT}
        ):
            raise ValueError(
                "BELIEVES, SUSPECTS, and DISBELIEVES must target WORLD_FACT or EVENT, "
                "not CLAIM or another target kind"
            )
        if self.supporting_claim_proposal_id is not None:
            if (
                self.target.target_kind != KnowledgeTargetKind.CLAIM
                and self.epistemic_basis
                not in {
                    EpistemicBasis.STATED,
                    EpistemicBasis.HEARD,
                }
            ):
                raise ValueError(
                    "supporting_claim_proposal_id requires CLAIM target or STATED/HEARD basis"
                )
        return self


class KnowledgeStateProposalBatchV1(StrictBaseModel):
    """New source-ordered v1.1 Knowledge State Proposal output batch."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Batch schema version.")
    batch_id: str = Field(description="Batch proposal id.")
    states: list[KnowledgeStateProposalV1] = Field(
        default_factory=list, description="Zero or more v1.1 states in source order."
    )

    @model_validator(mode="after")
    def validate_states(self) -> "KnowledgeStateProposalBatchV1":
        proposal_ids = [state.proposal_id for state in self.states]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("states must have unique proposal_id values")
        if any(state.schema_version != "1.1" for state in self.states):
            raise ValueError("KnowledgeStateProposalBatchV1 only permits v1.1 states")
        semantic_keys = [_knowledge_state_semantic_key(state) for state in self.states]
        if len(set(semantic_keys)) != len(semantic_keys):
            raise ValueError("states must not contain semantic duplicate knowledge states")
        return self


def _knowledge_state_semantic_key(state: KnowledgeStateProposalV1) -> tuple[object, ...]:
    """Return the conservative v1.1 key used to reject duplicate batch items."""

    subject = state.subject
    target = state.target
    if subject is None or target is None:
        return ("legacy", state.proposal_id)
    return (
        subject.resolution_status,
        subject.entity_proposal_id,
        _normalized_knowledge_text(subject.mention_text),
        target.resolution_status,
        target.target_kind,
        target.proposal_id,
        target.proposal_schema,
        _normalized_knowledge_text(target.target_text),
        state.epistemic_status,
        state.epistemic_basis,
        state.reality_layer,
        _knowledge_temporal_anchor_key(state.valid_from),
        _knowledge_temporal_anchor_key(state.valid_until),
    )


def _knowledge_temporal_anchor_key(
    anchor: KnowledgeTemporalAnchorV1 | None,
) -> tuple[object, ...] | None:
    if anchor is None:
        return None
    return (
        anchor.resolution_status,
        anchor.event_proposal_id,
        _normalized_knowledge_text(anchor.anchor_text or ""),
    )


def _normalized_knowledge_text(value: str) -> str:
    return " ".join(value.split()).casefold()


class TemporalRelationProposalV1(StrictBaseModel):
    """Candidate temporal relation between two events."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    source_event_id: str = Field(description="Source event id.")
    target_event_id: str = Field(description="Target event id.")
    relation: TemporalRelation = Field(description="Temporal relation label.")
    offset_value: int | None = Field(default=None, description="Optional time offset value.")
    offset_unit: str | None = Field(default=None, description="Optional time offset unit.")
    evidence_refs: list[EvidenceRefV1] = Field(
        default_factory=list,
        description="Evidence required when relation is known.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reasoning_summary: str | None = Field(
        default=None,
        description="Optional sanitized reasoning summary for Timeline audit.",
    )

    @model_validator(mode="after")
    def validate_relation(self) -> "TemporalRelationProposalV1":
        """Reject self loops and unsupported UNKNOWN offsets."""

        if self.source_event_id == self.target_event_id:
            raise ValueError("source_event_id and target_event_id cannot be the same")
        if self.relation == TemporalRelation.UNKNOWN:
            if self.offset_value is not None or self.offset_unit is not None:
                raise ValueError("UNKNOWN relation cannot include offset")
        elif not self.evidence_refs:
            raise ValueError("known temporal relations require at least one EvidenceRef")
        return self


class StateChangeEventRefV1(StrictBaseModel):
    """Source-grounded event context with optional EventProposalV1 linkage."""

    event_summary: str = Field(min_length=1, description="Minimal auditable source event summary.")
    event_proposal_id: str | None = Field(
        default=None, description="Candidate EventProposalV1 id; never a canonical id."
    )
    proposal_schema: str | None = Field(
        default=None, description="Candidate proposal schema when resolved."
    )
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether event_proposal_id is linked."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "StateChangeEventRefV1":
        if not self.event_summary.strip():
            raise ValueError("event_summary cannot be blank")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.UNRESOLVED:
            if self.event_proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED event requires event_proposal_id and proposal_schema to be null"
                )
            return self
        if not self.event_proposal_id or not self.event_proposal_id.strip():
            raise ValueError("RESOLVED event requires event_proposal_id")
        if self.proposal_schema != "EventProposalV1":
            raise ValueError("RESOLVED event requires proposal_schema=EventProposalV1")
        return self


class StateChangeTargetRefV1(StrictBaseModel):
    """Source-grounded persistent target with optional EntityProposalV1 linkage."""

    mention_text: str = Field(min_length=1, description="Non-blank source target mention.")
    target_kind: StateChangeTargetKind | None = Field(
        default=None,
        description="v1.3 persistent target category; absent in readable v1.1 payloads.",
    )
    entity_proposal_id: str | None = Field(
        default=None, description="Candidate EntityProposalV1 id; never a canonical id."
    )
    proposal_schema: str | None = Field(
        default=None, description="Candidate proposal schema when resolved."
    )
    resolution_status: KnowledgeReferenceResolutionStatus = Field(
        description="Whether entity_proposal_id is linked."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> "StateChangeTargetRefV1":
        if not self.mention_text.strip():
            raise ValueError("mention_text cannot be blank")
        if self.resolution_status == KnowledgeReferenceResolutionStatus.UNRESOLVED:
            if self.entity_proposal_id is not None or self.proposal_schema is not None:
                raise ValueError(
                    "UNRESOLVED target requires entity_proposal_id and proposal_schema to be null"
                )
            return self
        if not self.entity_proposal_id or not self.entity_proposal_id.strip():
            raise ValueError("RESOLVED target requires entity_proposal_id")
        if self.proposal_schema != "EntityProposalV1":
            raise ValueError("RESOLVED target requires proposal_schema=EntityProposalV1")
        return self


class StateChangeProposalV1(StrictBaseModel):
    """Candidate state mutation caused by an event, never a canonical state write."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = Field(
        default="1.3", description="Schema version; fresh output uses v1.3."
    )
    proposal_id: str = Field(description="Proposal id.")
    event_id: str | None = Field(default=None, description="Legacy v1.0 event id.")
    target_entity_id: str | None = Field(default=None, description="Legacy v1.0 entity id.")
    event: StateChangeEventRefV1 | None = Field(default=None, description="v1.1 event context.")
    target: StateChangeTargetRefV1 | None = Field(default=None, description="v1.1 change target.")
    attribute_path: StateChangeAttributePath | str = Field(
        description="State dimension; v1.2+ requires a controlled StateChangeAttributePath."
    )
    old_value: Any | None = Field(default=None, description="Previous value if known.")
    new_value: Any | None = Field(default=None, description="New value if known.")
    persistent: bool = Field(description="Whether this state persists after the event.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    new_value_evidence_indexes: list[int] | None = Field(
        default=None,
        description="v1.3 indexes of evidence_refs that directly support new_value.",
    )
    persistence_evidence_indexes: list[int] | None = Field(
        default=None,
        description="v1.3 indexes of evidence_refs that explicitly support persistence.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")

    @model_validator(mode="before")
    @classmethod
    def infer_unversioned_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "schema_version" in value:
            return value
        if "event_id" in value or "target_entity_id" in value:
            return {**value, "schema_version": "1.0"}
        return value

    @model_validator(mode="after")
    def validate_versioned_contract(self) -> "StateChangeProposalV1":
        if self.schema_version == "1.0":
            if not self.event_id or not self.target_entity_id:
                raise ValueError("v1.0 requires event_id and target_entity_id")
            return self
        if self.event_id is not None or self.target_entity_id is not None:
            raise ValueError(
                f"v{self.schema_version} cannot include legacy event_id or target_entity_id"
            )
        if self.event is None or self.target is None:
            raise ValueError(
                f"v{self.schema_version} requires event and target source-first references"
            )
        if self.schema_version in {"1.2", "1.3"}:
            self._validate_v12_semantics()
        return self

    def _validate_v12_semantics(self) -> None:
        """Apply the controlled source-first State Change semantic contract."""

        if self.target is None or self.target.target_kind is None:
            raise ValueError(f"v{self.schema_version} target requires target_kind")
        attribute_path = str(self.attribute_path)
        allowed_paths = {path.value for path in StateChangeAttributePath}
        if self.schema_version == "1.2":
            allowed_paths -= _STATE_CHANGE_APPEARANCE_PATHS
        if attribute_path not in allowed_paths:
            raise ValueError(
                f"v{self.schema_version} attribute_path must be a controlled "
                "StateChangeAttributePath"
            )
        target_kind = str(self.target.target_kind)
        allowed_target_kinds = _STATE_CHANGE_PATH_TARGET_KINDS[attribute_path]
        if target_kind not in allowed_target_kinds:
            raise ValueError(
                f"v{self.schema_version} attribute_path is incompatible with target_kind"
            )
        _validate_state_change_value(self.old_value, attribute_path, field_name="old_value")
        if self.old_value is not None and isinstance(self.old_value, str):
            if self.old_value.strip().casefold() in _STATE_CHANGE_UNKNOWN_OLD_VALUES:
                raise ValueError(
                    f"v{self.schema_version} old_value cannot use an unknown placeholder"
                )
        if self.new_value is None:
            raise ValueError(f"v{self.schema_version} new_value must not be null")
        _validate_state_change_value(self.new_value, attribute_path, field_name="new_value")
        if attribute_path in _STATE_CHANGE_APPEARANCE_PATHS and isinstance(self.new_value, str):
            if self.new_value.strip().casefold() in _STATE_CHANGE_UNKNOWN_VALUES:
                raise ValueError(
                    f"v{self.schema_version} new_value cannot use an unknown placeholder"
                )
        if isinstance(self.new_value, str) and self.new_value.strip().startswith("可能是"):
            raise ValueError(f"v{self.schema_version} new_value cannot use speculative wording")
        _validate_state_change_evidence_indexes(
            self.new_value_evidence_indexes,
            field_name="new_value_evidence_indexes",
            evidence_count=len(self.evidence_refs),
            required_nonempty=True,
        )
        _validate_state_change_evidence_indexes(
            self.persistence_evidence_indexes,
            field_name="persistence_evidence_indexes",
            evidence_count=len(self.evidence_refs),
            required_nonempty=self.persistent,
        )
        if not self.persistent and self.persistence_evidence_indexes != []:
            raise ValueError(
                f"v{self.schema_version} persistent=false requires "
                "persistence_evidence_indexes to be empty"
            )


class StateChangeProposalBatchV1(StrictBaseModel):
    """Source-window State Change Proposal output batch."""

    schema_version: Literal["1.1", "1.2", "1.3"] = Field(
        default="1.3", description="Batch schema version; fresh output uses v1.3."
    )
    batch_id: str = Field(description="Batch proposal id.")
    changes: list[StateChangeProposalV1] = Field(
        default_factory=list,
        description="Zero or more distinct version-consistent state changes in source order.",
    )

    @model_validator(mode="after")
    def validate_changes(self) -> "StateChangeProposalBatchV1":
        proposal_ids = [change.proposal_id for change in self.changes]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("changes must have unique proposal_id values")
        if any(change.schema_version != self.schema_version for change in self.changes):
            raise ValueError(
                f"StateChangeProposalBatchV1 only permits v{self.schema_version} changes"
            )
        semantic_keys = [_state_change_semantic_key(change) for change in self.changes]
        if len(set(semantic_keys)) != len(semantic_keys):
            raise ValueError("changes must not contain semantic duplicate state changes")
        return self


def _state_change_semantic_key(change: StateChangeProposalV1) -> tuple[object, ...]:
    """Return the exact conservative key used to reject duplicate batch items."""

    event = change.event
    target = change.target
    if event is None or target is None:
        return ("legacy", change.proposal_id)
    return (
        event.event_summary,
        event.resolution_status,
        event.event_proposal_id,
        event.proposal_schema,
        target.mention_text,
        target.target_kind,
        target.resolution_status,
        target.entity_proposal_id,
        target.proposal_schema,
        change.attribute_path,
        _state_change_value_key(change.old_value),
        _state_change_value_key(change.new_value),
        change.persistent,
        change.reality_layer,
    )


def _state_change_value_key(value: Any) -> object:
    """Make arbitrary JSON-like state values comparable without normalization."""

    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _state_change_value_key(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_state_change_value_key(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(repr(_state_change_value_key(item)) for item in value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


_STATE_CHANGE_UNKNOWN_OLD_VALUES = {"未知", "不明", "n/a", "待确认"}

_STATE_CHANGE_PATH_TARGET_KINDS: dict[str, set[str]] = {
    StateChangeAttributePath.HEALTH_INJURY.value: {StateChangeTargetKind.CHARACTER.value},
    StateChangeAttributePath.LIFE_STATUS.value: {StateChangeTargetKind.CHARACTER.value},
    StateChangeAttributePath.LOCATION.value: {
        StateChangeTargetKind.CHARACTER.value,
        StateChangeTargetKind.OBJECT.value,
    },
    StateChangeAttributePath.POSSESSION_HOLDER.value: {StateChangeTargetKind.OBJECT.value},
    StateChangeAttributePath.PHYSICAL_CONDITION.value: {
        StateChangeTargetKind.OBJECT.value,
        StateChangeTargetKind.LOCATION.value,
    },
    StateChangeAttributePath.ACCESSIBILITY.value: {
        StateChangeTargetKind.OBJECT.value,
        StateChangeTargetKind.LOCATION.value,
    },
    StateChangeAttributePath.AVAILABILITY.value: {
        StateChangeTargetKind.OBJECT.value,
        StateChangeTargetKind.ORGANIZATION.value,
    },
    StateChangeAttributePath.QUANTITY.value: {StateChangeTargetKind.OBJECT.value},
    StateChangeAttributePath.ROLE_STATUS.value: {StateChangeTargetKind.CHARACTER.value},
    StateChangeAttributePath.APPEARANCE_CLOTHING.value: {StateChangeTargetKind.CHARACTER.value},
    StateChangeAttributePath.APPEARANCE_HAIRSTYLE.value: {StateChangeTargetKind.CHARACTER.value},
}

_STATE_CHANGE_APPEARANCE_PATHS = {
    StateChangeAttributePath.APPEARANCE_CLOTHING.value,
    StateChangeAttributePath.APPEARANCE_HAIRSTYLE.value,
}

_STATE_CHANGE_UNKNOWN_VALUES = _STATE_CHANGE_UNKNOWN_OLD_VALUES | {"unknown"}


def _validate_state_change_value(
    value: Any,
    attribute_path: str,
    *,
    field_name: str,
) -> None:
    """Validate deterministic scalar value constraints without source-text inference."""

    if value is None:
        if field_name == "old_value":
            return
        raise ValueError("v1.2 new_value must not be null")
    if isinstance(value, bool):
        is_scalar = True
    else:
        is_scalar = isinstance(value, (str, int, float))
    if not is_scalar:
        raise ValueError(f"v1.2 {field_name} must be a JSON scalar")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"v1.2 {field_name} cannot be blank")
    if attribute_path == StateChangeAttributePath.QUANTITY.value:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"v1.2 {field_name} for quantity must be numeric")
        return
    if attribute_path in {
        StateChangeAttributePath.ACCESSIBILITY.value,
        StateChangeAttributePath.AVAILABILITY.value,
    }:
        if isinstance(value, (str, bool)):
            return
        raise ValueError(f"v1.2 {field_name} for {attribute_path} must be string or boolean")
    if not isinstance(value, str):
        raise ValueError(f"v1.2 {field_name} for {attribute_path} must be a string")


def _validate_state_change_evidence_indexes(
    indexes: list[int] | None,
    *,
    field_name: str,
    evidence_count: int,
    required_nonempty: bool,
) -> None:
    """Validate local EvidenceRef indexes without interpreting quote semantics."""

    if indexes is None:
        if required_nonempty:
            raise ValueError(f"v1.2 {field_name} is required")
        return
    if required_nonempty and not indexes:
        raise ValueError(f"v1.2 {field_name} must not be empty")
    if len(set(indexes)) != len(indexes):
        raise ValueError(f"v1.2 {field_name} must not contain duplicate indexes")
    if any(index < 0 or index >= evidence_count for index in indexes):
        raise ValueError(f"v1.2 {field_name} contains an out-of-range index")


_RELATIONSHIP_SYMMETRIC_KINDS = {
    RelationshipKind.SIBLING_OF.value,
    RelationshipKind.SPOUSE_OF.value,
    RelationshipKind.ROMANTIC_PARTNER_OF.value,
    RelationshipKind.RELATIVE_OF.value,
    RelationshipKind.COOPERATES_WITH.value,
    RelationshipKind.ALLIED_WITH.value,
    RelationshipKind.HOSTILE_TO.value,
    RelationshipKind.RIVALS_WITH.value,
}

_RELATIONSHIP_KIND_METADATA: dict[str, tuple[str, str]] = {
    RelationshipKind.PARENT_OF.value: (RelationshipDomain.KINSHIP.value, "DIRECTED"),
    RelationshipKind.CHILD_OF.value: (RelationshipDomain.KINSHIP.value, "DIRECTED"),
    RelationshipKind.SIBLING_OF.value: (RelationshipDomain.KINSHIP.value, "SYMMETRIC"),
    RelationshipKind.SPOUSE_OF.value: (RelationshipDomain.KINSHIP.value, "SYMMETRIC"),
    RelationshipKind.ROMANTIC_PARTNER_OF.value: (
        RelationshipDomain.ROMANTIC.value,
        "SYMMETRIC",
    ),
    RelationshipKind.RELATIVE_OF.value: (RelationshipDomain.KINSHIP.value, "SYMMETRIC"),
    RelationshipKind.MEMBER_OF.value: (RelationshipDomain.AFFILIATION.value, "DIRECTED"),
    RelationshipKind.LEADS.value: (RelationshipDomain.HIERARCHY.value, "DIRECTED"),
    RelationshipKind.COMMANDS.value: (RelationshipDomain.HIERARCHY.value, "DIRECTED"),
    RelationshipKind.REPORTS_TO.value: (RelationshipDomain.HIERARCHY.value, "DIRECTED"),
    RelationshipKind.MASTER_OF.value: (RelationshipDomain.HIERARCHY.value, "DIRECTED"),
    RelationshipKind.DISCIPLE_OF.value: (RelationshipDomain.HIERARCHY.value, "DIRECTED"),
    RelationshipKind.TRUSTS.value: (RelationshipDomain.TRUST.value, "DIRECTED"),
    RelationshipKind.DISTRUSTS.value: (RelationshipDomain.TRUST.value, "DIRECTED"),
    RelationshipKind.DEPENDS_ON.value: (RelationshipDomain.DEPENDENCY.value, "DIRECTED"),
    RelationshipKind.COOPERATES_WITH.value: (
        RelationshipDomain.COOPERATION.value,
        "SYMMETRIC",
    ),
    RelationshipKind.ALLIED_WITH.value: (RelationshipDomain.COOPERATION.value, "SYMMETRIC"),
    RelationshipKind.HOSTILE_TO.value: (RelationshipDomain.HOSTILITY.value, "SYMMETRIC"),
    RelationshipKind.RIVALS_WITH.value: (RelationshipDomain.RIVALRY.value, "SYMMETRIC"),
    RelationshipKind.PROTECTS.value: (RelationshipDomain.PROTECTION.value, "DIRECTED"),
    RelationshipKind.THREATENS.value: (RelationshipDomain.HOSTILITY.value, "DIRECTED"),
    RelationshipKind.DECEIVES.value: (RelationshipDomain.DECEPTION.value, "DIRECTED"),
    RelationshipKind.BETRAYS.value: (RelationshipDomain.DECEPTION.value, "DIRECTED"),
}

_RELATIONSHIP_CHANGE_EFFECTS = {
    RelationshipSignalEffect.FORMATION.value,
    RelationshipSignalEffect.STRENGTHENING.value,
    RelationshipSignalEffect.WEAKENING.value,
    RelationshipSignalEffect.TERMINATION.value,
}


def _relationship_participant_pair_allowed(
    kind: str,
    subject: RelationshipParticipantKind,
    counterpart: RelationshipParticipantKind,
) -> bool:
    """Apply the closed participant matrix without resolving entity identity."""

    character = RelationshipParticipantKind.CHARACTER.value
    organization = RelationshipParticipantKind.ORGANIZATION.value
    subject_kind = str(subject)
    counterpart_kind = str(counterpart)
    if kind in {
        RelationshipKind.PARENT_OF.value,
        RelationshipKind.CHILD_OF.value,
        RelationshipKind.SIBLING_OF.value,
        RelationshipKind.SPOUSE_OF.value,
        RelationshipKind.ROMANTIC_PARTNER_OF.value,
        RelationshipKind.RELATIVE_OF.value,
    }:
        return subject_kind == character and counterpart_kind == character
    if kind == RelationshipKind.MEMBER_OF.value:
        return subject_kind == character and counterpart_kind in {character, organization}
    if kind in {
        RelationshipKind.LEADS.value,
        RelationshipKind.COMMANDS.value,
        RelationshipKind.REPORTS_TO.value,
        RelationshipKind.MASTER_OF.value,
        RelationshipKind.DISCIPLE_OF.value,
    }:
        return subject_kind == character and counterpart_kind in {character, organization}
    return subject_kind in {character, organization} and counterpart_kind in {
        character,
        organization,
    }


class RelationshipSignalProposalV1(StrictBaseModel):
    """Source-first, proposal-only binary relationship signal."""

    schema_version: Literal["1.0"] = Field(
        default="1.0",
        description=(
            "Relationship Signal Schema Contract v1.0; no canonical relationship or legacy "
            "payload conversion is performed."
        ),
    )
    proposal_id: str = Field(description="Candidate relationship signal id.")
    subject: RelationshipParticipantRefV1 = Field(description="Source-ordered first participant.")
    counterpart: RelationshipParticipantRefV1 = Field(description="Second participant.")
    relationship_domain: RelationshipDomain
    relationship_kind: RelationshipKind
    directionality: RelationshipDirectionality
    signal_effect: RelationshipSignalEffect
    assertion_polarity: RelationshipAssertionPolarity
    evidence_basis: RelationshipEvidenceBasis
    support_level: RelationshipSupportLevel
    source_speaker: RelationshipSourceSpeakerRefV1 | None = Field(
        default=None,
        description="Required only for direct or reported statements.",
    )
    context_event: RelationshipContextEventRefV1 | None = Field(
        default=None,
        description="Optional local EventProposalV1 context reference.",
    )
    temporal_anchor: RelationshipTemporalAnchorV1 = Field(
        description="Explicit source/time anchor; Schema does not infer ordering."
    )
    reality_layer: RealityLayer = Field(description="Narrative reality layer preserved verbatim.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1, description="Independent source evidence references."
    )
    confidence: float = Field(ge=0, le=1, description="Proposal confidence for review only.")

    @model_validator(mode="after")
    def validate_contract(self) -> "RelationshipSignalProposalV1":
        kind = str(self.relationship_kind)
        metadata = _RELATIONSHIP_KIND_METADATA.get(kind)
        if metadata is None:
            raise ValueError("relationship_kind is not supported by Relationship Signal v1.0")
        expected_domain, expected_direction = metadata
        if str(self.relationship_domain) != expected_domain:
            raise ValueError("relationship_domain does not match relationship_kind")
        if str(self.directionality) != expected_direction:
            raise ValueError("directionality does not match relationship_kind")
        if not _relationship_participant_pair_allowed(
            kind, self.subject.participant_kind, self.counterpart.participant_kind
        ):
            raise ValueError("participant_kind combination is not allowed for relationship_kind")
        if _relationship_same_identity(self.subject, self.counterpart):
            raise ValueError("subject and counterpart must be distinct participants")
        if (
            str(self.relationship_domain) == RelationshipDomain.KINSHIP.value
            and self.signal_effect == RelationshipSignalEffect.TERMINATION
        ):
            raise ValueError("KINSHIP relationship does not allow TERMINATION")
        if self.signal_effect == RelationshipSignalEffect.UNKNOWN:
            raise ValueError("Relationship Signal v1.0 does not allow UNKNOWN signal_effect")

        if self.signal_effect == RelationshipSignalEffect.DENIAL:
            if self.assertion_polarity != RelationshipAssertionPolarity.DENIED:
                raise ValueError("DENIAL signal_effect requires DENIED assertion_polarity")
        elif self.assertion_polarity != RelationshipAssertionPolarity.AFFIRMED:
            raise ValueError("non-DENIAL signal_effect requires AFFIRMED assertion_polarity")

        basis = self.evidence_basis
        if basis in {
            RelationshipEvidenceBasis.DIRECT_STATEMENT,
            RelationshipEvidenceBasis.REPORTED_STATEMENT,
        }:
            if self.source_speaker is None:
                raise ValueError("statement evidence_basis requires source_speaker")
            if self.support_level == RelationshipSupportLevel.EXPLICIT:
                raise ValueError("statement evidence_basis cannot use EXPLICIT support_level")
        elif basis in {
            RelationshipEvidenceBasis.NARRATED,
            RelationshipEvidenceBasis.OBSERVED_ACTION,
        }:
            if self.source_speaker is not None:
                raise ValueError("narrated or observed evidence_basis forbids source_speaker")
            if basis == RelationshipEvidenceBasis.OBSERVED_ACTION and self.support_level == (
                RelationshipSupportLevel.EXPLICIT
            ):
                raise ValueError("OBSERVED_ACTION cannot use EXPLICIT support_level")
        elif basis == RelationshipEvidenceBasis.INFERRED:
            if self.source_speaker is not None:
                raise ValueError("INFERRED evidence_basis forbids source_speaker")
            if len(self.evidence_refs) < 2:
                raise ValueError("INFERRED evidence_basis requires at least two evidence_refs")
            if self.support_level != RelationshipSupportLevel.LIMITED:
                raise ValueError("INFERRED evidence_basis requires LIMITED support_level")
            if self.signal_effect in _RELATIONSHIP_CHANGE_EFFECTS:
                raise ValueError("INFERRED evidence_basis cannot describe relationship changes")

        if self.signal_effect in _RELATIONSHIP_CHANGE_EFFECTS:
            if not self.temporal_anchor.anchor_text:
                raise ValueError(
                    "relationship change signal requires non-empty temporal anchor_text"
                )

        evidence_keys = [
            (ref.chunk_id, ref.quote_start, ref.quote_end, ref.quote_text)
            for ref in self.evidence_refs
        ]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("evidence_refs must not contain duplicate references")
        return self


class RelationshipSignalProposalBatchV1(StrictBaseModel):
    """Source-window Relationship Signal proposals with exact semantic deduplication."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Fresh batch version.")
    batch_id: str = Field(description="Batch proposal id.")
    signals: list[RelationshipSignalProposalV1] = Field(
        default_factory=list,
        description="Zero or more source-grounded relationship signals.",
    )

    @model_validator(mode="after")
    def validate_signals(self) -> "RelationshipSignalProposalBatchV1":
        proposal_ids = [signal.proposal_id for signal in self.signals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("signals must have unique proposal_id values")
        semantic_keys = [_relationship_signal_semantic_key(signal) for signal in self.signals]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("signals must not contain semantic duplicate relationship signals")
        return self


def _relationship_same_identity(
    subject: RelationshipParticipantRefV1,
    counterpart: RelationshipParticipantRefV1,
) -> bool:
    """Reject only identities the source-first payload can prove are identical."""

    if (
        subject.resolution_status == RelationshipResolutionStatus.RESOLVED
        and counterpart.resolution_status == RelationshipResolutionStatus.RESOLVED
    ):
        return subject.entity_proposal_id == counterpart.entity_proposal_id
    if (
        subject.resolution_status == RelationshipResolutionStatus.UNRESOLVED
        and counterpart.resolution_status == RelationshipResolutionStatus.UNRESOLVED
    ):
        return subject.mention_text == counterpart.mention_text
    return False


def _relationship_participant_key(
    participant: RelationshipParticipantRefV1,
) -> tuple[object, ...]:
    return (
        participant.mention_text,
        str(participant.participant_kind),
        str(participant.resolution_status),
        participant.entity_proposal_id,
        participant.proposal_schema,
    )


def _relationship_signal_semantic_key(
    signal: RelationshipSignalProposalV1,
) -> tuple[object, ...]:
    participants = [
        _relationship_participant_key(signal.subject),
        _relationship_participant_key(signal.counterpart),
    ]
    if signal.directionality == RelationshipDirectionality.SYMMETRIC:
        participants.sort(key=repr)
    speaker = (
        _relationship_participant_key(signal.source_speaker)
        if signal.source_speaker is not None
        else None
    )
    context = (
        (
            signal.context_event.event_summary,
            str(signal.context_event.resolution_status),
            signal.context_event.event_proposal_id,
            signal.context_event.proposal_schema,
        )
        if signal.context_event is not None
        else None
    )
    temporal = (
        signal.temporal_anchor.valid_from,
        signal.temporal_anchor.valid_until,
        signal.temporal_anchor.anchor_text,
        str(signal.temporal_anchor.resolution_status),
        signal.temporal_anchor.event_proposal_id,
        signal.temporal_anchor.proposal_schema,
    )
    return (
        tuple(participants),
        str(signal.relationship_domain),
        str(signal.relationship_kind),
        str(signal.directionality),
        str(signal.signal_effect),
        str(signal.assertion_polarity),
        str(signal.evidence_basis),
        str(signal.support_level),
        speaker,
        context,
        temporal,
        str(signal.reality_layer),
    )
