# AIOps 告警驱动自治运维闭环设计

本文基于 SxDevOps 当前实现，并参考 Robusta、StackStorm、Keep、Grafana OnCall 和 OpenClaw 的设计思想，重新评估“从告警产生到根因定位，再到处置和复盘”的智能运维闭环。

结论先行：之前“告警接入 -> Agent 取证 -> 根因定位 -> 生成处置动作 -> 审批执行 -> 验证复盘”的方向是对的，但还不是最优。最优形态不应该是 Agent 直接统管全流程，而应该是 **Incident-first 的平台工作流驱动 Agent**。平台负责告警归并、状态机、权限、审批、执行和审计；LLM 负责理解问题、生成假设、组织证据、匹配 SOP、解释风险和沉淀经验。

## 1. 开源项目对照

| 项目 | 可借鉴点 | 对 SxDevOps 的启发 | 不应照搬的点 |
| --- | --- | --- | --- |
| Robusta | 用 playbook 在 Prometheus/Kubernetes 告警触发后自动补充日志、图表、Runbook 和可能处置建议。 | 告警进来后先做只读增强和上下文取证，再让 Agent 基于证据分析。 | 不应只做 Kubernetes 场景，也不应把所有排障逻辑写死成 YAML playbook。 |
| StackStorm | 典型事件驱动自动化模型：sensor/trigger -> rule -> action/workflow，并保留执行审计。 | 事件入口、规则匹配、动作执行和审计必须是平台确定性能力，不能交给 LLM 自由串联。 | 不应把 SxDevOps 改造成通用 SOAR/自动化引擎，现阶段只做 AIOps 所需最小闭环。 |
| Keep | 把告警管理、降噪、拓扑相关、workflow 和 provider 连接起来，支持把相关告警归并为 incident。 | SxDevOps 需要 Incident 聚合层，不能让每条 Alert 都单独触发一次孤立分析。 | 不应先追求复杂 AI 相关和多租户 provider 市场，先把现有告警、指标、日志、Trace、事件、任务串起来。 |
| Grafana OnCall | 关注告警分组、路由、升级、认领和自动恢复，与 Alertmanager 分组机制对齐。 | 告警到达后应该先确定归属、分组、负责人和升级策略，再进入智能分析。 | Grafana OnCall OSS 已在 2026-03-24 归档，新方案只借鉴路由和升级思想，不依赖其实现。 |
| OpenClaw | local-first gateway、会话隔离、多 agent 路由、first-class tools、skills、权限和 session 状态。 | SxDevOps 应保留多 Agent、Skill、MCP、权限审批和会话上下文，但不能用硬分类器限制 LLM 的工具选择。 | OpenClaw 是通用 Agent 平台，不是 AIOps 领域模型；SxDevOps 仍需要 Incident、告警、拓扑、任务中心这些运维实体。 |

核心共识：

1. 告警进入系统后，第一步不是“问 LLM 怎么办”，而是归并、关联、补上下文。
2. 自动化执行必须由确定性平台工作流承载，LLM 不能直接越过权限和审计执行命令。
3. LLM 最适合做证据解释、根因假设、方案比较、Runbook 匹配和复盘总结。
4. 高风险操作必须有审批、预检、回滚方案和执行后验证。
5. 经验沉淀应回到 Skill、Runbook、告警规则、拓扑和知识环境，而不是只留在聊天记录里。

## 2. 当前 SxDevOps 基础

当前项目已经具备闭环所需的大部分底座：

| 能力 | 已有实现 | 价值 |
| --- | --- | --- |
| 告警接入 | `Alert`、`AlertIntegration`、Webhook 接入、Alertmanager 字段归一化。 | 可以承接外部监控系统告警。 |
| 告警治理 | 接收人、接收组、聚合规则、抑制规则、静默规则、升级策略、通知规则。 | 可以支撑告警路由和降噪。 |
| Agent 配置 | `AIOpsAgentProfile` 支持默认 Agent、模型、Skill、MCP、工具策略、执行策略、默认知识环境。 | 可以支撑多 Agent 和环境绑定。 |
| 工具体系 | 内置 MCP 工具、外部 MCP、Skill、Action Handler、工具调用审计。 | 可以把平台能力暴露给 LLM。 |
| 证据能力 | 告警、指标、日志、Trace、K8s、任务中心、事件中心、知识图谱等工具。 | 可以形成根因分析证据链。 |
| 执行边界 | `AIOpsPendingAction`、任务中心、HostTask、RBAC、确认并执行。 | 可以支撑安全处置和审计。 |
| 异步任务 | `AIOpsExternalTask` 有状态、计划步骤、结果、错误信息。 | 可以承接告警触发后的后台分析任务。 |

