# AIOps LLM 调用链借鉴 Ongrid 设计

更新时间：2026-07-01

参考源码：`https://github.com/ongridio/ongrid`，本地校验目录 `/mnt/data/ongridio-ongrid`，HEAD `b1385c9a7d5eda4df9df950433c54432589c2344`。

## Ongrid 值得吸收的调用链思想

1. **Orchestrator 与 Worker 分层**
   - 告警进入后不直接阻塞告警链路，而是由 investigator usecase 做启用开关、严重级别、去重、并发、超时等 gate。
   - 真正的根因分析交给 `incident-investigator` worker，worker 只负责只读诊断和输出报告。

2. **LLM 自由度放在有边界的 ReAct 内**
   - Worker 可以自主选择工具和上溯路径，但 prompt 和运行时同时限制工具预算。
   - 同一工具失败或空结果达到阈值后必须换方向或收敛，不允许反复改表达式空转。

3. **安全角色独立**
   - 只读 investigator 禁止执行变更工具。
   - mutating/destructive 操作由 reviewer worker 做二审，默认拒绝，approve 必须满足 SOP、目标状态、无并行操作、可回滚。

4. **结构化二阶段提取**
   - Worker 先给可读 RCA 报告。
   - 再用一次短 LLM 调用抽取 `root_cause`、影响窗口、证据、建议动作、置信度；失败时回退到可读报告。

5. **失败可恢复**
   - 自动调查失败不影响告警入库。
   - Worker 超出 MaxStep 时尝试从已保存 transcript 中 salvage 局部结论。

## SxDevOps 当前对应状态

SxDevOps 已经具备 Agent、MCP、Skill、Action、权限审批、任务中心审计、Incident 证据/RCA/建议动作等骨架；但通用聊天运行时仍主要集中在 `aiops.services._dispatch_with_tool_runtime`，之前的约束更多写在 prompt 和路由规则里。

本轮先吸收 Ongrid 的最低风险核心：**工具预算策略下沉到后端运行时**。这保留 LLM 自主选择工具的能力，但由后端统一拦截重复同参调用、工具过度使用和连续空结果空转。

## 已落地

- 新增 `aiops.tool_runtime_policy.ToolRuntimeBudget`：
  - 本轮最多 10 次工具调用。
  - 同一工具最多 3 次。
  - 同一工具连续 2 次空结果或错误后停止该方向。
  - 相同工具 + 相同参数禁止重复调用。
- `_build_runtime_prompt` 注入工具预算提示，让模型先知道边界。
- `_dispatch_with_tool_runtime` 执行工具前做预算检查，执行后记录空结果状态。
- assistant 消息 metadata 写入 `tool_budget`，方便审计为什么某次工具调用被停止。
- Incident 只读调查调度增加 runtime gate：
  - 默认只自动调查 warning/critical，info 级 Incident 只入库并记录跳过原因。
  - 后台调查默认最多并发 2 个，超过上限时跳过本次调查并写入 Incident 元数据。
  - 跳过记录写入 `last_investigation`、`last_investigation_skip` 和 EventWall，避免前端误判为“正在调查”。
- Incident 只读调查增加协作式超时和局部结论：
  - 每个取证步骤前检查 `AIOPS_INCIDENT_INVESTIGATION_TIMEOUT_SECONDS`，达到预算后停止后续取证。
  - 已采集证据会继续生成低置信 RCA 和只读建议，任务结果标记 `partial=true`。
  - 局部结论只使用本轮已采集证据，不复用上一次调查的旧证据生成验证任务。
- 高风险 PendingAction 增加执行前 Reviewer Gate：
  - manual_confirm 的高风险/critical 动作和 full_auto 动作都必须先通过 reviewer。
  - 当前 reviewer 是后端规则型安全检查，不增加新的模型调用；它检查执行目标、执行后验证计划、回滚或幂等说明，以及明显危险命令模式。
  - reviewer 结果写入 `AIOpsPendingAction.result_payload.review`、授权快照和任务中心 `source_context.authorization.review`，前端可直接展示 `review_status`、`review_summary` 和 `review_required`。
  - 未通过 reviewer 的人工确认动作保持 pending；Full Auto 动作标记 failed，并保留 reviewer 审计结果。
- 默认 Agent 初始化修正：
  - 内置 `general` 会作为兜底存在。
  - 已有启用的自定义默认 Agent 时，`general` 不再抢占默认位。
  - 唯一默认 Agent 被停用时，`general` 会恢复为启用默认，避免聊天入口失去可用默认 Agent。
- RCA 报告结构化二阶段：
  - 只读调查结束后生成 `rca_report`，把 Incident、主根因、因果链、支持证据、证据缺口、建议补查和建议动作合成一个稳定结构。
  - 报告只引用当前调查证据包中的 evidence ID，不读取原始 payload，不扩大敏感数据暴露面。
  - 完整报告写入调查任务 `orchestration_state.rca_report`；摘要写入 `result_payload.rca_report` 和 Incident `metadata.last_rca_report`，详情 API 直接返回 `rca_report`。
  - 前端 Incident 工作台新增“RCA 调查报告”区域，先展示结论总览，再展示假设、处置方案和证据。
- 通用聊天预算收敛：
  - 当模型后续工具调用全部被预算策略拦截，且本轮已经采集到工具证据时，运行时立即基于已有证据生成局部结论。
  - 该路径不再追加规划轮次，也跳过二阶段 formatter，避免在已知不可继续的方向上继续消耗模型调用。
  - assistant metadata 写入 `runtime_stop_reason=tool_budget_stopped`、`partial_answer=true` 和 `formatter_skip_reason=tool_budget_stopped`，审计可解释为什么提前收敛。
- 通用聊天运行摘要：
  - assistant 消息 metadata 写入 `runtime_transcript`，把运行上下文、Action 决策、Skill 注入、工具调用、预算停止、回复整形和最终回复压缩为稳定摘要。
  - 审计会话 API 返回最新 assistant 消息的 `runtime_transcript`，审计页新增“运行摘要”面板，便于回看为什么得到当前回答。
  - 摘要只保存计数、状态和短文本，不保存原始 prompt 或完整工具 payload，避免把审计能力做成新的敏感数据出口。

## 后续优先级

1. **P0：Incident 调查专用 orchestrator 深化**
   - 已完成严重级别 gate、全局并发上限、skipped 状态审计、协作式超时和局部结论 salvage。
   - 后续可继续补更细的 UI 展示和历史调查对比。

2. **P1：Reviewer Agent**
   - 已完成第一阶段：后端规则型 reviewer gate 覆盖高风险人工确认和 Full Auto。
   - 后续再评估是否增加 LLM reviewer；前提是必须保留当前确定性规则作为硬拦截，避免把安全边界完全交给模型判断。

3. **P1：RCA 报告结构化二阶段**
   - 已完成第一阶段：基于当前证据包和主根因假设生成确定性结构化报告。
   - 后续如引入 LLM 报告润色，必须保留当前结构化报告作为事实边界，禁止模型新增未观测事实。

4. **P2：通用聊天 MaxStep salvage**
   - 已完成第一阶段：工具预算拦截后，如果已有工具证据，直接收敛为局部结论，并生成 `runtime_transcript` 摘要供审计页展示。
   - 后续可继续补跨轮对比和压缩轨迹，把同一问题的多轮调查串成更清晰的审计视图。

## 边界

不直接照搬 Ongrid 的 Go runtime、worker 生命周期或模型路由实现。SxDevOps 保持 Django 当前结构，优先在现有 Agent/MCP/Skill/Action 模型上增加深度较高的小模块，避免一次性重写。
