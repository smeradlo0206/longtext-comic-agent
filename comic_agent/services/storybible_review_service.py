"""Deterministic review of persisted StoryBible proposals; no generation is permitted."""

import json
from collections.abc import Iterable
from typing import Any

from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryBibleEvidenceCheckV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryBibleReviewContextV1,
    StoryBibleReviewDecision,
    StoryBibleReviewIssueSeverity,
    StoryBibleReviewIssueV1,
    StoryBibleReviewResultV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.id_service import stable_id
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)
from comic_agent.services.storybible_validator import EvidenceLookup, StoryBibleValidator


class StoryBibleReviewService:
    """Audit existing proposal facts using source and approved Timeline data only."""

    def __init__(self, evidence_lookup: EvidenceLookup) -> None:
        self._evidence_lookup = evidence_lookup

    def review(
        self,
        context: StoryBibleReviewContextV1,
        *,
        production_run: StoryBibleProductionRunV1,
        proposal: StoryBibleCuratorProposalV1,
        commit_plan: CommitPlanV1,
        approved_timeline: ApprovedTimelineBundleV1,
    ) -> StoryBibleReviewResultV1:
        issues: list[StoryBibleReviewIssueV1] = []
        proposal_hash = storybible_proposal_hash(proposal)
        self._validate_lineage(
            context,
            production_run,
            proposal,
            commit_plan,
            approved_timeline,
            proposal_hash,
            issues,
        )

        evidence_checks = self._check_all_evidence(
            proposal, commit_plan, approved_timeline
        )
        for check in evidence_checks:
            if not check.valid:
                self._add_issue(
                    issues,
                    category="INVALID_EVIDENCE",
                    severity=StoryBibleReviewIssueSeverity.BLOCKING,
                    message=check.message or "Evidence grounding failed.",
                    affected_ids=[check.owner_id],
                    evidence_refs=[check.evidence_ref],
                )

        entities = [
            update.profile
            for update in commit_plan.updates
            if isinstance(update, ProfileUpdateProposalV1)
        ]
        relationships = [
            update.relationship
            for update in commit_plan.updates
            if isinstance(update, RelationshipUpdateProposalV1)
        ]
        states = [
            update.state
            for update in commit_plan.updates
            if isinstance(update, StateUpdateProposalV1)
        ]
        world_rules = [
            update.world_rule
            for update in commit_plan.updates
            if isinstance(update, WorldRuleUpdateProposalV1)
        ]
        self._validate_entities(entities, context.canonical_snapshot.profiles, issues)
        self._validate_relationships(
            relationships,
            entities,
            context.canonical_snapshot.profiles,
            context.canonical_snapshot.relationships,
            approved_timeline,
            issues,
        )
        self._validate_states(
            states,
            entities,
            context.canonical_snapshot.profiles,
            approved_timeline,
            issues,
        )
        self._validate_world_rules(
            world_rules, context.canonical_snapshot.world_rules, issues
        )
        if all(check.valid for check in evidence_checks):
            try:
                StoryBibleValidator(self._evidence_lookup).validate_commit_plan(
                    commit_plan,
                    canonical_profiles=context.canonical_snapshot.profiles,
                    canonical_states=context.canonical_snapshot.states,
                )
            except ValueError as error:
                self._add_issue(
                    issues,
                    category="CANONICAL_CONFLICT",
                    severity=StoryBibleReviewIssueSeverity.BLOCKING,
                    message=str(error),
                    affected_ids=self._plan_resource_ids(commit_plan),
                )
        self._include_declared_conflicts(proposal, issues)

        issues.sort(key=lambda issue: issue.issue_id)
        blocking_ids = {
            affected_id
            for issue in issues
            if issue.severity == StoryBibleReviewIssueSeverity.BLOCKING
            for affected_id in issue.affected_ids
        }
        if any(
            issue.severity == StoryBibleReviewIssueSeverity.BLOCKING for issue in issues
        ):
            decision = StoryBibleReviewDecision.REJECT
        elif issues:
            decision = StoryBibleReviewDecision.NEEDS_HUMAN_REVIEW
        else:
            decision = StoryBibleReviewDecision.APPROVE
        return StoryBibleReviewResultV1(
            review_id=context.review_id,
            project_id=context.project_id,
            storybible_run_id=context.source_storybible_run_id,
            proposal_hash=proposal_hash,
            decision=decision,
            issues=issues,
            evidence_checks=sorted(evidence_checks, key=lambda check: check.check_id),
            validated_entities=sorted({
                entity.profile_id
                for entity in entities
                if entity.profile_id not in blocking_ids
            }),
            validated_relationships=sorted({
                relationship.relationship_id
                for relationship in relationships
                if relationship.relationship_id not in blocking_ids
            }),
            validated_world_rules=sorted({
                rule.rule_id for rule in world_rules if rule.rule_id not in blocking_ids
            }),
            reviewed_at=context.reviewed_at,
        )

    def _validate_lineage(
        self,
        context: StoryBibleReviewContextV1,
        production_run: StoryBibleProductionRunV1,
        proposal: StoryBibleCuratorProposalV1,
        commit_plan: CommitPlanV1,
        timeline: ApprovedTimelineBundleV1,
        proposal_hash: str,
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        failures: list[str] = []
        if production_run.status != StoryBibleProductionRunStatus.SUCCEEDED:
            failures.append("production run is not SUCCEEDED")
        if production_run.run_id != context.source_storybible_run_id:
            failures.append("production run id mismatch")
        if production_run.project_id != context.project_id:
            failures.append("production project mismatch")
        if (
            proposal.project_id != context.project_id
            or commit_plan.project_id != context.project_id
        ):
            failures.append("proposal project mismatch")
        if timeline.project_id != context.project_id:
            failures.append("Timeline project mismatch")
        if production_run.approved_timeline_bundle_id != timeline.bundle_id:
            failures.append("production Timeline lineage mismatch")
        if context.source_approved_timeline_bundle_id != timeline.bundle_id:
            failures.append("review Timeline lineage mismatch")
        if (
            context.canonical_snapshot_hash
            != production_run.canonical_storybible_snapshot_hash
        ):
            failures.append("canonical snapshot hash mismatch")
        if (
            canonical_storybible_snapshot_hash(context.canonical_snapshot)
            != context.canonical_snapshot_hash
        ):
            failures.append("canonical snapshot content mismatch")
        if context.proposal_hash != proposal_hash:
            failures.append("proposal hash mismatch")
        if proposal.commit_plan != commit_plan:
            failures.append("proposal commit plan mismatch")
        if production_run.curator_proposal != proposal:
            failures.append("production proposal mismatch")
        for message in failures:
            self._add_issue(
                issues,
                category="PRODUCTION_LINEAGE_INVALID",
                severity=StoryBibleReviewIssueSeverity.BLOCKING,
                message=message,
                affected_ids=[context.source_storybible_run_id],
            )

    def _check_all_evidence(
        self,
        proposal: StoryBibleCuratorProposalV1,
        plan: CommitPlanV1,
        timeline: ApprovedTimelineBundleV1,
    ) -> list[StoryBibleEvidenceCheckV1]:
        owned: list[tuple[str, EvidenceRefV1]] = []
        owned.extend((proposal.proposal_id, ref) for ref in proposal.evidence_refs)
        owned.extend((plan.commit_plan_id, ref) for ref in plan.evidence_refs)
        for conflict in proposal.conflicts:
            owned.extend((conflict.conflict_id, ref) for ref in conflict.evidence_refs)
        for update in plan.updates:
            owned.extend((update.update_id, ref) for ref in update.evidence_refs)
            resource = self._resource(update)
            resource_id = self._resource_id(resource)
            owned.extend((resource_id, ref) for ref in resource.evidence_refs)
        owned.extend((timeline.bundle_id, ref) for ref in timeline.evidence_refs)
        for relation in timeline.temporal_relations:
            owned.extend((relation.proposal_id, ref) for ref in relation.evidence_refs)

        checks: dict[str, StoryBibleEvidenceCheckV1] = {}
        for owner_id, evidence_ref in owned:
            evidence_key = json.dumps(
                evidence_ref.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            check_id = stable_id("storybible-evidence-check", owner_id, evidence_key)
            valid, message = self._validate_evidence(evidence_ref, proposal.project_id)
            checks[check_id] = StoryBibleEvidenceCheckV1(
                check_id=check_id,
                owner_id=owner_id,
                evidence_ref=evidence_ref,
                valid=valid,
                message=message,
            )
        return list(checks.values())

    def _validate_evidence(
        self, evidence_ref: EvidenceRefV1, project_id: str
    ) -> tuple[bool, str | None]:
        chunk = self._evidence_lookup.get_chunk(evidence_ref.chunk_id)
        if chunk is None:
            return False, "Evidence chunk does not exist."
        if chunk.project_id != project_id:
            return False, "Evidence chunk belongs to another project."
        if evidence_ref.quote_start is not None and evidence_ref.quote_end is not None:
            if evidence_ref.quote_end > len(chunk.text):
                return False, "Evidence offsets exceed the source chunk."
            if (
                evidence_ref.quote_text is not None
                and chunk.text[evidence_ref.quote_start : evidence_ref.quote_end]
                != evidence_ref.quote_text
            ):
                return False, "Evidence offsets do not match quote_text."
        elif (
            evidence_ref.quote_text is not None
            and evidence_ref.quote_text not in chunk.text
        ):
            return False, "Evidence quote_text is not present in the source chunk."
        return True, None

    def _validate_entities(
        self,
        entities: list[StoryEntityProfileV1],
        canonical_entities: list[StoryEntityProfileV1],
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        ids: set[str] = set()
        identity_owner: dict[str, str] = {}
        for entity in canonical_entities:
            for name in (entity.canonical_name, *entity.aliases):
                identity_owner[name.strip().casefold()] = entity.profile_id
        for entity in entities:
            if entity.profile_id in ids:
                self._blocking(issues, "ENTITY_ID_DUPLICATE", [entity.profile_id])
            ids.add(entity.profile_id)
            for name in (entity.canonical_name, *entity.aliases):
                key = name.strip().casefold()
                owner = identity_owner.get(key)
                if owner is not None and owner != entity.profile_id:
                    self._blocking(
                        issues, "ENTITY_IDENTITY_CONFLICT", sorted([owner, entity.profile_id])
                    )
                identity_owner[key] = entity.profile_id

    def _validate_relationships(
        self,
        relationships: list[StoryRelationshipV1],
        entities: list[StoryEntityProfileV1],
        canonical_entities: list[StoryEntityProfileV1],
        canonical_relationships: list[StoryRelationshipV1],
        timeline: ApprovedTimelineBundleV1,
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        entity_ids = {
            entity.profile_id for entity in [*canonical_entities, *entities]
        }
        event_ids = set(timeline.event_ids)
        ids: set[str] = set()
        for relationship in relationships:
            if relationship.relationship_id in ids:
                self._blocking(
                    issues, "RELATIONSHIP_ID_DUPLICATE", [relationship.relationship_id]
                )
            ids.add(relationship.relationship_id)
            if {
                relationship.source_profile_id,
                relationship.target_profile_id,
            } - entity_ids:
                self._blocking(
                    issues, "RELATIONSHIP_ENTITY_REFERENCE_INVALID", [relationship.relationship_id]
                )
            self._validate_event_anchors(
                relationship.relationship_id,
                [relationship.valid_from_event_id, relationship.valid_until_event_id],
                event_ids,
                issues,
            )
            self._validate_interval(
                relationship.relationship_id,
                relationship.valid_from_order,
                relationship.valid_until_order,
                issues,
            )
        all_relationships = [*canonical_relationships, *relationships]
        proposed_ids = {relationship.relationship_id for relationship in relationships}
        for index, left in enumerate(all_relationships):
            for right in all_relationships[index + 1 :]:
                if not {left.relationship_id, right.relationship_id} & proposed_ids:
                    continue
                if left.relationship_id == right.relationship_id:
                    continue
                same_fact = (
                    left.source_profile_id == right.source_profile_id
                    and left.target_profile_id == right.target_profile_id
                    and left.relationship_type.casefold()
                    == right.relationship_type.casefold()
                )
                if same_fact and left.attributes != right.attributes and self._intervals_overlap(
                        left.valid_from_order,
                        left.valid_until_order,
                        right.valid_from_order,
                        right.valid_until_order,
                    ):
                    affected = sorted([left.relationship_id, right.relationship_id])
                    shared_keys = set(left.attributes) & set(right.attributes)
                    deterministic = any(
                        left.attributes[key] != right.attributes[key] for key in shared_keys
                    )
                    self._add_issue(
                        issues,
                        category="RELATIONSHIP_CONFLICT",
                        severity=(
                            StoryBibleReviewIssueSeverity.BLOCKING
                            if deterministic
                            else StoryBibleReviewIssueSeverity.REVIEW_REQUIRED
                        ),
                        message=(
                            "Overlapping relationship attributes contradict."
                            if deterministic
                            else "Overlapping relationship semantics require human review."
                        ),
                        affected_ids=affected,
                    )

    def _validate_states(
        self,
        states: list[StoryEntityStateV1],
        entities: list[StoryEntityProfileV1],
        canonical_entities: list[StoryEntityProfileV1],
        timeline: ApprovedTimelineBundleV1,
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        entity_ids = {
            entity.profile_id for entity in [*canonical_entities, *entities]
        }
        event_ids = set(timeline.event_ids)
        ids: set[str] = set()
        for state in states:
            if state.state_id in ids:
                self._blocking(issues, "STATE_ID_DUPLICATE", [state.state_id])
            ids.add(state.state_id)
            if state.profile_id not in entity_ids:
                self._blocking(issues, "STATE_ENTITY_REFERENCE_INVALID", [state.state_id])
            self._validate_event_anchors(
                state.state_id,
                [
                    state.triggering_event_id,
                    state.valid_from_event_id,
                    state.valid_until_event_id,
                ],
                event_ids,
                issues,
            )
            self._validate_interval(
                state.state_id,
                state.valid_from_order,
                state.valid_until_order,
                issues,
            )

    def _validate_world_rules(
        self,
        rules: list[WorldRuleV1],
        canonical_rules: list[WorldRuleV1],
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        ids: set[str] = set()
        facts: dict[tuple[str, str], WorldRuleV1] = {
            ((rule.scope or "").strip().casefold(), rule.name.strip().casefold()): rule
            for rule in canonical_rules
        }
        for rule in rules:
            if rule.rule_id in ids:
                self._blocking(issues, "WORLD_RULE_ID_DUPLICATE", [rule.rule_id])
            ids.add(rule.rule_id)
            if rule.scope is not None and not rule.scope.strip():
                self._blocking(issues, "WORLD_RULE_SCOPE_INVALID", [rule.rule_id])
            key = ((rule.scope or "").strip().casefold(), rule.name.strip().casefold())
            previous = facts.get(key)
            if previous is not None and previous.rule_id != rule.rule_id:
                self._blocking(
                    issues,
                    (
                        "WORLD_RULE_CONFLICT"
                        if previous.statement.strip() != rule.statement.strip()
                        else "WORLD_RULE_DUPLICATE"
                    ),
                    sorted([previous.rule_id, rule.rule_id]),
                )
            facts[key] = rule

    def _include_declared_conflicts(
        self,
        proposal: StoryBibleCuratorProposalV1,
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        resource_by_update = {
            update.update_id: self._resource_id(self._resource(update))
            for update in proposal.commit_plan.updates
        }
        for conflict in proposal.conflicts:
            self._add_issue(
                issues,
                category=(
                    "DECLARED_DETERMINISTIC_CONFLICT"
                    if conflict.blocking
                    else "UNKNOWN_SEMANTIC_CONFLICT"
                ),
                severity=(
                    StoryBibleReviewIssueSeverity.BLOCKING
                    if conflict.blocking
                    else StoryBibleReviewIssueSeverity.REVIEW_REQUIRED
                ),
                message=conflict.summary,
                affected_ids=sorted(
                    resource_by_update[update_id]
                    for update_id in conflict.affected_update_ids
                ),
                evidence_refs=conflict.evidence_refs,
            )

    def _validate_event_anchors(
        self,
        resource_id: str,
        anchors: Iterable[str | None],
        approved_event_ids: set[str],
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        if any(anchor is not None and anchor not in approved_event_ids for anchor in anchors):
            self._blocking(issues, "TIMELINE_ANCHOR_MISSING", [resource_id])

    def _validate_interval(
        self,
        resource_id: str,
        start: int | None,
        end: int | None,
        issues: list[StoryBibleReviewIssueV1],
    ) -> None:
        if start is not None and end is not None and end < start:
            self._blocking(issues, "TEMPORAL_INTERVAL_INVALID", [resource_id])

    @staticmethod
    def _intervals_overlap(
        left_start: int | None,
        left_end: int | None,
        right_start: int | None,
        right_end: int | None,
    ) -> bool:
        return not (
            left_end is not None
            and right_start is not None
            and left_end < right_start
            or right_end is not None
            and left_start is not None
            and right_end < left_start
        )

    def _blocking(
        self, issues: list[StoryBibleReviewIssueV1], category: str, affected_ids: list[str]
    ) -> None:
        self._add_issue(
            issues,
            category=category,
            severity=StoryBibleReviewIssueSeverity.BLOCKING,
            message=category.replace("_", " ").capitalize() + ".",
            affected_ids=affected_ids,
        )

    @staticmethod
    def _add_issue(
        issues: list[StoryBibleReviewIssueV1],
        *,
        category: str,
        severity: StoryBibleReviewIssueSeverity,
        message: str,
        affected_ids: list[str],
        evidence_refs: list[EvidenceRefV1] | None = None,
    ) -> None:
        affected_ids = sorted(set(affected_ids))
        issue_id = stable_id("storybible-review-issue", category, *affected_ids, message)
        issue = StoryBibleReviewIssueV1(
            issue_id=issue_id,
            category=category,
            severity=severity,
            message=message,
            affected_ids=affected_ids,
            evidence_refs=evidence_refs or [],
        )
        if issue.issue_id not in {existing.issue_id for existing in issues}:
            issues.append(issue)

    @staticmethod
    def _resource(update: Any) -> Any:
        if isinstance(update, ProfileUpdateProposalV1):
            return update.profile
        if isinstance(update, RelationshipUpdateProposalV1):
            return update.relationship
        if isinstance(update, StateUpdateProposalV1):
            return update.state
        return update.world_rule

    @staticmethod
    def _resource_id(resource: Any) -> str:
        for field in ("profile_id", "relationship_id", "state_id", "rule_id"):
            value = getattr(resource, field, None)
            if value is not None:
                return str(value)
        raise TypeError("unsupported StoryBible resource")

    @classmethod
    def _plan_resource_ids(cls, plan: CommitPlanV1) -> list[str]:
        return sorted({cls._resource_id(cls._resource(update)) for update in plan.updates})
