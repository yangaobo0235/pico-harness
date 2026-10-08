from __future__ import annotations

import json
from pathlib import Path

from pico.capabilities.tools.builtin.message import MessageTool
from pico.extensions.evolution.judge.prompts import JUDGE_SYSTEM_PROMPT, PROPOSABLE_WHERE
from pico.extensions.evolution.judge.schema import PatchWhere

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_facing_surfaces_exclude_removed_capabilities() -> None:
    rendered = (JUDGE_SYSTEM_PROMPT + "\n" + json.dumps(MessageTool().parameters, sort_keys=True)).lower()

    for removed in (
        "telegram",
        "discord",
        "whatsapp",
        "deep research",
        "mirothinker",
        "skill hub",
        "media generation",
    ):
        assert removed not in rendered


def test_candidate_prompt_uses_current_pico_paths() -> None:
    assert "src/domains/" not in JUDGE_SYSTEM_PROMPT
    assert "memory_engine/everos/" not in JUDGE_SYSTEM_PROMPT
    assert "src/pico/integrations/plugins/memory/everos/" not in JUDGE_SYSTEM_PROMPT
    assert "public backend contract" in JUDGE_SYSTEM_PROMPT
    for immutable_path in (
        "src/pico/extensions/evaluation/prompts/",
        "src/pico/extensions/evaluation/hooks/",
        "src/pico/resources/skills/",
        "src/pico/runtime/agent/loop.py",
        "src/pico/runtime/context/",
    ):
        assert immutable_path not in JUDGE_SYSTEM_PROMPT


def test_candidate_prompt_only_offers_current_mutable_surface() -> None:
    assert PatchWhere.judge_prompt not in PROPOSABLE_WHERE
    assert PatchWhere.skill not in PROPOSABLE_WHERE
    assert PatchWhere.loop_override not in PROPOSABLE_WHERE
    assert PatchWhere.context_override not in PROPOSABLE_WHERE
    assert PatchWhere.control not in PROPOSABLE_WHERE
    where_block = JUDGE_SYSTEM_PROMPT.split("# Step 2", 1)[1].split("# Step 3", 1)[0]
    assert {where.value for where in PROPOSABLE_WHERE} == {
        line.split("`", 2)[1] for line in where_block.splitlines() if line.strip().startswith("- `")
    }


def test_shipped_example_requires_sealed_external_output() -> None:
    example = (REPO_ROOT / "examples/workflows/evolve_appworld.yaml").read_text(encoding="utf-8")

    assert "\n  test_task_file:" in example
    assert "可写且位于 repo_root 外" in example
    assert "人工评审" in example
