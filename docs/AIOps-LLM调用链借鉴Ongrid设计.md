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

## 后续优先级

1. **P0：Incident 调查专用 orchestrator 深化**
   - 已完成严重级别 gate、全局并发上限、skipped 状态审计、协作式超时和局部结论 salvage。
   - 后续可继续补更细的 UI 展示和历史调查对比。

2. **P1：Reviewer Agent**
   - 对高风险 Action 生成独立二审结果，而不是只依赖确认按钮和权限判断。
   - Reviewer 只读、默认 reject，结果写回待审批动作。

3. **P1：RCA 报告结构化二阶段**
   - 当前有 `generate_incident_llm_root_cause` 结构化假设。后续可增加报告抽取层，把自然语言 RCA 映射为根因、因果链、证据、建议动作、置信度。

4. **P2：通用聊天 MaxStep salvage**
   - Incident 调查已支持超预算局部结论。后续可对通用聊天保存更完整 transcript，超预算时生成低置信局部结论，而不是只报失败。

## 边界

不直接照搬 Ongrid 的 Go runtime、worker 生命周期或模型路由实现。SxDevOps 保持 Django 当前结构，优先在现有 Agent/MCP/Skill/Action 模型上增加深度较高的小模块，避免一次性重写。
