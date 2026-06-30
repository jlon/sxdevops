# AIOps 告警驱动闭环落地状态

更新时间：2026-06-30

本文记录 `docs/AIOps-告警驱动自治运维闭环设计.md` 的当前落地状态，避免后续重复开发同一能力。

## 阶段状态

| 阶段 | 状态 | 已落地能力 |
| --- | --- | --- |
| 阶段 1：Incident 聚合层 | 已完成 | Alert 写入后归并 Incident；Alert 详情可查看、启动调查、关联 Incident；Incident 列表支持核心过滤。 |
| 阶段 2：只读证据采集 | 已完成 | 自动创建 `incident.investigate` 任务；采集告警、指标、日志、Trace、K8s、事件、资源底座证据；失败不阻塞告警写入。 |
| 阶段 3：结构化根因假设 | 已完成 | 规则 RCA 保底；LLM RCA Planner 可基于压缩证据升级主假设；LLM 输出必须引用已有证据 ID，异常或越权输出回退规则结论。 |
| 阶段 4：处置建议、审批执行和验证 | 已完成 | 生成 `AIOpsIncidentAction`；写入 `AIOpsPendingAction`；确认后进入任务中心执行；Host/K8s 任务完成或后台异常都会回写验证状态、证据和事件。 |
| 阶段 5：复盘和沉淀 | 已完成 | 关闭或验证恢复后生成复盘知识；Incident 可生成 Skill 审批草案和 Runbook 草案；Runbook 关联复盘知识；详情时间线包含事件、证据、根因和动作。 |

## 最近提交

- `9c37b45 feat(aiops): enrich incident retrospective timeline`
- `81de269 feat(aiops): link incident runbooks to review knowledge`
- `a80a9ba fix(aiops): sync incident verification on worker failure`
- `baa789e feat(aiops): add llm rca planner fallback`
- `e730b16 feat(aiops): propose incident verification tasks`

## 验证

最近一次验证命令：

```bash
python manage.py test aiops.testcases.incident_runtime --verbosity=1
python manage.py test aiops.testcases.agent_execution ops.test_host_tasks --verbosity=1
python -m compileall aiops ops
python manage.py check
python manage.py makemigrations --check --dry-run aiops
```

验证结果：

- `aiops.testcases.incident_runtime`：41 tests OK。
- `aiops.testcases.agent_execution ops.test_host_tasks`：39 tests OK。
- `compileall aiops ops`：通过。
- `manage.py check`：通过。
- `makemigrations --check --dry-run aiops`：无迁移变更。

## 已知非本轮问题

- `python manage.py makemigrations --check --dry-run ops` 会提示 `ops` app 存在历史模型/迁移漂移；本轮没有改 `ops` 模型，未混入修复。
- 工作树仍有前端、HBase 文档和本地配置相关未提交文件，属于既有脏文件，本轮未纳入提交。

## 下一步建议

1. 做一次浏览器 E2E：Alertmanager HBase 告警进入系统 -> Alert 详情启动智能调查 -> Incident 详情查看证据/RCA/建议动作 -> 生成 Runbook/Skill 草案。
2. 单独处理 `ops` 迁移漂移，避免未来模型变更时混入大量无关 migration。
3. 基于真实 HBase 告警样本完善 HBase 专属 Skill 和 Runbook 模板。
