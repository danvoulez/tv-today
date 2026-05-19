"""Robust JSON extraction for local LLM responses.

Ollama format=json is helpful but not a contract. Local models can still wrap
JSON in markdown or prose. This parser accepts clean JSON first, then extracts
the first balanced object/array from the response.
"""

from __future__ import annotations

import json
import re
from typing import Any

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def loads_llm_json(text: str, default: Any = None) -> Any:
    if not text:
        return default

    candidates = [text.strip()]
    candidates.extend(match.strip() for match in _CODE_FENCE_RE.findall(text))

    extracted = _extract_first_json_value(text)
    if extracted:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return default


def _extract_first_json_value(text: str) -> str | None:
    starts = [i for i, ch in enumerate(text) if ch in "[{" ]
    for start in starts:
        opening = text[start]
        closing = "]" if opening == "[" else "}"
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]
    return None
