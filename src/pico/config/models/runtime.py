"""运行期可调参数的默认值与取值范围。

这里集中“需要跨层引用、又确实会被 CLI 或实验脚本改写”的数字与枚举：单轮输出与历史长度上限、
Shell 超时范围、工具结果裁剪长度、委派子 Agent 的默认预算，以及审批策略取值。工具内部把
这些值用于校验，但不会因为改了这里就改变协议含义；真正决定 prompt 各段比例的预算属于
`pico.runtime.context.budget`。
"""

APPROVAL_ASK = "ask"
APPROVAL_AUTO = "auto"
APPROVAL_NEVER = "never"

APPROVAL_POLICIES = (APPROVAL_ASK, APPROVAL_AUTO, APPROVAL_NEVER)

DEFAULT_APPROVAL_POLICY = APPROVAL_ASK
DEFAULT_MAX_STEPS = 6
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.9
DEFAULT_REQUEST_TIMEOUT_S = 300
#: 模型连续返回无法解析的输出时，一轮请求允许消耗的最大 attempt 倍数下限。
MIN_RETRY_HEADROOM = 4

#: 工具结果与历史渲染的字符上限；它们同时约束写进 Session 的体积与进入 Prompt 的体积。
MAX_TOOL_OUTPUT = 4000
MAX_HISTORY = 12000

#: Shell 默认超时与允许区间：上限刻意压得很小，长任务应由模型分次发起而不是延长单次预算。
TOOL_SHELL_TIMEOUT_DEFAULT_S = 20
TOOL_SHELL_TIMEOUT_MIN_S = 1
TOOL_SHELL_TIMEOUT_MAX_S = 120

TOOL_READ_FILE_DEFAULT_START = 1
TOOL_READ_FILE_DEFAULT_END = 200
TOOL_LIST_FILES_MAX_ENTRIES = 200
TOOL_SEARCH_MAX_MATCHES = 200

#: 委派子 Agent 的默认预算；子 Agent 只读、步数更少，用来收敛“调查类”动作的成本。
DELEGATE_DEFAULT_MAX_STEPS = 3
DEFAULT_MAX_DEPTH = 1

#: 扫描仓库时整段跳过的目录名。版本控制、虚拟环境与 Pico 自己的状态目录都不属于源代码，
#: 列进 prompt 或搜索结果只会挤占预算；`__pycache__` 之类缓存同理。
IGNORED_PATH_NAMES = frozenset({".git", ".pico", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv"})

#: 首次进入仓库时优先读取的项目文档，按“最可能改变 agent 行动方式”排序。
PROJECT_DOC_NAMES = ("AGENTS.md", "README.md", "pyproject.toml", "package.json")

#: 传给 Shell 的环境变量白名单。不继承父进程全部环境，避免把与任务无关的凭证带进命令执行。
DEFAULT_SHELL_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "PWD",
    "SHELL",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
)
