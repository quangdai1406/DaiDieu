"""Draft nodes and the content hash that approvals bind to (recipients + subject + body)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

import jsonschema

URGENCIES = ["low", "normal", "high", "urgent"]
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["category", "urgency", "confidence", "needs_dai", "summary", "draft_body",
                 "citations", "sensitivity_flags"],
    "properties": {
        "category": {"type": "string", "maxLength": 60},
        "urgency": {"enum": URGENCIES},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "needs_dai": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 600},
        "draft_body": {"type": "string", "maxLength": 5000},
        "citations": {"type": "array", "items": {"type": "string", "maxLength": 300}},
        "sensitivity_flags": {"type": "array", "items": {"type": "string", "maxLength": 60}},
    },
}


class DraftSchemaError(ValueError):
    """The model's output did not match the draft schema."""


def validate_draft(data: dict[str, Any]) -> dict[str, Any]:
    try:
        jsonschema.validate(data, DRAFT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise DraftSchemaError(exc.message) from exc
    return {k: data[k] for k in DRAFT_SCHEMA["properties"]}  # unknown keys are dropped


def content_hash(recipients: Sequence[str], subject: str, body: str) -> str:
    canonical = json.dumps(
        {"to": list(recipients), "subject": subject, "body": body},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reply_subject(original: str) -> str:
    one_line = re.sub(r"\s+", " ", original).strip()[:200]
    return one_line if one_line.lower().startswith("re:") else f"Re: {one_line}"
