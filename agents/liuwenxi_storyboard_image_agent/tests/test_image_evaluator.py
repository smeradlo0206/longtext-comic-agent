from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_images_qwen_vl", ROOT / "scripts" / "evaluate_images_qwen_vl.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hard_defect_list_is_normalized() -> None:
    evaluator = load_evaluator()
    defects = evaluator.normalize_hard_defects(["extra_person", "unwanted_text"])
    assert defects["extra_person"] is True
    assert defects["unwanted_text"] is True
    assert defects["watermark_or_logo"] is False


def test_string_booleans_are_normalized_but_unknown_values_fail() -> None:
    evaluator = load_evaluator()
    defects = evaluator.normalize_hard_defects(
        {
            "extra_person": "false",
            "extra_limb_or_finger": "true",
            "broken_face_or_body": False,
            "unwanted_text": False,
            "watermark_or_logo": False,
        }
    )
    assert defects["extra_limb_or_finger"] is True
    with pytest.raises(ValueError):
        evaluator.normalize_hard_defects(["not-a-known-defect"])
