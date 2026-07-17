"""LangGraph-ready workflow placeholders."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowPlaceholder:
    """Minimal workflow descriptor reserved for future LangGraph wiring."""

    workflow_id: str
    description: str


SOURCE_IMPORT_WORKFLOW = WorkflowPlaceholder(
    workflow_id="source-import-v1",
    description="Import source file, split chapters, create chunks, and persist evidence chain.",
)
