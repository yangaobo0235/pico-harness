"""结果工件所需的事实采集与载荷拼装。

这里放的是"写进工件之前先要拿到什么"：Git 提交与分支、当前 locale、按时区格式化的时间戳、
fixture 快照 ID、工件文件摘要、workspace 内相对路径，以及一份与运行时同形的 checkpoint 载荷。
每个函数只做一次外部观察或一次纯计算，返回值可以直接 JSON 序列化，因此 `engine.py` 组织工件时
不需要再处理任何异常路径。

本模块不驱动控制循环，也不解释这些事实的含义（判定通过与否属于 `engine.py`），更不写文件
（落盘属于 `engine.py` 的 `_write_artifact`）。这些名字保留下划线前缀是有意取舍：它们只在
`pico.extensions.evaluation` 包内被 `engine.py` 复用，不属于包级稳定入口，因此改名或加参数
不算破坏外部调用方；采集口径本身也不做缓存，因为"同一进程跑两次基准"必须各自重新观察。
"""

import hashlib
import locale as locale_module
import subprocess
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pico.extensions.evaluation.config import (
    BENCHMARK_SCHEMA_VERSION,
    SCRIPTED_MODEL_OUTPUTS,
    TASK_FIXTURE_ARTIFACTS,
)

#: 单次 Git 调用的超时秒数：基准常在 CI 里跑，不能因为仓库锁或超大仓库把整次评测挂住。
GIT_TIMEOUT_S = 5


