# AgDevOps 运维与交付平台

AgDevOps 是一个基于 Django、Django REST framework、Channels、Vue 3 和 Element Plus 构建的一体化运维平台，覆盖 **CMDB、应用发布、容器运维、日志审计、Nginx 管理、告警中心** 与 **IaC 资源编排** 等核心场景。

它不只是一个传统 CRUD 后台，而是一个更偏 **企业级运维平台 / 平台工程 / 交付平台** 风格的全栈项目，适合用于：

- 企业内部统一运维门户
- 云资源治理与 CMDB 演示项目
- 企业发布平台与审批流演示环境
- DevOps / SRE / 平台工程方向的作品集项目

最新版本重点强化了三条主线能力：

- **应用发布平台化**：支持 `Docker 环境`、`K8s 集群`、审批流、灰度 / 批次发布、回滚、重新执行与 CMDB 自动关联
- **容器运维增强**：补齐 K8s 集群摘要、Pod Terminal、配置版本回滚、Docker 日志查看与镜像治理
- **平台治理完善**：强化 RBAC 权限模型、工具市场双部署模式、SQL 审计页内整合与 IaC 执行链路

> 如果你希望展示一个“有业务闭环、有运维深度、有产品化页面”的全栈项目，这个仓库会比普通管理后台更有说服力。

## 简历项目描述版

- **项目名称**：AgDevOps 运维与交付平台
- **项目定位**：面向企业内部的统一运维、发布与资源治理平台
- **技术栈**：Django / DRF / Channels / Vue 3 / Element Plus / Kubernetes Python Client / Terraform
- **核心能力**：CMDB、应用发布、审批流、K8s / Docker 运维、日志审计、IaC 资源编排
- **项目亮点**：实现自研应用的 Docker / K8s 双模式发布，支持审批流、回滚、重试、批次 / 灰度流程，并联动 CMDB 形成发布闭环

## 近期更新亮点

- 应用发布升级为企业发布平台风格，支持 `Docker 环境`、`K8s 集群`、审批流、灰度 / 批次发布、回滚、重新执行与 CMDB 自动关联
- K8s 集群页新增摘要卡片与运行提示，支持快速查看节点健康、异常 Pod、PVC Pending 与工作负载状态
- Pod 支持浏览器内交互式 Terminal，基于 WebSocket 直连容器 shell，并保留独立 `ops.k8s.exec` 权限
- ConfigMap / Secret 支持 YAML 预览、变更 diff、历史快照、最近回滚与指定版本回滚
- Docker 环境补齐容器日志查看、详情检查、悬空镜像清理与批量删除，便于日常治理与演示
- SQL 审计整合为页内 Tab 视图，支持 `MySQL`、`MongoDB`、`PolarDB`，并加强数据源、工单、查询等 RBAC 权限控制
- 工具市场支持 `Docker Compose 单机` 与 `Kubernetes` 双部署模式，可按模板直接选择主机或 K8s 集群发版

## 为什么这个项目适合展示

- **模块完整**：覆盖 CMDB、应用发布、K8s、Docker、日志、审计、IaC，不是单页 CRUD
- **链路完整**：从资源纳管、发布审批、状态回查到 CMDB 回写，形成闭环
- **后端有深度**：包含审批流、异步执行、SSH 远程操作、K8s API 调用与 CMDB 关系同步
- **前端有产品感**：多个核心页面已做产品化布局，适合直接演示
- **汇报友好**：既能讲平台价值，也能讲真实技术实现

## 产品导览

如果你准备把这个仓库展示给团队、客户或面试官，README 首页建议重点展示下面 4 个页面：

| 页面 | 建议截图内容 | 展示重点 |
| --- | --- | --- |
| 仪表盘 | 首页总览卡片、趋势图、告警摘要 | 体现平台化与可视化能力 |
| CMDB | 资源树、配置项列表、拓扑或资源详情 | 体现资源治理与资产沉淀能力 |
| 日志中心 / SQL 审计 | 查询条件、结果列表、审计记录、多引擎支持说明 | 体现运维排障与审计能力 |
| IaC 资源编排 | 方案列表、方案设计、配置预览、执行与同步CMDB | 体现交付自动化与基础设施编排能力 |

