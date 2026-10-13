"""``python -m pico`` 的入口。

发行安装使用 ``pico`` 命令，源码运行使用本模块，两者调用同一个 `main`，因此行为不依赖安装方式。
返回值直接作为进程退出码，脚本调用方可以据此判断一次请求是否成功。
"""

from pico.interfaces.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
