# 智银 Agent · AI Banking Agent

> 人工智能赛道参赛作品：以自然语言对话为交互入口的银行人工智能体，安全置于体验之前。

## 项目简介

《智银 Agent》以自建模拟银行核心系统为底座：用户用日常语言表达金融意图，系统借助大模型完成语义理解并自主规划子任务 DAG，在严格的安全框架约束内执行智能转账、账单分析、理财、卡片管理、订阅与跨场景联动六大场景共 24 项工具操作。与"能力优先"的同类作品不同，我们把安全置于体验之前——绿黄红三级权限独立于大模型、提示词无法绕过，叠加注入双路防御、回复数值幻觉校验、trace_id 全链路审计与四触发异常熔断；156 项自动化测试全部通过、渗透测试 66/66、20 条越狱语料 100% 拦截。可信的智能，才能真正带来便捷的金融服务。

## 核心特性

- **六大场景全覆盖**：智能转账、账单分析、理财、卡片管理、订阅管理、跨场景联动，共 24 项工具（转账/AA 收款、分类统计与异常识别、申购赎回、虚拟卡/挂失/额度、订阅识别与取消、资金锁定与定时任务）。
- **绿黄红三级权限独立于 LLM**：风险标签定义在服务端工具注册表，Planner 与提示词均无法自标或绕过；黄色操作弹确认卡片、红色操作叠加模拟 MFA，用户确认经独立状态机通道回传，对话内容不能伪造"已确认"。
- **五重安全机制**：注入双路防御（正则规则 + LLM 分类器，模型路 fail-closed）、回复数值幻觉校验（与工具结果比对，不符即重新生成）、trace_id 全链路审计（六类事件可回放）、四触发异常熔断（工具失败/MFA 失败/注入命中/异常时段大额）、容器沙箱隔离（Agent 零数据库直连）。
- **LangGraph 七节点自主规划**：guard_in → intent → planner → executor → tool_dispatch → reflector → responder，子任务 DAG 拓扑执行，中断/回退/人工接管全支持，执行进度实时可视化。
- **24 工具白名单 + Agent 零 DB 直连**：一切读写只经 bank-core REST API，LLM 输出永不直接落库——这是幻觉防护与操作审计的架构基础。
- **管家/透视双层 UI**：`Shift+Tab` 一键切换。管家模式去终端化（一句话结论 + 折叠过程），透视模式完整呈现 DAG 图/裁决日志/审计流；同一会话切换不丢状态，刷新后待办卡自动恢复。
- **Web + IM 双渠道**：IM 通道确认卡降级为"回复 1 确认 / 2 取消"、MFA 降级为短信验证码输入——UI 降级，安全等级不降级。
- **156 项自动化测试**：bank-core 22 + agent-service 134（含安全渗透 66/66，越狱语料拦截率 100.0%），交付前全绿。

## 系统组成

| 模块 | 目录 | 说明 |
|---|---|---|
| Mock Bank Core | `bank-core/` | 模拟银行核心，账户/交易/理财/卡片/订阅 REST API（FastAPI + SQLite） |
| Agent Service | `agent-service/` | Agent 核心（LangGraph）+ 会话网关 + 安全中间件 + 工具层（FastAPI + WebSocket） |
| Web App | `web-app/` | 聊天式银行 APP 前端（Vue 3 + Element Plus + ECharts） |
| 部署 | `deploy/` | docker-compose 一键部署 |
| 文档 | `docs/` | 赛题分析、系统详细设计、安全设计等 |
| 脚本 | `scripts/` | 种子数据、联调与演示脚本 |

## 仓库结构

```
AI-banking-technical-Agent/
├── bank-core/                  # Mock 银行核心：账户/交易/理财/卡片/订阅权威数据源（FastAPI + SQLite，:8100）
│   ├── app/                    #   main.py / models / routers / seed.py（启动自动建表 + 幂等种子）
│   └── tests/                  #   pytest 22 项
├── agent-service/              # Agent 核心：LangGraph 七节点状态图 + 安全中间件 + 24 工具白名单（:8200）
│   ├── app/                    #   graph/ 状态图 · security/ 五安全机制 · tools/ · channels/（Web/IM 双渠道）
│   └── tests/                  #   pytest 134 项（含安全渗透 66/66 与越狱语料）
├── web-app/                    # 聊天式银行 APP：管家/透视双层 UI（Vue 3 + Element Plus + ECharts，:8080）
│   └── src/                    #   views/（login/chat/im/audit 四页）· components/ 八类消息卡片 · stores/
├── deploy/                     # docker-compose 一键部署（bank-core:8100 → agent-service:8200 → web-app:8080）
├── docs/                       # 赛题分析、系统设计、安全自评、验收报告等 11 篇文档
└── scripts/                    # 种子数据、联调冒烟与演示脚本（reset_demo.ps1 / regression.ps1）
```