def _git_value(args: list[str], fallback: str = "", cwd: Path | None = None) -> str:
    """在 ``cwd`` 下执行一次只读 Git 命令，返回标准输出的首尾去空白结果。

    ``args`` 是 `git` 之后的参数列表；``fallback`` 是拿不到内容时的替代值（默认空字符串，
    即工件里写成 `"commit_sha": ""`）；``cwd`` 省略时取当前工作目录。命令成功但输出为空也
    使用 ``fallback``，避免下游把空串误读成"这条事实确实为空"。

    Git 不可用、不在仓库内、超时或权限不足都按"这项事实缺失"处理而不向上抛：缺一条提交号只让
    工件少一项，让整次评测失败则毫无价值。这里不重试、不校验 Git 版本，也不采集 dirty 状态。
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT_S,
        )
        return result.stdout.strip() or fallback
    except Exception:
        return fallback


def _current_locale() -> str:
    """返回当前 `LC_CTYPE` locale 名称，取不到时退回系统默认 locale 或 ``"C"``。

    无输入，也不改变更名：`locale.setlocale` 只传类别时是查询而非设置。Windows 或精简容器里
    查询与回退都可能抛异常（`getdefaultlocale` 在部分环境返回 ``(None, None)``），因此两条路径
    都捕获异常，最终退到 ``"C"``。

    这个值只用于说明"这次工件是在什么 locale 下采集的"，不参与通过与否的判定，所以不做归一化，
    也不试图把 ``Chinese_China`` 之类平台专有名字翻译成 BCP-47。
    """
    try:
        return locale_module.setlocale(locale_module.LC_CTYPE)
    except Exception:
        return locale_module.getdefaultlocale()[0] or "C"


def _now_in_timezone(timezone_name: str) -> str:
    """按 ``timezone_name`` 返回秒级 ISO-8601 时间戳（形如 ``2026-04-15T08:00:00+0800``）。

    显式带偏移而没有时区名，是为了让工件里的时间既可排序又无需再查表。时区名未知或缺少 tzdata
    时直接抛 ``ZoneInfoNotFoundError``——时间戳是工件的可复现性证据，静默退回 UTC 会让两次运行
    看起来可比其实不可比。这里不缓存时间，也不接受 ``datetime`` 注入，固定"当前时刻"这一种来源。
    """
    return datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%dT%H:%M:%S%z")


def _artifact_path_for_task(task: dict[str, Any]) -> str:
    """返回 ``task`` 所在 fixture 中"预期会被写出的工件文件名"。

    输入是校验过的任务字典，用到 `fixture_repo` 一项；只按目录名查 `TASK_FIXTURE_ARTIFACTS`，
    因为基准刻意把 fixture 平铺在 `tests/fixtures/` 下。任务缺 `fixture_repo` 键时抛
    ``KeyError``，属于"绕过了 `validate_benchmark`"的调用错误，不在这里补默认值。

    未知 fixture 抛 ``ValueError``（消息含目录名），因为新增 fixture 必须同时在这里登记，
    否则"工件存在"这一判定会悄悄退化成恒假。这里不检查文件是否真的存在，存在与否由调用方判断。
    """
    fixture_repo_name = Path(str(task["fixture_repo"])).name
    if fixture_repo_name not in TASK_FIXTURE_ARTIFACTS:
        raise ValueError(f"unsupported fixture repo for artifact lookup: {fixture_repo_name}")
    return TASK_FIXTURE_ARTIFACTS[fixture_repo_name]


def _workspace_relative(path: Path | str, workspace_root: Path | str) -> str:
    """把 ``path`` 表达成相对 ``workspace_root`` 的正向相对路径字符串。

    两端都先 `resolve()`，因此符号链接与 `..` 已折叠，绝对路径与相对路径混合传入也能对上。
    工件里只记相对路径：绝对路径含机器与临时目录信息，会让同一提交产出的工件互不相等。

    ``path`` 不在 ``workspace_root`` 之内时抛 ``ValueError``（`relative_to` 的原生行为），这里
    不捕获，也不退回"截断成最后几段"——把越界读成成功会让 fixture 复制位置写错也无人察觉。
    """
    return str(Path(path).resolve().relative_to(Path(workspace_root).resolve()))


def _scripted_outputs_for_task(task: dict[str, Any]) -> list[str]:
    """返回 ``task`` 对应的脚本化模型输出序列副本。

    返回新列表而不是共享的常量对象，因为 `FakeModelClient` 会弹出队首元素；直接把常量交出去
    会让同一进程内的第二次运行拿到空脚本。任务 ID 未登记时抛 ``ValueError``（消息含任务 ID），
    因为"没有脚本"意味着基准被改动过，让它在第一步就失败远好于跑到一半假装模型无话可说。
    """
    outputs = SCRIPTED_MODEL_OUTPUTS.get(task["id"])
    if outputs is None:
        raise ValueError(f"no scripted model outputs for benchmark task: {task['id']}")
    return list(outputs)


def _fixture_snapshot_id(fixture_paths: Iterable[Path | str]) -> str:
    """对若干 fixture 目录的全部内容计算一个 ``sha256:`` 前缀快照 ID。

    ``fixture_paths`` 可以是生成器（调用方就是这样传的），内部先做集合去重再按路径字符串排序，
    目录内的文件按相对路径排序，每一项写入"目录名 + `NUL` + 相对路径 + `NUL` + 字节内容 + `NUL`"。
    这样空目录、重命名与内容交换不会得到相同摘要；不递归进入符号链接指向的目录，因为 `rglob`
    只对普通文件取样。

    读取的是字节而不是文本，因此非 UTF-8 的 fixture 也能稳定摘要，不会因为解码失败而让整份工件
    无法生成。文件不可读时抛原生 ``OSError`` 而不是跳过：跳过的摘要与完整的摘要长得一样，会让
    "快照其实少了一个文件"变得看不出来。目录不存在时结果为空摘要（全零哈希），因为基准已经在校验
    阶段要求 fixture 目录存在，走到这里却不该发生。
    """
    sha = hashlib.sha256()
    for fixture_path in sorted({Path(path).resolve() for path in fixture_paths}, key=lambda path: str(path)):
        fixture_files = sorted(
            (item for item in fixture_path.rglob("*") if item.is_file()),
            key=lambda item: str(item.relative_to(fixture_path)),
        )
        for path in fixture_files:
            sha.update(str(fixture_path.name).encode("utf-8"))
            sha.update(b"\0")
            sha.update(str(path.relative_to(fixture_path)).encode("utf-8"))
            sha.update(b"\0")
            sha.update(path.read_bytes())
            sha.update(b"\0")
    return "sha256:" + sha.hexdigest()


def _checkpoint_payload(
    checkpoint_id: str,
    current_goal: str,
    next_step: str,
    runtime_identity: dict[str, Any],
    *,
    schema_version: int | str = BENCHMARK_SCHEMA_VERSION,
    current_blocker: str = "",
    key_files: list[dict[str, Any]] | None = None,
    freshness: dict[str, Any] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """拼出一份与运行时 checkpoint 同形的字典，用于在任务开始前预置现场。

    位置参数是必填的四项：``checkpoint_id``、``current_goal``、``next_step`` 与
    ``runtime_identity``（调用方传 `agent.workspace.fingerprint()` 之类的真实事实）。
    关键字参数都有默认值：``schema_version`` 等于 `BENCHMARK_SCHEMA_VERSION` 时写成运行时用的
    ``"phase1-v1"`` 字面量，否则原样转成字符串；``key_files``/``freshness`` 为 ``None`` 时给出空
    容器；``summary`` 为空时退回 ``current_goal``，与运行时"没有摘要就用目标占位"一致。
    `completed` 与 `excluded` 恒为空列表，`parent_checkpoint_id` 恒为空串，`created_at` 是固定
    时间戳。

    这里不复用 `pico.runtime.agent.checkpoints` 的构造函数，因为那些函数会从"当下"推导 ID、时间与
    runtime 身份；评测要的恰好相反——一份可预测、字段齐全、能让恢复分支被触发的假现场。字段集合
    若与运行时漂移，评测的就不再是恢复逻辑，那属于测试夹具该跟着修的地方。
    """
    return {
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": "",
        "schema_version": "phase1-v1" if schema_version == BENCHMARK_SCHEMA_VERSION else str(schema_version),
        "created_at": "2026-04-15T08:00:00+00:00",
        "current_goal": current_goal,
        "completed": [],
        "excluded": [],
        "current_blocker": current_blocker,
        "next_step": next_step,
        "key_files": list(key_files or []),
        "freshness": dict(freshness or {}),
        "summary": summary or current_goal,
        "runtime_identity": dict(runtime_identity),
    }


def _digest_file(path: Path | str) -> str:
    """返回 ``path`` 文件内容的 ``sha256:`` 十六进制摘要。

    按字节读取，因此编码无关，非 UTF-8 或二进制文件同样可摘要；文件不存在或不可读时抛
    ``OSError``——调用方只在"工件已经存在"时才走到这里，报错说明存在性判断之后文件被外部删掉了。
    不做分块、也不校验文件是否属于本次 fixture，工件可能被外部改动正是这个字段要暴露的事实。
    """
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
