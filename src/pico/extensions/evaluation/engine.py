"""固定基准评测引擎：把每个任务跑到收敛，再产出一份可归档的工件。

`BenchmarkEvaluator` 是本模块的唯一核心对象：它为每个任务从仓库里的 fixture 复制一份干净工作区，
在其上装配一套完整运行时（`Pico` + `WorkspaceContext` + `SessionStore` + `RunStore` +
`FakeModelClient`），必要时先预置现场，然后 `ask()` 一次，用外部 `verifier` 命令、工件文件是否存在、
步数预算与停止原因四个条件共同判定这次是否通过，并把逐任务结果行交给 `benchmark.summarize_rows`
汇总。`run_fixed_benchmark` 与 `run_harness_regression_v2` 是同一台机器的两个具名入口，差别只在
默认工件路径。

这里不实现任何 agent 行为：控制循环属于 `pico.runtime`，工具与记忆属于 `pico.capabilities`，字段
校验属于 `benchmark.py`，事实采集属于 `artifacts.py`；本模块只是这些既有接口的组合者，因此它
观察运行而不改变运行时行为。它也不做并行、不做重试、不做多次采样取中位数——一次评测要的是
"这一次确实发生了什么"，任何自动重试都会把不确定的行为伪装成确定的结论。
"""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pico.capabilities.memory.state import is_effectively_empty
from pico.config.paths import WorkspacePaths
from pico.contracts.turns import STOP_REASON_FINAL_ANSWER_RETURNED
from pico.extensions.evaluation.artifacts import (
    _artifact_path_for_task,
    _checkpoint_payload,
    _current_locale,
    _digest_file,
    _fixture_snapshot_id,
    _git_value,
    _now_in_timezone,
    _scripted_outputs_for_task,
    _workspace_relative,
)
from pico.extensions.evaluation.benchmark import load_benchmark, summarize_rows
from pico.extensions.evaluation.config import (
    BENCHMARK_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_PATH,
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_HARNESS_REGRESSION_V2_ARTIFACT_PATH,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEZONE,
    DEFAULT_TOP_P,
)
from pico.integrations.llm.providers.fake import FakeModelClient
from pico.observability.runs.store import RunStore
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _apply_task_setup(agent: Pico, task: dict[str, Any], fixture_copy_root: Path) -> None:
    """按任务里的 `setup` 段预置运行现场，让恢复类分支在第一次 `ask()` 之前就是可触发的。

    ``agent`` 是已经装配好但还没跑过的实例，``task`` 是规范化后的任务字典，
    ``fixture_copy_root`` 是该任务独占的 fixture 副本目录（写文件必须落在这里，不能碰仓库原件）。
    没有 `setup`、`setup` 为空映射，或 `kind` 不属于下列三种时，函数直接返回：预置是可选项，
    未知 `kind` 也不会报错，这样新增 setup 类型时旧评测只是"什么都没做"而不是整体失败。

    三种现场各有副作用，全部走公开接口而不是私有属性：`context_reduction` 灌入
    ``history_count``（默认 12）条长历史与 ``note_count``（默认 6）条长笔记，再把
    `context_manager` 的 `total_budget`（默认 900）与 `section_budgets` 压小，逼出上下文收缩与
    checkpoint；`freshness_mismatch` 为 ``path``（默认 ``sample.txt``）写下过期摘要、把带该摘要
    新鲜度的 checkpoint 存进会话，然后用 ``mutated_text`` 真的改写文件；`workspace_mismatch`
    只存一份 `workspace_fingerprint` 为固定假值的 checkpoint，用来触发指纹失配重建。
    """
    setup = dict(task.get("setup", {}) or {})
    if not setup:
        return

    kind = str(setup.get("kind", "")).strip()
    if kind == "context_reduction":
        history_count = int(setup.get("history_count", 12))
        note_count = int(setup.get("note_count", 6))
        for index in range(history_count):
            agent.record(
                {
                    "role": "user" if index % 2 == 0 else "assistant",
                    "content": f"benchmark-history-{index}-" + ("A" * 220),
                    "created_at": f"2026-04-15T09:{index:02d}:00+00:00",
                }
            )
        for index in range(note_count):
            agent.memory.append_note(
                f"benchmark-note-{index}-" + ("B" * 180),
                tags=("recall",),
                created_at=f"2026-04-15T10:{index:02d}:00+00:00",
            )
        agent.session["memory"] = agent.memory.to_dict()
        agent.context_manager.total_budget = int(setup.get("total_budget", 900))
        agent.context_manager.section_budgets = dict(
            setup.get(
                "section_budgets",
                {"prefix": 120, "memory": 120, "relevant_memory": 120, "history": 160},
            )
        )
        return

    if kind == "freshness_mismatch":
        path = str(setup.get("path", "sample.txt"))
        summary_text = str(setup.get("summary", f"{path}: stale benchmark summary"))
        agent.memory.set_file_summary(path, summary_text)
        agent.memory.remember_file(path)
        freshness = agent.memory.to_dict()["file_summaries"][path]["freshness"]
        agent.session["memory"] = agent.memory.to_dict()
        agent.session["checkpoints"] = {
            "current_id": "ckpt_freshness",
            "items": {
                "ckpt_freshness": _checkpoint_payload(
                    "ckpt_freshness",
                    current_goal="Re-anchor stale benchmark file state",
                    next_step=f"Re-read {path}",
                    runtime_identity={"workspace_fingerprint": agent.workspace.fingerprint()},
                    key_files=[{"path": path, "freshness": freshness}],
                    freshness={path: freshness},
                    summary="stale benchmark checkpoint",
                )
            },
        }
        agent.session_store.save(agent.session)
        (fixture_copy_root / path).write_text(
            str(setup.get("mutated_text", "alpha\nbeta\nstale-updated\nplaceholder\n")), encoding="utf-8"
        )
        return

    if kind == "workspace_mismatch":
        agent.session["checkpoints"] = {
            "current_id": "ckpt_workspace",
            "items": {
                "ckpt_workspace": _checkpoint_payload(
                    "ckpt_workspace",
                    current_goal="Recover after benchmark workspace drift",
                    next_step="Rebuild runtime state from a fresh checkpoint",
                    runtime_identity={"workspace_fingerprint": "outdated-benchmark-fingerprint"},
                    summary="workspace drift benchmark checkpoint",
                )
            },
        }
        agent.session_store.save(agent.session)
        return


