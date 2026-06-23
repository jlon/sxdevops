# AIOps Agent 权限审批与注册设计

本文定义 SxDevOps AIOps agent 的下一阶段改造方案。目标是把当前“全局智能体配置 + 待确认动作 + 任务草稿”升级为“默认通用 agent + 可注册 agent + 后端权限策略 + 单次授权/自动执行 + 任务中心审计”的闭环。

## 1. 结论

整体方向合理，但必须拆清四层边界：

1. **用户 RBAC** 决定用户能不能看、配置、生成、确认和执行。
2. **Agent 配置** 决定这个 agent 默认用什么模型、Skill、MCP、工具范围和执行模式。
3. **运行时授权** 决定本次写入或执行动作是否需要用户主动确认。
4. **任务中心审计** 记录真正落地的执行任务、来源 agent、授权人、风险、目标和结果。

不能把“full 权限”做成前端开关，也不能让 LLM 直接绕过任务中心执行命令。full 权限的含义应是：后端确认用户、agent、工具和动作都允许自动执行后，自动创建 `HostTask` 并启动；任务中心仍保留完整审计记录。

## 2. 当前实现评估

当前代码已经具备基础模块，但链路没有闭合：

| 模块 | 当前状态 | 问题 |
| --- | --- | --- |
| `AIOpsAgentConfig` | 只有全局默认配置 | 缺少多个 agent profile，无法注册不同 persona、工具范围和执行策略 |
| `AIOpsSkill` / `AIOpsMCPServer` | 已有 Skill 和 MCP 配置 | 主要按全局配置启用，缺少 agent 级绑定和能力边界 |
| `AIOpsPendingAction` | 已有待确认动作 | 目前确认后返回任务草稿，`materialized_in_task_center=false`，不是“确认并执行” |
| `HostTask` | 已有任务中心、风险等级、生命周期、AIOps 来源 | AIOps 确认链路没有直接复用任务中心创建并启动逻辑 |
| RBAC | 已有 `aiops.task.generate`、`aiops.task.execute`、`ops.task.execute`、`ops.host.execute` | 缺少 agent 注册、agent 使用、full-auto 执行的权限语义 |
| 前端确认按钮 | 文案是“确认载入” | 实际语义和目标语义不一致，应改为“确认载入并执行” |

`HostTaskViewSet.create()` 已经能创建任务后调用 `start_host_task()` 或 `start_k8s_task()`，所以 AIOps 不需要另造执行引擎。正确做法是把 AIOps 的确认和自动执行都收敛到任务中心记录。

## 3. AionUi 与 OpenClaw 参考

AionUi 的设计可借鉴三点：

1. **Agent registry 独立**：AionUi 通过 `/api/agents` 暴露可用 agent，通过 custom agent API 注册、编辑、启停本地 agent。SxDevOps 也应把 agent profile 作为一等配置，而不是把所有能力塞进全局 `AIOpsAgentConfig`。
2. **权限模式是运行时模式**：AionUi 有逐操作确认和 YOLO/Full-Auto。它不是替代用户权限的角色，而是在已有权限允许后决定是否弹确认卡片。SxDevOps 也应把 full-auto 建成“权限 + agent 策略 + 风险策略”的组合结果。
3. **Skill 是注入能力，不是执行权限**：AionUi 会按会话注入 Skill 和 MCP。Skill 告诉 agent 怎么做，不能绕过后端权限。SxDevOps 已有相同方向，应继续保持。

关于 OpenClaw：从 AionUi 的集成痕迹看，OpenClaw 是可选 agent backend/gateway，而不是业务问题分类器。它关注 agent 接入、会话、技能和权限请求。SxDevOps 的 Action Router 可以保留，但只能作为候选上下文和安全策略，不应把 LLM 锁死在一个硬分类里。上次“本地 HBase 集群查不到节点数”的问题，本质上就是路由/分类把问题提前缩窄，工具结果无法覆盖真实上下文。

## 4. 目标概念

### 4.1 Agent Profile

新增 agent profile 概念。每个 profile 至少包含：