主要缺口：

1. 缺少 Incident 作为告警、证据、根因、动作和复盘的聚合根。
2. 告警接入后没有自动进入只读调查任务。
3. 当前聊天链路强，告警驱动链路弱，容易变成“用户问了才查”。
4. 根因结论还偏文本，没有结构化假设、反证、置信度和缺口。
5. 处置动作和执行后验证没有稳定绑定到同一个故障对象。
6. 复盘结果没有反哺 Skill、Runbook、抑制规则和拓扑。

## 3. 设计原则

1. **Incident-first**：Alert 是信号，Incident 是工作对象。所有分析、动作、验证和复盘都围绕 Incident。
2. **只读自动，写入审批**：告警触发后的自动分析只允许只读工具；写入、重启、扩缩容、发布回滚等动作必须进入审批或预授权策略。
3. **平台编排，LLM 推理**：平台决定状态流转、工具边界、权限、预算和审计；LLM 在受控输入内做推理和总结。
4. **证据先于结论**：根因必须绑定证据和反证。证据不足时输出缺口，而不是编造结论。
5. **动作必须可验证**：每个处置动作都要有前置条件、风险、回滚方式和验证计划。
6. **经验可沉淀**：复盘必须能转化为 Skill、Runbook、告警规则、静默规则、拓扑关系或知识环境配置建议。
7. **保持 KISS**：优先复用 Alert、EventRecord、AIOpsExternalTask、AIOpsPendingAction、HostTask，不新造大而全工作流引擎。

## 4. 目标闭环

### 4.1 告警进入

```text
Alertmanager / Zabbix / 夜莺 / 通用 Webhook
-> AlertIntegration 校验 token 和签名
-> normalize_alert_payload 归一化字段
-> upsert_alert 写入或更新 Alert
-> IncidentIntakeService 归并到 Incident
```

归并依据按优先级使用：

1. `fingerprint`
2. `group_key`
3. `environment + cluster + namespace + service + resource + metric_name + title`
4. 拓扑关系和时间窗口

同一个时间窗口内，同一服务或同一依赖链路上的相关 Alert 应进入同一个 Incident。这样可以避免告警风暴时为每条告警重复启动 Agent。

### 4.2 自动只读调查

Incident 创建或严重程度升级后，平台创建一个 `AIOpsExternalTask`：

```text
Incident created
-> create AIOpsExternalTask(action_code=incident.investigate)
-> InvestigationOrchestrator 生成只读取证计划
-> 执行证据采集工具
-> 写入 IncidentEvidence
-> 调用 LLM 生成根因假设
-> 写入 IncidentHypothesis
-> 返回摘要给告警中心和智能助手
```

默认取证范围：

| 证据类型 | 来源 |
| --- | --- |
| 告警证据 | 当前 Alert、同组 Alert、近期恢复/活跃告警。 |
| 指标证据 | `query_alert_metrics`、服务 RED、K8s 运行态、节点资源。 |
| 日志证据 | 日志中心数据源，按服务、环境、时间窗口和错误模式查询。 |
| Trace 证据 | 慢调用、错误 Span、上下游依赖。 |
| K8s 证据 | Pod、Deployment、StatefulSet、Service、Event、重启、资源限制。 |
| 变更证据 | 事件中心、任务中心、工单系统、发布审批。 |
| 拓扑证据 | 知识环境、K8s 集群、服务依赖、任务资源底座。 |

自动取证必须有预算：

| 项 | 默认值 |
| --- | --- |
| 时间窗口 | 告警前后 60 分钟 |
| 指标查询 | 最多 8 条 PromQL |
| 日志查询 | 最多 5 个查询，每个 Top 20 摘要 |
| Trace 查询 | 最多 5 个服务/接口摘要 |
| K8s 查询 | 限定同环境、同集群、同 namespace |
| LLM 调用 | 默认 1 次假设生成，失败可回退代码摘要 |

### 4.3 根因假设

