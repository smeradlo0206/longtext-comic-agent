"""Predictable mock providers for unit tests."""

import json
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from comic_agent.providers.image import ImageResult

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class MockMode(StrEnum):
    """Mock provider behavior mode."""

    SUCCESS = "SUCCESS"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    TIMEOUT = "TIMEOUT"


class MockLLMProvider:
    """Network-free structured LLM mock."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        mode: MockMode = MockMode.SUCCESS,
    ) -> None:
        self._response = response or {}
        self._mode = mode

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Return configured structured data or deterministic errors."""

        if self._mode == MockMode.TIMEOUT:
            raise TimeoutError("mock provider timeout")
        if self._mode == MockMode.SCHEMA_ERROR:
            try:
                output_model.model_validate(self._response)
            except ValidationError as exc:
                raise ValueError("mock schema error") from exc
            raise ValueError("mock schema error")
        return output_model.model_validate(self._response)


class LocalSafeDemoProvider:
    """Deterministic, network-free provider for the opt-in local pipeline demo only."""

    def __init__(self, *, scenario: str = "success") -> None:
        self.calls = 0
        self._scenario = scenario
        self._event_calls = 0
        self._timeline_calls = 0

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Return evidence-backed event batches and ordered Timeline relations."""

        self.calls += 1
        if output_model.__name__ == "EventProposalBatchV1":
            self._event_calls += 1
            return output_model.model_validate(self._event_batch(request))
        if output_model.__name__ == "TemporalRelationProposalV1":
            return output_model.model_validate(self._temporal_relation(request))
        return output_model.model_validate({"batch_id": "local-demo-empty", "items": []})

    def _event_batch(self, request: dict[str, object]) -> dict[str, object]:
        input_context = request.get("input_context")
        if not isinstance(input_context, dict):
            raise ValueError("local demo requires Narrative input context")
        raw_chunks = input_context.get("source_chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            raise ValueError("local demo requires a source chunk")
        first_chunk = raw_chunks[0]
        if not isinstance(first_chunk, dict):
            raise ValueError("local demo source chunk is invalid")
        chunk_id = first_chunk.get("chunk_id")
        text = first_chunk.get("text")
        if not isinstance(chunk_id, str) or not isinstance(text, str):
            raise ValueError("local demo source chunk is invalid")
        sentences = [
            sentence.strip()
            for sentence in text.replace("！", "。").replace("!", ".").split("。")
            if sentence.strip()
        ]
        if not sentences:
            sentences = [text.strip()]
        return {
            "batch_id": "local-safe-demo-events",
            "events": [
                {
                    "proposal_id": f"local-demo-event-{index}",
                    "event_type": "local_demo_event",
                    "summary": f"Local demo event {index}",
                    "participant_ids": [],
                    "actor_resolution_status": "UNKNOWN",
                    "evidence_refs": [
                        {
                            "chunk_id": chunk_id,
                            "quote_text": (
                                "not present in source"
                                if self._scenario == "recover_gate2" and self._event_calls == 1
                                else sentence
                            ),
                        }
                    ],
                    "confidence": 1.0,
                    "reality_layer": "PRIMARY",
                }
                for index, sentence in enumerate(sentences, start=1)
            ],
        }

    def _temporal_relation(self, request: dict[str, object]) -> dict[str, object]:
        messages = request.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError("local demo Timeline request is invalid")
        user = messages[-1]
        if not isinstance(user, dict) or not isinstance(user.get("content"), str):
            raise ValueError("local demo Timeline request is invalid")
        payload = json.loads(user["content"])
        first = payload["event_a"]
        second = payload["event_b"]
        self._timeline_calls += 1
        return {
            "proposal_id": "local-demo-temporal-relation",
            "source_event_id": first["proposal_id"],
            "target_event_id": second["proposal_id"],
            "relation": (
                "AFTER"
                if self._scenario == "recover_gate3" and self._timeline_calls == 2
                else "BEFORE"
            ),
            "evidence_refs": first["evidence_refs"],
            "confidence": 1.0,
        }


class MockImageProvider:
    """Network-free image provider mock."""

    def generate(self, request: dict[str, object]) -> ImageResult:
        """Return a predictable mock image URI."""

        panel_id = str(request.get("panel_id", "image"))
        return ImageResult(
            storage_uri=f"mock://images/{panel_id}.png",
            width=1024,
            height=1024,
            metadata={"mode": "generate"},
        )

    def edit(self, request: dict[str, object]) -> ImageResult:
        """Return a predictable mock edit URI."""

        panel_id = str(request.get("panel_id", "image"))
        return ImageResult(
            storage_uri=f"mock://images/{panel_id}-edit.png",
            width=1024,
            height=1024,
            metadata={"mode": "edit"},
        )