| 字段 | 含义 |
| --- | --- |
| `name` / `slug` | 展示名和稳定标识 |
| `description` | agent 的用途说明 |
| `is_default` | 默认通用 agent |
| `is_builtin` | 平台内置，不允许删除 |
| `is_enabled` | 是否可被会话选择 |
| `provider` | 默认模型提供商，未设置时继承全局配置 |
| `system_prompt` / `welcome_message` | agent 自己的提示词和欢迎语 |
| `enabled_skill_ids` | agent 级 Skill 白名单 |
| `enabled_mcp_server_ids` | agent 级 MCP 白名单 |
| `tool_policy` | 可用工具、风险上限、是否允许写入/执行 |
| `execution_policy` | `manual_confirm` / `full_auto` / `read_only` 等默认运行策略 |
| `allowed_role_codes` | 可使用该 agent 的角色白名单，空表示只看 RBAC |
| `created_by` / `updated_by` | 审计字段 |

默认内置 agent：

- `slug=general`
- 名称：`通用运维 Agent`
- 默认启用
- 继承全局模型、Skill、MCP
- 默认 `manual_confirm`
- 允许只读分析和任务草稿生成

### 4.2 Agent Registry

Registry 负责：

1. 确保默认通用 agent 存在。
2. 返回当前用户可见、可用的 agent 列表。
3. 创建、更新、启停和删除自定义 agent。
4. 在 bootstrap 中返回默认 agent、可选 agent 和运行时策略。
5. 在会话和消息 metadata 中记录 `agent_slug`、`agent_name` 和策略快照。

### 4.3 Action Router

Action Router 保留，但定位调整：

- 它给出候选 action、缺失上下文、风险边界和推荐 Skill。
- 它不能把 LLM 的工具选择锁死在一个业务分类里。
- 最终可用工具应由以下集合求交集：

```text
agent tool_policy
∩ selected/action recommended tools
∩ enabled Skill tool dependencies
∩ MCP 当前可用工具
∩ 用户 RBAC
∩ 后端工具风险策略
```

## 5. 权限模型

新增或明确以下权限：

| 权限 | 用途 |
| --- | --- |
| `aiops.agent.view` | 查看 agent registry |
| `aiops.agent.manage` | 注册、编辑、启停和删除 agent |
| `aiops.agent.run` | 使用非默认 agent |
| `aiops.agent.full_execute` | 允许 agent 在策略允许时跳过逐操作确认，自动落任务中心并执行 |
| `aiops.task.generate` | 生成待确认动作或任务草稿 |
| `aiops.task.execute` | 确认 AIOps 待执行动作 |
| `ops.task.execute` | 任务中心执行权限 |
| `ops.host.execute` | 主机任务执行权限 |
| `ops.k8s.manage` / `ops.k8s.exec` | K8s 管理和 Pod 命令执行权限 |

角色建议：

| 角色 | Agent 能力 |
| --- | --- |
| 平台管理员 | 全部权限，包括 full-auto |
| 运维管理员 | 使用 agent、生成任务、手动确认执行；是否 full-auto 由权限单独授予 |
| 研发工程师 | 只读分析和生成待确认动作，不能确认执行 |
| 只读访客 | 只读问答，不能生成动作 |
| 审计员 | 查看会话、动作和任务审计 |

权限检查顺序：

1. 用户是否可访问 AIOps。
2. 用户是否可使用所选 agent。
3. agent 是否启用，角色白名单是否允许。
4. 工具所需 RBAC 是否满足。
5. 动作风险是否超过 agent 策略上限。
6. 若是写入或执行动作，判断是否需要单次确认。
7. 若走 full-auto，检查 `aiops.agent.full_execute` 和对应领域执行权限。

## 6. 执行与审批流程

### 6.1 只读分析

只读工具可以直接执行，但必须记录工具调用审计：

```text
用户提问
-> 选择 agent
-> LLM 规划只读工具
-> 后端按 RBAC 执行工具
-> 返回事实、引用、回答
-> 记录工具调用和模型成本
```

### 6.2 有限权限：确认载入并执行

有限权限不是“无权限”。它表示用户具备执行权限，但 agent 不能自动执行重大操作。

