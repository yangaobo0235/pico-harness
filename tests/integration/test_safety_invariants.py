"""Safety invariants enforced by the runtime, not by model cooperation."""

import os
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pico.bootstrap.container import build_runtime
from pico.config.models.runtime import APPROVAL_AUTO, APPROVAL_NEVER
from pico.config.providers import PROVIDER_OLLAMA
from pico.contracts.turns import TaskState
from pico.integrations.llm.providers.fake import FakeModelClient
from pico.interfaces.cli.app import build_arg_parser
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _build_workspace(tmp_path: Path) -> WorkspaceContext:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _build_agent(tmp_path: Path, outputs: list[str], **kwargs: object) -> Pico:
    workspace = _build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    kwargs.setdefault("approval_policy", APPROVAL_AUTO)
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        **kwargs,
    )


def _build_agent_from_args(args: object) -> Pico:
    """Map a parsed CLI namespace into the bootstrap entry point.

    Mirrors `pico.interfaces.cli.app.main`, so a test that goes through the parser
    exercises the same wiring the command line uses.
    """
    return build_runtime(
        cwd=args.cwd,
        resume=args.resume,
        approval_policy=args.approval,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=args.secret_env_names,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        host=args.host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout if args.provider == PROVIDER_OLLAMA else args.openai_timeout,
    )


class _DummyModelClient:
    """Stand-in client that records construction and refuses to answer."""

    def __init__(self, *args: object, **kwargs: object):
        self.args = args
        self.kwargs = kwargs

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: object) -> str:
        raise AssertionError("model should not be invoked")


def _quote(argument: str) -> str:
    """Quote one command argument for the shell `run_shell` actually uses.

    ``shell=True`` hands the string to the platform shell, and cmd.exe does not treat single
    quotes as quoting characters, so POSIX-style `shlex.quote` output would fail there before
    the interpreter ever starts. Double quotes work on both shells as long as the argument
    itself carries none, which interpreter paths and repo-local script names do not.
    """
    if os.name == "nt":
        return f'"{argument}"'
    return shlex.quote(argument)


def _can_create_symlink(directory: Path) -> bool:
    """Probe whether the current user may create symlinks here.

    The containment check under test runs on the resolved path, but it can only be exercised
    once a link exists. Windows rejects link creation without developer mode or the
    SeCreateLinkPrivilege right, so the probe runs the real operation instead of guessing from
    the platform name.
    """
    probe_target = directory / "symlink-probe-target.txt"
    probe_link = directory / "symlink-probe-link.txt"
    probe_target.write_text("probe\n", encoding="utf-8")
    try:
        probe_link.symlink_to(probe_target)
    except (OSError, NotImplementedError):
        return False
    finally:
        probe_link.unlink(missing_ok=True)
        probe_target.unlink(missing_ok=True)
    return True


def test_workspace_escape_is_rejected(tmp_path: Path):
    """A relative path climbing out of the repository is refused before any read."""
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    agent = _build_agent(tmp_path, [])

    result = agent.run_tool("read_file", {"path": "../outside.txt"})

    assert "path escapes workspace" in result


def test_symlink_path_traversal_is_rejected(tmp_path: Path):
    """Containment is checked on the resolved path, so a link out still fails."""
    if not _can_create_symlink(tmp_path):
        pytest.skip("the current user cannot create symlinks in this environment")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    agent = _build_agent(tmp_path, [])

    result = agent.run_tool("read_file", {"path": "linked.txt"})

    assert "path escapes workspace" in result


def test_risky_tool_deny_behavior(tmp_path: Path):
    """``never`` denies risky calls without touching stdin, so headless runs never hang."""
    agent = _build_agent(tmp_path, [], approval_policy=APPROVAL_NEVER)

    result = agent.run_tool("run_shell", {"command": "echo hi", "timeout": 20})

    assert result == "error: approval denied for run_shell"


def test_cli_build_agent_wires_secret_env_names_from_parser(tmp_path: Path):
    """`--secret-env-name` repeats reach the runtime redaction list."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    with (
        patch.dict(os.environ, {"GITHUB_PAT": "ghp-1", "GH_PAT": "ghp-2"}, clear=True),
        patch(
            "pico.bootstrap.providers.OllamaModelClient",
            _DummyModelClient,
        ),
    ):
        args = build_arg_parser().parse_args(
            [
                "--cwd",
                str(tmp_path),
                "--approval",
                "auto",
                "--secret-env-name",
                "GITHUB_PAT",
                "--secret-env-name",
                "GH_PAT",
            ]
        )
        agent = _build_agent_from_args(args)
        assert set(agent.secret_env_summary()["secret_env_names"]) == {"GITHUB_PAT", "GH_PAT"}


def test_cli_build_agent_uses_default_configured_secret_names(tmp_path: Path):
    """The built-in secret name list covers the common provider and forge variables."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    with (
        patch.dict(os.environ, {"GH_PAT": "ghp-default-1"}, clear=True),
        patch(
            "pico.bootstrap.providers.OllamaModelClient",
            _DummyModelClient,
        ),
    ):
        args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--approval", "auto"])
        agent = _build_agent_from_args(args)
        assert agent.secret_env_summary()["secret_env_names"] == ["GH_PAT"]


