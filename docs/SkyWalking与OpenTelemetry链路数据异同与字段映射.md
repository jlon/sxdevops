# SkyWalking 与 OpenTelemetry 链路数据异同与字段映射

## 1. 结论先行

SkyWalking 和 OpenTelemetry 都能表达分布式链路中的 `Trace`、`Span`、父子关系、耗时、错误状态和标签信息，但它们并不处于同一层级：

- `OpenTelemetry` 更偏向 **采集标准、上下文传播标准、数据模型标准**
- `SkyWalking` 更偏向 **完整可观测平台、查询后端、拓扑分析和 UI 产品**

因此，两者的关系不是互斥关系，而是：

- `OpenTelemetry` 负责回答“链路数据如何标准化地产生和上报”
- `SkyWalking` 负责回答“链路数据如何接收、存储、查询、分析和展示”

对 AgDevOps 来说，最合理的策略不是二选一，而是：

- **采集侧优先拥抱 OpenTelemetry 规范**
- **查询侧兼容 SkyWalking 以及 Jaeger / Zipkin / Tempo 等多种后端**
- **产品侧构建统一的 Trace 领域模型和统一排障 UI**

---

## 2. 相同点

无论是 SkyWalking 还是 OpenTelemetry 风格的 Trace 数据，核心结构高度相通。

### 2.1 共同的数据语义

- 都以 `Trace` 作为一次完整请求或事务的链路单元
- 都以 `Span` 作为链路中的一个局部操作单元
- 都能表达 `parent-child` 父子关系
- 都能表达服务、实例、操作名、开始时间、结束时间、耗时
- 都能标识错误状态或异常事件
- 都能携带附加标签信息
- 都适合绘制瀑布图、链路列表、错误高亮、慢调用定位

### 2.2 对统一 UI 的意义

这意味着在 AgDevOps 内部，可以将不同来源的数据统一抽象为同一套前端展示模型，例如：

- `trace_id`
- `span_id`
- `parent_span_id`
- `service_name`
- `instance_name`
- `operation_name`
- `start_time`
- `end_time`
- `duration_ms`
- `is_error`
- `status_code`
- `tags`
- `logs_or_events`
- `source_provider`

只要把 SkyWalking、Jaeger、Zipkin、Tempo 甚至未来更多后端的数据归一化成这套内部模型，页面展示层就可以保持稳定。

---

## 3. 不同点

## 3.1 定位不同

### SkyWalking

- 是完整可观测平台
- 有自己的 Agent、OAP、查询接口、拓扑分析和 UI
- 更强调平台能力和运行分析能力

### OpenTelemetry

- 是开放标准与生态
- 定义 Trace / Metrics / Logs 的采集与传输规范
- 更强调跨语言、跨厂商的标准化接入能力

一句话概括：

- `SkyWalking` 是产品平台
- `OpenTelemetry` 是标准体系

## 3.2 数据模型组织方式不同

SkyWalking 和 OTel 都有 Span，但字段组织方式不一样。

### OpenTelemetry 常见字段

- `traceId`
- `spanId`
- `parentSpanId`
- `name`
- `kind`
- `startTimeUnixNano`
- `endTimeUnixNano`
- `attributes`
- `events`
- `status`
- `resource.attributes`

### SkyWalking 常见字段

- `traceId`
- `segmentId`
- `spanId`
- `parentSpanId`
- `serviceCode`
- `serviceInstanceName`
- `endpointName`
- `type`
- `peer`
- `component`
- `layer`
- `tags`
- `logs`

差异重点：

- OTel 更偏向“标准字段 + attributes 扩展”
- SkyWalking 更偏向“平台语义字段 + 查询友好字段”

## 3.3 语义增强来源不同

### OpenTelemetry

语义主要来自：

- `Semantic Conventions`
- `resource.attributes`
- `span.attributes`
- `status`
- `events`

### SkyWalking

语义主要来自：

- SkyWalking Agent 的自动识别
- 平台自身的 `service / endpoint / component / layer` 建模
- OAP 查询结果中的聚合语义

实际结果是：

- SkyWalking 原生数据天然更适合直接画服务拓扑、调用层级和组件分类
- OTel 数据通常需要做一层归一化，才能更适合 UI 统一展示

## 3.4 上下文传播标准不同

### OpenTelemetry

常见传播标准：

- `W3C Trace Context`
- `traceparent`
- `tracestate`
- `baggage`

### SkyWalking