### 平台首页总览

![平台首页总览](docs/screenshots/dashboard.png)

平台首页总览：统一展示主机、发布、日志、告警等关键运营指标，体现平台首页的总览能力。

### CMDB 资产治理

![CMDB 资产治理](docs/screenshots/cmdb.png)

CMDB 资产治理：通过资源树、配置项、关系与成本视角实现资源沉淀，支撑后续发布与治理闭环。

### 日志与审计

![日志与审计](docs/screenshots/logs-or-sql.png)

日志与审计：支持日志检索、SQL / 数据库审计与问题排查，覆盖 `MySQL`、`MongoDB`、`PolarDB` 等典型场景。

### IaC 资源编排

![IaC 资源编排](docs/screenshots/iac-orchestration.png)

IaC 资源编排：按模块设计云资源，生成 Terraform 配置，并联动执行与同步 CMDB。

### README 首页截图说明文案

如果你后续补截图，建议直接按下面这套文案放在图片下方：

1. `平台首页总览`：统一展示主机、发布、日志、告警等关键运营指标
2. `CMDB 资产治理`：通过资源树、配置项、关系与成本视角实现资源沉淀
3. `日志与审计`：支持日志检索、SQL / 数据库审计与问题排查，覆盖 `MySQL`、`MongoDB`、`PolarDB`
4. `IaC 资源编排`：按模块设计云资源，生成 Terraform 配置并联动执行、同步 CMDB

### 推荐截图命名

如果你后续准备把截图正式放进仓库，建议统一放到 `docs/screenshots/`，命名如下：

- `docs/screenshots/dashboard.png`
- `docs/screenshots/cmdb.png`
- `docs/screenshots/logs-or-sql.png`
- `docs/screenshots/iac-orchestration.png`

## 核心能力

- 仪表盘：汇总主机、部署、日志、告警等关键指标
- 主机管理：主机纳管、连通性测试、WebShell 终端
- CMDB：CI 类型、配置项、资源树、资源拓扑、成本分析、资源申请
- 应用发布：自研应用发布单、审批流、Docker / K8s 双模式、灰度 / 批次、回滚、重新执行、CMDB 自动关联
- 容器管理：K8s 集群摘要、Pod Terminal、工作负载扩缩容、配置版本回滚、Docker 日志与镜像治理
- Nginx 管理：环境、证书、域名、路由与配置发布
- 日志中心：日志源管理、日志查询、收藏条件、趋势图
- SQL 审计：页内 Tab 式数据源、SQL 工单、只读查询，支持 `MySQL`、`MongoDB`、`PolarDB` 并加强 RBAC 审批与查询控制
- 工具市场：内置中间件模板市场，支持 Docker Compose 单机与 Kubernetes 双模式部署
- IaC 资源编排：按模块配置云资源，生成 Terraform 工程，支持执行记录与同步 CMDB

## 典型使用场景

- **企业内部运维门户**：统一承载资产、发布、日志、容器、告警与审计能力
- **平台工程演示项目**：展示应用发布、资源治理、审批流和 IaC 的完整能力
- **交付 / 售前演示环境**：通过真实页面快速说明平台化建设思路
- **求职作品集项目**：适合突出全栈工程能力、运维场景理解与产品化思维

## 应用发布

- 发布对象：面向公司自研应用，与工具市场的中间件 / 开源组件部署能力独立
- 发布模式：支持 `Docker 环境` 与 `K8s 集群`
- 发布流程：支持发布单创建、审批流、状态查看、重新执行、回滚与下线
- 发布策略：支持标准发布、灰度发布、批次发布
- CMDB 联动：发布后自动登记应用 CI、目标 CI，并建立 `runs_on` 关系