LLM 不直接输出“最终真相”，而是输出候选假设：

```json
{
  "title": "checkout-api 发布后 5xx 升高",
  "root_cause_type": "change_regression",
  "confidence": 0.72,
  "supporting_evidence": [12, 15, 18],
  "counter_evidence": [21],
  "missing_evidence": ["缺少 checkout-api 近 30 分钟错误日志样例"],
  "recommended_next_checks": ["补查错误日志", "检查最近发布工单"]
}
```

平台应展示：

1. 最可能根因。
2. 支持证据。
3. 反证。
4. 证据缺口。
5. 下一步只读检查。

当证据冲突或置信度低时，系统应自动补充只读检查，而不是直接生成重启或回滚动作。

### 4.4 处置建议

处置建议分三类：

| 类型 | 示例 | 处理方式 |
| --- | --- | --- |
| 继续调查 | 补查日志、补查 Trace、确认发布记录。 | 只读自动执行，可追加到同一 Incident。 |
| 低风险缓解 | 扩容副本、切流、临时调高限流阈值。 | 生成 PendingAction，满足预授权策略时可自动执行。 |
| 高风险修复 | 重启核心服务、回滚发布、执行批量命令、修改数据库。 | 必须人工确认，必须记录回滚和验证计划。 |

每个动作必须包含：

1. 目标资源：环境、集群、命名空间、服务、主机或工单。
2. 动作内容：命令、K8s patch、任务模板或 Runbook。
3. 风险等级：low、medium、high、critical。
4. 前置条件：例如确认当前副本数、确认有可用实例。
5. 回滚方式：例如恢复副本数、撤销 patch、回滚版本。
6. 验证计划：执行后重新查询哪些指标、日志、事件或任务结果。

### 4.5 审批和执行

执行仍然走现有 `AIOpsPendingAction` 和任务中心：

```text
RemediationProposal
-> AIOpsPendingAction(status=pending)
-> 用户确认或策略预授权
-> HostTask / K8s Task 创建
-> start_host_task / start_k8s_task
-> 结果回写 PendingAction、HostTask、EventRecord、IncidentAction
```

策略：

1. `read_only` Agent 永远不能生成执行动作。
2. `manual_confirm` Agent 可以生成 PendingAction，但不能跳过确认。
3. `full_auto` Agent 也不能无条件执行，必须同时满足用户 RBAC、Agent 策略、动作风险、目标范围和预授权规则。
4. `critical` 风险动作永远需要人工确认。
5. 所有执行类动作必须进入任务中心，即使是 full-auto，任务中心也作为审计系统。

### 4.6 执行后验证

动作完成后，平台自动启动验证：

```text
HostTask completed
-> VerificationWorker 读取 action.verification_plan
-> 重新查询告警状态、核心指标、日志错误率、K8s 状态
-> 更新 IncidentAction.verification_status
-> 决定 Incident 状态
```

验证结果：

| 状态 | 含义 |
| --- | --- |
| `verified_resolved` | 告警恢复，关键指标回落，无明显错误。 |
| `partially_improved` | 指标好转但未完全恢复，需要继续观察。 |
| `no_improvement` | 执行无明显效果，应回滚或升级。 |
| `verification_failed` | 验证工具失败，不能判断结果。 |

### 4.7 复盘和沉淀

Incident 关闭后生成复盘摘要：

1. 影响范围。
2. 时间线。
3. 根因和证据。
4. 已执行动作和验证结果。
5. 未解决风险。
6. 可沉淀项。

可沉淀项包括：

| 类型 | 示例 |
| --- | --- |
| Skill | “HBase RegionServer GC 告警排障 Skill”。 |
| Runbook | “HBase RegionServer 重启和验证 Runbook”。 |
| 告警规则 | 调整阈值、补充标签、添加 runbook_url。 |
| 抑制/静默规则 | 对已知维护窗口抑制噪音。 |
| 知识环境 | 绑定 HBase 集群、namespace、指标源、日志源、任务资源。 |
| 拓扑关系 | 补充 HBase 与 ZooKeeper、HDFS、业务服务的依赖关系。 |

## 5. 数据模型设计

### 5.1 AIOpsIncident

