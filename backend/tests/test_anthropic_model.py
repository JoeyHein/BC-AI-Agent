"""The BC assistant must not call a retired Anthropic model id."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings, settings
from app.services.agent_service import bc_agent_service

# Retired on the Claude API, or deprecated with a retirement date already set.
# A hardcoded copy of any of these will 404 (or will, on the retirement date).
_RETIRED_MODEL_IDS = (
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-20240620",
    "claude-3-7-sonnet-20250219",
    "claude-3-sonnet-20240229",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
)


def test_default_model_is_current_sonnet():
    assert Settings.model_fields["ANTHROPIC_MODEL"].default == "claude-sonnet-5-5"


def test_bc_assistant_reads_model_from_settings():
    assert bc_agent_service.model == settings.ANTHROPIC_MODEL
    assert bc_agent_service.model not in _RETIRED_MODEL_IDS


def test_app_code_has_no_hardcoded_retired_model_ids():
    root = Path(__file__).resolve().parents[1] / "app"
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for model_id in _RETIRED_MODEL_IDS:
            if model_id in text:
                hits.append(f"{path.relative_to(root)}: {model_id}")
    assert hits == []