### 当前实现方式

- Docker 环境：后端通过 SSH 连接目标 Docker 环境，生成并上传 `docker-compose.yml`，执行 `docker-compose up -d`
- K8s 集群：后端读取 `kubeconfig`，动态构建 `Deployment / Service` 并调用 Kubernetes Python Client 下发到集群

### 相关文档

- 详细版：`docs/应用发布执行逻辑与时序图.md`
- 汇报版：`docs/应用发布执行逻辑-汇报版.md`

## 技术架构

- **后端**：`Django` + `Django REST framework` + `Channels`
- **前端**：`Vue 3` + `Pinia` + `Vue Router` + `Element Plus`
- **实时能力**：WebSocket 用于 Pod Terminal 等交互场景
- **执行能力**：SSH 远程执行、Docker Compose、Kubernetes Python Client、Terraform
- **数据存储**：默认本地开发使用 `SQLite`

## 适合怎么讲这个项目

如果你在面试、汇报或项目路演中介绍这个仓库，可以按下面的顺序展开：

1. **平台定位**：这是一个面向企业内部的统一运维与交付平台
2. **核心闭环**：CMDB 沉淀资源，应用发布执行变更，日志 / 审计负责排障，IaC 负责资源交付
3. **技术深度**：不是纯 CRUD，包含审批流、异步任务、K8s API、SSH 执行、CMDB 联动
4. **产品化能力**：多个核心页面具备可直接演示的布局与交互
5. **扩展空间**：可继续增强灰度流量控制、发布报表、自动回滚和实时日志流

## 工具市场双模式部署

- 部署模式：同一份服务模板可同时支持 `Docker Compose 单机` 与 `Kubernetes`
- Docker Compose：选择目标主机后，通过 SSH 上传 `docker-compose.yml` 并在远端执行
- Kubernetes：选择目标集群、命名空间、发布名称与副本数后，自动渲染 YAML 并下发资源
- 运维动作：两种模式都支持部署状态跟踪、日志查看、启动、停止和卸载
- 内置模板：执行 `python manage.py seed_templates` 后，内置 MySQL、Redis、PostgreSQL、MongoDB、Nginx、Jenkins、GitLab、Grafana、Elasticsearch、Loki、JumpServer、Nacos、XXL-Job，以及 Java / Python / Go / Node.js 运行环境，均可直接选择 K8s 部署

详细说明见 `docs/工具市场部署模式.md`

## 容器运维增强

### Kubernetes 集群操作台

- 集群级摘要：统一汇总节点、Pod、工作负载、PVC、ConfigMap、Secret 等核心指标，并给出运行提示
- Pod 运维：支持日志查看、资源 YAML、事件排查，以及基于 WebSocket 的浏览器内 Pod Terminal
- 工作负载操作：Deployment / StatefulSet 支持查看关联 Pod、在线扩缩容与状态回查
- 配置治理：ConfigMap / Secret 支持文本编辑、保存前 diff 预览、历史版本列表、最近回滚和指定版本回滚

#### K8s Pod Terminal

![K8s Pod Terminal](docs/screenshots/k8s-pod-terminal.png)

K8s Pod Terminal：在浏览器内直接进入 Pod Shell，支持预置命令、会话日志导出与独立 RBAC 权限控制。

### Docker 环境治理

- 容器列表采用兼容性更好的 JSON 行格式采集，降低不同 Docker 版本下的解析差异
- 支持容器日志弹窗、Inspect 详情查看、单容器启停重启与删除
- 镜像管理支持批量删除和 `dangling` 镜像一键清理，方便演示镜像治理流程

## IaC 资源编排

当前已支持阿里云和华为云两类云厂商的 Terraform 资源编排。

### 当前支持的编排能力