Incident 是故障工作对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | char | Incident 标题。 |
| `status` | enum | `open`、`investigating`、`mitigating`、`verifying`、`resolved`、`closed`。 |
| `severity` | enum | `critical`、`warning`、`info`。 |
| `source_type` | char | 来源类型，例如 `alert`、`manual`。 |
| `dedupe_key` | char | 归并键。 |
| `environment` | char | 环境。 |
| `cluster` | char | 集群。 |
| `namespace` | char | 命名空间。 |
| `service` | char | 服务。 |
| `resource_type` | char | 资源类型。 |
| `resource` | char | 资源标识。 |
| `impact_summary` | text | 影响摘要。 |
| `current_hypothesis_id` | bigint | 当前主假设。 |
| `owner` | char | 负责人或认领人。 |
| `started_at` | datetime | 首次触发时间。 |
| `detected_at` | datetime | 平台检测时间。 |
| `resolved_at` | datetime | 恢复时间。 |
| `closed_at` | datetime | 关闭时间。 |
| `metadata` | json | 扩展字段。 |

索引建议：

1. `status + severity`
2. `dedupe_key`
3. `environment + service`
4. `cluster + namespace`
5. `started_at`

### 5.2 AIOpsIncidentAlert

连接 Incident 和 Alert。

| 字段 | 说明 |
| --- | --- |
| `incident_id` | Incident。 |
| `alert_id` | Alert。 |
| `role` | `primary`、`related`、`symptom`、`resolved_signal`。 |
| `linked_reason` | 关联原因。 |

### 5.3 AIOpsIncidentEvidence

保存结构化证据摘要，避免把原始大日志塞进 LLM 上下文。

| 字段 | 说明 |
| --- | --- |
| `incident_id` | Incident。 |
| `kind` | `alert`、`metric`、`log`、`trace`、`k8s`、`change`、`task`、`topology`。 |
| `source` | 数据源或工具名。 |
| `tool_invocation_id` | 对应 `AIOpsToolInvocation`。 |
| `scope` | 环境、集群、namespace、服务等范围。 |
| `window_start` / `window_end` | 时间窗口。 |
| `summary` | 给人和 LLM 使用的摘要。 |
| `payload` | 结构化结果。 |
| `weight` | `strong`、`medium`、`weak`、`counter`。 |
| `collected_at` | 采集时间。 |

### 5.4 AIOpsIncidentHypothesis

保存根因候选。

| 字段 | 说明 |
| --- | --- |
| `incident_id` | Incident。 |
| `title` | 假设标题。 |
| `root_cause_type` | `change_regression`、`resource_saturation`、`dependency_failure`、`config_error`、`capacity`、`unknown`。 |
| `confidence` | 0 到 1。 |
| `supporting_evidence_ids` | 支持证据。 |
| `counter_evidence_ids` | 反证。 |
| `missing_evidence` | 证据缺口。 |
| `recommended_next_checks` | 下一步检查。 |
| `status` | `candidate`、`primary`、`rejected`、`confirmed`。 |

### 5.5 AIOpsIncidentAction

连接假设、待确认动作、任务和验证结果。

| 字段 | 说明 |
| --- | --- |
| `incident_id` | Incident。 |
| `hypothesis_id` | 对应根因假设。 |
| `pending_action_id` | 对应 `AIOpsPendingAction`。 |
| `host_task_id` | 对应任务中心任务。 |
| `action_type` | `investigate`、`mitigate`、`fix`、`rollback`、`verify`。 |
| `risk_level` | 风险等级。 |
| `status` | `proposed`、`approved`、`running`、`completed`、`failed`、`canceled`。 |
| `preconditions` | 前置条件。 |
| `rollback_plan` | 回滚计划。 |
| `verification_plan` | 验证计划。 |
| `verification_status` | 验证状态。 |
| `result_summary` | 执行结果摘要。 |

### 5.6 时间线

不建议第一阶段新增独立 timeline 表。优先复用 `EventRecord`：

1. Incident 创建。
2. Alert 关联。
3. 取证任务开始/结束。
4. 假设生成。
5. 待确认动作生成。
6. 用户确认。
7. 任务执行开始/结束。
8. 验证结果。
9. Incident 关闭。

如果后续 `EventRecord` 不能满足查询性能或展示需求，再抽出 `AIOpsIncidentTimeline`。

## 6. 运行时架构

