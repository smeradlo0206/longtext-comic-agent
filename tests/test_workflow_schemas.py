from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comic_agent.schemas.workflow import (
    AgentInputRefV1,
    AgentOutputRefV1,
    AgentRunStatus,
    AgentRunV1,
    MockProviderResultV1,
    NarrativeAnalysisResultV1,
    ProviderResultV1,
    ProviderType,
)


def provider_result_payload() -> dict[str, object]:
    return {
        "provider_result_id": "provider-result-1",
        "provider_name": "mock-llm",
        "provider_type": ProviderType.MOCK,
        "output_schema": "EventProposalV1",
        "structured_output": {"proposal_id": "proposal-1"},
        "success": True,
        "latency_ms": 12,
    }


def agent_run_payload() -> dict[str, object]:
    return {
        "agent_run_id": "agent-run-1",
        "project_id": "project-1",
        "agent_name": "MockEventAgent",
        "input_chunk_ids": ["chunk-1", "chunk-2"],
        "output_proposal_ids": ["proposal-1"],
        "output_schema": "EventProposalV1",
        "provider_result_id": "provider-result-1",
        "status": AgentRunStatus.SUCCEEDED,
        "started_at": datetime(2026, 7, 28, tzinfo=UTC),
        "completed_at": datetime(2026, 7, 28, 0, 0, 1, tzinfo=UTC),
        "payload": {"mode": "mock"},
    }


def test_agent_run_minimal_valid_example() -> None:
    agent_run = AgentRunV1(**agent_run_payload())

    assert agent_run.agent_run_id == "agent-run-1"
    assert agent_run.input_chunk_ids == ["chunk-1", "chunk-2"]
    assert agent_run.output_proposal_ids == ["proposal-1"]
    assert agent_run.output_schema == "EventProposalV1"


def test_agent_run_can_record_input_and_output_refs() -> None:
    agent_run = AgentRunV1(
        **(
            agent_run_payload()
            | {
                "input_refs": [
                    AgentInputRefV1(
                        object_id="chunk-1",
                        object_schema="SourceChunkV1",
                        role="source_chunk",
                    )
                ],
                "output_refs": [
                    AgentOutputRefV1(
                        object_id="proposal-1",
                        object_schema="EventProposalV1",
                        role="event_proposal",
                    )
                ],
            }
        )
    )

    assert agent_run.input_refs[0].object_id == "chunk-1"
    assert agent_run.output_refs[0].object_schema == "EventProposalV1"


def test_agent_run_requires_valid_status() -> None:
    with pytest.raises(ValidationError):
        AgentRunV1(**(agent_run_payload() | {"status": "DONE"}))


def test_agent_run_requires_status() -> None:
    payload = agent_run_payload()
    payload.pop("status")

    with pytest.raises(ValidationError):
        AgentRunV1(**payload)


def test_provider_result_success_example() -> None:
    result = ProviderResultV1(**provider_result_payload())

    assert result.provider_type == ProviderType.MOCK
    assert result.output_schema == "EventProposalV1"
    assert result.success is True
    assert result.error_message is None


def test_provider_result_success_rejects_error_message() -> None:
    with pytest.raises(ValidationError):
        ProviderResultV1(**(provider_result_payload() | {"error_message": "should not be present"}))


def test_provider_result_success_requires_output() -> None:
    with pytest.raises(ValidationError):
        ProviderResultV1(
            **(
                provider_result_payload()
                | {
                    "raw_output": None,
                    "structured_output": None,
                }
            )
        )


def test_provider_result_failure_can_record_error_message() -> None:
    result = ProviderResultV1(
        **(
            provider_result_payload()
            | {
                "success": False,
                "structured_output": None,
                "error_message": "mock schema error",
            }
        )
    )

    assert result.success is False
    assert result.error_message == "mock schema error"


def test_provider_result_failure_requires_error_message() -> None:
    with pytest.raises(ValidationError):
        ProviderResultV1(
            **(provider_result_payload() | {"success": False, "structured_output": None})
        )


def test_agent_run_succeeded_requires_input_chunks() -> None:
    with pytest.raises(ValidationError):
        AgentRunV1(**(agent_run_payload() | {"input_chunk_ids": []}))


