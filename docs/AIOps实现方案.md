# AIOps 智能助手实现方案

## 1. 实现原则

- 优先复用现有平台能力，不重新发明资源、告警、日志、链路与任务体系
- 第一阶段先做平台内智能入口，而不是通用 Agent 平台
- 所有工具调用都走后端受控服务层，前端不直接拼装越权查询
- 高风险动作必须二次确认并记录审计

## 2. 模块映射

- 资源查询：`cmdb`、`ops.host`、`multicloud`、`iac`
- 告警与证据：`ops.alert`、`ops.log`、`ops.observability`、`eventwall`
- 自动化执行：`ops.host-tasks`、`ops.host-task-templates`
- 权限控制：`rbac`

## 3. 前端页面

### 全局聊天浮窗

- 入口位置：`AppLayout.vue` 右下角
- 主要区域：
  - 顶部栏：标题、当前模型、新建会话、最小化
  - 消息区：用户消息、助手回答、引用卡片、动作卡片
  - 输入区：多行输入框、发送按钮、快捷问题

### 管理员配置页

- 路由：`/aiops/config`
- 页面结构：`hero + stats cards + runtime strip + tabs/content`
- Tabs：
  - 模型配置
  - 机器人策略
  - MCP
  - Skill
  - 执行安全
  - 审计概览

## 4. 后端 API

### 用户侧接口

- `GET /api/aiops/bootstrap/`
- `GET /api/aiops/sessions/`
- `POST /api/aiops/sessions/`
- `GET /api/aiops/sessions/{id}/messages/`
- `POST /api/aiops/sessions/{id}/messages/`
- `POST /api/aiops/actions/{id}/confirm/`
- `POST /api/aiops/actions/{id}/cancel/`

### 管理员接口

- `GET /api/aiops/admin/config/`
- `PUT /api/aiops/admin/config/`
- `POST /api/aiops/admin/config/test_model/`
- `GET /api/aiops/admin/mcp-servers/`
- `POST /api/aiops/admin/mcp-servers/`
- `PUT /api/aiops/admin/mcp-servers/{id}/`
- `DELETE /api/aiops/admin/mcp-servers/{id}/`
- `POST /api/aiops/admin/mcp-servers/{id}/test/`
- `GET /api/aiops/admin/skills/`
- `POST /api/aiops/admin/skills/`
- `PUT /api/aiops/admin/skills/{id}/`
- `DELETE /api/aiops/admin/skills/{id}/`
- `GET /api/aiops/admin/audit/overview/`

## 5. 数据模型

- `AIOpsModelProvider`
- `AIOpsAgentConfig`
- `AIOpsChatSession`
- `AIOpsChatMessage`
- `AIOpsPendingAction`
- `AIOpsToolInvocation`
- `AIOpsMCPServer`
- `AIOpsSkill`

## 6. 工具层

第一阶段实现 6 个工具：

- `query_resources`
- `query_alerts`
- `query_events`
- `query_traces`
- `query_logs`
- `generate_host_task`
- `execute_host_task`

## 7. 编排流程

### 问答类

1. 解析用户意图
2. 判断工具集合
3. 做权限过滤
4. 查询结构化数据
5. 组织回答并附证据

### 分析类

1. 查告警
2. 查事件
3. 查链路 / 日志
4. 查最近任务 / 部署 / 资源变更
5. 输出事实、推断和建议

### 执行类

1. 生成任务草稿
2. 展示目标、命令、风险
3. 用户确认
4. 真正执行
5. 回写结果和审计

## 8. 迭代顺序

1. 落地 aiops app、模型、迁移、RBAC
2. 实现基础 API 与聊天服务
3. 接入管理员配置页
4. 接入全局浮窗与前端 API
5. 增加任务草稿与确认执行
6. 构建验证与回归修正
