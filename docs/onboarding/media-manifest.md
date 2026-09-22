# Onboarding 媒体验收清单

截图、GIF、视频和报告类资产都不写入 Git。这份文本清单定义场景和验收项，维护者据此
复现对外媒体，而不需要提交二进制制品。

| ID | 场景 | 必须可见的证据 | 密钥处理 |
| --- | --- | --- | --- |
| `first-turn` | 从语言选择到第一条回复的 `pico onboard --skip-memory` 全过程 | 已选择 Provider、Memory 明确关闭，以及一条 `Agent:` 回复 | API Key 遮蔽；使用可丢弃的仓库路径 |
| `feishu-config` | 飞书开放平台加 Pico CLI | 长连接、`im.message.receive_v1`、已发布版本和脱敏后的渠道配置 | App Secret、Encrypt Key、Verification Token 和租户身份均脱敏 |
| `feishu-live` | 一条入站飞书消息和 Pico 回复 | 同一会话内被接收的入站事件和回复 | 用户名、open_id、消息 ID 和凭证均脱敏 |
| `agent-install` | 正式版的 Pico 安装和 JSON 健康检查 | 已安装版本加 `pico doctor --json` | Gitee Token、带签名的 URL 查询串和本机 home 路径均脱敏 |

## 采集规则

- 采集正式版 wheel 的安装过程，不要采集可编辑的开发 Checkout。
- 在外部资产描述里，把每个资产绑定到对应的 Pico tag、操作系统和采集日期。
- 使用可丢弃的 Git 仓库，以及可丢弃的 Provider 或飞书凭证。
- 命令和输出在 README 宽度下仍需可读。宁可裁剪终端界面元素，也不要缩小文字。
- 跳过的 probe、fixture 或模拟机器人回复都不能标为真实成功。
- 资产只发布到维护者批准的外部位置。URL 稳定且目标读者可访问之后，才加入 README
  链接。
