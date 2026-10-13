"""工作区边界：把文件动作锚在仓库根之内，并给出模型可见的第一印象。

`Workspace` 只做两件事——把相对路径解析成根目录之内的绝对路径（越界即 `ValueError`），以及渲染
一段“根目录 + 顶层清单 + README 摘录”的快照文本给 Prompt 使用。`clip` 是同一条边界的另一半：
任何要回灌给模型的长文本都先截断，并带上被裁掉的字符数，让“我看到的不是全部”这件事留在文本里。
`IGNORED_NAMES` 是清单与搜索共同的忽略集合，Git 目录、虚拟环境和各类缓存都不进模型视野。

这里不采集 Git 事实、不算指纹、也不做前后差异比较——那些属于主项目的 `runtime/workspace`；路径
归属检查在主项目里也单独下沉到 `security.authorization.workspace_paths`。教学版把“解析”和
“判断是否在根内”写在同一个方法里，因为读者只需要一次就能记住这条边界。`clip` 不保证按行或按
Token 对齐，截断点可以落在任意字符之间。
"""

from pathlib import Path

IGNORED_NAMES = {".git", ".mini-pico", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv"}


class Workspace:
    """一次运行的根目录，负责路径归属判断与工作区快照渲染。

    构造时立刻 `resolve()`，因此符号链接与 `..` 在比较之前就已经被展开：指向仓库外的链接同样会被
    拒绝，而不是只在字符串层面看起来安全。
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    @classmethod
    def build(cls, cwd: Path | str = ".") -> "Workspace":
        """按给定目录建立一个工作区，缺省用当前工作目录。"""
        return cls(Path(cwd).resolve())

    def path(self, value: object) -> Path:
        """把模型给出的相对路径解析成根目录之内的绝对路径。

        结果必须等于根目录或位于根目录之下，否则抛 `path escapes workspace`。入参先 `str()`，
        因为参数来自模型输出的 JSON，类型不可信；这里不校验文件是否存在，存在性属于各工具自己的
        参数校验。
        """
        candidate = (self.root / str(value)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("path escapes workspace")
        return candidate

    def relative(self, path: Path | str) -> str:
        """把绝对路径换算回相对根目录的显示形式，供工具输出与工件使用。"""
        return str(Path(path).resolve().relative_to(self.root))

    def snapshot_text(self) -> str:
        """渲染进入 Prompt 的工作区第一印象：根路径、顶层条目与 README 前 1200 字符。

        只遍历顶层而不递归，目录排在文件之前并按小写名称排序，因此同一棵树的渲染结果是稳定的。
        条目上限 80 条、README 截断到 1200 字符，都是有意的粗预算：教学版没有段预算机制，
        快照必须自带长度上限，否则一棵大仓库会把 Prompt 撑到看不出历史。
        """
        readme = self.root / "README.md"
        readme_text = ""
        if readme.exists():
            readme_text = readme.read_text(encoding="utf-8", errors="replace")[:1200]
        entries = []
        for item in sorted(self.root.iterdir(), key=lambda path: (path.is_file(), path.name.lower())):
            if item.name in IGNORED_NAMES:
                continue
            entries.append(("[D] " if item.is_dir() else "[F] ") + item.name)
        listing = "\n".join(entries[:80]) or "(empty)"
        return f"Workspace root: {self.root}\nFiles:\n{listing}\nREADME excerpt:\n{readme_text}"


def clip(text: object, limit: int = 4000) -> str:
    """把文本裁到至多 ``limit`` 个字符，超长时在末尾追加被裁掉的字符数。

    入参先 `str()`，因此工具结果、异常文本与模型输出都能直接传入。后缀里的字符数让读者能判断
    “少了多少”，而不是只看到一个省略号；不裁剪时原样返回，不额外加任何标记。
    """
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
