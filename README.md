# AgDevOps 运维平台

基于 Django、Django REST framework、Channels 与 Vue 3 / Element Plus 的一体化运维平台，覆盖主机管理、CMDB、部署管理、容器管理、Nginx 管理、日志中心、告警中心、SQL 审计等常见运维场景。

## 术语说明

- CMDB：Configuration Management Database，配置管理数据库
- CI：Configuration Item，配置项或资源对象
- WebShell：浏览器内主机终端入口

## 核心能力

- 仪表盘：聚合主机、部署、告警等核心指标
- 主机管理：主机台账、状态展示、WebShell 入口
- CMDB：资源类型、配置项、资源树、拓扑关系、成本分析、优化建议、资源申请
- 部署管理：部署记录、状态查看与发布追踪
- 容器管理：K8s 集群、Docker 环境管理
- Nginx 管理：域名、路由、证书与环境配置
- 日志中心：数据源管理、日志查询、多标签页、历史记录、收藏条件、趋势图
- SQL 审计：数据源管理、SQL 工单、只读查询
- 工具市场：预留扩展型运维工具能力

## 最近更新

- CMDB 拓扑支持更清晰的筛选范围控制，适合做同环境资源梳理与邻接分析
- CMDB 成本分析支持按月份查看、近 6 月趋势、Top 资源与多维度聚合
- CMDB 优化建议基于资源状态、环境、规格与月成本给出节流提示
- CI 关系增加自关联校验与唯一性约束，避免重复或无效关系
- 新增 CMDB 自动关联设计文档，便于后续扩展关系发现能力

## 技术栈

- 后端：Django + Django REST framework + Channels + Daphne
- 前端：Vue 3 + Vite + Element Plus + Pinia + Vue Router + ECharts
- 数据存储：SQLite（默认开发配置）

## 界面预览

### CMDB 成本分析

![CMDB 成本分析页](frontend/cmdb-cost-check-fixed.png)

## 项目结构

```text
agdevops/
├─ backend/
│  ├─ agdevops/                  # Django 配置
│  ├─ ops/                       # 仪表盘、主机、部署、日志、告警
│  ├─ cmdb/                      # CMDB、拓扑、成本、资源申请
│  ├─ marketplace/               # 工具市场
│  ├─ sqlaudit/                  # SQL 审计
│  ├─ requirements.txt
│  └─ manage.py
├─ frontend/
│  ├─ src/api/                   # 前端 API 封装
│  ├─ src/components/            # 复用组件
│  ├─ src/layout/                # 布局与菜单
│  ├─ src/router/                # 路由配置
│  ├─ src/stores/                # Pinia store
│  ├─ src/views/                 # 页面视图
│  └─ package.json
├─ docs/
│  ├─ CMDB使用手册.md
│  └─ CMDB自动关联设计稿.md
└─ README.md
```

## 快速启动

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
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
# 后端全量测试
cd backend && python manage.py test

# 加载演示数据
cd backend && python manage.py seed_data

# 前端开发
cd frontend && npm run dev

# 前端生产构建
cd frontend && npm run build

# 前端本地预览构建结果
cd frontend && npm run preview
```

## 日志中心说明

- 支持 Loki、ELK / Elasticsearch、阿里云 SLS
- 首次迁移后可配合演示数据直接查看日志查询页面
- 默认配置项位于 `backend/agdevops/settings.py`
- 可通过环境变量覆盖日志源配置，例如 `LOKI_URL`、`ELK_URL`、`ELK_AUTH_TYPE`、`ALIYUN_SLS_ENDPOINT`、`ALIYUN_SLS_PROJECT`

## 文档

- `docs/CMDB使用手册.md`：CMDB 列表、拓扑与成本能力说明
- `docs/CMDB自动关联设计稿.md`：CMDB 自动发现关系的设计思路

## 开发说明

- 当前默认配置面向本地开发：`DEBUG = True`、SQLite、开放 CORS
- `frontend/dist/`、`frontend/node_modules/`、`backend/__pycache__/`、`db.sqlite3` 为生成产物，不建议提交
- 使用 Daphne 运行后端时，修改 Python 代码后需要手动重启服务

## License

MIT