- 基础信息：方案名称、描述、云厂商、区域、可用区
- 网络：VPC、子网、开放端口
- 服务器：支持配置多台服务器
- 数据库：RDS、Redis 独立标签页按需启用
- 网络附加资源：SLB / ELB、NAT 网关按需启用
- 对象存储：支持创建多个 Bucket
- 配置预览：可直接编辑生成后的 Terraform 文件内容
- 执行与同步 CMDB：支持 `init / plan / apply / destroy` 与资源回写

### 页面使用建议

推荐使用顺序如下：

1. 在“方案列表”中打开已有方案，或点击右上角“新建方案”
2. 在“方案设计”中完成各模块参数填写
3. 点击“生成配置并预览”查看 Terraform 文件
4. 在“配置预览”中确认内容并保存方案
5. 在“执行与同步CMDB”中执行 Terraform 或同步到 CMDB

## RBAC 权限体系

项目内置统一 RBAC 权限模型，新增功能也应遵循同一套约束。

- 模型：用户、用户组、角色、权限字典
- 后端：统一在 `backend/rbac/registry.py` 注册权限，在 `backend/rbac/permissions.py` 做接口校验
- 前端：路由、侧边栏、页面按钮、敏感操作统一接入 `frontend/src/stores/auth.js`
- WebSocket / WebShell：服务端二次校验，不依赖前端隐藏

### 已覆盖的权限范围

- 用户 / 用户组 / 角色 / 权限字典管理
- 主机、终端、部署、告警、日志、SQL 审计、服务市场
- CMDB、K8s、Docker、Nginx、IaC 的页面级与按钮级权限控制

### 演示账号

执行 `cd backend && python manage.py seed_data` 后，会自动补齐 RBAC 演示数据。默认密码均为 `Admin@123456`。

- `admin`
- `ops_demo`
- `dev_demo`
- `audit_demo`
- `viewer_demo`

## 快速启动

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py seed_templates
python -m daphne -b 0.0.0.0 -p 8000 agdevops.asgi:application
```

后端默认地址：`http://localhost:8000`

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认地址：`http://localhost:3000`

## 常用命令

```bash
# 后端测试
cd backend && python manage.py test

# 初始化或刷新演示数据
cd backend && python manage.py seed_data

# 初始化或刷新工具市场模板
cd backend && python manage.py seed_templates

# 前端开发
cd frontend && npm run dev

# 前端构建
cd frontend && npm run build

# 前端预览
cd frontend && npm run preview
```

## 项目结构

```text
agdevops/
|- backend/
|  |- agdevops/                  # Django 配置
|  |- ops/                       # 仪表盘、主机、部署、日志、告警
|  |- cmdb/                      # CMDB、拓扑、成本、资源申请
|  |- marketplace/               # 工具市场
|  |- rbac/                      # RBAC 权限系统
|  |- sqlaudit/                  # SQL 审计
|  |- iac/                       # Terraform IaC 编排与执行
|  |- requirements.txt
|  `- manage.py
|- frontend/
|  |- src/api/                   # 前端 API 封装
|  |- src/components/            # 复用组件
|  |- src/layout/                # 布局与菜单
|  |- src/lib/                   # 前端图表等基础封装
|  |- src/router/                # 路由配置
|  |- src/stores/                # Pinia store
|  `- src/views/                 # 页面视图
|- docs/
|  `- screenshots/               # README 首页截图与占位图
`- README.md
```

## 开发说明

- 当前默认配置面向本地开发：`DEBUG = True`、SQLite、开放 CORS
- `frontend/dist/`、`frontend/node_modules/`、`backend/__pycache__/`、`db.sqlite3` 为生成产物，不建议提交
- 使用 Daphne 运行后端时，修改 Python 代码后需要手动重启服务
- 涉及 UI 变更时，建议至少执行一次 `cd frontend && npm run build`
- 涉及后端逻辑变更时，建议至少执行一次 `cd backend && python manage.py test`
- 工具市场模板升级后，建议执行一次 `cd backend && python manage.py seed_templates` 以刷新内置模板

## License

MIT