class BenchmarkEvaluator:
    """按固定脚本跑完一份基准并写出结果工件的评测器。

    构造参数就是这次评测的全部设定，全部带默认值：``benchmark_path`` 与 ``artifact_path`` 是输入
    与输出路径，``workspace_root`` 是 fixture 副本与运行目录的落点（省略时用 `tempfile.mkdtemp`
    建一个 ``pico-benchmark-`` 前缀的临时目录，因此默认不会污染仓库，也不会被评测器自动清理），
    ``model_name``/``model_version``/``temperature``/``top_p``/``max_new_tokens`` 只作为
    可复现性证据写进工件、不参与任何判定（真实解码由脚本化假模型完成），``timezone_name`` 决定
    工件时间戳格式，``model_client_factory`` 是替换模型后端的唯一钩子。

    `repo_root` 由 ``benchmark_path`` 自身的位置反推（其祖父目录），因此基准放在
    ``<repo>/benchmarks/`` 下时 `fixture_repo` 与 `runtime` 的 Git 事实都指向真正的仓库；把基准
    放到仓库之外会让工件里的相对路径失效，这需要调用方显式处理而不是在这里猜测。本对象不校验
    参数取值、不缓存结果，也不保证并发安全：一次实例只对应一次顺序评测。
    """

    def __init__(
        self,
        benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
        artifact_path: str | Path = DEFAULT_ARTIFACT_PATH,
        workspace_root: str | Path | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        model_version: str = DEFAULT_MODEL_VERSION,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
        timezone_name: str = DEFAULT_TIMEZONE,
        model_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.benchmark_path = Path(benchmark_path)
        self.artifact_path = Path(artifact_path)
        self.workspace_root = (
            Path(workspace_root) if workspace_root is not None else Path(tempfile.mkdtemp(prefix="pico-benchmark-"))
        )
        self.model_name = model_name
        self.model_version = model_version
        self.temperature = temperature
        self.top_p = top_p
        self.max_new_tokens = max_new_tokens
        self.timezone_name = timezone_name
        self.model_client_factory = model_client_factory
        self.repo_root = self.benchmark_path.resolve().parent.parent

    def load(self) -> dict[str, Any]:
        """按本实例的 `repo_root` 读取并校验基准，返回规范化后的定义。

        只做一次 `load_benchmark`，把路径细节留给调用方；文件缺失、非 UTF-8 或校验不通过都原样
        抛出。`run()` 会自行调用它，因此单独跑一次评测不需要先手动 `load()`。
        """
        return load_benchmark(self.benchmark_path, repo_root=self.repo_root)

    def run(self) -> dict[str, Any]:
        """跑完基准里的所有任务，写出工件并返回工件字典（与磁盘内容逐字相同）。

        返回的顶层字段依次是 `schema_version`、`captured_at`、`runtime`（`commit_sha` 与 `branch`，
        Git 不可用时为空串）、`benchmark`（`source` 相对路径与 `task_count`）、`reproducibility`
        （`fixture_snapshot_id`、模型身份、`decoding` 三元组、`timezone`、`locale`）、`summary`、
        与 `summary` 同值的顶层 `failure_category_counts`，最后是逐任务 `rows`。

        任务是**按基准里的顺序串行**执行的，任何一个任务抛出的异常都会中止整次评测——中途失败
        不会留下部分工件，因为工件只在全部跑完后写一次。工件写入前不检查是否已存在：存在即覆盖，
        这样"重跑同一份基准"始终得到当前事实而不是上一次的残骸。`captured_at` 每次调用都取当下，
        所以同一提交跑两次的工件不会字节相同，可复现性靠 `fixture_snapshot_id` 与解码参数比对。
        """
        benchmark = self.load()
        rows = [self.run_task(task) for task in benchmark["tasks"]]
        summary = summarize_rows(rows)
        artifact = {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "captured_at": _now_in_timezone(self.timezone_name),
            "runtime": {
                "commit_sha": _git_value(["rev-parse", "HEAD"], cwd=self.repo_root),
                "branch": _git_value(["branch", "--show-current"], cwd=self.repo_root),
            },
            "benchmark": {
                "source": str(self.benchmark_path.resolve().relative_to(self.repo_root)),
                "task_count": len(benchmark["tasks"]),
            },
            "reproducibility": {
                "fixture_snapshot_id": _fixture_snapshot_id(
                    self.repo_root / str(task["fixture_repo"]) for task in benchmark["tasks"]
                ),
                "model_name": self.model_name,
                "model_version": self.model_version,
                "decoding": {
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "max_new_tokens": self.max_new_tokens,
                },
                "timezone": self.timezone_name,
                "locale": _current_locale(),
            },
            "summary": summary,
            "failure_category_counts": summary["failure_category_counts"],
            "rows": rows,
        }
        self._write_artifact(artifact)
        return artifact

    def run_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """在干净的 fixture 副本上跑完一个任务，返回一行结果记录。

        输入是 `load()` 规范化过的任务字典（用到 `id`、`fixture_repo`、`prompt`、`allowed_tools`、
        `step_budget`、`expected_artifact`、`verifier`、`category` 与可选 `setup`），副本按
        `<workspace_root>/<task id>/<fixture 目录名>` 落点；**每次调用先删除已存在的副本再整目录
        复制**，因此重复评测同一 `workspace_root` 总是从干净 fixture 出发，仓库里的 fixture 原件
        始终不被改写。副本父目录用 `mkdir(parents=True, exist_ok=True)` 建立；fixture 源目录缺失
        时 `copytree` 抛 ``FileNotFoundError`` 中止整次评测，因为"没得测"不该被记成一行失败。

        运行时装配全部走既有公开接口：工作区以 fixture 副本自身为根（`repo_root_override`），
        会话与运行记录写进副本内的 `.pico/`（`WorkspacePaths`），模型默认是脚本化
        `FakeModelClient`，`model_client_factory` 存在时改由它接收 ``task``/``workspace`` 两个关键字
        参数构造后端。`_apply_task_setup` 之后先记录四项"开局是否干净"的事实（历史为空、记忆
        有效为空、任务摘要为空、情景笔记为空），再 `ask()` 一次。

        通过的定义是四个条件同时成立：`within_budget`（工具步数不超过 `step_budget`）、
        `verifier_passed`（外部命令退出码为 0）、`expected_artifact_exists`（该 fixture 预期的
        工件文件确实存在）、`non_failure_stop_reason`（停止原因是 `final_answer_returned`）。
        未通过时 `failure_category` 取 `_failure_category` 的第一个命中项。`verifier` 在副本目录里
        以 `shell=True` 执行，其 `stdout`/`stderr`/退出码原样进工件，因此任务失败也是可读的证据而
        不是异常；工件文件不存在时 `artifact_digest` 写成空串而不是报错。

        `fixture_copy_relpath`、`run_dir_relpath`、`task_state_relpath`、`report_relpath` 都相对
        `workspace_root` 表达，绝对路径不出现在工件里。返回的键顺序即工件 `rows` 元素里的顺序，
        末尾两项 `task_state` 与 `report` 是运行时字典与报告的完整快照，本方法不裁剪它们。
        """
        task = dict(task)
        fixture_source = self.repo_root / task["fixture_repo"]
        fixture_copy_root = self.workspace_root / task["id"] / fixture_source.name
        if fixture_copy_root.exists():
            shutil.rmtree(fixture_copy_root)
        fixture_copy_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fixture_source, fixture_copy_root)

        workspace = WorkspaceContext.build(
            fixture_copy_root,
            repo_root_override=fixture_copy_root,
        )
        state_paths = WorkspacePaths(fixture_copy_root)
        session_store = SessionStore(state_paths.sessions_dir)
        run_store = RunStore(state_paths.runs_dir)
        if self.model_client_factory is not None:
            model_client = self.model_client_factory(task=task, workspace=workspace)
        else:
            model_client = FakeModelClient(_scripted_outputs_for_task(task))
        agent = Pico(
            model_client=model_client,
            workspace=workspace,
            session_store=session_store,
            run_store=run_store,
            approval_policy="auto",
            max_steps=int(task["step_budget"]),
            max_new_tokens=self.max_new_tokens,
            allowed_tools=task["allowed_tools"],
        )
        _apply_task_setup(agent, task, fixture_copy_root)

        initial_history_empty = len(agent.session["history"]) == 0
        initial_memory_state = agent.memory.to_dict()
        initial_memory_empty = is_effectively_empty(initial_memory_state)
        initial_task_summary_empty = not str(initial_memory_state["working"]["task_summary"]).strip()
        initial_episodic_notes_empty = not initial_memory_state["episodic_notes"]

        final_answer = agent.ask(task["prompt"])
        task_state = agent.current_task_state
        run_dir = Path(agent.current_run_dir)
        task_state_path = agent.run_store.task_state_path(task_state)
        report_path = agent.run_store.report_path(task_state)
        report = agent.run_store.load_report(task_state.run_id)

        artifact_path = _artifact_path_for_task(task)
        artifact_file = fixture_copy_root / artifact_path
        expected_artifact_exists = artifact_file.exists()
        artifact_digest = _digest_file(artifact_file) if expected_artifact_exists else ""

        verifier = subprocess.run(
            task["verifier"],
            cwd=fixture_copy_root,
            shell=True,
            capture_output=True,
            text=True,
        )

        within_budget = task_state.tool_steps <= int(task["step_budget"])
        verifier_passed = verifier.returncode == 0
        non_failure_stop_reason = task_state.stop_reason == STOP_REASON_FINAL_ANSWER_RETURNED
        passed = within_budget and verifier_passed and expected_artifact_exists and non_failure_stop_reason
        failure_category = (
            None
            if passed
            else self._failure_category(
                within_budget=within_budget,
                verifier_passed=verifier_passed,
                expected_artifact_exists=expected_artifact_exists,
                non_failure_stop_reason=non_failure_stop_reason,
            )
        )

        return {
            "id": task["id"],
            "prompt": task["prompt"],
            "fixture_repo": task["fixture_repo"],
            "fixture_copy_relpath": _workspace_relative(fixture_copy_root, self.workspace_root),
            "run_id": task_state.run_id,
            "run_dir_relpath": _workspace_relative(run_dir, self.workspace_root),
            "task_state_relpath": _workspace_relative(task_state_path, self.workspace_root),
            "report_relpath": _workspace_relative(report_path, self.workspace_root),
            "allowed_tools": list(task["allowed_tools"]),
            "step_budget": int(task["step_budget"]),
            "expected_artifact": task["expected_artifact"],
            "artifact_path": artifact_path,
            "artifact_exists": expected_artifact_exists,
            "artifact_digest": artifact_digest,
            "verifier": task["verifier"],
            "verifier_exit_code": verifier.returncode,
            "verifier_stdout": verifier.stdout,
            "verifier_stderr": verifier.stderr,
            "category": task["category"],
            "status": "pass" if passed else "fail",
            "passed": passed,
            "failure_category": failure_category,
            "within_budget": within_budget,
            "verifier_passed": verifier_passed,
            "expected_artifact_exists": expected_artifact_exists,
            "non_failure_stop_reason": non_failure_stop_reason,
            "tool_steps": task_state.tool_steps,
            "attempts": task_state.attempts,
            "final_answer": final_answer,
            "stop_reason": task_state.stop_reason,
            "initial_history_empty": initial_history_empty,
            "initial_memory_empty": initial_memory_empty,
            "initial_task_summary_empty": initial_task_summary_empty,
            "initial_episodic_notes_empty": initial_episodic_notes_empty,
            "task_state": task_state.to_dict(),
            "report": report,
        }

    def _failure_category(
        self,
        within_budget: bool,
        verifier_passed: bool,
        expected_artifact_exists: bool,
        non_failure_stop_reason: bool,
    ) -> str | None:
        """给一次未通过的任务挑一个归因标签，只取第一个命中的条件。

        判定顺序是 `missing_artifact` → `budget_exceeded` → `verifier_failed` →
        `failure_stop_reason`：文件根本没写出来比"超预算"更接近根因，先报出去才有助于定位。
        四个条件全部成立时不该走到这里，返回 ``unknown`` 作为兜底而不是抛错，因为这只意味着
        通过判定与归因判定在某处失去了同步，值得留下可对比的行。参数都是布尔，不做默认值。
        """
        if not expected_artifact_exists:
            return "missing_artifact"
        if not within_budget:
            return "budget_exceeded"
        if not verifier_passed:
            return "verifier_failed"
        if not non_failure_stop_reason:
            return "failure_stop_reason"
        return "unknown"

    def _write_artifact(self, artifact: dict[str, Any]) -> None:
        """把 ``artifact`` 以缩进 2、键排序的 JSON 写到 `artifact_path`，末尾保留一个换行。

        父目录用 `mkdir(parents=True, exist_ok=True)` 建立，目标文件已存在时直接覆盖：工件是"最近
        一次评测"的快照，保留历史属于外层归档策略，不该由评测器代劳。编码固定 UTF-8，非 ASCII
        的 verifier 输出会转义成 ``\\uXXXX``（`ensure_ascii` 取默认值），因此工件在任何机器上
        读回都是同一串字节。写入失败（权限、磁盘、非法字符）原样抛出，不做静默降级。
        """
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_fixed_benchmark(
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    artifact_path: str | Path = DEFAULT_ARTIFACT_PATH,
    workspace_root: str | Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    timezone_name: str = DEFAULT_TIMEZONE,
    model_client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """构造一台 `BenchmarkEvaluator` 并立刻跑完，返回已写盘的工件字典。

    参数与 `BenchmarkEvaluator.__init__` 一一同名同默认值，全部可省略；省略
    ``workspace_root`` 时使用临时目录，因此一次调用不留痕迹在仓库里（也不会自动删）。
    这是脚本与 CI 的推荐入口：调用方不需要管理评测器实例的生命周期。

    只跑一次，不重试也不聚合多次结果——需要"重复若干次看方差"请在调用方循环，把循环藏进本函数
    会让工件与 `captured_at` 的对应关系变得含糊。
    """
    evaluator = BenchmarkEvaluator(
        benchmark_path=benchmark_path,
        artifact_path=artifact_path,
        workspace_root=workspace_root,
        model_name=model_name,
        model_version=model_version,
        temperature=temperature,
        top_p=top_p,
        max_new_tokens=max_new_tokens,
        timezone_name=timezone_name,
        model_client_factory=model_client_factory,
    )
    return evaluator.run()


def run_harness_regression_v2(
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    artifact_path: str | Path = DEFAULT_HARNESS_REGRESSION_V2_ARTIFACT_PATH,
    workspace_root: str | Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    timezone_name: str = DEFAULT_TIMEZONE,
    model_client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """以 v2 回归的默认工件路径跑同一套基准，等价于改了 ``artifact_path`` 的 `run_fixed_benchmark`。

    存在的意义是让"harness 回归"这类结论落到 `artifacts/harness-regression-v2.json`，与基准
    v1 的工件并存而互不覆盖；任务、判定口径与解码默认值都沿用基准，不在此处分叉。除
    ``artifact_path`` 外所有参数与 `run_fixed_benchmark` 同义同默认值。

    这里不复制评测逻辑，也不给 v2 单独定义 schema 版本：一旦两个入口开始分别解释任务，
    "同一份基准"这个前提就消失了，回归数字不再可比。
    """
    return run_fixed_benchmark(
        benchmark_path=benchmark_path,
        artifact_path=artifact_path,
        workspace_root=workspace_root,
        model_name=model_name,
        model_version=model_version,
        temperature=temperature,
        top_p=top_p,
        max_new_tokens=max_new_tokens,
        timezone_name=timezone_name,
        model_client_factory=model_client_factory,
    )