def test_agent_run_succeeded_requires_output_or_provider_result() -> None:
    with pytest.raises(ValidationError):
        AgentRunV1(
            **(
                agent_run_payload()
                | {
                    "output_proposal_ids": [],
                    "provider_result_id": None,
                    "provider_result": None,
                }
            )
        )


def test_agent_run_succeeded_accepts_inline_provider_result_without_output_ids() -> None:
    agent_run = AgentRunV1(
        **(
            agent_run_payload()
            | {
                "output_proposal_ids": [],
                "provider_result_id": None,
                "provider_result": ProviderResultV1(**provider_result_payload()),
            }
        )
    )

    assert agent_run.provider_result is not None


def test_agent_run_failed_requires_error_message() -> None:
    with pytest.raises(ValidationError):
        AgentRunV1(
            **(
                agent_run_payload()
                | {
                    "output_proposal_ids": [],
                    "provider_result_id": None,
                    "status": AgentRunStatus.FAILED,
                    "error_message": None,
                }
            )
        )


def test_agent_run_failed_allows_empty_outputs_with_error_message() -> None:
    agent_run = AgentRunV1(
        **(
            agent_run_payload()
            | {
                "output_proposal_ids": [],
                "provider_result_id": None,
                "status": AgentRunStatus.FAILED,
                "error_message": "mock schema error",
            }
        )
    )

    assert agent_run.status == AgentRunStatus.FAILED
    assert agent_run.output_proposal_ids == []


def test_mock_provider_result_records_mock_event_output() -> None:
    result = MockProviderResultV1(
        provider_result_id="provider-result-1",
        output_schema="EventProposalV1",
        structured_output={
            "proposal_id": "proposal-1",
            "event_type": "handoff",
            "summary": "陈野把伞递给林夏。",
            "evidence_refs": [{"chunk_id": "chunk-1"}],
            "confidence": 0.9,
            "reality_layer": "PRIMARY",
        },
        success=True,
    )

    assert result.provider_type == ProviderType.MOCK
    assert result.provider_name == "mock"
    assert result.structured_output["proposal_id"] == "proposal-1"


def test_unversioned_legacy_analysis_result_defaults_to_empty_knowledge_states() -> None:
    result = NarrativeAnalysisResultV1.model_validate(
        {"analysis_run_id": "analysis-legacy", "events": [], "entities": [], "claims": []}
    )

    assert result.schema_version == "1.0"
    assert result.knowledge_states == []


def test_analysis_result_reads_legacy_payloads_and_defaults_state_changes() -> None:
    v10 = NarrativeAnalysisResultV1.model_validate(
        {"analysis_run_id": "analysis-v10", "events": [], "entities": [], "claims": []}
    )
    v11 = NarrativeAnalysisResultV1.model_validate(
        {
            "analysis_run_id": "analysis-v11",
            "events": [],
            "entities": [],
            "claims": [],
            "knowledge_states": [],
        }
    )
    v12 = NarrativeAnalysisResultV1.model_validate(
        {
            "schema_version": "1.2",
            "analysis_run_id": "analysis-v12",
            "events": [],
            "entities": [],
            "claims": [],
            "knowledge_states": [],
            "state_changes": [],
        }
    )
    current = NarrativeAnalysisResultV1(analysis_run_id="analysis-current")

    assert v10.schema_version == "1.0"
    assert v10.knowledge_states == []
    assert v10.state_changes == []
    assert v11.schema_version == "1.1"
    assert v11.state_changes == []
    assert v12.schema_version == "1.2"
    assert current.schema_version == "1.3"
    assert current.knowledge_states == []
    assert current.state_changes == []


def test_analysis_result_unversioned_state_changes_payload_reads_as_v13() -> None:
    result = NarrativeAnalysisResultV1.model_validate(
        {"analysis_run_id": "analysis-v13-unversioned", "state_changes": []}
    )

    assert result.schema_version == "1.3"
    assert result.state_changes == []


def test_workflow_schemas_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgentRunV1(**(agent_run_payload() | {"api_key": "secret"}))