- 历史上有自己的传播体系和探针生态
- 现代场景下也会逐步兼容更多标准方式
- 但其原生模型并不完全等同于 OTel 标准模型

所以在真实环境中经常会出现：

- 新系统优先使用 OTel 标准
- 老系统或深度 Java Agent 场景继续使用 SkyWalking 原生能力

## 3.5 查询接口不同

这点对 AgDevOps 非常关键。

OpenTelemetry 定义了上报格式，但并没有统一规定所有后端都必须暴露同一套查询 API。不同后端的查询方式可能完全不同：

- SkyWalking：GraphQL / OAP 查询接口
- Jaeger：Jaeger Query HTTP API
- Zipkin：Zipkin v2 API
- Tempo：Tempo Query API

因此：

- **采集侧可以统一成 OTel**
- **查询侧仍然需要按后端分别适配**

## 3.6 时间精度和状态表达不同

### 时间精度

- SkyWalking 常见为毫秒级时间戳
- Jaeger / Zipkin 常见为微秒级
- OTel 原生常见为纳秒级

### 状态表达

- OTel 常通过 `status.code`、`events`、`attributes` 表达错误
- SkyWalking 常直接给出 `isError`
- Jaeger / Zipkin 常需要结合 `error=true`、`http.status_code>=500`、异常日志等信息推断

这决定了 AgDevOps 在归一化时必须做：

- 时间单位统一
- 错误状态统一推断
- 字段优先级统一

---

## 4. 数据模型对照表

| AgDevOps 统一字段 | SkyWalking 常见来源 | OTel / Tempo 常见来源 | Jaeger 常见来源 | Zipkin 常见来源 |
| --- | --- | --- | --- | --- |
| `trace_id` | `traceId` | `traceID / traceId` | `traceID` | `traceId` |
| `span_id` | `spanId` | `spanId` | `spanID` | `id` |
| `parent_span_id` | `parentSpanId` | `parentSpanId` | `references[].spanID` | `parentId` |
| `service_name` | `serviceCode` | `resource.attributes['service.name']` | `process.serviceName` | `localEndpoint.serviceName` |
| `instance_name` | `serviceInstanceName` | `resource.attributes['service.instance.id']` | 通常无统一字段 | 通常无统一字段 |
| `operation_name` | `endpointName` | `name` | `operationName` | `name` |
| `span_kind` | `type` | `kind` | `span.kind` tag | `kind` |
| `start_time` | `startTime` | `startTimeUnixNano` | `startTime` | `timestamp` |
| `end_time` | `endTime` | `endTimeUnixNano` | `startTime + duration` | `timestamp + duration` |
| `duration_ms` | `endTime - startTime` | `end - start` | `duration / 1000` | `duration / 1000` |
| `is_error` | `isError` | `status.code=ERROR` 或异常事件 | `error=true` / 状态码推断 | `error=true` / 状态码推断 |
| `peer` | `peer` | `peer.service / server.address / net.peer.*` | `peer.address / http.url` | `remoteEndpoint.serviceName` |
| `component` | `component` | `db.system / rpc.system / net.transport` 等 | `component / otel.library.name` | `component / db.system` |
| `layer` | `layer` | 由 attributes 推断 | 由 tags 推断 | 由 kind / tags 推断 |
| `tags` | `tags` | `attributes` | `tags` | `tags` |
| `logs_or_events` | `logs` | `events` | `logs` | `annotations` |

---

## 5. AgDevOps 内部统一模型建议

建议 AgDevOps 不直接把某一家后端的原始结构透传给前端，而是统一成自己的领域模型。

## 5.1 Trace 摘要模型

适合链路列表展示：

- `trace_id`
- `service_id`
- `service_name`
- `instance_name`
- `endpoint_names`
- `duration_ms`
- `start`
- `is_error`
- `state`
- `source_provider`

## 5.2 Trace 详情模型

适合右侧详情、瀑布图、排障联动：

- `trace_id`
- `service_name`
- `duration_ms`
- `span_count`
- `error_count`
- `services`
- `endpoints`
- `spans`

## 5.3 Span 统一模型

适合瀑布图和 Span 明细：

- `span_id`
- `parent_span_id`
- `service_code`
- `service_instance_name`
- `endpoint_name`
- `start_time`
- `end_time`
- `duration_ms`
- `type`
- `peer`
- `component`
- `is_error`
- `layer`
- `tags`
- `logs`

---

## 6. 归一化时最容易踩坑的点

