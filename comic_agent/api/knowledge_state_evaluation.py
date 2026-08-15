"""Offline Knowledge State evaluation endpoints backed only by bundled fixtures."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from comic_agent.agents.knowledge_state_extraction import KnowledgeStateExtractionAgent
from comic_agent.api.demo import require_demo_access_code
from comic_agent.config import get_settings
from comic_agent.providers.openai_compatible import (
    ProviderHttpError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.providers.openai_compatible import (
    build_openai_compatible_provider as _build_configured_provider,
)
from comic_agent.schemas.evaluation import (
    KnowledgeStateEvaluationCaseSummaryV1,
    KnowledgeStateEvaluationCaseV1,
    KnowledgeStateEvaluationEvaluateRequestV1,
    KnowledgeStateEvaluationFailureDiagnosticsV1,
    KnowledgeStateEvaluationReportRequestV1,
    KnowledgeStateEvaluationReportV1,
    KnowledgeStateEvaluationResultV1,
    KnowledgeStateEvaluationRunFailureCategory,
    KnowledgeStateEvaluationRunFailureV1,
    KnowledgeStateEvaluationRunOutcomeV1,
    KnowledgeStateEvaluationRunRequestV1,
    KnowledgeStateEvaluationRunResultV1,
)
from comic_agent.schemas.narrative import KnowledgeStateProposalBatchV1
from comic_agent.services.knowledge_state_evaluator import (
    build_knowledge_state_evaluation_report,
    evaluate_knowledge_state_case,
)

router = APIRouter(prefix="/knowledge-state-evaluation", tags=["knowledge-state-evaluation"])


def _fixture_cases() -> list[KnowledgeStateEvaluationCaseV1]:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_state_evaluation_cases.json"
    )
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [KnowledgeStateEvaluationCaseV1.model_validate(item) for item in data]


def _case_or_404(case_id: str) -> KnowledgeStateEvaluationCaseV1:
    for case in _fixture_cases():
        if case.case_id == case_id:
            return case
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation case not found")


@router.get("/cases", response_model=list[KnowledgeStateEvaluationCaseSummaryV1])
def list_cases() -> list[KnowledgeStateEvaluationCaseSummaryV1]:
    """List bundled synthetic cases without exposing source snippets."""

    return [
        KnowledgeStateEvaluationCaseSummaryV1(
            case_id=case.case_id,
            title=case.title,
            category=case.category,
            risk_tags=case.risk_tags,
            fixture_origin=case.fixture_origin,
            zero_output_expected=not case.expected_states,
        )
        for case in _fixture_cases()
    ]


@router.get("/cases/{case_id}", response_model=KnowledgeStateEvaluationCaseV1)
def get_case(case_id: str) -> KnowledgeStateEvaluationCaseV1:
    """Return one bundled fixture; fixture source is synthetic or redacted only."""

    return _case_or_404(case_id)


@router.post("/cases/{case_id}/evaluate", response_model=KnowledgeStateEvaluationResultV1)
def evaluate_case(
    case_id: str,
    payload: KnowledgeStateEvaluationEvaluateRequestV1,
) -> KnowledgeStateEvaluationResultV1:
    """Evaluate an already structured batch without providers, persistence, or writes."""

    return evaluate_knowledge_state_case(_case_or_404(case_id), payload.batch)


@router.post("/report", response_model=KnowledgeStateEvaluationReportV1)
def build_report(
    payload: KnowledgeStateEvaluationReportRequestV1,
) -> KnowledgeStateEvaluationReportV1:
    """Aggregate typed batches without calling a Provider or writing state."""

    cases_by_id = {case.case_id: case for case in _fixture_cases()}
    unknown_ids = {
        item.case_id for item in payload.evaluations
    } | {item.case_id for item in payload.run_failures}
    if not unknown_ids.issubset(cases_by_id):
        raise HTTPException(status_code=404, detail="Evaluation case not found")
    return build_knowledge_state_evaluation_report(
        payload.evaluations,
        cases_by_id,
        payload.run_failures,
    )


@router.post(
    "/cases/{case_id}/run",
    response_model=KnowledgeStateEvaluationRunOutcomeV1,
    dependencies=[Depends(require_demo_access_code)],
)
def run_case_with_real_llm(
    case_id: str,
    payload: KnowledgeStateEvaluationRunRequestV1,
    request: Request,
) -> KnowledgeStateEvaluationRunOutcomeV1:
    """Optionally run a bundled fixture through the configured provider after explicit opt-in."""

    if not payload.real_llm_requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set real_llm_requested=true to run an external provider.",
        )
    settings = get_settings()
    if not settings.enable_real_llm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Real LLM is disabled by server settings.",
        )
    provider = getattr(request.app.state, "narrative_analyst_provider", None)
    if provider is None:
        try:
            provider = _build_configured_provider(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No configured provider is available for explicit real-LLM evaluation.",
            ) from exc
    case = _case_or_404(case_id)
    input_context: dict[str, object] = {
        "project_id": case.source_chunks[0].project_id,
        "source_chunk_ids": [chunk.chunk_id for chunk in case.source_chunks],
        "source_chunks": [chunk.model_dump(mode="json") for chunk in case.source_chunks],
    }
    agent = KnowledgeStateExtractionAgent(provider)
    request_attempts = 1
    try:
        batch = agent.run(input_context)
    except (ProviderResponseError, ValidationError) as first_exc:
        request_attempts = 2
        recovery_context = dict(input_context)
        recovery_context["output_recovery"] = "schema_validation"
        recovery_context.update(_schema_recovery_context(first_exc))
        try:
            batch = agent.run(recovery_context)
        except (ProviderResponseError, ValidationError) as recovery_exc:
            return _run_failure(
                case_id,
                KnowledgeStateEvaluationRunFailureCategory.PROVIDER_SCHEMA_VALIDATION,
                recovery_exc,
                request_attempts,
            )
        except Exception as recovery_exc:  # noqa: BLE001 - sanitized boundary
            return _run_failure(
                case_id,
                _failure_category(recovery_exc),
                recovery_exc,
                request_attempts,
            )
    except Exception as exc:  # noqa: BLE001 - sanitized provider boundary
        return _run_failure(case_id, _failure_category(exc), exc, request_attempts)
    if not isinstance(batch, KnowledgeStateProposalBatchV1):
        return _run_failure(
            case_id,
            KnowledgeStateEvaluationRunFailureCategory.PROVIDER_SCHEMA_VALIDATION,
            ProviderResponseError(
                "Provider output did not validate",
                diagnostics={"expected_output_schema": "KnowledgeStateProposalBatchV1"},
            ),
            request_attempts,
        )
    return KnowledgeStateEvaluationRunResultV1(
        case_id=case_id,
        request_attempts=request_attempts,
        batch=batch,
        evaluation=evaluate_knowledge_state_case(case, batch),
    )


def _failure_category(exc: Exception) -> KnowledgeStateEvaluationRunFailureCategory:
    if isinstance(exc, ProviderTimeoutError):
        return KnowledgeStateEvaluationRunFailureCategory.PROVIDER_TIMEOUT
    if isinstance(exc, ProviderNetworkError):
        return KnowledgeStateEvaluationRunFailureCategory.PROVIDER_NETWORK
    if isinstance(exc, ProviderHttpError):
        return KnowledgeStateEvaluationRunFailureCategory.PROVIDER_HTTP
    if isinstance(exc, (ProviderResponseError, ValidationError)):
        return KnowledgeStateEvaluationRunFailureCategory.PROVIDER_SCHEMA_VALIDATION
    return KnowledgeStateEvaluationRunFailureCategory.UNKNOWN_PROVIDER_FAILURE


def _schema_recovery_context(exc: ProviderResponseError | ValidationError) -> dict[str, object]:
    """Forward only allowlisted schema rule labels to the one recovery attempt."""

    diagnostics = getattr(exc, "diagnostics", {})
    if not isinstance(diagnostics, dict):
        return {}
    rule_codes = diagnostics.get("schema_error_rule_codes")
    if not isinstance(rule_codes, list):
        return {}
    safe_rule_codes = sorted({code for code in rule_codes if isinstance(code, str)})
    return {"schema_error_rule_codes": safe_rule_codes} if safe_rule_codes else {}


def _run_failure(
    case_id: str,
    category: KnowledgeStateEvaluationRunFailureCategory,
    exc: Exception,
    request_attempts: int,
) -> KnowledgeStateEvaluationRunFailureV1:
    diagnostics = getattr(exc, "diagnostics", {})
    if isinstance(exc, ValidationError):
        diagnostics = {
            "schema_error_kind": "validation_error",
            "schema_error_field_paths": [
                ".".join(str(part) for part in error.get("loc", ()))
                for error in exc.errors()
            ],
            "expected_output_schema": "KnowledgeStateProposalBatchV1",
        }
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    allowed = {
        key: value
        for key, value in diagnostics.items()
        if key
        in {
            "schema_error_kind",
            "schema_error_field_paths",
            "schema_error_rule_codes",
            "expected_output_schema",
            "timeout_kind",
            "timeout_seconds",
            "request_attempts",
            "http_status_code",
        }
    }
    allowed["request_attempts"] = request_attempts
    safe_diagnostics = KnowledgeStateEvaluationFailureDiagnosticsV1.model_validate(allowed)
    message_by_category = {
        KnowledgeStateEvaluationRunFailureCategory.PROVIDER_SCHEMA_VALIDATION: (
            "Provider output failed KnowledgeStateProposalBatchV1 schema validation "
            "after one recovery retry."
        ),
        KnowledgeStateEvaluationRunFailureCategory.PROVIDER_TIMEOUT: "Provider request timed out.",
        KnowledgeStateEvaluationRunFailureCategory.PROVIDER_NETWORK: (
            "Provider network request failed."
        ),
        KnowledgeStateEvaluationRunFailureCategory.PROVIDER_HTTP: (
            "Provider returned an HTTP error."
        ),
        KnowledgeStateEvaluationRunFailureCategory.PROVIDER_CONFIGURATION: (
            "Provider configuration is unavailable."
        ),
        KnowledgeStateEvaluationRunFailureCategory.UNKNOWN_PROVIDER_FAILURE: (
            "Provider run failed with an unknown sanitized error."
        ),
    }
    return KnowledgeStateEvaluationRunFailureV1(
        case_id=case_id,
        failure_category=category,
        message=message_by_category[category],
        diagnostics=safe_diagnostics,
    )
