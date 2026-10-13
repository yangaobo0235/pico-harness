"""产品身份：对外名称、终端首屏与请求标识。

这些字符串会出现在欢迎界面、帮助文本和 HTTP User-Agent 里，集中定义以免同一个产品在
不同地方写成不同名字。``USER_AGENT`` 跟随工具协议的线上格式版本，而不是发行版本号：
代理网关按它区分请求语义，随 ``pyproject`` 版本一起跳动反而会让对端统计失真。
"""

PRODUCT_NAME = "pico"
PRODUCT_SUBTITLE = "local coding agent"
PRODUCT_STATUS_LINE = "calm shell, ready for work"

#: 首屏 Logo。逐字符保留，宽度参与终端盒子排版，不做动态生成。
PRODUCT_LOGO = (
    "        /\\___/\\\\",
    "       (  o o  )",
    "       /   ^   \\\\",
    "      /|       |\\\\",
)
USER_AGENT = "pico/0.1"