```text
Alert Webhook
  -> Alerting Service
  -> Incident Intake Service
  -> Investigation Orchestrator
  -> Evidence Collectors
  -> RCA Planner
  -> Remediation Planner
  -> PendingAction / HostTask
  -> Verification Worker
  -> Retrospective Writer
```

### 6.1 Incident Intake Service

职责：

1. 解析 Alert 归并键。
2. 创建或更新 Incident。
3. 关联主告警和相关告警。
4. 判断是否需要启动调查任务。
5. 写入事件中心。

### 6.2 Investigation Orchestrator

职责：

1. 根据 Incident 范围选择 Agent、知识环境和工具。
2. 生成只读取证计划。
3. 调用 Evidence Collector。
4. 控制预算、超时和失败兜底。
5. 调用 RCA Planner。

这里不需要复杂 DAG。第一阶段用固定阶段即可：

```text
alerts -> metrics -> logs -> traces -> k8s -> changes -> topology -> rca
```

### 6.3 Evidence Collectors

每类证据一个 collector，内部复用现有工具：

| Collector | 复用能力 |
| --- | --- |
| AlertEvidenceCollector | `query_alerts`、Alert ORM。 |
| MetricEvidenceCollector | `query_alert_metrics`。 |
| LogEvidenceCollector | `query_logs`。 |
| TraceEvidenceCollector | `query_traces`。 |
| K8sEvidenceCollector | `query_k8s_cluster_summary`、`query_k8s_resources`。 |
| ChangeEvidenceCollector | `query_event_wall`、工单、任务中心。 |
| TopologyEvidenceCollector | 知识环境、资源上下文、知识图谱。 |

Collector 输出统一写入 `AIOpsIncidentEvidence`。

### 6.4 RCA Planner

职责：

1. 读取 Incident 和 Evidence 摘要。
2. 调用 LLM 生成候选假设。
3. 强制要求证据 ID、反证、缺口和置信度。
4. 低质量输出回退到规则摘要。
5. 将结果写入 `AIOpsIncidentHypothesis`。

RCA Prompt 只注入当前 Incident 的压缩证据，不注入全量会话历史，避免慢和贵。

### 6.5 Remediation Planner

职责：

1. 根据主假设匹配 Skill、Runbook 和 Action。
2. 生成处置建议，不直接执行。
3. 对动作做风险分类。
4. 生成前置条件、回滚和验证计划。
5. 写入 `AIOpsIncidentAction` 和 `AIOpsPendingAction`。

### 6.6 Verification Worker

职责：

1. 监听任务完成事件。
2. 根据验证计划重新采集最小证据。
3. 判断恢复、改善、无效或无法验证。
4. 更新 Incident 状态。
5. 必要时建议回滚或升级。

### 6.7 Retrospective Writer

职责：

1. 生成复盘摘要。
2. 给出可沉淀建议。
3. 如果用户确认，将建议转为 Skill/Runbook 草案或配置变更草案。

## 7. Agent、Skill、MCP、Action 的位置

| 概念 | 定位 | 在闭环中的作用 |
| --- | --- | --- |
| Agent | 角色和运行策略。 | 决定模型、知识环境、默认 Skill、可用 MCP、执行策略和权限边界。 |
| MCP | 工具协议和数据入口。 | 把告警、指标、日志、Trace、K8s、任务、事件等能力提供给 Agent。 |
| Skill | 领域方法和输出约束。 | 约束如何调查 HBase、K8s、数据库、网络等问题，以及如何输出证据和建议。 |
| Action | 平台动作语义。 | 表示“告警根因分析”“K8s 诊断”“生成任务”“自愈建议”等可治理流程。 |
| Incident | 运维工作对象。 | 承载告警、证据、假设、动作、验证和复盘。 |

关键调整：

1. Action Router 只能给候选 Action 和风险策略，不能把 LLM 锁死在单一工具集合。
2. Skill 采用按需注入，优先按 Incident 类型、服务标签、告警名、用户问题和 Agent 配置触发。
3. MCP 工具仍由后端注册表、用户 RBAC、Agent 策略和 Action 风险共同过滤。
4. Agent 不是 Incident 的替代物。不同 Agent 可以参与同一个 Incident，但 Incident 是事实和状态的中心。

## 8. UI 设计

新增或增强“Incident 工作台”：