## 快速开始

```bash
# 一键启动全栈（bank-core + agent-service + web-app）
docker compose -f deploy/docker-compose.yml up --build
```

### 本地三进程开发

```bash
# 1) 模拟银行核心 :8100（首次启动自动建库 + 写种子）
cd bank-core && python -m uvicorn app.main:app --port 8100

# 2) Agent 服务 :8200（LLM_API_KEY 未设置时自动走规则降级路，仍可完整演示）
cd agent-service && python -m uvicorn app.main:app --port 8200

# 3) 前端 :8080（/api 与 /ws 反代到 :8200）
cd web-app && npm run dev
```

演示入口：`/chat` 主战场（管家/透视双模式，`Shift+Tab` 切换）· `/im` 模拟 IM 降级通道 · `/audit/{trace_id}` 审计回放 · agent-service 自带 `/demo` 极简联调页。

## 演示指南

### 演示前重置（必跑）

```powershell
# 停服务 → 删库（含审计/待办/熔断/checkpoint）→ 重启 → fresh seed，约 9 秒恢复演示数据
powershell -ExecutionPolicy Bypass -File scripts/reset_demo.ps1
```

重置后演示数据自检清单：余额 ¥52,300.00 · 通讯录 8 人（含两个"李磊"，尾号 3821/7790，用于同名消歧）· 订阅 6 条 · 理财产品 12 只（R1-R5）。

### 演示前一键回归

```powershell
# 确保两服务在线 → bank-core pytest → 重置 bank 演示库 → agent-service pytest + 渗透报告 → IM 实连冒烟
# 汇总绿/红报告，全部通过退出码 0；实测约 76 秒，同日可重复执行
powershell -ExecutionPolicy Bypass -File scripts/regression.ps1
```

> 注意：回归执行后演示库含测试流水，正式上台前请再跑一次 `reset_demo.ps1`。

### 演示主线建议

1. **跨场景联动**："下个月 15 号是我爱人生日，帮我提前准备好" → 自动规划 DAG：锁定资金 + 定时下单鲜花蛋糕 + 生日提醒，节点进度实时点亮；
2. **安全机制透视**：会话中按 `Shift+Tab` 切透视模式，展示 DAG 图 / 裁决日志 / 审计流三页签与熔断计数；
3. **审计回放**：从回执进入 `/audit/{trace_id}`，六类事件时间线 400ms 逐条点亮，决策链路全程可追溯。

## 测试

```bash
# bank-core：22 项
cd bank-core && python -m pytest tests -q

# agent-service：134 项（含安全渗透 66/66，越狱语料拦截率 100.0%）
cd agent-service && python -m pytest tests -q
```

渗透报告（66 用例全通过）位于 `agent-service/tests/security/report/pentest_report.md`，越狱语料 fixture 为 `agent-service/tests/security/jailbreak_corpus.jsonl`（20 条）。

## 冒烟与回归

```bash
# IM 渠道降级实连冒烟（两服务在线时跑通确认卡文本降级 + 回执 + 审计回放）
python scripts/m3_im_smoke.py
```

无 PowerShell 环境时的手动重置等价操作（演示脚本内部同此逻辑）：

```bash
# 停掉 8100/8200 两服务后删除数据库，重启即恢复 fresh seed
Remove-Item bank-core/data/bank.db*, agent-service/data/agent.db*
```

本地开发启动方式见各子模块 README 与 `docs/02-系统详细设计.md` §14 部署设计。

## 文档导航

1. [赛题分析与开发方案](docs/01-赛题分析与开发方案.md)
2. [系统详细设计](docs/02-系统详细设计.md)
3. [模块接口与提示词设计](docs/03-模块接口与提示词设计.md)
4. [前端详细设计](docs/04-前端详细设计.md)
5. [里程碑验收标准与交付物](docs/05-验收标准与交付物.md)
6. [总体开发计划（场景整合·设计定调·一致性·里程碑）](docs/06-总体开发计划.md)
7. [部署文件增量设计（Dockerfile / nginx / M3 验收 / git 结构）](docs/07-部署文件增量设计.md)
8. [交付前验收报告（M3 静态 19/19 · 测试 156/156 · 部署校验 16/16）](docs/08-交付前验收报告.md)
9. [安全自评报告](docs/09-安全自评报告.md)
10. [作品简介](docs/10-作品简介.md)
11. [GitHub 仓库描述（中英双版本）](docs/11-仓库描述.md)
