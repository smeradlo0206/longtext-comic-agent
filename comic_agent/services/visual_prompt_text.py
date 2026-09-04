"""Keep post-generation lettering content out of image-model prompts."""

from __future__ import annotations

import re

from comic_agent.schemas.visual import PanelTextOverlayV1

_QUOTE_OPEN = r"[\u201c\u300c\u300e\"]"
_QUOTE_CLOSE = r"[\u201d\u300d\u300f\"]"
_SPEECH_CUE = (
    r"(?:\u56de\u7b54|\u7b54\u9053|\u8bf4\u9053|\u8bf4\u7740|\u8be2\u95ee|\u95ee\u9053|"
    r"\u63d0\u9192|\u544a\u8bc9|\u62db\u547c|\u56de\u5e94|\u5ba3\u5e03|\u89e3\u91ca|"
    r"\u4ecb\u7ecd|\u611f\u53f9|\u8868\u793a|\u8bf4|\u95ee|\u7b54|\u558a\u9053|\u558a|\u9053|"
    r"says?|asks?|repl(?:y|ies|ied)|answers?|tells?|shouts?|calls?\s+out)"
)
_DIALOGUE_ACTION = "\u505a\u51fa\u81ea\u7136\u4ea4\u6d41\u7684\u8868\u60c5\u548c\u624b\u52bf"
_VISUAL_PROP_REPLACEMENTS = (
    (
        "\u624b\u91cc\u7684\u62a5\u5230\u6750\u6599",
        "\u624b\u91cc\u7684\u7eaf\u8272\u786c\u58f3\u8d44\u6599\u5939\uff0c\u5c01\u9762\u5e73\u6574",
    ),
    ("\u62a5\u5230\u6750\u6599", "\u7eaf\u8272\u786c\u58f3\u8d44\u6599\u5939"),
    ("\u6838\u5bf9\u5b8c\u8bc1\u4ef6", "\u6838\u5bf9\u5b8c\u6210"),
    (
        "\u6574\u9f50\u7684\u6750\u6599\u888b",
        "\u5c01\u597d\u7684\u7eaf\u8272\u8d44\u6599\u888b\uff0c\u8868\u9762\u5e73\u6574",
    ),
    ("registration materials", "a closed solid-color document folder"),
)


def visual_expression_without_overlay_text(
    expression: str,
    overlays: list[PanelTextOverlayV1],
) -> str:
    """Remove literal lettering copy while preserving visible communication behavior."""

    rendered = expression
    for overlay in overlays:
        text = re.escape(overlay.text)
        if overlay.kind == "dialogue":
            rendered = re.sub(
                rf"{_SPEECH_CUE}\s*[,，]?\s*[:：]?\s*{_QUOTE_OPEN}?\s*{text}\s*{_QUOTE_CLOSE}?",
                _DIALOGUE_ACTION,
                rendered,
                flags=re.IGNORECASE,
            )
            rendered = rendered.replace(overlay.text, _DIALOGUE_ACTION)
        else:
            rendered = rendered.replace(overlay.text, "")

    # Removing an overlay can expose an unmatched quote or a bare speech-introduction cue.
    rendered = re.sub(
        rf"{_SPEECH_CUE}\s*[,，]?\s*[:：]\s*{_QUOTE_OPEN}?\s*{_QUOTE_CLOSE}?",
        _DIALOGUE_ACTION,
        rendered,
        flags=re.IGNORECASE,
    )
    rendered = re.sub(r"[\u201c\u201d\u300c\u300d\u300e\u300f\"]", "", rendered)
    for source, replacement in _VISUAL_PROP_REPLACEMENTS:
        rendered = rendered.replace(source, replacement)
    rendered = re.sub(
        rf"(?:{re.escape(_DIALOGUE_ACTION)}\s*[.。]?\s*){{2,}}",
        _DIALOGUE_ACTION,
        rendered,
    )
    rendered = re.sub(r"\s{2,}", " ", rendered)
    return rendered.strip(" ,，:：")