1. 顶部：标题、严重级别、状态、影响范围、负责人、持续时间。
2. 左侧：时间线，展示告警、取证、假设、动作、验证和复盘。
3. 中间：证据板，按告警、指标、日志、Trace、K8s、变更、拓扑分组。
4. 右侧：根因假设卡，展示置信度、支持证据、反证和缺口。
5. 底部：处置方案，展示风险、前置条件、回滚、验证计划和确认按钮。
6. 聊天入口：绑定当前 Incident、Agent 和知识环境，用户追问时自动带上 Incident 上下文。

告警中心中的 Alert 详情页应提供：

1. “查看 Incident”。
2. “启动智能调查”。
3. “关联已有 Incident”。
4. “标记为噪音/抑制建议”。

智能助手中的体验：

1. 选择 Agent 后不应该强制新建会话，除非用户主动新会话。
2. 如果 Agent 绑定默认知识环境，用户不需要重复选择环境。
3. 在 Incident 上下文中聊天时，问题默认围绕当前 Incident，不要求用户重复描述集群、服务和时间窗口。

## 9. 权限和安全

权限边界：

| 能力 | 所需权限 |
| --- | --- |
| 查看 Incident | `aiops.incident.view` |
| 手动创建/编辑 Incident | `aiops.incident.manage` |
| 启动只读调查 | `aiops.incident.investigate` |
| 查看证据 | 对应数据域权限，例如 `ops.alert.view`、`ops.metric.query`、日志权限。 |
| 生成处置建议 | `aiops.task.generate` |
| 确认处置动作 | `aiops.task.execute` 加目标领域执行权限。 |
| Full-auto | `aiops.agent.full_execute` 加目标领域执行权限，加 Agent 策略允许。 |
| 关闭 Incident | `aiops.incident.close` |
| 沉淀 Skill/Runbook | `aiops.skill.manage` 或对应 Runbook 权限。 |

安全规则：

1. 所有写入动作必须生成 `AIOpsPendingAction`。
2. 所有执行动作必须进入任务中心。
3. Full-auto 只跳过交互确认，不跳过任务中心、RBAC、风险策略和审计。
4. LLM 输出的命令必须经过后端参数清洗和危险命令检测。
5. 高危动作必须有回滚和验证计划，否则不能进入确认。
6. 只读调查不得读取超出 Incident 作用域的数据源。

## 10. 分阶段落地

### 阶段 1：Incident 聚合层

目标：

1. 新增 `AIOpsIncident`、`AIOpsIncidentAlert`。
2. Alert webhook 写入后自动归并 Incident。
3. Alert 详情页能看到关联 Incident。
4. Incident 列表支持状态、严重级别、环境、服务、集群过滤。

验收：

1. 同一 Alertmanager group 下多条告警归并到同一个 Incident。
2. 同一 fingerprint 的重复告警更新已有 Incident。
3. 告警恢复后 Incident 能标记为待验证或已恢复。

### 阶段 2：只读调查任务

目标：

1. 新增 `AIOpsIncidentEvidence`。
2. Incident 创建后自动创建 `AIOpsExternalTask(action_code=incident.investigate)`。
3. 复用现有工具采集告警、指标、日志、K8s、变更证据。
4. 结果写入证据板。

验收：

1. Alertmanager 推送 HBase 告警后，系统自动生成证据摘要。
2. 证据采集失败不会阻塞告警写入。
3. 每次工具调用都有审计记录和耗时。

### 阶段 3：结构化根因假设

目标：

1. 新增 `AIOpsIncidentHypothesis`。
2. RCA Planner 根据证据生成候选根因。
3. 前端展示支持证据、反证、缺口和置信度。
4. 聊天追问自动引用当前 Incident 和主假设。

验收：

1. LLM 不能输出没有证据 ID 的根因。
2. 证据不足时能输出缺口和下一步只读检查。
3. 用户追问“为什么这么判断”时能回到同一 Incident 的证据。

### 阶段 4：处置建议、审批执行和验证

目标：

1. 新增 `AIOpsIncidentAction`。
2. Remediation Planner 生成处置建议。
3. 写入 `AIOpsPendingAction`，确认后进入任务中心执行。
4. Verification Worker 执行后验证。

验收：

1. 高风险动作必须确认。
2. 任务中心记录来源 Incident、Agent、PendingAction。
3. 执行后自动查询告警和指标，更新验证状态。
4. 无改善时提示回滚或升级。