```text
LLM 生成执行候选
-> 后端生成 AIOpsPendingAction(status=pending)
-> 前端显示“确认载入并执行”
-> 用户点击确认
-> 后端校验用户、agent、风险、RBAC 和动作归属
-> 创建 HostTask(trigger_source=aiops)
-> 写入 source_context: agent、pending_action、authorization
-> 调用任务中心执行器启动任务
-> 更新 PendingAction(status=executed, task_id=...)
-> 任务结果进入任务中心和事件审计
```

按钮文案必须改成“确认载入并执行”。如果已执行，按钮不应再显示“再次载入”，而应提供“查看任务”或“再次执行需重新生成”。

### 6.3 Full 权限：自动录入任务中心并执行

full-auto 只在后端同时满足以下条件时生效：

1. 用户有 `aiops.agent.full_execute`。
2. 用户有目标领域执行权限，例如 `ops.task.execute`、`ops.host.execute`、`ops.k8s.exec`。
3. agent 的 `execution_policy` 允许 full-auto。
4. 动作风险没有超过 agent 策略。
5. 目标、命令、集群、命名空间等关键字段已预检完整。

满足后流程为：

```text
LLM 生成执行候选
-> 后端创建 PendingAction(status=confirmed 或 executed, auto_authorized=true)
-> 后端创建 HostTask
-> 后端立即启动任务
-> PendingAction 写入 task_id 和授权快照
-> 任务中心成为执行审计系统
```

即使 full-auto，也不能直接执行 shell、kubectl 或外部命令。所有实际执行必须先落 `HostTask`。

### 6.4 高风险动作

建议保留一个全局安全阈值：

- `critical` 风险默认仍要求用户确认。
- 平台管理员可在 agent policy 中显式允许 `critical_full_auto`。
- critical 动作必须有回滚说明、目标快照、命令摘要和风险说明。

这样既支持 full 权限，又避免误把破坏性动作变成静默执行。

## 7. 数据与审计

### 7.1 PendingAction 结果字段

`result_payload` 应记录：

```json
{
  "task_id": 123,
  "task_name": "巡检 HBase RegionServer",
  "materialized_in_task_center": true,
  "execution_started": true,
  "authorization": {
    "mode": "manual_confirm",
    "confirmed_by": "demo",
    "confirmed_at": "2026-06-23T10:00:00Z",
    "agent_slug": "general",
    "risk_level": "high",
    "permissions_checked": ["aiops.task.execute", "ops.task.execute"]
  }
}
```

### 7.2 HostTask source_context

`HostTask.source_context` 应记录：

```json
{
  "source": "aiops",
  "session_id": 1,
  "message_id": 2,
  "pending_action_id": 3,
  "agent_slug": "general",
  "agent_name": "通用运维 Agent",
  "execution_policy": "manual_confirm",
  "authorization_mode": "manual_confirm",
  "request_summary": "检查 HBase 集群节点数",
  "risk_reason": "批量命令执行"
}
```

### 7.3 事件中心

每个关键节点记录事件：

- agent action 生成
- 用户确认或取消
- full-auto 自动授权
- 任务中心任务创建
- 任务启动
- 任务完成或失败

## 8. API 设计

新增 API：

| 方法 | 路径 | 权限 | 用途 |
| --- | --- | --- | --- |
| `GET` | `/api/aiops/admin/agents/` | `aiops.agent.view` | 查看 agent 列表 |
| `POST` | `/api/aiops/admin/agents/` | `aiops.agent.manage` | 注册 agent |
| `PATCH` | `/api/aiops/admin/agents/{id}/` | `aiops.agent.manage` | 更新 agent |
| `DELETE` | `/api/aiops/admin/agents/{id}/` | `aiops.agent.manage` | 删除自定义 agent |
| `POST` | `/api/aiops/admin/agents/{id}/set-default/` | `aiops.agent.manage` | 设置默认 agent |
| `GET` | `/api/aiops/bootstrap/` | `aiops.chat.view` | 返回默认 agent、可用 agent 和运行策略 |
| `POST` | `/api/aiops/chat/sessions/` | `aiops.chat.view` | 可传 `agent_id` 或 `agent_slug` |
| `POST` | `/api/aiops/actions/{id}/confirm/` | `aiops.task.execute` | 确认并立即执行 |

