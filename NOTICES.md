# 第三方版权与许可证

Pico 使用 [Apache License 2.0](LICENSE)，包含以下第三方项目的代码。原始版权声明和完整许可证随发行包保存在 `LICENSES/`。

## 来源与许可证

| 项目 | 来源 | 许可证 |
| --- | --- | --- |
| nanobot | [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | [MIT-nanobot.txt](LICENSES/MIT-nanobot.txt) |
| hermes-agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | [MIT-hermes-agent.txt](LICENSES/MIT-hermes-agent.txt) |
| ink | [vadimdemedes/ink](https://github.com/vadimdemedes/ink) | [MIT-ink.txt](LICENSES/MIT-ink.txt) |
| React、React DOM、Scheduler | [facebook/react](https://github.com/facebook/react) | [MIT-react.txt](LICENSES/MIT-react.txt) |
| Ajv | [ajv-validator/ajv](https://github.com/ajv-validator/ajv) | [MIT-ajv.txt](LICENSES/MIT-ajv.txt) |
| fast-deep-equal | [epoberezkin/fast-deep-equal](https://github.com/epoberezkin/fast-deep-equal) | [MIT-fast-deep-equal.txt](LICENSES/MIT-fast-deep-equal.txt) |
| json-schema-traverse | [epoberezkin/json-schema-traverse](https://github.com/epoberezkin/json-schema-traverse) | [MIT-json-schema-traverse.txt](LICENSES/MIT-json-schema-traverse.txt) |
| fast-uri | [fastify/fast-uri](https://github.com/fastify/fast-uri) | [BSD-3-Clause-fast-uri.txt](LICENSES/BSD-3-Clause-fast-uri.txt) |

## nanobot

Copyright (c) 2025 nanobot contributors

引入来源为 v0.1.5.post3。相关代码位于 `src/pico`，覆盖 Agent、工具、渠道、CLI、配置、调度、Provider、会话、技能、模板和基础操作，包含 Pico 修改。

## hermes-agent

Copyright (c) 2025 Nous Research

引入来源为提交 `dd0923bb89ed2dd56f82cb63656a1323f6f42e6f`。相关代码位于 `apps/tui`，包括 `@hermes/ink` 分支。Pico 修改包括产品标识、环境变量、RPC 客户端和 Python 运行时桥接。

## ink

Copyright (c) Vadym Demedes, Sindre Sorhus, and ink contributors

通过 `@hermes/ink` 分支引入，代码位于 `apps/tui/packages/hermes-ink`，保留原包名。源文件中的声明保留 ink contributors、Nous Research 和 EverMind modifications 的归属链。

## Trace 查看器运行依赖

React、React DOM、Scheduler 用于浏览器界面。Ajv 及其 fast-deep-equal、json-schema-traverse、fast-uri 依赖用于 Trace API 响应校验。这些代码随编译后的 JavaScript 分发；对应原始许可证全文保存在上表文件中，纳入 wheel 与 sdist 的归属校验。
