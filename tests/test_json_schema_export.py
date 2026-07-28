import json

from scripts import export_json_schemas


def test_json_schema_export_includes_phase_one_workflow_schemas(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    export_json_schemas.main()

    output_dir = tmp_path / "schema_exports"
    assert (output_dir / "AgentRunV1.json").exists()
    assert (output_dir / "ProviderResultV1.json").exists()
    assert (output_dir / "MockProviderResultV1.json").exists()
    assert (output_dir / "ClaimProposalV1.json").exists()
    assert (output_dir / "KnowledgeStateProposalV1.json").exists()

    event_schema = json.loads((output_dir / "EventProposalV1.json").read_text(encoding="utf-8"))
    claim_schema = json.loads((output_dir / "ClaimProposalV1.json").read_text(encoding="utf-8"))
    knowledge_schema = json.loads(
        (output_dir / "KnowledgeStateProposalV1.json").read_text(encoding="utf-8")
    )
    source_chunk_schema = json.loads(
        (output_dir / "SourceChunkV1.json").read_text(encoding="utf-8")
    )

    assert "actor_resolution_status" in event_schema["properties"]
    assert "evidence_refs" in event_schema["properties"]
    assert "confidence" in event_schema["properties"]
    assert "evidence_refs" in event_schema["required"]
    assert "confidence" in event_schema["required"]
    assert event_schema["additionalProperties"] is False
    assert event_schema["properties"]["confidence"]["minimum"] == 0
    assert event_schema["properties"]["confidence"]["maximum"] == 1
    assert "claim_type" in claim_schema["properties"]
    assert "verification_status" in claim_schema["properties"]
    assert "evidence_refs" in claim_schema["required"]
    assert claim_schema["additionalProperties"] is False
    assert "epistemic_status" in knowledge_schema["properties"]
    assert "evidence_refs" in knowledge_schema["required"]
    assert knowledge_schema["additionalProperties"] is False
    assert "char_start" in source_chunk_schema["properties"]
    assert "char_end" in source_chunk_schema["properties"]
    assert "checksum" in source_chunk_schema["properties"]
