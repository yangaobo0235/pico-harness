"""Tests for mini_pico public contract: exports, CLI surface and the README mapping to `src/pico`."""

import inspect
import re
import subprocess
import sys
from pathlib import Path

import mini_pico
from mini_pico.cli import build_agent, build_arg_parser
from mini_pico.runtime import Pico


def test_mini_pico_module_and_public_exports():
    """Root package exposes the teaching objects and `python -m mini_pico` reaches the same CLI."""
    assert mini_pico.Pico is not None
    assert mini_pico.FakeModelClient is not None
    assert not hasattr(mini_pico, "MiniAgent")
    result = subprocess.run([sys.executable, "-m", "mini_pico", "--help"], capture_output=True, text=True, check=True)
    assert "Teaching-sized Pico agent harness" in result.stdout


def test_readme_main_mapping_points_to_existing_files():
    """The pre-refactor flat layout the original contract test pinned stays readable on disk."""
    repo_root = Path(__file__).resolve().parents[3]
    main_files = [
        "pico/cli.py",
        "pico/runtime.py",
        "pico/agent_loop.py",
        "pico/context_manager.py",
        "pico/providers/clients.py",
        "pico/tool_executor.py",
        "pico/tools.py",
        "pico/task_state.py",
        "pico/run_store.py",
        "pico/workspace.py",
    ]
    for path in main_files:
        assert (repo_root / path).exists()


def test_readme_layer_mapping_points_to_existing_src_pico_modules():
    """The correspondence table names `src/pico` modules that really exist, so it can't drift silently."""
    readme = Path(__file__).resolve().parents[1] / "README.md"
    referenced = sorted(set(re.findall(r"src/pico/[A-Za-z0-9_/]+\.py", readme.read_text(encoding="utf-8"))))
    assert referenced
    repo_root = readme.resolve().parents[2]
    for path in referenced:
        assert (repo_root / path).exists(), path


def test_cli_argument_surface_keeps_its_flags_and_defaults():
    """Flags, dest names and defaults are user-facing text, so they keep their exact spelling."""
    parser = build_arg_parser()
    assert vars(parser.parse_args([])) == {
        "prompt": [],
        "cwd": ".",
        "approval": "auto",
        "max_steps": 4,
        "max_new_tokens": 512,
    }
    parsed = parser.parse_args(["read", "README", "--cwd", "elsewhere", "--approval", "never", "--max-steps", "9"])
    assert parsed.prompt == ["read", "README"]
    assert (parsed.cwd, parsed.approval, parsed.max_steps, parsed.max_new_tokens) == ("elsewhere", "never", 9, 512)
    assert "Teaching-sized Pico agent harness." in parser.format_help()


def test_runtime_constructor_keeps_its_parameter_names_and_defaults():
    """`Pico(...)` keeps the same parameter order and defaults, so neither entry path shifts."""
    parameters = list(inspect.signature(Pico.__init__).parameters.values())[1:]
    assert [parameter.name for parameter in parameters] == [
        "model_client",
        "workspace",
        "run_store",
        "approval_policy",
        "max_steps",
        "max_new_tokens",
    ]
    assert {
        parameter.name: parameter.default
        for parameter in parameters
        if parameter.default is not inspect.Parameter.empty
    } == {"approval_policy": "auto", "max_steps": 4, "max_new_tokens": 512}


def test_agent_assembled_from_cli_args_keeps_artifacts_inside_the_workspace(tmp_path):
    """`build_agent` writes under the workspace it was pointed at and defaults to the fake backend."""
    (tmp_path / "README.md").write_text("alpha\n", encoding="utf-8")
    agent = build_agent(build_arg_parser().parse_args(["--cwd", str(tmp_path)]))

    assert isinstance(agent, Pico)
    assert agent.run_store.root == tmp_path.resolve() / ".mini-pico" / "runs"
    assert (agent.approval_policy, agent.max_steps, agent.max_new_tokens) == ("auto", 4, 512)
    assert isinstance(agent.model_client, mini_pico.FakeModelClient)
    assert agent.model_client.outputs is None
    assert agent.history == []
    assert agent.current_task_state is None