### 阶段 5：复盘和沉淀

目标：

1. 关闭 Incident 时生成复盘报告。
2. 支持把复盘建议转为 Skill/Runbook 草案。
3. 支持把噪音类告警转为抑制/静默建议。
4. 支持补充知识环境和拓扑关系建议。

验收：

1. 每个关闭的 Incident 有完整时间线。
2. 可从 Incident 一键生成 Skill 草案。
3. 复盘报告能引用证据和动作结果。

## 11. HBase 示例流程

告警：

```text
alertname=HBaseRegionServerDown
severity=critical
cluster=hbase-local
namespace=hbase
service=hbase-regionserver
```

系统流程：

1. Alertmanager Webhook 推送到 SxDevOps。
2. `Alert` 写入，按 `cluster + namespace + service + alertname` 创建 Incident。
3. 平台自动启动只读调查。
4. 采集 HBase RegionServer Pod、StatefulSet、Service、K8s Event、CPU/Memory、重启次数、日志错误摘要。
5. 关联 ZooKeeper、HDFS 和最近任务/变更。
6. RCA Planner 输出候选：
   - RegionServer Pod CrashLoopBackOff，支持证据为 K8s Event 和日志。
   - 节点内存压力导致 OOMKilled，支持证据为内存指标和 Pod last_state。
   - HDFS/ZooKeeper 依赖异常，证据不足，需要补查。
7. 系统建议：
   - 先补查 RegionServer 最近 200 行错误日志。
   - 如确认 OOM，可生成调高资源限制或重启 Pod 的任务草案。
8. 用户确认后，任务中心执行。
9. 执行后验证 RegionServer ready、告警恢复、读写延迟回落。
10. 关闭 Incident，生成 HBase 故障复盘和 Skill 沉淀建议。

## 12. 为什么这是当前更优方案

1. 它保留 SxDevOps 的优势：告警、可观测性、任务中心、事件中心、RBAC、Agent 已经在一个平台内。
2. 它吸收开源项目共识：告警先归并和增强，动作由确定性工作流执行，LLM 不越权。
3. 它避免硬分类器问题：Action Router 只做策略提示，不限制 LLM 使用相关工具。
4. 它解决慢的问题：告警触发时后台预取证，用户打开时已有证据，不需要每次聊天重新全量调查。
5. 它解决失忆问题：Incident 承载长期上下文，聊天会话只是一种交互入口。
6. 它可渐进落地：先加 Incident 和只读取证，再做 RCA、动作、验证和复盘，不需要一次重写 Agent。

## 13. 暂不做

1. 不做通用 SOAR 编排器。
2. 不做任意 YAML workflow 执行。
3. 不做无边界自动修复。
4. 不做全量日志和时序数据入库。
5. 不让 LLM 直接执行 shell、kubectl 或数据库写入。
6. 不在第一阶段引入复杂多 Agent 协作协议。

## 14. 参考来源

- Robusta Playbooks: https://docs.robusta.dev/improve_holmes_docs/playbook-reference/what-are-playbooks.html
- Robusta Prometheus Alert Enrichment: https://docs.robusta.dev/master/user-guide/alerts.html
- StackStorm Overview: https://docs.stackstorm.com/overview.html
- StackStorm Sensors and Triggers: https://docs.stackstorm.com/sensors.html
- StackStorm Rules: https://docs.stackstorm.com/rules.html
- Keep Introduction: https://docs.keephq.dev/overview/introduction
- Keep Service Topology: https://docs.keephq.dev/overview/servicetopology
- Keep Topology Correlation: https://docs.keephq.dev/overview/correlation-topology
- Grafana OnCall Integrations: https://grafana.com/docs/oncall/latest/configure/integrations/
- Grafana OnCall Alertmanager Integration: https://grafana.com/docs/oncall/latest/configure/integrations/references/alertmanager/
- Grafana OnCall Escalation Chains and Routes: https://grafana.com/docs/oncall/latest/configure/escalation-chains-and-routes/
- OpenClaw Gateway Configuration: https://docs.openclaw.ai/gateway/configuration
- OpenClaw Skills: https://docs.openclaw.ai/tools/skills
- OpenClaw 本地源码也已作为补充参考，重点查看 gateway、sessions、tools、skills、permissions 和 multi-agent routing。
