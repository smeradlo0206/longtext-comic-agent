"""OpenAI-compatible structured-generation provider."""

import json
import re
import socket
import ssl
from collections.abc import Mapping
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from comic_agent.config import Settings
from comic_agent.providers.llm import OutputModelT as ProviderOutputModelT
from comic_agent.schemas.reliability import (
    ProviderCapabilityProfileV1,
    ProviderCapabilityState,
    ProviderExecutionMetadataV1,
    ProviderPreflightResponseV1,
    StructuredOutputMode,
    StructuredOutputPolicy,
)


class OpenAICompatibleProvider:
    """Generate validated JSON through an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[ProviderOutputModelT],
    ) -> ProviderOutputModelT:
        """Post a JSON-object request and validate the first assistant message."""

        payload = dict(request)
        payload["model"] = self._model
        payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
            response = client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()
        return output_model.model_validate_json(self._message_content(response.json()))

    @staticmethod
    def _message_content(response_payload: object) -> str:
        if not isinstance(response_payload, dict):
            raise ValueError("provider response must be a JSON object")
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider response must contain at least one choice")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("provider choice must be a JSON object")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("provider choice must contain a message object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("provider message content must be a JSON string")
        return content


OutputModelT = TypeVar("OutputModelT", bound=BaseModel)
ProviderDiagnostics = dict[str, object]
MAX_TIMEOUT_ATTEMPTS = 2


class ProviderResponseError(ValueError):
    """Sanitized provider response parsing error with non-secret diagnostics."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ProviderHttpError(ValueError):
    """Sanitized HTTP provider error with status-only diagnostics."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ProviderTimeoutError(TimeoutError):
    """Sanitized timeout error that records only request-level metadata."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ProviderNetworkError(ValueError):
    """Sanitized transport failure without URL, body, or credential details."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class HttpClient(Protocol):
    """HTTP client surface used by OpenAICompatibleLLMProvider."""

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> httpx.Response:
        """POST JSON data to an HTTP endpoint."""


class OpenAICompatibleLLMProvider:
    """Structured provider for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.llm.ustc.edu.cn/v1",
        model: str = "deepseek-v4-pro",
        provider_name: str = "ustc-openai-compatible",
        response_format: str | None = None,
        structured_output_policy: StructuredOutputPolicy = StructuredOutputPolicy.JSON_OBJECT_ONLY,
        timeout_seconds: int = 60,
        max_output_tokens: int = 2000,
        http_client: HttpClient | None = None,
    ) -> None:
        if api_key is None or api_key.strip() == "":
            raise ValueError("LLM API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._provider_name_value = provider_name
        self._response_format = response_format.strip() if response_format else None
        self._structured_output_policy = structured_output_policy
        self._capability_profile: ProviderCapabilityProfileV1 | None = None
        self._last_execution_metadata: ProviderExecutionMetadataV1 | None = None
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._http_client = http_client or httpx.Client()

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Generate and validate one structured Pydantic model."""

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(request, output_model),
            "temperature": 0,
            "max_tokens": self._max_output_tokens,
        }
        output_mode = self._selected_output_mode()
        response_format = self._response_format_for(output_mode, output_model)
        if response_format is not None:
            payload["response_format"] = response_format

        request_attempts = 1
        try:
            response, request_attempts = self._post_with_one_timeout_retry(payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderHttpError(
                self._classify_http_status_error(exc.response.status_code),
                diagnostics={
                    "http_status_code": exc.response.status_code,
                    "request_attempts": request_attempts,
                },
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderNetworkError(
                self._classify_connect_error(exc),
                diagnostics={"request_attempts": request_attempts},
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderNetworkError(
                "LLM provider network error", diagnostics={"request_attempts": request_attempts}
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                "LLM provider request error", diagnostics={"request_attempts": request_attempts}
            ) from exc

        try:
            response_payload = response.json()
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM provider response format is invalid") from exc
        diagnostics = self._response_diagnostics(response_payload)
        self._last_execution_metadata = ProviderExecutionMetadataV1(
            selected_output_mode=output_mode,
            capability_state=(self._capability_profile.state if self._capability_profile else None),
            finish_reason=(
                diagnostics.get("finish_reason")
                if isinstance(diagnostics.get("finish_reason"), str)
                else None
            ),
            prompt_tokens=self._diagnostic_int(diagnostics, "usage_prompt_tokens"),
            completion_tokens=self._diagnostic_int(diagnostics, "usage_completion_tokens"),
            total_tokens=self._diagnostic_int(diagnostics, "usage_total_tokens"),
            expected_output_schema=output_model.__name__,
        )
        self._validate_response_content(content, diagnostics)

        try:
            payload = json.loads(self._extract_json(content))
        except json.JSONDecodeError as exc:
            if self._exceeded_max_output_tokens(diagnostics):
                raise ProviderResponseError(
                    self._max_output_tokens_error_message(),
                    diagnostics=diagnostics,
                ) from exc
            raise ProviderResponseError(
                "LLM provider response did not contain valid JSON",
                diagnostics=diagnostics,
            ) from exc

        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            diagnostics.update(self.schema_validation_diagnostics(exc, output_model))
            self._last_execution_metadata = self._last_execution_metadata.model_copy(
                update={"schema_diagnostics": self._safe_schema_diagnostics(diagnostics)}
            )
            raise ProviderResponseError(
                (
                    self._max_output_tokens_error_message()
                    if self._exceeded_max_output_tokens(diagnostics)
                    else "LLM provider response failed schema validation"
                ),
                diagnostics=diagnostics,
            ) from exc

    def apply_capability_profile(self, profile: ProviderCapabilityProfileV1) -> None:
        """Apply only a source-free profile resolved by the capability service."""

        if profile.provider_name != self._provider_name() or profile.model_name != self._model:
            raise ValueError("capability profile does not match configured provider/model")
        self._capability_profile = profile

    def last_execution_metadata(self) -> ProviderExecutionMetadataV1 | None:
        """Return allowlisted metadata from the latest call; never response content."""

        return self._last_execution_metadata

    def probe_structured_output(
        self, policy: StructuredOutputPolicy
    ) -> ProviderCapabilityProfileV1:
        """Probe the configured endpoint using only fixed readiness messages and schema."""

        supports_strict = False
        supports_json_object = False
        supports_usage = False
        supports_finish = False
        strict_error: ProviderHttpError | None = None
        if policy != StructuredOutputPolicy.JSON_OBJECT_ONLY:
            try:
                diagnostics = self._probe(StructuredOutputMode.STRICT_JSON_SCHEMA)
                supports_strict = True
                supports_json_object = True
                supports_usage = self._diagnostic_int(diagnostics, "usage_total_tokens") is not None
                supports_finish = isinstance(diagnostics.get("finish_reason"), str)
            except ProviderHttpError as exc:
                strict_error = exc
                status = exc.diagnostics.get("http_status_code")
                if not isinstance(status, int) or status not in {400, 404, 415, 422}:
                    raise
        if policy != StructuredOutputPolicy.REQUIRE_STRICT and not supports_strict:
            try:
                diagnostics = self._probe(StructuredOutputMode.JSON_OBJECT)
                supports_json_object = True
                supports_usage = self._diagnostic_int(diagnostics, "usage_total_tokens") is not None
                supports_finish = isinstance(diagnostics.get("finish_reason"), str)
            except ProviderHttpError as exc:
                status = exc.diagnostics.get("http_status_code")
                if not isinstance(status, int) or status not in {400, 404, 415, 422}:
                    raise
        mode = (
            StructuredOutputMode.STRICT_JSON_SCHEMA
            if supports_strict
            else StructuredOutputMode.JSON_OBJECT
            if supports_json_object and policy != StructuredOutputPolicy.REQUIRE_STRICT
            else StructuredOutputMode.UNAVAILABLE
        )
        return ProviderCapabilityProfileV1(
            provider_name=self._provider_name(),
            model_name=self._model,
            state=(
                ProviderCapabilityState.AVAILABLE
                if mode != StructuredOutputMode.UNAVAILABLE
                else ProviderCapabilityState.UNSUPPORTED
            ),
            supports_json_object=supports_json_object,
            supports_strict_json_schema=supports_strict,
            supports_usage_reporting=supports_usage,
            supports_finish_reason=supports_finish,
            selected_output_mode=mode,
            http_status_code=(
                strict_error.diagnostics.get("http_status_code")
                if strict_error is not None
                and isinstance(strict_error.diagnostics.get("http_status_code"), int)
                else None
            ),
            safe_issue_codes=(
                []
                if mode != StructuredOutputMode.UNAVAILABLE
                else ["UNSUPPORTED_STRUCTURED_OUTPUT"]
            ),
        )

    def _probe(self, mode: StructuredOutputMode) -> ProviderDiagnostics:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Return only the required readiness JSON."},
                {"role": "user", "content": "Readiness probe. No external context."},
            ],
            "temperature": 0,
            "max_tokens": 32,
            "response_format": self._response_format_for(mode, ProviderPreflightResponseV1),
        }
        response, attempts = self._post_with_one_timeout_retry(payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderHttpError(
                self._classify_http_status_error(exc.response.status_code),
                diagnostics={
                    "http_status_code": exc.response.status_code,
                    "request_attempts": attempts,
                },
            ) from exc
        response_payload = response.json()
        content = response_payload["choices"][0]["message"]["content"]
        ProviderPreflightResponseV1.model_validate(json.loads(self._extract_json(content)))
        return self._response_diagnostics(response_payload)

    def _selected_output_mode(self) -> StructuredOutputMode:
        if self._capability_profile is not None:
            if self._capability_profile.selected_output_mode == StructuredOutputMode.UNAVAILABLE:
                raise ProviderResponseError(
                    "structured Provider output is unavailable",
                    diagnostics={"safe_issue_code": "UNSUPPORTED_STRUCTURED_OUTPUT"},
                )
            return self._capability_profile.selected_output_mode
        # Preserve the historical explicit environment override. New source-bearing
        # paths resolve a persisted profile before calling this provider.
        if self._response_format == "json_object":
            return StructuredOutputMode.JSON_OBJECT
        return StructuredOutputMode.PROMPT_ONLY

    @staticmethod
    def _response_format_for(
        mode: StructuredOutputMode, output_model: type[BaseModel]
    ) -> dict[str, Any] | None:
        if mode == StructuredOutputMode.JSON_OBJECT:
            return {"type": "json_object"}
        if mode == StructuredOutputMode.STRICT_JSON_SCHEMA:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__.lower(),
                    "schema": output_model.model_json_schema(),
                    "strict": True,
                },
            }
        return None

    @staticmethod
    def _diagnostic_int(diagnostics: ProviderDiagnostics, key: str) -> int | None:
        value = diagnostics.get(key)
        return value if isinstance(value, int) and value >= 0 else None

    @staticmethod
    def _safe_schema_diagnostics(diagnostics: ProviderDiagnostics) -> ProviderDiagnostics:
        keys = {
            "finish_reason",
            "usage_prompt_tokens",
            "usage_completion_tokens",
            "usage_total_tokens",
            "schema_error_kind",
            "schema_error_field_paths",
            "schema_error_rule_codes",
            "expected_output_schema",
        }
        return {key: value for key, value in diagnostics.items() if key in keys}

    def _provider_name(self) -> str:
        return self._provider_name_value

    @staticmethod
    def schema_validation_diagnostics(
        exc: ValidationError,
        output_model: type[BaseModel] | str,
    ) -> ProviderDiagnostics:
        """Return schema-only Pydantic metadata without invalid values or response content."""

        field_paths: list[str] = []
        error_kinds: list[str] = []
        rule_codes: list[str] = []
        for error in exc.errors(include_input=False):
            error_type = error.get("type")
            if isinstance(error_type, str):
                error_kinds.append(error_type)
            location = error.get("loc")
            if not isinstance(location, tuple):
                continue
            path_parts = [str(item) for item in location if isinstance(item, (str, int))]
            if path_parts:
                field_paths.append(".".join(path_parts))
            rule_code = OpenAICompatibleLLMProvider._schema_validation_rule_code(error)
            if rule_code is not None:
                rule_codes.append(rule_code)
        unique_kinds = sorted(set(error_kinds))
        output_schema_name = (
            output_model if isinstance(output_model, str) else output_model.__name__
        )
        if output_schema_name == "RelationshipSignalProposalBatchV1" and field_paths:
            rule_codes.append("RELATIONSHIP_SIGNAL_SCHEMA_INVALID")
        diagnostics: ProviderDiagnostics = {
            "schema_error_kind": unique_kinds[0] if len(unique_kinds) == 1 else "multiple",
            "schema_error_field_paths": sorted(set(field_paths)),
            "expected_output_schema": output_schema_name,
        }
        if rule_codes:
            diagnostics["schema_error_rule_codes"] = sorted(set(rule_codes))
        return diagnostics

    @staticmethod
    def _schema_validation_rule_code(error: Mapping[str, object]) -> str | None:
        """Map only known static model rules to safe recovery labels."""

        message = str(error.get("msg", ""))
        known_rules = {
            "for quantity must be numeric": "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER",
            "must be a JSON scalar": "STATE_CHANGE_VALUE_MUST_BE_SCALAR",
            "cannot be blank": "STATE_CHANGE_VALUE_MUST_NOT_BE_BLANK",
            "new_value must not be null": "STATE_CHANGE_NEW_VALUE_REQUIRED",
            "old_value cannot use an unknown placeholder": (
                "STATE_CHANGE_OLD_VALUE_MUST_NOT_BE_UNKNOWN"
            ),
            "attribute_path is incompatible with target_kind": (
                "STATE_CHANGE_TARGET_KIND_ATTRIBUTE_PATH_MISMATCH"
            ),
            "contains an out-of-range index": "STATE_CHANGE_EVIDENCE_INDEX_OUT_OF_RANGE",
            "new_value_evidence_indexes is required": "STATE_CHANGE_NEW_VALUE_EVIDENCE_REQUIRED",
            "new_value_evidence_indexes must not be empty": (
                "STATE_CHANGE_NEW_VALUE_EVIDENCE_REQUIRED"
            ),
            "new_value_evidence_indexes must not contain duplicate": (
                "STATE_CHANGE_NEW_VALUE_EVIDENCE_DUPLICATE"
            ),
            "persistence_evidence_indexes is required": (
                "STATE_CHANGE_PERSISTENCE_EVIDENCE_REQUIRED"
            ),
            "persistence_evidence_indexes must not contain duplicate": (
                "STATE_CHANGE_PERSISTENCE_EVIDENCE_DUPLICATE"
            ),
            "persistent=false requires": "STATE_CHANGE_PERSISTENCE_INDEX_RULE",
            "must not contain semantic duplicate": "STATE_CHANGE_SEMANTIC_DUPLICATE",
            "must have unique proposal_id": "STATE_CHANGE_DUPLICATE_PROPOSAL_ID",
            "requires event and target": "STATE_CHANGE_SOURCE_FIRST_REFERENCES_REQUIRED",
            "BELIEVES, SUSPECTS, and DISBELIEVES must target WORLD_FACT or EVENT": (
                "BELIEF_ATTITUDE_REQUIRES_WORLD_FACT_OR_EVENT"
            ),
            "v1.1 cannot include legacy": "V1_1_LEGACY_FIELDS_FORBIDDEN",
            "UNRESOLVED target requires proposal_id and proposal_schema to be null": (
                "TARGET_REFERENCE_MUST_STAY_UNRESOLVED"
            ),
            "UNRESOLVED event requires proposal_id and proposal_schema to be null": (
                "EVENT_REFERENCE_MUST_STAY_UNRESOLVED"
            ),
            "RESOLVED event requires proposal_id and proposal_schema": (
                "RESOLVED_EVENT_REQUIRES_CANDIDATE_PROPOSAL"
            ),
            "RESOLVED target requires proposal_id and proposal_schema": (
                "RESOLVED_TARGET_REQUIRES_CANDIDATE_PROPOSAL"
            ),
            "target_kind and proposal_schema must match a candidate Proposal type": (
                "TARGET_KIND_PROPOSAL_SCHEMA_MISMATCH"
            ),
            "supporting_claim_proposal_id requires CLAIM target or STATED/HEARD basis": (
                "SUPPORTING_CLAIM_REQUIRES_SUPPORTED_LINK"
            ),
            "relationship_domain does not match relationship_kind": (
                "RELATIONSHIP_SIGNAL_DOMAIN_KIND_MISMATCH"
            ),
            "directionality does not match relationship_kind": (
                "RELATIONSHIP_SIGNAL_DIRECTIONALITY_MISMATCH"
            ),
            "statement evidence_basis requires source_speaker": (
                "RELATIONSHIP_SIGNAL_STATEMENT_REQUIRES_SPEAKER"
            ),
            "statement evidence_basis cannot use EXPLICIT support_level": (
                "RELATIONSHIP_SIGNAL_STATEMENT_SUPPORT_LEVEL_INVALID"
            ),
            "OBSERVED_ACTION cannot use EXPLICIT support_level": (
                "RELATIONSHIP_SIGNAL_OBSERVED_ACTION_SUPPORT_LEVEL_INVALID"
            ),
            "relationship change signal requires non-empty temporal anchor_text": (
                "RELATIONSHIP_SIGNAL_CHANGE_REQUIRES_TEMPORAL_ANCHOR"
            ),
        }
        for message_prefix, code in known_rules.items():
            if message_prefix in message:
                return code
        return None

    def _post_with_one_timeout_retry(self, payload: dict[str, Any]) -> tuple[httpx.Response, int]:
        """Retry one timeout, connection failure, or transient HTTP response safely."""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        for request_attempt in range(1, MAX_TIMEOUT_ATTEMPTS + 1):
            try:
                response = self._http_client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
                if self._is_retryable_http_status(response.status_code):
                    if request_attempt < MAX_TIMEOUT_ATTEMPTS:
                        continue
                return response, request_attempt
            except httpx.TimeoutException as exc:
                if request_attempt == MAX_TIMEOUT_ATTEMPTS:
                    timeout_kind = self._timeout_kind(exc)
                    raise ProviderTimeoutError(
                        (f"LLM provider {timeout_kind} timeout after {request_attempt} attempts"),
                        diagnostics={
                            "timeout_kind": timeout_kind,
                            "timeout_seconds": self._timeout_seconds,
                            "request_attempts": request_attempt,
                        },
                    ) from exc
            except httpx.ConnectError as exc:
                if request_attempt == MAX_TIMEOUT_ATTEMPTS:
                    raise ProviderNetworkError(
                        self._classify_connect_error(exc),
                        diagnostics={"request_attempts": request_attempt},
                    ) from exc
        raise AssertionError("timeout retry loop exited unexpectedly")

    def _is_retryable_http_status(self, status_code: int) -> bool:
        """Retry temporary capacity responses once, never auth or malformed requests."""

        return status_code == 429 or status_code >= 500

    def _timeout_kind(self, exc: httpx.TimeoutException) -> str:
        """Return a safe, phase-level timeout label without provider details."""

        if isinstance(exc, httpx.ConnectTimeout):
            return "connect"
        if isinstance(exc, httpx.ReadTimeout):
            return "read"
        if isinstance(exc, httpx.WriteTimeout):
            return "write"
        if isinstance(exc, httpx.PoolTimeout):
            return "pool"
        return "request"

    def _messages(
        self,
        request: dict[str, object],
        output_model: type[BaseModel],
    ) -> list[dict[str, str]]:
        system_prompt = str(
            request.get(
                "system_prompt",
                "You are a strict extraction model. Return JSON only.",
            )
        )
        user_prompt = str(request.get("user_prompt", "Extract one structured object."))
        input_context = request.get("input_context", {})
        schema_name = output_model.__name__
        output_contract = self._compact_output_contract(output_model)
        schema_json = json.dumps(output_contract, ensure_ascii=False, separators=(",", ":"))
        context_json = json.dumps(input_context, ensure_ascii=False, sort_keys=True)
        return [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n"
                    "Return only valid JSON. Do not return markdown or explanations."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    f"Output schema: {schema_name}\n"
                    f"Output contract: {schema_json}\n"
                    f"{self._format_recovery_instruction(input_context, schema_name)}"
                    f"Input context: {context_json}"
                ),
            },
        ]

    def _format_recovery_instruction(self, input_context: object, schema_name: str) -> str:
        """Return a fixed, source-free correction instruction for one schema retry."""

        if not isinstance(input_context, dict):
            return ""
        if input_context.get("output_recovery") not in {
            "schema_validation",
            "state_change_schema_recovery",
        }:
            return ""
        batch_contract = {
            "EventProposalBatchV1": ("events", True),
            "EntityProposalBatchV1": ("entities", True),
            "ClaimProposalBatchV1": ("claims", True),
            "KnowledgeStateProposalBatchV1": ("states", False),
            "StateChangeProposalBatchV1": ("changes", False),
            "RelationshipSignalProposalBatchV1": ("signals", False),
        }.get(schema_name)
        if batch_contract is None:
            return ""
        batch_field, requires_non_empty_items = batch_contract
        rule_codes = input_context.get("schema_error_rule_codes")
        safe_rule_codes = (
            sorted({item for item in rule_codes if isinstance(item, str)})
            if isinstance(rule_codes, list)
            else []
        )
        if requires_non_empty_items:
            batch_instruction = f"Include a non-empty {batch_field} array and every required field."
        elif schema_name == "KnowledgeStateProposalBatchV1":
            batch_instruction = (
                "Include a states array and every required field for each item. "
                "states may be empty only when no explicit, auditable knowledge state is supported."
            )
        else:
            batch_instruction = (
                f"Include a {batch_field} array and every required field for each item. "
                f"{batch_field} may be empty only when no reliable, auditable output is supported."
            )
        knowledge_state_shape = ""
        if schema_name == "KnowledgeStateProposalBatchV1":
            knowledge_state_shape = (
                " For each v1.1 state, use this unresolved-reference shape: "
                '{"schema_version":"1.1","subject":{"mention_text":"...",'
                '"entity_proposal_id":null,"resolution_status":"UNRESOLVED"},'
                '"target":{"target_kind":"WORLD_FACT","target_text":"...",'
                '"proposal_id":null,"proposal_schema":null,'
                '"resolution_status":"UNRESOLVED"},"valid_from":null,"valid_until":null}. '
                "Do not emit legacy id fields. Use EVENT instead of WORLD_FACT only when "
                "the target is a concrete occurrence."
            )
        state_change_shape = ""
        if schema_name == "StateChangeProposalBatchV1":
            state_change_shape = (
                " For every change, return a complete valid StateChangeProposalV1. "
                "quantity old_value and new_value must be JSON numbers: correct 4; "
                'wrong "4", "四", "四瓶", or {"count":4}. Do not coerce values, '
                "drop other valid changes, or return a partial batch."
            )
        relationship_signal_shape = ""
        if schema_name == "RelationshipSignalProposalBatchV1":
            statement_support_recovery = ""
            if "RELATIONSHIP_SIGNAL_STATEMENT_SUPPORT_LEVEL_INVALID" in safe_rule_codes:
                statement_support_recovery = (
                    " For DIRECT_STATEMENT or REPORTED_STATEMENT, include source_speaker and use "
                    "support_level=LIMITED or support_level=STRONG, never EXPLICIT. "
                )
            relationship_signal_shape = (
                " For every signal, return a complete v1.0 RelationshipSignalProposalV1. "
                "Use UNRESOLVED participant, speaker, context-event, and temporal-event references "
                "with null candidate IDs and schemas, for example "
                '"resolution_status":"UNRESOLVED","entity_proposal_id":null,'
                '"proposal_schema":null. NARRATED may use EXPLICIT and forbids a speaker; '
                "DIRECT_STATEMENT or REPORTED_STATEMENT require a speaker and cannot use EXPLICIT; "
                "OBSERVED_ACTION forbids a speaker and EXPLICIT. "
                "Use PRESENT unless an explicit temporal anchor supports a change effect. "
                'A denial requires signal_effect="DENIAL" and assertion_polarity="DENIED". '
                "A traitor label is Claim-only: never output BETRAYS unless the evidence quote "
                "explicitly describes a betrayal action between the two participants. "
                "no longer trusts means DISTRUSTS plus FORMATION with an explicit anchor. "
                "Do not output INFERRED, resolved links, legacy fields, "
                "or a non-batch object."
                f"{statement_support_recovery}"
            )
        rule_hint = (
            f" The previous output violated these safe schema rules: {', '.join(safe_rule_codes)}."
            if safe_rule_codes
            else ""
        )
        return (
            "Format recovery instruction: Return exactly one "
            f"{schema_name} JSON object. Return no markdown, explanation, reasoning, or alternate "
            f"schema. {batch_instruction}{rule_hint}{knowledge_state_shape}"
            f"{state_change_shape}{relationship_signal_shape}\n\n"
        )

    def _compact_output_contract(self, output_model: type[BaseModel]) -> dict[str, object]:
        """Return a small, reference-free schema guide derived from Pydantic."""

        schema = output_model.model_json_schema()
        definitions = schema.get("$defs")
        definition_map = definitions if isinstance(definitions, dict) else {}
        contract = self._compact_schema_node(schema, definition_map, set())
        return contract if isinstance(contract, dict) else {"type": "object"}

    def _compact_schema_node(
        self,
        node: object,
        definitions: dict[str, object],
        resolving_refs: set[str],
    ) -> object:
        """Keep only generation-relevant JSON Schema fields and inline local refs."""

        if not isinstance(node, dict):
            return node

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition_name = reference.removeprefix("#/$defs/")
            if definition_name in resolving_refs:
                return {"type": "object"}
            definition = definitions.get(definition_name)
            return self._compact_schema_node(
                definition,
                definitions,
                resolving_refs | {definition_name},
            )

        compact: dict[str, object] = {}
        for key in ("type", "enum", "const"):
            value = node.get(key)
            if value is not None:
                compact[key] = value

        required = node.get("required")
        if isinstance(required, list):
            compact["required"] = [item for item in required if isinstance(item, str)]

        properties = node.get("properties")
        if isinstance(properties, dict):
            compact["properties"] = {
                str(name): self._compact_schema_node(value, definitions, resolving_refs)
                for name, value in properties.items()
            }

        items = node.get("items")
        if isinstance(items, dict):
            compact["items"] = self._compact_schema_node(items, definitions, resolving_refs)

        for key in ("anyOf", "oneOf"):
            variants = node.get(key)
            if isinstance(variants, list):
                compact[key] = [
                    self._compact_schema_node(variant, definitions, resolving_refs)
                    for variant in variants
                ]

        return compact

    def _extract_json(self, content: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()

        stripped = content.strip()
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", stripped):
            candidate = stripped[match.start() :]
            try:
                _, end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            return candidate[:end].strip()
        return stripped

    def _validate_response_content(
        self,
        content: Any,
        diagnostics: ProviderDiagnostics,
    ) -> None:
        if self._exceeded_max_output_tokens(diagnostics):
            raise ProviderResponseError(
                self._max_output_tokens_error_message(),
                diagnostics=diagnostics,
            )
        if content is None:
            raise ProviderResponseError(
                "LLM provider response content is missing",
                diagnostics=diagnostics,
            )
        if not isinstance(content, str):
            type_name = type(content).__name__
            raise ProviderResponseError(
                f"LLM provider response content has unsupported type: {type_name}",
                diagnostics=diagnostics,
            )
        if content.strip() == "":
            raise ProviderResponseError(
                "LLM provider response content is missing",
                diagnostics=diagnostics,
            )

    def _response_diagnostics(self, response_payload: Any) -> ProviderDiagnostics:
        choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
        choices_list = choices if isinstance(choices, list) else []
        first_choice = choices_list[0] if choices_list else None
        first_choice_dict = first_choice if isinstance(first_choice, dict) else {}
        message = first_choice_dict.get("message")
        message_dict = message if isinstance(message, dict) else {}
        content = message_dict.get("content")
        usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
        usage_dict = usage if isinstance(usage, dict) else {}

        diagnostics: ProviderDiagnostics = {
            "finish_reason": (
                first_choice_dict.get("finish_reason")
                if isinstance(first_choice_dict.get("finish_reason"), str)
                else None
            ),
            "response_has_choices": bool(choices_list),
            "choices_count": len(choices_list),
            "message_keys": sorted(str(key) for key in message_dict),
            "content_type": type(content).__name__,
            "has_reasoning_content": "reasoning_content" in message_dict,
            "has_tool_calls": bool(message_dict.get("tool_calls")),
        }
        if isinstance(content, str):
            diagnostics["content_length"] = len(content)

        token_fields = {
            "prompt_tokens": "usage_prompt_tokens",
            "completion_tokens": "usage_completion_tokens",
            "total_tokens": "usage_total_tokens",
        }
        for source_key, diagnostic_key in token_fields.items():
            token_value = usage_dict.get(source_key)
            if isinstance(token_value, int):
                diagnostics[diagnostic_key] = token_value

        return diagnostics

    def _exceeded_max_output_tokens(self, diagnostics: ProviderDiagnostics) -> bool:
        return diagnostics.get("finish_reason") == "length"

    def _max_output_tokens_error_message(self) -> str:
        return "LLM provider response exceeded max output tokens before final content"

    def _classify_http_status_error(self, status_code: int) -> str:
        if status_code in {401, 403}:
            reason = "authentication or authorization failed"
        elif status_code == 404:
            reason = "endpoint or model not found"
        elif status_code == 429:
            reason = "rate limited"
        elif status_code == 400:
            reason = "bad request"
        elif status_code >= 500:
            reason = "provider server error"
        else:
            reason = "request rejected"
        return f"LLM provider HTTP error: {status_code} ({reason})"

    def _classify_connect_error(self, exc: httpx.ConnectError) -> str:
        for cause in self._iter_exception_causes(exc):
            if isinstance(cause, socket.gaierror):
                return "LLM provider DNS resolution failed"
            if isinstance(cause, ssl.SSLError):
                return "LLM provider TLS handshake failed"
            if isinstance(cause, ConnectionRefusedError):
                return "LLM provider connection refused"

        message = str(exc).lower()
        if any(token in message for token in ("dns", "getaddrinfo", "name or service")):
            return "LLM provider DNS resolution failed"
        if any(token in message for token in ("ssl", "tls", "certificate")):
            return "LLM provider TLS handshake failed"
        if "refused" in message:
            return "LLM provider connection refused"
        return "LLM provider connection failed"

    def _iter_exception_causes(self, exc: BaseException) -> list[BaseException]:
        causes: list[BaseException] = []
        current = exc.__cause__
        while current is not None:
            causes.append(current)
            current = current.__cause__
        return causes


def build_openai_compatible_provider(settings: Settings) -> OpenAICompatibleLLMProvider:
    """Build the configured production provider from one authoritative settings object."""

    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    return OpenAICompatibleLLMProvider(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        provider_name=settings.llm_provider_name,
        response_format=settings.llm_response_format,
        structured_output_policy=settings.llm_structured_output_policy,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