兼容策略：

- 未传 `agent_id` 时使用默认通用 agent。
- 旧 `AIOpsAgentConfig` 继续保存全局模型、欢迎语和默认开关。
- 旧前端未选择 agent 时不影响聊天。

## 9. 前端设计

### 9.1 智能体配置页

在 `AIOpsConfig.vue` 增加“Agent 列表”区域：

- 展示默认 agent、自定义 agent、启用状态、执行策略、Skill 数、MCP 数。
- 支持创建、编辑、启停、设为默认、删除自定义 agent。
- 内置默认 agent 可编辑策略，但不能删除。
- 执行策略显示：
  - 只读
  - 逐操作确认
  - Full Auto

### 9.2 聊天窗口

聊天窗口增加 agent 选择：

- 默认显示当前 agent 名称。
- 用户无 `aiops.agent.run` 时只能使用默认 agent。
- 切换 agent 后，新会话写入 agent 快照。
- 欢迎语和快捷问题来自所选 agent，未设置则继承全局配置。

### 9.3 确认卡片

确认卡片文案调整：

- pending：`确认载入并执行`
- executed 且有 `task_id`：`查看任务 #id`
- canceled：`已取消`
- failed：展示错误详情

## 10. 落地计划

按完整功能逐步提交：

1. **Agent Registry 后端与默认通用 agent**
   - 新增 `AIOpsAgentProfile` 模型、迁移、serializer、viewset。
   - bootstrap 返回默认 agent 和可用 agent。
   - RBAC 增加 agent 相关权限。
   - 提交后可通过 API 注册和查看 agent。

2. **Agent 管理前端**
   - AIOps 配置页增加 Agent 列表和编辑表单。
   - 前端 API wrapper 补齐。
   - 提交后平台管理员可在页面注册 agent。

3. **运行时 agent 选择**
   - 会话创建和发送消息支持 `agent_id/agent_slug`。
   - 调度层按 agent 选择模型、Skill、MCP 和工具策略。
   - 消息 metadata 记录 agent 快照。

4. **确认载入并执行**
   - 改造 `confirm_action()`，确认后创建并启动 `HostTask`。
   - 前端文案改为“确认载入并执行”。
   - PendingAction 写入 `task_id` 和授权快照。

5. **Full-auto 后端策略**
   - 增加权限策略服务。
   - 满足 full 权限和 agent 策略时自动创建并执行 `HostTask`。
   - critical 风险按全局阈值处理。

6. **审计与回看**
   - AIOps 审计页展示 agent、授权模式、任务 ID。
   - 任务中心详情展示 AIOps 来源和授权快照。

## 11. 验收标准

1. 系统启动或访问 bootstrap 时，默认通用 agent 自动存在。
2. 平台管理员可以注册、编辑、启停和删除自定义 agent。
3. 普通用户只能看到自己有权使用的 agent。
4. LLM 只读查询不需要确认，但工具调用进入审计。
5. 有限权限用户执行重大操作时必须点击“确认载入并执行”。
6. 确认后必须创建 `HostTask`，并立即通过任务中心执行器启动。
7. full 权限用户在 agent 策略允许时自动落 `HostTask` 并执行。
8. 所有执行都能从 PendingAction、HostTask、事件中心和 AIOps 审计追溯。
9. Action Router 不再把 LLM 工具选择锁死在单一业务分类里。

## 12. 风险与约束

- 不允许把 full-auto 做成前端隐藏按钮。后端必须二次校验。
- 不允许 LLM 直接执行 shell、kubectl、SQL 或外部 API。必须通过平台工具和任务中心。
- 不允许 Skill 携带密钥、kubeconfig、token 或生产凭据。
- 不允许把业务分类器作为唯一工具选择依据。分类只能提供候选 action 和安全边界。
- 不允许未落任务中心的后台执行。任务中心是执行审计事实源。