def test_cli_build_agent_loads_project_env_secrets_before_redaction_setup(tmp_path: Path):
    """Project `.env` is loaded before the client is built, so its keys get redacted."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PICO_DEEPSEEK_API_KEY=sk-project-secret\n", encoding="utf-8")
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("pico.bootstrap.providers.AnthropicCompatibleModelClient", _DummyModelClient),
    ):
        args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "deepseek"])
        agent = _build_agent_from_args(args)
        assert agent.secret_env_summary()["secret_env_names"] == ["PICO_DEEPSEEK_API_KEY"]


def test_cli_build_agent_reads_secret_names_from_environment_config(tmp_path: Path):
    """`PICO_SECRET_ENV_NAMES` extends the list without any CLI flag."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    with (
        patch.dict(
            os.environ,
            {
                "PICO_CUSTOM_SECRET": "custom-secret-value",
                "PICO_SECRET_ENV_NAMES": "PICO_CUSTOM_SECRET",
            },
            clear=True,
        ),
        patch("pico.bootstrap.providers.OllamaModelClient", _DummyModelClient),
    ):
        args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--approval", "auto"])
        agent = _build_agent_from_args(args)
        assert agent.secret_env_summary()["secret_env_names"] == ["PICO_CUSTOM_SECRET"]


def test_run_shell_uses_allowlisted_environment_only(tmp_path: Path):
    """Commands inherit the allowlist, not the parent environment."""
    secret = "shh-allowlist-secret"
    agent = _build_agent(tmp_path, [], approval_policy=APPROVAL_AUTO)
    (tmp_path / "env_probe.py").write_text(
        'import os\nprint(os.getenv("PICO_ALLOWLIST_SECRET", "missing"))\n',
        encoding="utf-8",
    )
    command = f"{_quote(sys.executable)} {_quote('env_probe.py')}"

    with patch.dict(os.environ, {"PICO_ALLOWLIST_SECRET": secret}, clear=False):
        result = agent.run_tool("run_shell", {"command": command, "timeout": 20})

    assert secret not in result
    assert "missing" in result


def test_bound_tool_methods_delegate_into_lower_layers(tmp_path: Path):
    """The facade's direct tool helpers forward to the owning module instead of reimplementing."""
    agent = _build_agent(tmp_path, [], approval_policy=APPROVAL_AUTO)

    with patch("pico.capabilities.tools.builtin.shell.subprocess.run") as fake_run:
        fake_run.return_value = type(
            "Result",
            (),
            {"returncode": 0, "stdout": "toolkit-shell\n", "stderr": ""},
        )()
        shell_result = agent.tool_run_shell({"command": "echo bypass", "timeout": 20})

    assert "toolkit-shell" in shell_result
    fake_run.assert_called_once()
    assert agent.tool_run_shell.__func__.__module__ == "pico.runtime.agent.agent"

    with patch("pico.runtime.subagents.manager.spawn", return_value="manager-delegate") as fake_spawn:
        delegate_result = agent.tool_delegate({"task": "inspect README.md", "max_steps": 2})

    assert delegate_result == "manager-delegate"
    fake_spawn.assert_called_once()


def test_delegate_depth_limit_is_enforced(tmp_path: Path):
    """Once the depth budget is spent, validation rejects a further delegation."""
    agent = _build_agent(tmp_path, [], depth=1, max_depth=1)

    try:
        agent.validate_tool("delegate", {"task": "inspect README.md", "max_steps": 2})
    except ValueError as exc:
        assert "delegate depth exceeded" in str(exc)
    else:
        raise AssertionError("delegate depth validation did not fail")


def test_delegate_child_is_read_only(tmp_path: Path):
    """Delegation buys a second pair of eyes, not extra write permission."""
    target = tmp_path / "child-was-not-allowed.txt"
    agent = _build_agent(
        tmp_path,
        [
            '<tool>{"name":"delegate","args":{"task":"write a file","max_steps":2}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"child-was-not-allowed.txt","content":"nope"}}</tool>',
            "<final>child done</final>",
            "<final>parent done</final>",
        ],
    )

    result = agent.ask("Delegate the work")

    assert result == "parent done"
    assert not target.exists()
    tool_events = [item for item in agent.session["history"] if item["role"] == "tool"]
    assert tool_events[0]["name"] == "delegate"
    assert "delegate_result" in tool_events[0]["content"]


def test_configured_secret_env_names_are_redacted_in_trace_and_report(tmp_path: Path):
    """Declared secrets never reach disk, in nested payloads or in the final report."""
    github_pat = "ghp_configured_secret_123"
    gh_pat = "ghp_configured_secret_456"
    with patch.dict(os.environ, {"GITHUB_PAT": github_pat, "GH_PAT": gh_pat}, clear=True):
        agent = _build_agent(
            tmp_path,
            [],
            secret_env_names=("GITHUB_PAT", "GH_PAT"),
        )
        state = TaskState.create(run_id="run_001", task_id="task_001", user_request="Mask configured secrets")
        agent.run_store.start_run(state)

        assert set(agent.secret_env_summary()["secret_env_names"]) == {"GITHUB_PAT", "GH_PAT"}

        payload = {
            "GITHUB_PAT": github_pat,
            "GH_PAT": gh_pat,
            "nested": {"GITHUB_PAT": github_pat, "GH_PAT": gh_pat},
            "list": [github_pat, gh_pat],
        }
        agent.emit_trace(state, "tool_executed", payload)
        agent.run_store.write_report(
            state,
            agent.redact_artifact({"task_state": state.to_dict(), "payload": payload}),
        )

    run_dir = agent.run_store.run_dir(state.run_id)
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.json").read_text(encoding="utf-8")

    assert github_pat not in trace_text
    assert gh_pat not in trace_text
    assert github_pat not in report_text
    assert gh_pat not in report_text
    assert trace_text.count("<redacted>") >= 4
    assert report_text.count("<redacted>") >= 4
