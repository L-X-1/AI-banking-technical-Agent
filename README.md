# AI Banking Agent · 银行 AI 智能体

> 人工智能赛道参赛作品：通过自然语言对话理解用户金融意图，自主规划并在严格安全框架内执行银行业务操作，支持 APP / IM 多渠道接入。

## 系统组成

| 模块 | 目录 | 说明 |
|---|---|---|
| Mock Bank Core | `bank-core/` | 模拟银行核心系统，账户/交易/理财/卡片/订阅 REST API（FastAPI + SQLite） |
| Agent Service | `agent-service/` | Agent 核心（LangGraph）+ 会话网关 + 安全中间件 + 工具层（FastAPI + WebSocket） |
| Web App | `web-app/` | 聊天式银行 APP 前端（Vue 3 + Element Plus + ECharts） |
| 部署 | `deploy/` | docker-compose 一键部署 |
| 文档 | `docs/` | 赛题分析、系统详细设计、安全设计等 |
| 脚本 | `scripts/` | 种子数据、联调与演示脚本 |

## 文档导航

1. [赛题分析与开发方案](docs/01-赛题分析与开发方案.md)
2. [系统详细设计](docs/02-系统详细设计.md)
3. [模块接口与提示词设计](docs/03-模块接口与提示词设计.md)
4. [前端详细设计](docs/04-前端详细设计.md)
5. [里程碑验收标准与交付物](docs/05-验收标准与交付物.md)
6. [总体开发计划（场景整合·设计定调·一致性·里程碑）](docs/06-总体开发计划.md)

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

### 冒烟与回归

```bash
# IM 渠道降级实连冒烟（两服务在线时跑通确认卡文本降级 + 回执 + 审计回放）
python scripts/m3_im_smoke.py

# 单元/E2E（bank-core 与 agent-service 各自独立）
cd bank-core && python -m pytest tests -q        # 22 项
cd agent-service && python -m pytest tests -q    # 134 项（含渗透 66/66）

# 演示前重置（PowerShell：删库 → 重启两服务 → fresh seed）
Remove-Item bank-core/data/bank.db*, agent-service/data/agent.db*
```

本地开发启动方式见各子模块 README 与 `docs/02-系统详细设计.md` 第 13 章。
