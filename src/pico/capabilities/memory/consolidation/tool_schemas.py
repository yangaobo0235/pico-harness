"""Model-facing annotation and profile-refresh tool schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _build_annotate_tool(*, enable_foresight: bool) -> list[dict]:
    """构造 LLM-facing ``annotate_conversation`` Tool Definition。

    Tool 始终要求 ``episode_summary``，并详细约束单行 Timestamp、Concrete Identifiers、Content/Process
    Tags。只有 ``enable_foresight=True`` 时才加入 ``foresight_hint`` Slot 及其 Prediction/Window/
    Confidence/Source Schema；关闭时 **根本不要求模型预测**，既节省 Tokens，也缩小 Prompt 与输出面。

    返回值是 Provider Tool Schema List，不执行 Tool，也不保证 LLM 遵守规则；写回前仍有代码层 Validation。
    """
    properties: dict[str, dict] = {
        "episode_summary": {
            "type": "array",
            "description": (
                "One entry per distinct event. Each entry is a SINGLE LINE "
                "(no newlines), formatted exactly as:\n"
                "  '[YYYY-MM-DD HH:MM] <summary, <=100 chars> #tag1 #tag2'\n\n"
                "SUMMARY — must include concrete identifiers (file paths, "
                "function names, PR/issue numbers, percentages, time/size "
                "values). Generic descriptions waste a slot.\n"
                "  GOOD: 'PR #1287 merged: require_auth(scope) replaces 6 "
                "sites in api/views/+middleware/'\n"
                "  BAD:  'User worked on auth refactor'\n\n"
                "TAGS — 1-4 tags per entry, kebab-case. Two CLASSES:\n"
                "  (A) CONTENT tags — name WHAT the episode is about. "
                "Every episode MUST carry at least one content tag. "
                "Use existing slugs from the 'tags you've recently used' "
                "list (see prompt) before inventing new ones — DO NOT "
                "split one project across multiple slugs like "
                "#project-clawtrack-release / -docs / -cli; pick ONE "
                "stable slug per project. New project tags follow "
                "'#project-<work-slug>' where slug names the WORK, not "
                "the codebase. Other content tags: {#perf, #bug, "
                "#decision, #blocker, #deferred, #pivot, #pr, #review, "
                "#rfc, #design, #infra, #sql, #ml}.\n"
                "  (B) PROCESS tags — {#question, #habit, #answer} "
                "describe HOW the user is interacting, not WHAT about. "
                "They are SUFFIXES only — NEVER the primary tag. "
                "An episode tagged ONLY '#question' or ONLY '#habit' is "
                "INVALID and will be rejected. Always pair with at "
                "least one content tag.\n"
                "  AVOID '#task' entirely — it's meaningless filler.\n\n"
                "Order entries by conversation timestamp. Empty array only "
                "when the chunk produced no substantive event."
            ),
            "items": {"type": "string"},
        },
    }
    required: list[str] = ["episode_summary"]
    description = (
        "Annotate this conversation chunk for episodic memory. Produces "
        "tagged episode lines. Does NOT update the user profile — that "
        "happens separately via refresh_profile_section when tag "
        "frequency warrants a focused rewrite."
    )
    if enable_foresight:
        properties["foresight_hint"] = {
            "type": "array",
            "description": (
                "Predictions / behavioral patterns inferred from this "
                "conversation. Fill when ANY of these signals present:\n"
                "(a) User explicitly defers a task ('I'll come back to "
                "X tomorrow', 'next sprint').\n"
                "(b) A recurring pattern visible across 2+ episodes "
                "(e.g. Saturday runs across multiple weeks → predict "
                "next Saturday run; Sunday-night planning → predict "
                "next Sunday planning). Look back at the 'tags you've "
                "recently used' list — if it shows recurring habits, "
                "emit them as foresight.\n"
                "(c) User commits to a specific future action with "
                "time anchor ('I'll write RFC tomorrow', "
                "'release Monday 9am').\n"
                "(d) An upcoming dated event mentioned in conversation "
                "('birthday 5/25', 'demo next Friday', 'deadline EOM').\n"
                "Empty array ONLY if none of (a)-(d) signals present. "
                "Default lean: emit foresight when reasonable — a "
                "low-confidence prediction is more useful than no "
                "prediction. Aim for 1-3 entries per substantive "
                "annotate call."
            ),
            "items": {
                "type": "object",
                "required": [
                    "prediction",
                    "window",
                    "confidence",
                    "src_ts",
                ],
                "properties": {
                    "prediction": {"type": "string"},
                    "window": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "src_ts": {"type": "string"},
                },
            },
        }
        required.append("foresight_hint")
        description = (
            "Annotate this conversation chunk for episodic memory. "
            "Produces tagged episode lines and foresight predictions. "
            "Does NOT update the user profile — that happens separately "
            "via refresh_profile_section when tag frequency warrants a "
            "focused rewrite."
        )
    return [
        {
            "type": "function",
            "function": {
                "name": "annotate_conversation",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
    ]


_REFRESH_SECTION_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "refresh_profile_section",
            "description": (
                "Rewrite ONE H2 section of user.md given recent episodes "
                "tagged with a specific topic. Other H2 sections are left "
                "untouched by the splicer — do not include their content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_heading": {
                        "type": "string",
                        "description": (
                            "Exact H2 heading line to replace, e.g. "
                            "'## Projects' or '## Habits'. Must include "
                            "the leading '## '. If the topic naturally fits "
                            "inside an existing H2 (e.g. tag #project-b -> "
                            "'## Projects'), use that existing heading and "
                            "structure project-specific content under H3 in "
                            "the body. Only create a new H2 if no existing "
                            "section fits."
                        ),
                    },
                    "section_body": {
                        "type": "string",
                        "description": (
                            "New markdown body for this section, NOT "
                            "including the heading line itself. Every bullet "
                            "MUST end with '[src: episodes.md @ "
                            "YYYY-MM-DD HH:MM]'. H3/H4 sub-headings are "
                            "allowed within the body."
                        ),
                    },
                },
                "required": ["section_heading", "section_body"],
            },
        },
    }
]
