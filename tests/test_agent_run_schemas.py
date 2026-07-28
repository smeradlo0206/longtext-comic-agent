from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1


def test_agent_run_records_mock_agent_input_and_output() -> None:
    agent_run = AgentRunV1(
        agent_run_id="agent-run-1",
        project_id="project-1",
        source_chunk_id="chunk-1",
        agent_id="mock-event-agent",
        status=AgentRunStatus.SUCCEEDED,
        output_proposal_id="proposal-1",
    )

    assert agent_run.status == "SUCCEEDED"
    assert agent_run.output_proposal_id == "proposal-1"