## 6.1 ID 结构差异

- SkyWalking 除 `traceId` 外，常还强调 `segmentId`
- Jaeger / Zipkin / Tempo 更偏 `traceId + spanId`

建议：

- 内部 UI 统一以 `trace_id + span_id` 作为主展示键
- `segment_id` 作为保留字段，仅在兼容 SkyWalking 原生深钻时使用

## 6.2 时间单位不一致

- 毫秒、微秒、纳秒混用非常常见
- 如果不统一，瀑布图长度会完全错误

建议：

- 后端适配层统一转换为 `ISO8601` 时间字符串
- 计算耗时时统一转换成 `duration_ms`

## 6.3 错误判断不能只看一个字段

不同后端对错误的表达方式不同，不能简单依赖单一字段。

建议按优先级综合判断：

1. 明确错误标志，如 `isError=true`
2. `status.code=ERROR`
3. `error=true`
4. `http.status_code >= 500`
5. 异常事件或日志存在

## 6.4 服务名和操作名来源不同

- OTel 里服务名通常在 `resource.attributes`
- SkyWalking 里服务名直接来自 `serviceCode`
- OTel 的操作名一般是 `span.name`
- SkyWalking 的操作名一般是 `endpointName`

建议：

- `service_name` 和 `operation_name` 必须分别映射
- 不要把两者混成一个显示字段

## 6.5 拓扑不是所有后端都直接返回

- SkyWalking 常能直接返回服务拓扑
- Jaeger / Zipkin / Tempo 更多时候只返回 Trace 数据本身

建议：

- 有原生拓扑时优先使用后端结果
- 无原生拓扑时，允许 AgDevOps 根据 Trace 明细做轻量推导
- 但不要在 AgDevOps 内重建复杂拓扑存储引擎

---

## 7. 对 AgDevOps 产品设计的建议

## 7.1 不要试图做“另一个 SkyWalking / Jaeger”

AgDevOps 更适合承担的是：

- 统一入口
- 权限管控
- 多后端兼容
- Trace 与日志、告警、发布、CMDB 的联动

而不是：

- 自己实现 Trace 存储
- 自己实现 Trace 采集协议
- 自己替代各原生平台的全部高级诊断能力

## 7.2 推荐的产品定位

建议产品定位分成两层：

### 第一层：统一排障入口

AgDevOps 负责：

- Trace 查询
- Trace 详情
- 统一瀑布图
- 日志联动
- 告警联动
- 发布联动
- 监控联动
- CMDB / RBAC / 业务上下文补全

### 第二层：原生深度诊断入口

SkyWalking / Jaeger / Zipkin / Tempo 负责：

- 原生高级分析
- 原生特性查询
- 更深层的故障钻取
- 平台专属高级功能

即：

- **AgDevOps 是统一排障入口**
- **原生链路平台是深度诊断入口**

---

## 8. 推荐的接入策略

## 8.1 采集侧策略

优先建议：

- 新系统：优先接入 `OpenTelemetry SDK / Agent`
- 存量 SkyWalking 系统：继续兼容 `SkyWalking Agent`

原因：

- OTel 更标准，未来兼容性更强
- SkyWalking 在存量场景下仍然常见，不能忽略

## 8.2 查询侧策略

AgDevOps 后端继续维护 provider 适配层：

- `skywalking`
- `tempo`
- `jaeger`
- `zipkin`

每个 provider 各自负责：

- 服务列表查询
- Trace 列表查询
- Trace 详情查询
- 统一字段归一化

## 8.3 前端展示策略

前端只依赖统一结构，不感知各后端原始字段差异：

- 左侧链路列表展示统一摘要
- 右侧概览 + Timeline + Waterfall 展示统一详情
- 联动按钮统一跳转日志、告警、发布、监控、原生平台

---

## 9. 一句话总结

SkyWalking 和 OpenTelemetry 在“链路是什么”这件事上高度相通，但在“数据如何产生、如何表达、如何查询、如何增强”上存在明显差异。

对 AgDevOps 而言，最佳实践是：

**采集侧拥抱 OpenTelemetry 标准，查询侧兼容 SkyWalking 与 OTel 生态后端，展示侧坚持统一 Trace 内部模型和统一排障 UI。**

---

## 10. 相关阅读

- [链路追踪接入与展示实现思路](./链路追踪接入与展示实现思路.md)
- [链路追踪真实环境数据流转说明](./链路追踪真实环境数据流转说明.md)
