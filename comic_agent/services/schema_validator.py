"""Schema validation helpers."""

from pydantic import BaseModel


def json_schema_for(model: type[BaseModel]) -> dict[str, object]:
    """Return JSON Schema for a Pydantic model."""

    return model.model_json_schema()
