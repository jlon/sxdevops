<template>
  <div class="observability-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Connection /></el-icon>
          </span>
          <h2>链路追踪</h2>
          <p class="page-inline-desc">支持接入 SkyWalking 与 OpenTelemetry 生态下的 Zipkin、Jaeger、Tempo 等链路数据</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="refreshAll" :loading="loading.catalog || loading.search">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button size="small" v-if="canQueryLogs" @click="router.push('/logs/query')">日志查询</el-button>
        <el-button size="small" v-if="canViewAlerts" @click="router.push('/alerts')">告警中心</el-button>
        <el-button size="small" v-if="canViewGrafana" @click="router.push('/observability/grafana')">监控看板</el-button>
        <el-button size="small" v-if="hasNativeTracingUi" type="primary" @click="openTracingUi">
          外部打开
        </el-button>
      </div>
    </section>

    <div class="neo-tabs theme-blue log-center-tabs trace-center-tabs">
      <button
        v-if="canViewTrace"
        class="neo-tab-btn"
        :class="{ active: activeTraceTab === 'traces' }"
        @click="changeTraceTab('traces')"
      >
        <el-icon style="margin-right:4px;"><Search /></el-icon>
        Trace 查询
      </button>
      <button
        v-if="canViewTraceDataSources"
        class="neo-tab-btn"
        :class="{ active: activeTraceTab === 'datasources' }"
        @click="changeTraceTab('datasources')"
      >
        <el-icon style="margin-right:4px;"><Document /></el-icon>
        链路数据源
      </button>
    </div>

    <template v-if="activeTraceTab === 'traces' && canViewTrace">
    <section class="panel trace-query-unified-card">
      <div class="trace-query-unified-head">
        <div class="trace-query-title-block">
          <div class="trace-query-title-row">
            <h3>Trace 查询</h3>
          </div>
        </div>
      </div>

      <div class="trace-query-unified-body">
        <div class="trace-query-provider-strip">
          <div class="trace-filter-datasource-row">
            <span class="trace-query-provider-label">数据源</span>
            <el-select
              v-model="filters.datasourceId"
              class="search-control trace-datasource-control"
              size="small"
              clearable
              filterable
              placeholder="选择当前 Provider 下的数据源"
              :disabled="!canViewTraceDataSources || !filteredTracingDataSources.length"
              @change="changeDataSource"
            >
              <el-option
                v-for="item in filteredTracingDataSources"
                :key="item.id"
                :label="`${item.name}${item.is_default ? '（默认）' : ''}（${providerNameByKey(item.provider)}）`"
                :value="String(item.id)"
              />
            </el-select>
          </div>
        </div>

        <div class="search-panel search-panel--merged">
          <div class="trace-filter-service-row">
            <div class="trace-filter-grid trace-filter-grid--primary">
              <div class="trace-inline-filter">
                <span class="trace-inline-filter__label">服务</span>
                <el-select v-model="filters.serviceId" class="search-control" size="small" clearable filterable placeholder="选择服务">
                  <el-option v-for="item in services" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </div>
              <div class="trace-inline-filter">
                <span class="trace-inline-filter__label">Trace</span>
                <el-input class="search-control" size="small" v-model.trim="filters.traceId" placeholder="输入 Trace ID 直达" clearable />
              </div>
              <div class="trace-inline-filter">
                <span class="trace-inline-filter__label">关键字</span>
                <el-input class="search-control" size="small" v-model.trim="filters.keyword" placeholder="接口 / 服务名 / 关键字" clearable />
              </div>
              <div class="trace-inline-filter trace-inline-filter--compact">
                <span class="trace-inline-filter__label">数量</span>
                <el-input-number class="search-number advanced-filter-control advanced-filter-number" size="small" v-model="filters.limit" :min="5" :max="50" :step="5" />
              </div>
            </div>
          </div>
          <div class="trace-filter-grid trace-filter-grid--advanced trace-filter-grid--toolbar">
            <div class="trace-inline-filter trace-inline-filter--compact">
              <span class="trace-inline-filter__label">状态</span>
              <el-select v-model="filters.traceState" class="search-control advanced-filter-control" size="small" placeholder="全部状态">
                <el-option label="全部状态" value="ALL" />
                <el-option label="正常链路" value="SUCCESS" />
                <el-option label="错误链路" value="ERROR" />
              </el-select>
            </div>
            <div class="trace-inline-filter trace-inline-filter--compact">
              <span class="trace-inline-filter__label">排序</span>
              <el-select v-model="filters.sortBy" class="search-control advanced-filter-control" size="small" placeholder="最近开始">
                <el-option label="最近开始" value="latest" />
                <el-option label="最慢优先" value="slowest" />
                <el-option label="错误优先" value="errors" />
              </el-select>
            </div>
            <div class="trace-inline-filter trace-inline-filter--time">
              <span class="trace-inline-filter__label">时间</span>
              <el-date-picker
                v-model="filters.timeRange"
                class="search-control time-range-picker advanced-filter-time"
                size="small"
                type="datetimerange"
                range-separator="至"
                start-placeholder="开始"
                end-placeholder="结束"
                format="YYYY-MM-DD HH:mm"
                unlink-panels
                :shortcuts="timeRangeShortcuts"
              />
            </div>
            <div class="trace-filter-actions">
              <el-button size="small" type="primary" class="search-action-primary" @click="runSearch()" :loading="loading.search">查询 Trace</el-button>
              <el-button size="small" plain class="search-action-secondary" @click="resetFilters">重置</el-button>
            </div>
          </div>

          <div class="search-summary-bar trace-query-summary-bar">
            <span v-for="item in searchPanelSummary" :key="item.label" class="query-pill">
              {{ item.label }}：{{ item.value }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <h3>调用拓扑</h3>
        <div class="section-head-tags">
          <el-tag size="small" type="success">节点 {{ focusedTopology.node_count || 0 }}</el-tag>
          <el-tag size="small" type="warning">调用 {{ focusedTopology.call_count || 0 }}</el-tag>
          <el-button size="small" text @click="topologyExpanded = !topologyExpanded">
            {{ topologyExpanded ? '收起' : '展开' }}
          </el-button>
        </div>
      </div>
      <button
        v-if="!topologyExpanded"
        type="button"
        class="compact-summary-bar compact-summary-bar--action"
        @click="topologyExpanded = true"
      >
        <span>节点 {{ focusedTopology.node_count || 0 }}</span>
        <span>调用 {{ focusedTopology.call_count || 0 }}</span>
        <span v-if="topologyHighlights.length">重点 {{ topologyHighlights[0].name }}</span>
        <strong class="compact-summary-bar__hint">点击展开</strong>
      </button>
      <div v-else class="topology-layout">
        <div ref="topologyChartRef" class="topology-chart" />
        <div class="topology-side">
          <div class="topology-list">
            <article
              v-for="item in pagedTopologyHighlights"
              :key="item.id"
              class="topology-item"
              :class="[`is-${item.role}`]"
            >
              <div class="topology-item-main">
                <strong :title="item.name">{{ item.shortName }}</strong>
                <span class="topology-item-role">{{ item.roleLabel }}</span>
              </div>
              <span class="topology-item-meta" :title="item.layer">{{ item.layer }}</span>
            </article>
          </div>
          <div v-if="topologyHighlights.length > TOPOLOGY_LIST_PAGE_SIZE" class="topology-pagination">
            <button
              type="button"
              class="trace-page-btn topology-page-btn"
              :disabled="topologyListPage <= 1"
              @click="topologyListPage -= 1"
            >
              上一页
            </button>
            <span class="trace-page-indicator">{{ topologyListPage }} / {{ topologyListPageCount }}</span>
            <button
              type="button"
              class="trace-page-btn topology-page-btn"
              :disabled="topologyListPage >= topologyListPageCount"
              @click="topologyListPage += 1"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </section>

    <div class="content-grid" :class="{ 'has-selected-trace': Boolean(selectedTraceId) }">
      <section class="panel traces-panel">
        <div class="section-head">
          <h3>链路列表</h3>
          <div class="section-head-tags">
            <el-tag size="small" type="info">命中 {{ searchSummary.match_count || displayTraces.length }} 条</el-tag>
            <el-tag size="small" effect="plain">排序 {{ sortLabel }}</el-tag>
          </div>
        </div>

        <el-empty v-if="!displayTraces.length && !loading.search" description="当前条件下未找到 Trace。" />

        <template v-else>
          <div class="trace-results" v-loading="loading.search">
            <article
              v-for="row in pagedDisplayTraces"
              :key="row.trace_id"
              class="trace-result-card"
              :class="{
                'is-active': row.trace_id === selectedTraceId,
                'is-error': row.is_error,
                'is-slow': Number(row.duration_ms || 0) >= slowThreshold,
              }"
            >
              <button type="button" class="trace-result-main" @click="selectTrace(row)">
                <div class="trace-result-line two-line-layout">
                  <div class="trace-title-row">
                    <span class="trace-accent-bar" :class="{ 'is-error': row.is_error, 'is-slow': Number(row.duration_ms || 0) >= slowThreshold }"></span>
                    <strong class="trace-result-operation" :title="tracePrimaryEndpoint(row)">{{ tracePrimaryEndpoint(row) }}</strong>
                  </div>
                  <div class="trace-meta-row">
                    <span class="trace-status-pill" :class="{ 'is-error': row.is_error }">
                      {{ row.is_error ? '失败' : '成功' }}
                    </span>
                    <span class="trace-duration-pill" :class="{ 'is-slow': Number(row.duration_ms || 0) >= slowThreshold }">
                      {{ formatDuration(row.duration_ms) }}
                    </span>
                    <span class="trace-result-time">{{ formatListTime(row.start) }}</span>
                  </div>
                </div>
              </button>
            </article>
          </div>

          <div v-if="displayTraces.length > TRACE_LIST_PAGE_SIZE" class="trace-pagination">
            <button
              type="button"
              class="trace-page-btn"
              :disabled="traceListPage <= 1"
              @click="traceListPage -= 1"
            >
              上一页
            </button>
            <span class="trace-page-indicator">{{ traceListPage }} / {{ traceListPageCount }}</span>
            <button
              type="button"
              class="trace-page-btn"
              :disabled="traceListPage >= traceListPageCount"
              @click="traceListPage += 1"
            >
              下一页
            </button>
          </div>
        </template>
      </section>

      <section class="panel detail-panel">
        <div class="section-head">
          <h3>Trace 详情</h3>
          <div class="section-head-tags">
            <el-tag v-if="selectedTraceId" size="small" type="warning">{{ selectedTraceId }}</el-tag>
          </div>
        </div>

        <el-empty v-if="!traceDetail && !loading.detail" description="选择一条 Trace 后查看 Span 详情。" />

        <template v-else>
          <div class="trace-workbench" v-loading="loading.detail">
            <div class="trace-header-card">
              <div class="trace-title-block">
                <div class="trace-title-row-main">
                  <span class="trace-provider-pill">{{ selectedProviderMeta?.provider_name || tracing.provider_name || 'Tracing' }}</span>
                  <h3>{{ traceTitle }}</h3>
                </div>
                <div class="trace-header-meta">
                  <div class="trace-id-row">
                    <span>Trace ID</span>
                    <code>{{ selectedTraceId || '--' }}</code>
                  </div>
                </div>
              </div>
              <div class="trace-kpi-grid">
                <div class="trace-kpi">
                  <span>Duration</span>
                  <strong>{{ formatDuration(traceDetail?.duration_ms) }}</strong>
                </div>
                <div class="trace-kpi">
                  <span>Services</span>
                  <strong>{{ traceDetail?.services?.length || 0 }}</strong>
                </div>
                <div class="trace-kpi">
                  <span>Spans</span>
                  <strong>{{ traceDetail?.span_count || 0 }}</strong>
                </div>
                <div class="trace-kpi danger-kpi">
                  <span>Errors</span>
                  <strong>{{ traceDetail?.error_count || 0 }}</strong>
                </div>
              </div>
              <div v-if="waterfallRows.length" class="trace-minimap trace-header-minimap">
                <div class="trace-minimap-head">
                  <strong>Trace Timeline</strong>
                </div>
                <div class="minimap-track">
                  <button
                    v-for="row in minimapRows"
                    :key="`minimap-${row.span_id}`"
                    type="button"
                    class="minimap-segment"
                    :class="{ 'is-error': row.is_error, 'is-selected': String(row.span_id) === selectedSpanId }"
                    :style="row.barStyle"
                    :title="`${row.endpoint_name || row.service_code} · ${formatDuration(row.duration_ms)}`"
                    @click="focusSpan(row.span_id)"
                  />
                </div>
              </div>
            </div>

            <div v-if="selectedTraceId" class="trace-context-actions">
              <div class="context-copy">
                <strong>排障联动</strong>
                <span>用 Trace ID、服务和时间窗口串起日志、告警、发布、监控与原生平台。</span>
              </div>
              <div class="context-actions">
                <button v-if="canQueryLogs" type="button" class="context-action-btn primary" @click="openLogsForCurrentTrace">查日志</button>
                <button v-if="canViewAlerts" type="button" class="context-action-btn" @click="openAlertsForTrace">查告警</button>
                <button v-if="canViewDeployments" type="button" class="context-action-btn" @click="openDeploymentsForTrace">看发布</button>
                <button v-if="canViewGrafana" type="button" class="context-action-btn" @click="openGrafanaForTrace">看监控</button>
                <button v-if="hasNativeTracingUi" type="button" class="context-action-btn" @click="openTracingUi">原生平台</button>
              </div>
            </div>

            <div v-if="traceDetail?.spans?.length" class="trace-insights">
              <button
                v-for="span in errorSpanHighlights"
                :key="`error-${span.span_id}`"
                type="button"
                class="insight-pill error-pill"
                @click="focusSpan(span.span_id)"
              >
                异常：{{ span.endpoint_name || span.service_code }} · {{ formatDuration(span.duration_ms) }}
              </button>
              <button
                v-for="span in slowSpanHighlights"
                :key="`slow-${span.span_id}`"
                type="button"
                class="insight-pill slow-pill"
                @click="focusSpan(span.span_id)"
              >
                慢调用：{{ span.endpoint_name || span.service_code }} · {{ formatDuration(span.duration_ms) }}
              </button>
              <span v-for="item in serviceHighlights" :key="item.service" class="insight-pill service-pill">
                {{ item.service }} · {{ item.count }} spans
              </span>
            </div>

            <div class="span-toolbar">
              <el-input v-model.trim="spanUi.keyword" size="small" clearable placeholder="过滤 Span / Service / Tag" />
              <el-select v-model="spanUi.service" size="small" clearable filterable placeholder="全部服务">
                <el-option v-for="item in traceDetail?.services || []" :key="item" :label="item" :value="item" />
              </el-select>
              <div class="span-filter-toggle">
                <span class="span-filter-label">状态</span>
                <div class="span-filter-segment">
                  <button
                    type="button"
                    class="span-filter-option"
                    :class="{ 'is-active': !spanUi.errorsOnly }"
                    @click="spanUi.errorsOnly = false"
                  >
                    全部
                  </button>
                  <button
                    type="button"
                    class="span-filter-option"
                    :class="{ 'is-active': spanUi.errorsOnly }"
                    @click="spanUi.errorsOnly = true"
                  >
                    仅错误
                  </button>
                </div>
              </div>
              <div class="span-filter-toggle">
                <span class="span-filter-label">耗时</span>
                <div class="span-filter-segment">
                  <button
                    type="button"
                    class="span-filter-option"
                    :class="{ 'is-active': !spanUi.slowOnly }"
                    @click="spanUi.slowOnly = false"
                  >
                    全部耗时
                  </button>
                  <button
                    type="button"
                    class="span-filter-option"
                    :class="{ 'is-active': spanUi.slowOnly }"
                    @click="spanUi.slowOnly = true"
                  >
                    仅慢调用
                  </button>
                </div>
              </div>
            </div>

            <div v-if="waterfallRows.length" class="trace-timeline-card">
              <div class="timeline-axis-row">
                <span>Service & Operation</span>
                <div class="timeline-axis">
                  <span>0 ms</span>
                  <span>{{ formatDuration(traceDetail?.duration_ms) }}</span>
                </div>
                <span>Duration</span>
              </div>

              <div class="timeline-body">
                <template v-for="row in filteredTimelineRows" :key="`timeline-${row.span_id}`">
                  <button
                    :id="`span-${selectedTraceId}-${row.span_id}`"
                    type="button"
                    class="timeline-row"
                    :class="{
                      'is-error': row.is_error,
                      'is-slow': row.duration_ms >= slowThreshold,
                      'is-selected': String(row.span_id) === selectedSpanId,
                      'is-critical': criticalSpanIds.has(String(row.span_id)),
                    }"
                    @click="toggleSpanDetails(row)"
                  >
                    <div class="timeline-label" :style="{ paddingLeft: `${row.depth * 16}px` }">
                      <span class="expand-mark">{{ isSpanExpanded(row.span_id) ? '▾' : '▸' }}</span>
                      <span class="service-dot" :style="{ background: row.serviceColor }"></span>
                      <div class="operation-cell">
                        <strong>{{ row.endpoint_name || row.service_code || 'Span' }}</strong>
                        <span>{{ row.service_code || '--' }} · {{ row.type || 'Span' }} · {{ row.layer || 'UNSET' }}</span>
                      </div>
                    </div>
                    <div class="timeline-track">
                      <div class="timeline-bar" :style="row.barStyle"></div>
                    </div>
                    <span class="timeline-duration">{{ formatDuration(row.duration_ms) }}</span>
                  </button>

                  <div v-if="isSpanExpanded(row.span_id)" class="timeline-detail">
                    <div class="timeline-detail-grid">
                      <div>
                        <span class="detail-label">Start</span>
                        <strong>{{ formatTime(row.start_time) }}</strong>
                      </div>
                      <div>
                        <span class="detail-label">Instance</span>
                        <strong>{{ row.service_instance_name || '--' }}</strong>
                      </div>
                      <div>
                        <span class="detail-label">Peer</span>
                        <strong>{{ row.peer || '--' }}</strong>
                      </div>
                      <div>
                        <span class="detail-label">Span ID</span>
                        <strong>{{ row.span_id }}</strong>
                      </div>
                    </div>
                    <div v-if="row.tags?.length" class="timeline-tags">
                      <span v-for="tag in row.tags" :key="`${row.span_id}-${tag.key}`" class="span-chip">{{ tag.key }} = {{ tag.value }}</span>
                    </div>
                    <div v-if="row.logs?.length" class="span-log-list">
                      <div v-for="log in row.logs" :key="`${row.span_id}-${log.time}`" class="span-log-item">
                        <strong>{{ formatTime(log.time) }}</strong>
                        <span>{{ formatLog(log.data) }}</span>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <el-empty v-else description="当前 Trace 未返回 Span Timeline。" />
          </div>
        </template>
      </section>
    </div>

    <section class="panel embed-panel">
      <div class="section-head">
        <h3>外部链路平台</h3>
        <div class="section-head-tags">
          <el-button size="small" text @click="embedExpanded = !embedExpanded">
            {{ embedExpanded ? '收起' : '展开' }}
          </el-button>
          <el-button size="small" v-if="hasNativeTracingUi" link type="primary" @click="openTracingUi">外部打开</el-button>
        </div>
      </div>

      <div v-if="!embedExpanded" class="compact-summary-bar">
        <span>{{ selectedProviderMeta?.provider_name || '--' }}</span>
        <span>{{ selectedProviderMeta?.embed_url ? '已配置嵌入地址' : '未配置嵌入地址' }}</span>
      </div>
      <template v-else>
        <iframe v-if="selectedProviderMeta?.embed_url" class="embed-frame" :src="selectedProviderMeta.embed_url" title="Tracing" />
        <el-alert
          v-else
          title="当前 Provider 未配置可嵌入 UI，仍可使用平台内标准化链路查询。"
          type="info"
          show-icon
          :closable="false"
        />
      </template>
    </section>
    </template>

    <template v-else-if="activeTraceTab === 'datasources' && canViewTraceDataSources">
      <TracingDataSources embedded />
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Document, RefreshRight, Search } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getObservabilityOverview, getTraceDetail, getTracingCatalog, getTracingDataSources, searchTracing } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import TracingDataSources from './TracingDataSources.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const loading = reactive({
  catalog: false,
  search: false,
  detail: false,
})

const overview = ref({ modules: {}, summary: {}, tips: [] })
const tracing = ref({})
const providers = ref([])
const tracingDataSources = ref([])
const services = ref([])
const traces = ref([])
const traceDetail = ref(null)
const selectedTraceId = ref('')
const selectedSpanId = ref('')
const topology = ref({})
const searchSummary = ref({})
const topologyChartRef = ref(null)
const expandedSpanIds = ref(new Set())
const topologyExpanded = ref(false)
const embedExpanded = ref(false)
const activeTraceTab = ref(route.query.tab === 'datasources' ? 'datasources' : 'traces')
const traceListPage = ref(1)
const topologyListPage = ref(1)

let topologyChart = null

const DEFAULT_DURATION_MINUTES = 30
const TRACE_LIST_PAGE_SIZE = 15
const TOPOLOGY_LIST_PAGE_SIZE = 6

function buildRelativeTimeRange(minutes = DEFAULT_DURATION_MINUTES) {
  const safeMinutes = Math.max(5, Number(minutes || DEFAULT_DURATION_MINUTES))
  const end = new Date()
  const start = new Date(end.getTime() - safeMinutes * 60 * 1000)
  return [start, end]
}

const filters = reactive({
  provider: '',
  datasourceId: '',
  serviceId: '',
  traceState: 'ALL',
  durationMinutes: DEFAULT_DURATION_MINUTES,
  timeRange: buildRelativeTimeRange(DEFAULT_DURATION_MINUTES),
  keyword: '',
  traceId: '',
  limit: 20,
  sortBy: 'latest',
})

const spanUi = reactive({
  keyword: '',
  service: '',
  errorsOnly: false,
  slowOnly: false,
})

const durationOptions = [
  { label: '最近 15 分钟', value: 15 },
  { label: '最近 30 分钟', value: DEFAULT_DURATION_MINUTES },
  { label: '最近 1 小时', value: 60 },
  { label: '最近 6 小时', value: 360 },
]

const timeRangeShortcuts = durationOptions.map((item) => ({
  text: item.label,
  value: () => buildRelativeTimeRange(item.value),
}))

const slowThreshold = 800

const selectedProviderMeta = computed(() =>
  providers.value.find((item) => item.provider === filters.provider)
  || providers.value.find((item) => item.active)
  || tracing.value
)

const filteredTracingDataSources = computed(() =>
  tracingDataSources.value.filter((item) => item.is_enabled)
)

const selectedTracingDataSource = computed(() =>
  tracingDataSources.value.find((item) => String(item.id) === String(filters.datasourceId))
)

const sortLabel = computed(() => ({
  latest: '最近开始',
  slowest: '最慢优先',
  errors: '错误优先',
}[filters.sortBy] || '最近开始'))

const searchPanelSummary = computed(() => {
  const items = [
    { label: 'Provider', value: selectedProviderMeta.value?.provider_name || '--' },
  ]
  if (selectedTracingDataSource.value?.name) {
    items.push({ label: '数据源', value: selectedTracingDataSource.value.name })
  }
  if (filters.serviceId) {
    items.push({ label: '服务', value: serviceNameById(filters.serviceId) || filters.serviceId })
  }
  items.push(
    { label: '时间', value: timeRangeSummary.value },
    { label: '状态', value: filters.traceState === 'ALL' ? '全部' : filters.traceState === 'ERROR' ? '错误' : '正常' },
    { label: '数量', value: `${filters.limit} 条` },
  )
  return items
})

const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewTrace = computed(() => authStore.hasPermission('ops.trace.view'))
const canViewAlerts = computed(() => authStore.hasPermission('ops.alert.view'))
const canViewGrafana = computed(() => authStore.hasPermission('ops.grafana.view'))
const canViewDeployments = computed(() => authStore.hasAnyPermission(['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve']))
const canViewTraceDataSources = computed(() => authStore.hasPermission('ops.trace.datasource.view'))
const hasNativeTracingUi = computed(() => Boolean(selectedProviderMeta.value?.ui_url || selectedProviderMeta.value?.query_url || selectedProviderMeta.value?.oap_url))

const displayTraces = computed(() => {
  const items = [...traces.value]
  if (filters.sortBy === 'slowest') {
    return items.sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
  }
  if (filters.sortBy === 'errors') {
    return items.sort((a, b) => Number(Boolean(b.is_error)) - Number(Boolean(a.is_error)) || Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
  }
  return items.sort((a, b) => parseTimeValue(b.start) - parseTimeValue(a.start))
})

const pagedDisplayTraces = computed(() => {
  const startIndex = (traceListPage.value - 1) * TRACE_LIST_PAGE_SIZE
  return displayTraces.value.slice(startIndex, startIndex + TRACE_LIST_PAGE_SIZE)
})

const traceListPageCount = computed(() => Math.max(1, Math.ceil(displayTraces.value.length / TRACE_LIST_PAGE_SIZE)))

const traceListMaxDuration = computed(() =>
  Math.max(...displayTraces.value.map((item) => Number(item.duration_ms || 0)), slowThreshold, 1)
)

const topologyHighlights = computed(() =>
  (focusedTopology.value.nodes || [])
    .map((item) => {
      const nodeId = String(item.id || '')
      const selectedNodeId = String(focusedTopology.value.selected_node_id || '')
      const hasIncoming = (focusedTopology.value.calls || []).some((call) => call.target === nodeId && call.source !== nodeId)
      const hasOutgoing = (focusedTopology.value.calls || []).some((call) => call.source === nodeId && call.target !== nodeId)
      const role = nodeId === selectedNodeId ? 'selected' : hasIncoming && !hasOutgoing ? 'downstream' : hasOutgoing && !hasIncoming ? 'upstream' : 'peer'
      return {
        id: item.id,
        name: item.name,
        shortName: ellipsisText(item.name, 20),
        layer: Array.isArray(item.layers) && item.layers.length ? item.layers.join(', ') : item.type || 'SERVICE',
        role,
        roleLabel: role === 'selected' ? '当前服务' : role === 'upstream' ? '上游' : role === 'downstream' ? '下游' : '关联',
      }
    })
    .sort((a, b) => {
      const order = { selected: 0, upstream: 1, downstream: 2, peer: 3 }
      return (order[a.role] ?? 9) - (order[b.role] ?? 9) || a.name.localeCompare(b.name)
    })
)

const pagedTopologyHighlights = computed(() => {
  const startIndex = (topologyListPage.value - 1) * TOPOLOGY_LIST_PAGE_SIZE
  return topologyHighlights.value.slice(startIndex, startIndex + TOPOLOGY_LIST_PAGE_SIZE)
})

const topologyListPageCount = computed(() => Math.max(1, Math.ceil(topologyHighlights.value.length / TOPOLOGY_LIST_PAGE_SIZE)))

const focusedTopology = computed(() => {
  const source = topology.value || {}
  const nodes = Array.isArray(source.nodes) ? source.nodes : []
  const calls = Array.isArray(source.calls) ? source.calls : []
  if (!filters.serviceId || !nodes.length) {
    return {
      node_count: source.node_count || nodes.length,
      call_count: source.call_count || calls.length,
      nodes,
      calls,
    }
  }

  const selectedService = services.value.find((item) => item.id === filters.serviceId)
  const candidateNames = new Set(
    [filters.serviceId, selectedService?.id, selectedService?.name, selectedService?.short_name]
      .map((item) => String(item || '').trim())
      .filter(Boolean)
  )

  const matchedNode = nodes.find((item) => candidateNames.has(String(item.id || '').trim()) || candidateNames.has(String(item.name || '').trim()))
  if (!matchedNode) {
    return {
      node_count: source.node_count || nodes.length,
      call_count: source.call_count || calls.length,
      nodes,
      calls,
    }
  }

  const selectedNodeId = matchedNode.id
  const relatedCalls = calls.filter((item) => item.source === selectedNodeId || item.target === selectedNodeId)
  const relatedNodeIds = new Set([selectedNodeId])
  relatedCalls.forEach((item) => {
    relatedNodeIds.add(item.source)
    relatedNodeIds.add(item.target)
  })

  const relatedNodes = nodes.filter((item) => relatedNodeIds.has(item.id))
  return {
    node_count: relatedNodes.length,
    call_count: relatedCalls.length,
    selected_node_id: selectedNodeId,
    nodes: relatedNodes,
    calls: relatedCalls,
  }
})

const traceSpans = computed(() => traceDetail.value?.spans || [])

const errorSpanHighlights = computed(() =>
  [...traceSpans.value]
    .filter((item) => item.is_error)
    .sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
    .slice(0, 3)
)

const slowSpanHighlights = computed(() =>
  [...traceSpans.value]
    .filter((item) => Number(item.duration_ms || 0) >= slowThreshold)
    .sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
    .slice(0, 3)
)

const serviceHighlights = computed(() => {
  const summary = new Map()
  traceSpans.value.forEach((item) => {
    const service = item.service_code || 'unknown'
    const current = summary.get(service) || { service, count: 0, errorCount: 0, maxDuration: 0 }
    current.count += 1
    if (item.is_error) current.errorCount += 1
    current.maxDuration = Math.max(current.maxDuration, Number(item.duration_ms || 0))
    summary.set(service, current)
  })
  return [...summary.values()]
    .sort((a, b) => b.count - a.count || b.maxDuration - a.maxDuration)
    .slice(0, 6)
})

const rootSpan = computed(() =>
  traceSpans.value.find((item) => item.parent_span_id === -1 || item.parent_span_id === '-1' || item.parent_span_id === '' || item.parent_span_id === null)
  || traceSpans.value[0]
  || null
)

const traceTitle = computed(() =>
  rootSpan.value?.endpoint_name
  || rootSpan.value?.service_code
  || traceDetail.value?.service_name
  || 'Trace Timeline'
)

const traceContextService = computed(() =>
  traceDetail.value?.service_name
  || rootSpan.value?.service_code
  || serviceNameById(filters.serviceId)
  || filters.serviceId
  || ''
)

const timeRangeSummary = computed(() => {
  const [start, end] = normalizeTimeRange(filters.timeRange)
  if (!start || !end) return `${filters.durationMinutes} 分钟`
  return `${formatMinuteTime(start)} ~ ${formatMinuteTime(end)}`
})

const waterfallRows = computed(() => {
  const spans = traceSpans.value
  if (!spans.length) return []
  const spanMap = new Map(spans.map((item) => [String(item.span_id), item]))
  const depthCache = new Map()
  const spanColors = ['#2563eb', '#0f766e', '#ea580c', '#7c3aed', '#db2777', '#0891b2', '#65a30d', '#9333ea', '#d97706', '#0284c7']
  const spanAccentColors = ['#38bdf8', '#2dd4bf', '#fb923c', '#a78bfa', '#f472b6', '#22d3ee', '#a3e635', '#c084fc', '#fbbf24', '#67e8f9']
  const startValues = spans.map((item) => parseTimeValue(item.start_time)).filter(Boolean)
  const minStart = startValues.length ? Math.min(...startValues) : 0
  const total = Math.max(Number(traceDetail.value?.duration_ms || 0), 1)

  const calcDepth = (span) => {
    const key = String(span.span_id)
    if (depthCache.has(key)) return depthCache.get(key)
    const parent = spanMap.get(String(span.parent_span_id))
    const depth = parent ? calcDepth(parent) + 1 : 0
    depthCache.set(key, depth)
    return depth
  }

  return [...spans]
    .sort((a, b) => parseTimeValue(a.start_time) - parseTimeValue(b.start_time))
    .map((span, index) => {
      const start = parseTimeValue(span.start_time)
      const offset = Math.max(0, start - minStart)
      const left = (offset / total) * 100
      const width = Math.max((Number(span.duration_ms || 0) / total) * 100, 2)
      const spanColor = span.is_error ? '#ef4444' : spanColors[index % spanColors.length]
      const spanAccentColor = span.is_error ? '#f97316' : spanAccentColors[index % spanAccentColors.length]
      const safeLeft = Math.min(left, 98)
      const safeWidth = Math.min(width, 100 - safeLeft)
      return {
        ...span,
        depth: calcDepth(span),
        offset_ms: offset,
        left_pct: safeLeft,
        width_pct: safeWidth,
        serviceColor: spanColor,
        spanColor,
        barStyle: {
          left: `${safeLeft}%`,
          width: `${safeWidth}%`,
          background: `linear-gradient(90deg, ${spanColor}, ${spanAccentColor})`,
        },
      }
    })
})

const filteredTimelineRows = computed(() => {
  const keyword = spanUi.keyword.trim().toLowerCase()
  return waterfallRows.value.filter((row) => {
    if (spanUi.service && row.service_code !== spanUi.service) return false
    if (spanUi.errorsOnly && !row.is_error) return false
    if (spanUi.slowOnly && Number(row.duration_ms || 0) < slowThreshold) return false
    if (!keyword) return true
    const haystack = [
      row.endpoint_name,
      row.service_code,
      row.service_instance_name,
      row.peer,
      row.layer,
      ...(row.tags || []).map((tag) => `${tag.key} ${tag.value}`),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(keyword)
  })
})

const minimapRows = computed(() => waterfallRows.value.slice(0, 80))

const criticalSpanIds = computed(() => {
  const rows = [...waterfallRows.value]
    .sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
    .slice(0, Math.min(4, waterfallRows.value.length))
  if (rootSpan.value) rows.push(rootSpan.value)
  return new Set(rows.map((item) => String(item.span_id)))
})

function parseTimeValue(value) {
  return parseDateValue(value)?.getTime() || 0
}

function serviceNameById(serviceId) {
  return services.value.find((item) => item.id === serviceId)?.name || ''
}

function formatDuration(value) {
  return `${Number(value || 0)} ms`
}

function formatTime(value) {
  if (!value) return '--'
  const date = parseDateValue(value)
  return !date || Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatListTime(value) {
  if (!value) return '--'
  const date = parseDateValue(value)
  if (!date || Number.isNaN(date.getTime())) return String(value)
  const now = new Date()
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
  return date.toLocaleString('zh-CN', sameDay
    ? { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }
    : { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function parseDateValue(value) {
  if (value === undefined || value === null || value === '') return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value

  const raw = String(value).trim()
  if (!raw) return null

  const compactMatch = raw.match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?$/)
  if (compactMatch) {
    const [, year, month, day, hour, minute, second = '00'] = compactMatch
    const date = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const numeric = Number(raw)
  if (Number.isFinite(numeric) && /^-?\d+(\.\d+)?$/.test(raw)) {
    const absValue = Math.abs(numeric)
    let milliseconds = numeric
    if (absValue < 100000000000) {
      milliseconds = numeric * 1000
    } else if (absValue >= 100000000000000000) {
      milliseconds = numeric / 1000000
    } else if (absValue >= 100000000000000) {
      milliseconds = numeric / 1000
    }
    const date = new Date(milliseconds)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const normalized = raw.includes(' ') && !raw.includes('T') ? raw.replace(' ', 'T') : raw
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatLog(items = []) {
  return items.map((item) => `${item.key}: ${item.value}`).join(' | ')
}

function normalizeTimeRange(value) {
  if (!Array.isArray(value) || value.length !== 2) return [null, null]
  const start = value[0] instanceof Date ? value[0] : new Date(value[0])
  const end = value[1] instanceof Date ? value[1] : new Date(value[1])
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return [null, null]
  return start.getTime() <= end.getTime() ? [start, end] : [end, start]
}

function minutesBetweenDates(start, end) {
  return Math.max(5, Math.ceil((end.getTime() - start.getTime()) / 60000))
}

function matchesDurationPreset(value, minutes) {
  const [start, end] = normalizeTimeRange(value)
  if (!start || !end) return false
  return Math.abs((end.getTime() - start.getTime()) - (minutes * 60 * 1000)) <= 60 * 1000
}

function syncDurationMinutesFromTimeRange() {
  const [start, end] = normalizeTimeRange(filters.timeRange)
  if (!start || !end) return
  filters.durationMinutes = minutesBetweenDates(start, end)
}

function formatMinuteTime(value) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function traceTimeRangePayload() {
  const [start, end] = normalizeTimeRange(filters.timeRange)
  if (!start || !end) return { start_time: '', end_time: '' }
  return {
    start_time: start.toISOString(),
    end_time: end.toISOString(),
  }
}

function formatDatasourceSummary(row) {
  const config = row?.config || {}
  if (row?.provider === 'skywalking') return [config.oap_url, config.ui_url].filter(Boolean).join(' / ') || '未配置 SkyWalking 地址'
  return [config.query_url, config.ui_url].filter(Boolean).join(' / ') || '未配置查询地址'
}

function providerNameByKey(provider) {
  return providers.value.find((item) => item.provider === provider)?.provider_name || provider || '--'
}

function traceServiceName(row) {
  return row?.service_name || serviceNameById(row?.service_id) || '--'
}

function tracePrimaryEndpoint(row) {
  return (row?.endpoint_names || []).find(Boolean) || traceServiceName(row)
}

function shortTraceId(traceId) {
  const value = String(traceId || '')
  if (value.length <= 14) return value || '--'
  return `${value.slice(0, 6)}…${value.slice(-6)}`
}

function ellipsisText(value, max = 18) {
  const text = String(value || '')
  if (text.length <= max) return text || '--'
  return `${text.slice(0, Math.max(1, max - 1))}…`
}

function traceHeatStyle(row) {
  const value = Number(row?.duration_ms || 0)
  const ratio = Math.min(100, Math.max(8, (value / traceListMaxDuration.value) * 100))
  return {
    width: `${ratio}%`,
    background: row?.is_error
      ? 'linear-gradient(90deg, #ef4444, #f97316)'
      : value >= slowThreshold
        ? 'linear-gradient(90deg, #f59e0b, #f97316)'
        : 'linear-gradient(90deg, #2563eb, #38bdf8)',
  }
}

function focusSpan(spanId) {
  if (spanId === undefined || spanId === null || !selectedTraceId.value) return
  const next = new Set(expandedSpanIds.value)
  next.add(String(spanId))
  expandedSpanIds.value = next
  selectedSpanId.value = String(spanId)
  nextTick(() => {
    document.getElementById(`span-${selectedTraceId.value}-${spanId}`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  })
}

function isSpanExpanded(spanId) {
  return expandedSpanIds.value.has(String(spanId))
}

function toggleSpanDetails(row) {
  const spanId = String(row?.span_id ?? '')
  if (!spanId) return
  const next = new Set(expandedSpanIds.value)
  if (next.has(spanId)) {
    next.delete(spanId)
  } else {
    next.add(spanId)
  }
  expandedSpanIds.value = next
  selectedSpanId.value = spanId
}

function resetSpanWorkbench(spans = []) {
  spanUi.keyword = ''
  spanUi.service = ''
  spanUi.errorsOnly = false
  spanUi.slowOnly = false
  const root = spans.find((item) => item.parent_span_id === -1 || item.parent_span_id === '-1' || item.parent_span_id === '' || item.parent_span_id === null) || spans[0]
  selectedSpanId.value = root ? String(root.span_id) : ''
  expandedSpanIds.value = root ? new Set([String(root.span_id)]) : new Set()
}

function resetFilters() {
  filters.traceState = 'ALL'
  filters.durationMinutes = DEFAULT_DURATION_MINUTES
  filters.timeRange = buildRelativeTimeRange(DEFAULT_DURATION_MINUTES)
  filters.keyword = ''
  filters.traceId = ''
  filters.limit = 20
  filters.sortBy = 'latest'
  if (services.value.length) {
    filters.serviceId = services.value[0].id
  }
}

function serviceIdFromRouteValue(raw) {
  if (!raw) return ''
  return services.value.find((item) => item.id === raw || item.name === raw || item.short_name === raw)?.id || ''
}

function routeWindowMinutes() {
  const raw = Number(route.query.window || 0)
  if (!Number.isFinite(raw) || raw <= 0) return DEFAULT_DURATION_MINUTES
  return raw
}

async function loadOverview() {
  overview.value = await getObservabilityOverview({ provider: filters.provider, datasource_id: filters.datasourceId })
}

async function loadTracingDataSources() {
  if (!canViewTraceDataSources.value) {
    tracingDataSources.value = []
    return
  }
  const response = await getTracingDataSources({ is_enabled: 'true' })
  tracingDataSources.value = Array.isArray(response) ? response : response.results || []
}

async function loadCatalog() {
  loading.catalog = true
  try {
    const response = await getTracingCatalog({ provider: filters.provider, datasource_id: filters.datasourceId })
    tracing.value = response.tracing || {}
    providers.value = response.providers || []
    services.value = response.services || []
    topology.value = response.topology || {}
    searchSummary.value = response.summary || {}
    traces.value = response.recent_traces || []
    if (!filters.provider) {
      filters.provider = response.tracing?.provider || providers.value[0]?.provider || 'demo'
    }
    if (!filters.datasourceId && response.tracing?.datasource_id) {
      filters.datasourceId = String(response.tracing.datasource_id)
    }
    if (!filters.serviceId && services.value.length) {
      filters.serviceId = services.value[0].id
    }
    await nextTick()
    renderTopology()
    if (traces.value.length) {
      await selectTrace(traces.value[0])
    }
  } finally {
    loading.catalog = false
  }
}

async function runSearch(selectFirst = true) {
  loading.search = true
  try {
    const rangePayload = traceTimeRangePayload()
    const response = await searchTracing({
      provider: filters.provider,
      datasource_id: filters.datasourceId,
      service_id: filters.serviceId,
      trace_state: filters.traceState,
      duration_minutes: filters.durationMinutes,
      start_time: rangePayload.start_time,
      end_time: rangePayload.end_time,
      keyword: filters.keyword,
      trace_id: filters.traceId,
      limit: filters.limit,
    })
    tracing.value = response.tracing || tracing.value
    providers.value = response.providers || providers.value
    services.value = response.services || services.value
    traces.value = response.traces || []
    searchSummary.value = response.summary || {}
    if (selectFirst && traces.value.length) {
      await selectTrace(traces.value[0])
    } else if (!traces.value.length) {
      selectedTraceId.value = ''
      selectedSpanId.value = ''
      expandedSpanIds.value = new Set()
      traceDetail.value = null
    }
  } finally {
    loading.search = false
  }
}

async function applyRouteTracePreset(force = false) {
  const traceId = typeof route.query.traceId === 'string' ? route.query.traceId.trim() : ''
  const provider = typeof route.query.provider === 'string' ? route.query.provider.trim() : ''
  const datasourceId = typeof route.query.datasourceId === 'string' ? route.query.datasourceId.trim() : ''
  let contextChanged = false
  if (provider && provider !== filters.provider) {
    filters.provider = provider
    contextChanged = true
  }
  if (datasourceId && datasourceId !== filters.datasourceId) {
    filters.datasourceId = datasourceId
    contextChanged = true
  }
  if (!traceId && contextChanged) {
    filters.serviceId = ''
    selectedTraceId.value = ''
    selectedSpanId.value = ''
    expandedSpanIds.value = new Set()
    traceDetail.value = null
    await loadOverview()
    await loadTracingDataSources()
    await loadCatalog()
    return true
  }
  if (!traceId) return false
  if (!force && filters.traceId === traceId) return false
  filters.traceId = traceId
  filters.keyword = typeof route.query.keyword === 'string' ? route.query.keyword.trim() : ''
  filters.serviceId = serviceIdFromRouteValue(typeof route.query.service === 'string' ? route.query.service.trim() : '')
  filters.durationMinutes = routeWindowMinutes()
  filters.timeRange = buildRelativeTimeRange(filters.durationMinutes)
  filters.traceState = 'ALL'
  await runSearch(true)
  return true
}

async function loadTrace(traceId) {
  if (!traceId) return
  loading.detail = true
  try {
    const response = await getTraceDetail(traceId, { provider: filters.provider, datasource_id: filters.datasourceId })
    tracing.value = response.tracing || tracing.value
    providers.value = response.providers || providers.value
    traceDetail.value = response.trace || null
    selectedTraceId.value = traceId
    resetSpanWorkbench(response.trace?.spans || [])
  } finally {
    loading.detail = false
  }
}

async function selectTrace(row) {
  if (!row?.trace_id) return
  await loadTrace(row.trace_id)
}

async function refreshAll() {
  await loadTracingDataSources()
  await loadOverview()
  await loadCatalog()
  if (services.value.length) {
    await runSearch(false)
  }
}

function openTracingUi() {
  const url = selectedProviderMeta.value?.ui_url || selectedProviderMeta.value?.query_url || selectedProviderMeta.value?.oap_url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function changeTraceTab(tabName) {
  const tab = String(tabName || 'traces')
  router.replace({
    path: route.path,
    query: {
      ...route.query,
      tab: tab === 'datasources' ? 'datasources' : undefined,
    },
  })
}

async function changeProvider(provider) {
  if (!provider) return
  filters.provider = provider
  filters.datasourceId = ''
  filters.serviceId = ''
  selectedTraceId.value = ''
  selectedSpanId.value = ''
  expandedSpanIds.value = new Set()
  traceDetail.value = null
  await router.replace({
    path: route.path,
    query: {
      ...route.query,
      provider,
      datasourceId: undefined,
      traceId: undefined,
      service: undefined,
      keyword: undefined,
    },
  })
  await loadTracingDataSources()
  await loadOverview()
  await loadCatalog()
}

async function changeDataSource(datasourceId) {
  filters.datasourceId = datasourceId || ''
  const datasource = selectedTracingDataSource.value
  if (datasource?.provider && datasource.provider !== filters.provider) {
    filters.provider = datasource.provider
  }
  filters.serviceId = ''
  selectedTraceId.value = ''
  selectedSpanId.value = ''
  expandedSpanIds.value = new Set()
  traceDetail.value = null
  await router.replace({
    path: route.path,
    query: {
      ...route.query,
      provider: filters.provider || undefined,
      datasourceId: filters.datasourceId || undefined,
      traceId: undefined,
      service: undefined,
      keyword: undefined,
    },
  })
  await loadOverview()
  await loadCatalog()
}

function openLogsForTrace(row) {
  if (!canQueryLogs.value || !row?.trace_id) return
  router.push({
    path: '/logs/query',
    query: {
      traceId: row.trace_id,
      service: row.service_name || row.service_id || '',
      provider: filters.provider,
      datasourceId: filters.datasourceId,
      window: String(filters.durationMinutes || 60),
      autoRun: '1',
    },
  })
}

function openLogsForCurrentTrace() {
  openLogsForTrace({
    trace_id: selectedTraceId.value,
    service_name: traceContextService.value,
  })
}

function openAlertsForTrace() {
  if (!canViewAlerts.value || !selectedTraceId.value) return
  router.push({
    path: '/alerts',
    query: {
      search: traceContextService.value || selectedTraceId.value,
      level: traceDetail.value?.error_count ? 'critical' : undefined,
      ack: traceDetail.value?.error_count ? '0' : undefined,
    },
  })
}

function openDeploymentsForTrace() {
  if (!canViewDeployments.value || !selectedTraceId.value) return
  router.push({
    path: '/workorders/releases',
    query: {
      keyword: traceContextService.value || traceTitle.value,
      service: traceContextService.value || undefined,
      traceId: selectedTraceId.value,
      source: 'trace',
    },
  })
}

function openGrafanaForTrace() {
  if (!canViewGrafana.value || !selectedTraceId.value) return
  router.push({
    path: '/observability/grafana',
    query: {
      dashboard: 'apm-overview',
      service: traceContextService.value || undefined,
      traceId: selectedTraceId.value,
      provider: filters.provider || undefined,
    },
  })
}

function renderTopology() {
  if (!topologyChartRef.value) return
  if (topologyChart && topologyChart.getDom() !== topologyChartRef.value) {
    topologyChart.dispose()
    topologyChart = null
  }
  if (!topologyChart) topologyChart = echarts.init(topologyChartRef.value)

  const topologyData = focusedTopology.value || {}
  const rawNodes = topologyData.nodes || []
  const rawLinks = topologyData.calls || []
  const selectedNodeId = String(topologyData.selected_node_id || '')
  const chartWidth = topologyChartRef.value.clientWidth || 780
  const chartHeight = topologyChartRef.value.clientHeight || 240
  const upstreamIds = rawLinks.filter((item) => item.target === selectedNodeId).map((item) => item.source)
  const downstreamIds = rawLinks.filter((item) => item.source === selectedNodeId).map((item) => item.target)
  const middleIds = rawNodes
    .map((item) => item.id)
    .filter((id) => id !== selectedNodeId && !upstreamIds.includes(id) && !downstreamIds.includes(id))

  const placeColumn = (ids, x) => {
    const count = ids.length || 1
    return new Map(
      ids.map((id, index) => [
        id,
        {
          x,
          y: ((index + 1) * chartHeight) / (count + 1),
        },
      ])
    )
  }

  const upstreamPositions = placeColumn(upstreamIds, chartWidth * 0.22)
  const downstreamPositions = placeColumn(downstreamIds, chartWidth * 0.78)
  const middlePositions = placeColumn(middleIds, chartWidth * 0.5)

  const nodes = rawNodes.map((item, index) => {
    const nodeId = String(item.id || '')
    const position = nodeId === selectedNodeId
      ? { x: chartWidth * 0.5, y: chartHeight * 0.5 }
      : upstreamPositions.get(nodeId) || downstreamPositions.get(nodeId) || middlePositions.get(nodeId) || { x: chartWidth * 0.5, y: chartHeight * 0.5 }
    const color = nodeId === selectedNodeId
      ? '#2563eb'
      : upstreamIds.includes(nodeId)
        ? '#0f766e'
        : downstreamIds.includes(nodeId)
          ? '#ea580c'
          : ['#7c3aed', '#0891b2', '#64748b'][index % 3]
    return {
      id: item.id,
      name: item.name,
      value: item.name,
      x: position.x,
      y: position.y,
      symbolSize: nodeId === selectedNodeId ? 54 : 40,
      itemStyle: {
        color,
        borderColor: nodeId === selectedNodeId ? 'rgba(191, 219, 254, 0.95)' : '#ffffff',
        borderWidth: nodeId === selectedNodeId ? 4 : 2,
        shadowBlur: nodeId === selectedNodeId ? 18 : 8,
        shadowColor: nodeId === selectedNodeId ? 'rgba(37, 99, 235, 0.28)' : 'rgba(15, 23, 42, 0.08)',
      },
      label: {
        position: 'bottom',
        formatter: () => ellipsisText(item.name, nodeId === selectedNodeId ? 18 : 14),
      },
    }
  })

  const links = rawLinks.map((item) => ({
    source: item.source,
    target: item.target,
    value: item.count || 0,
    lineStyle: {
      color: item.source === selectedNodeId ? '#fdba74' : '#99f6e4',
      width: Math.min(4, 1.6 + Number(item.count || 0) * 0.2),
      opacity: 0.95,
      curveness: 0.04,
    },
    symbol: ['none', 'arrow'],
    symbolSize: 8,
  }))

  topologyChart.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          if (params.dataType === 'edge') {
            const count = params.data?.value ? ` · ${params.data.value} 次` : ''
            return `${params.data.source} → ${params.data.target}${count}`
          }
          return params.data?.name || ''
        },
      },
      series: [
        {
          type: 'graph',
          layout: 'none',
          roam: true,
          draggable: true,
          label: { show: true, color: '#0f172a', fontSize: 11, distance: 8 },
          emphasis: {
            focus: 'adjacency',
            scale: true,
            lineStyle: {
              width: 3,
            },
          },
          data: nodes,
          links,
          lineStyle: { opacity: 0.92 },
        },
      ],
    },
    true
  )
  topologyChart.resize()
}

function handleResize() {
  topologyChart?.resize()
}

watch(
  () => [topology.value, filters.serviceId],
  async () => {
    topologyListPage.value = 1
    await nextTick()
    renderTopology()
  },
  { deep: true }
)

watch(topologyExpanded, async (expanded) => {
  if (!expanded) {
    topologyChart?.dispose()
    topologyChart = null
    return
  }
  await nextTick()
  renderTopology()
  setTimeout(() => {
    if (topologyExpanded.value) renderTopology()
  }, 60)
})

watch(
  () => filters.timeRange,
  () => {
    syncDurationMinutesFromTimeRange()
  },
  { deep: true, immediate: true }
)

watch(
  () => displayTraces.value.length,
  () => {
    if (traceListPage.value > traceListPageCount.value) {
      traceListPage.value = traceListPageCount.value
    }
    if (!displayTraces.value.length) {
      traceListPage.value = 1
    }
  },
  { immediate: true }
)

watch(
  () => selectedTraceId.value,
  (traceId) => {
    if (!traceId) return
    const index = displayTraces.value.findIndex((item) => item.trace_id === traceId)
    if (index === -1) return
    traceListPage.value = Math.floor(index / TRACE_LIST_PAGE_SIZE) + 1
  },
  { immediate: true }
)

onMounted(async () => {
  if (!canViewTrace.value) {
    activeTraceTab.value = canViewTraceDataSources.value ? 'datasources' : 'traces'
    return
  }
  filters.provider = typeof route.query.provider === 'string' ? route.query.provider : ''
  filters.datasourceId = typeof route.query.datasourceId === 'string' ? route.query.datasourceId : ''
  await loadTracingDataSources()
  await loadOverview()
  await loadCatalog()
  if (route.query.traceId) {
    await applyRouteTracePreset(true)
  } else if (!traces.value.length && services.value.length) {
    await runSearch(true)
  }
  window.addEventListener('resize', handleResize)
})

watch(
  () => [route.query.provider || '', route.query.datasourceId || '', route.query.traceId || '', route.query.service || '', route.query.keyword || '', route.query.window || ''].join('|'),
  async (value, previous) => {
    if (!value || value === previous) return
    await applyRouteTracePreset()
  }
)

watch(
  () => route.query.tab,
  (value) => {
    activeTraceTab.value = value === 'datasources' && canViewTraceDataSources.value ? 'datasources' : 'traces'
  },
  { immediate: true }
)

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  topologyChart?.dispose()
})
</script>

<style scoped>
.observability-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  padding: 12px 14px;
}

.hero,
.hero-copy,
.hero-title-row,
.hero-actions,
.section-head,
.section-head-tags,
.provider-card__title,
.toolbar-actions,
.waterfall-head,
.span-head,
.span-title,
.span-meta,
.span-tags,
.chips-wrap,
.detail-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-copy {
  gap: 4px;
}

.hero {
  align-items: center;
  justify-content: space-between;
}

.hero-title-row {
  align-items: baseline;
  gap: 12px;
}

.hero-title-row h2 {
  font-size: 23px;
  line-height: 1.1;
  margin: 0;
}

.page-inline-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.hero-icon {
  align-items: center;
  background: linear-gradient(135deg, #0f766e, #0ea5e9);
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.trace-center-tabs {
  margin-bottom: 0;
  padding: 4px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.9));
  border: 1px solid rgba(148,163,184,.16);
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.trace-center-tabs .neo-tab-btn {
  min-height: 38px;
  padding: 0 20px;
  border-radius: 8px;
}

.section-head {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.section-head h3 {
  font-size: 14px;
  line-height: 1.3;
  margin: 0;
}

.trace-query-unified-card {
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 16px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.04);
  padding: 10px 12px;
}

.trace-query-unified-head {
  align-items: center;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-bottom: 8px;
}

.trace-query-title-block {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.trace-query-title-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.trace-query-title-row h3 {
  color: #0f172a;
  font-size: 14px;
  letter-spacing: 0.01em;
  margin: 0;
}

.trace-query-unified-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trace-query-provider-strip {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
}

.trace-filter-datasource-row {
  align-items: center;
  display: flex;
  gap: 6px;
  min-height: 30px;
  width: 100%;
}

.trace-filter-service-row {
  align-items: center;
  display: flex;
  gap: 8px;
  min-height: 32px;
  padding-bottom: 6px;
  width: 100%;
}

.trace-inline-filter {
  align-items: center;
  column-gap: 8px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  min-width: 0;
}

.trace-inline-filter--compact {
  width: 100%;
}

.trace-inline-filter--time {
  min-width: 0;
  width: 100%;
}

.trace-inline-filter__label {
  color: #64748b;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  margin-right: 1px;
  white-space: nowrap;
}

.trace-query-provider-label {
  color: #64748b;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 500;
  margin-right: 4px;
  white-space: nowrap;
}

.trace-datasource-control {
  flex: 1 1 auto;
  max-width: none;
}

.compact-summary-bar {
  align-items: center;
  background: linear-gradient(180deg, #fafcff 0%, #ffffff 100%);
  border: 1px dashed rgba(148, 163, 184, 0.46);
  border-radius: 12px;
  color: #475569;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
}

.compact-summary-bar--action {
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  width: 100%;
}

.compact-summary-bar--action:hover {
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  border-color: rgba(100, 116, 139, 0.62);
}

.compact-summary-bar--action:focus-visible {
  outline: 2px solid rgba(59, 130, 246, 0.32);
  outline-offset: 2px;
}

.compact-summary-bar span {
  font-size: 11px;
}

.compact-summary-bar__hint {
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  margin-left: auto;
}

.search-panel {
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px;
}

.search-panel--merged {
  background: transparent;
  border: 0;
  border-top: 1px solid rgba(226, 232, 240, 0.64);
  border-radius: 0;
  padding: 8px 0 0;
}

.search-control,
.search-number {
  width: 100%;
}

.trace-filter-grid {
  display: grid;
  gap: 6px;
  width: 100%;
}

.trace-filter-grid--primary {
  align-items: center;
  column-gap: 8px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.08fr) minmax(0, 1.16fr) minmax(118px, 0.44fr);
}

.trace-filter-grid--advanced {
  align-items: center;
  column-gap: 8px;
  grid-template-columns: minmax(146px, 0.44fr) minmax(146px, 0.44fr) minmax(360px, 1fr) auto;
  margin-top: 7px;
}

.trace-filter-grid--toolbar {
  align-items: center;
  justify-content: flex-start;
  padding: 0;
}

.advanced-filter-control {
  width: 100%;
}

.advanced-filter-number {
  width: 100%;
}

.advanced-filter-time {
  min-width: 0;
  width: 100%;
}

.trace-filter-actions {
  align-items: center;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.96);
  border-radius: 10px;
  display: flex;
  gap: 4px;
  justify-content: flex-end;
  justify-self: end;
  min-height: 30px;
  padding: 3px;
  white-space: nowrap;
  width: auto;
}

.trace-filter-actions .el-button + .el-button {
  margin-left: 0;
}

.search-control :deep(.el-select__wrapper),
.search-control :deep(.el-input__wrapper),
.search-control :deep(.el-range-editor.el-input__wrapper),
.search-number :deep(.el-input__wrapper) {
  background: rgba(248, 250, 252, 0.82);
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(226, 232, 240, 0.92) inset;
  min-height: 30px;
}

.search-control :deep(.el-input__inner),
.search-control :deep(.el-select__selected-item),
.search-control :deep(.el-range-input),
.search-number :deep(.el-input__inner) {
  font-size: 12px;
}

.search-control :deep(.el-select__wrapper:hover),
.search-control :deep(.el-input__wrapper:hover),
.search-control :deep(.el-range-editor.el-input__wrapper:hover),
.search-number :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(191, 219, 254, 0.96) inset;
}

.search-action-primary {
  border-radius: 8px;
  box-shadow: none;
  font-size: 13px;
  font-weight: 600;
  min-width: 84px;
  min-height: 28px;
  padding-inline: 12px;
}

.search-action-secondary {
  background: transparent;
  border-color: transparent;
  color: #64748b;
  font-size: 12px;
  min-height: 28px;
  padding-inline: 10px;
}

.advanced-filter-time :deep(.el-range-input),
.advanced-filter-time :deep(.el-range-separator) {
  font-size: 11px;
}

.advanced-filter-time :deep(.el-range-editor.el-input__wrapper) {
  gap: 6px;
  justify-content: flex-start;
}

.advanced-filter-time :deep(.el-range-input) {
  flex: 1 1 0;
  min-width: 0;
  text-align: left;
}

.advanced-filter-time :deep(.el-range-separator) {
  color: #64748b;
  flex: 0 0 18px;
  text-align: center;
}

.advanced-filter-time :deep(.el-range__icon) {
  color: #94a3b8;
  margin-right: 2px;
}

.search-action-secondary:hover {
  background: #ffffff;
  border-color: rgba(203, 213, 225, 0.9);
  color: #1e3a8a;
}

.search-summary-bar {
  align-items: center;
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
}

.time-range-picker {
  width: 100%;
}

.search-summary-bar {
  align-items: center;
  border-top: 1px solid rgba(241, 245, 249, 0.92);
  display: flex;
  flex-wrap: nowrap;
  margin-top: 6px;
  padding-top: 6px;
}

.trace-query-summary-bar {
  margin-top: 2px;
}

.trace-query-summary-bar::-webkit-scrollbar {
  display: none;
}

.topology-layout {
  align-items: stretch;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.7fr) 178px;
}

.topology-chart {
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 12px;
  height: 300px;
}

.topology-side {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 300px;
  justify-content: flex-start;
  min-height: 300px;
}

.topology-list {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 3px;
  min-height: 0;
  overflow: hidden;
}

.topology-item {
  background: #fbfdff;
  border: 1px solid rgba(226, 232, 240, 0.88);
  border-radius: 9px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 7px;
}

.topology-item-main {
  align-items: center;
  display: flex;
  gap: 6px;
  justify-content: space-between;
  min-width: 0;
}

.topology-item strong {
  color: #0f172a;
  flex: 1 1 auto;
  font-size: 11px;
  line-height: 1.2;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topology-item-role {
  border-radius: 999px;
  display: inline-flex;
  font-size: 9px;
  line-height: 1;
  padding: 1px 5px;
  white-space: nowrap;
}

.topology-item.is-selected .topology-item-role {
  background: rgba(219, 234, 254, 0.95);
  color: #1d4ed8;
}

.topology-item.is-upstream .topology-item-role {
  background: rgba(204, 251, 241, 0.95);
  color: #0f766e;
}

.topology-item.is-downstream .topology-item-role {
  background: rgba(255, 237, 213, 0.95);
  color: #c2410c;
}

.topology-item.is-peer .topology-item-role {
  background: rgba(241, 245, 249, 0.95);
  color: #475569;
}

.topology-item-meta,
.topology-item span,
.chips-title,
.span-log-item span {
  color: var(--text-secondary);
  font-size: 10px;
}

.topology-item-meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topology-pagination {
  align-items: center;
  display: flex;
  flex: 0 0 auto;
  gap: 5px;
  justify-content: center;
  padding-top: 0;
}

.topology-page-btn {
  padding: 4px 8px;
}

.content-grid {
  align-items: start;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(340px, 0.8fr) minmax(0, 1.4fr);
}

.content-grid.has-selected-trace {
  grid-template-columns: minmax(280px, 0.52fr) minmax(0, 1.68fr);
}

.traces-panel {
  display: flex;
  flex-direction: column;
  max-height: none;
  min-height: 860px;
  overflow: hidden;
}

.query-pill {
  background: rgba(248, 250, 252, 0.82);
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 999px;
  color: #64748b;
  font-size: 10px;
  flex: 0 0 auto;
  padding: 3px 7px;
  white-space: nowrap;
}

.trace-results {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.trace-pagination {
  align-items: center;
  display: flex;
  gap: 6px;
  justify-content: center;
  margin-top: 8px;
  padding-top: 4px;
}

.trace-page-btn {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  color: #334155;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  padding: 5px 9px;
}

.trace-page-btn:disabled {
  color: #94a3b8;
  cursor: not-allowed;
  opacity: 0.7;
}

.trace-page-indicator {
  color: #64748b;
  font-size: 11px;
}

.trace-result-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  overflow: hidden;
  transition: all 0.2s ease;
}

.trace-result-card.is-active {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96) 0%, #ffffff 100%);
  border-color: rgba(37, 99, 235, 0.34);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.08);
}

.trace-result-card.is-error {
  border-color: rgba(239, 68, 68, 0.2);
}

.trace-result-card.is-slow:not(.is-error) {
  border-color: rgba(245, 158, 11, 0.24);
}

.trace-result-main {
  background: transparent;
  border: 0;
  cursor: pointer;
  display: block;
  padding: 6px 8px;
  text-align: left;
  width: 100%;
}

.trace-result-main:hover {
  background: rgba(248, 250, 252, 0.7);
}

.trace-result-line {
  min-width: 0;
}

.trace-result-line.two-line-layout {
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.15;
  min-width: 0;
  padding-left: 10px;
  position: relative;
}

.trace-title-row {
  align-items: center;
  display: flex;
  min-width: 0;
}

.trace-accent-bar {
  background: linear-gradient(180deg, #f59e0b 0%, #fb923c 100%);
  border-radius: 999px;
  bottom: 2px;
  left: 0;
  position: absolute;
  top: 2px;
  width: 3px;
}

.trace-result-card.is-active .trace-accent-bar {
  background: linear-gradient(180deg, #2563eb 0%, #0ea5e9 100%);
}

.trace-accent-bar.is-error {
  background: linear-gradient(180deg, #ef4444 0%, #f97316 100%);
}

.trace-accent-bar.is-slow:not(.is-error) {
  background: linear-gradient(180deg, #f59e0b 0%, #f97316 100%);
}

.trace-meta-row {
  align-items: center;
  display: flex;
  gap: 6px;
  min-width: 0;
}

.trace-result-operation {
  color: #0f172a;
  font-weight: 700;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.trace-duration-pill {
  background: rgba(37, 99, 235, 0.08);
  border-radius: 999px;
  color: #1d4ed8;
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  min-width: 42px;
  padding: 3px 7px;
  text-align: center;
}

.trace-duration-pill.is-slow {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.trace-status-pill {
  background: rgba(22, 163, 74, 0.1);
  border-radius: 999px;
  color: #15803d;
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  padding: 3px 7px;
}

.trace-status-pill.is-error {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.trace-result-time {
  color: #64748b;
  font-size: 10px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-panel {
  max-height: none;
  min-height: 860px;
  overflow: hidden;
}

.trace-workbench {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.trace-header-card {
  align-items: start;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  border: 1px solid #dbeafe;
  border-radius: 12px;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.8fr) minmax(320px, 1fr);
  padding: 8px 10px;
}

.trace-title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.trace-title-row-main {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.trace-title-block h3 {
  flex: 1;
  font-size: 16px;
  line-height: 1.15;
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-provider-pill {
  align-self: flex-start;
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 999px;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
}

.trace-header-meta,
.trace-id-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.trace-header-meta {
  justify-content: space-between;
}

.trace-id-row span,
.trace-kpi span,
.detail-label,
.operation-cell span,
.timeline-detail strong,
.timeline-duration {
  color: var(--text-secondary);
  font-size: 11px;
}

.trace-id-row code {
  background: rgba(15, 23, 42, 0.05);
  border-radius: 8px;
  color: #0f172a;
  font-size: 11px;
  max-width: 260px;
  overflow: hidden;
  padding: 2px 6px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-kpi-grid {
  display: grid;
  gap: 4px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.trace-kpi {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  justify-content: center;
  min-height: 42px;
  padding: 5px 7px;
}

.trace-kpi strong {
  color: #0f172a;
  font-size: 14px;
}

.trace-context-actions {
  align-items: center;
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.06), rgba(14, 165, 233, 0.03));
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 10px;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 5px 8px;
}

.context-copy {
  align-items: baseline;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.context-copy strong {
  color: #0f172a;
  flex: 0 0 auto;
  font-size: 12px;
  line-height: 1.2;
}

.context-copy span {
  color: #64748b;
  font-size: 11px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-actions {
  align-items: center;
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
}

.context-action-btn {
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  color: #334155;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  padding: 5px 8px;
}

.context-action-btn:hover {
  border-color: rgba(37, 99, 235, 0.28);
  color: #1d4ed8;
}

.context-action-btn.primary {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.18);
  color: #1d4ed8;
}

.danger-kpi {
  background: rgba(254, 242, 242, 0.92);
  border-color: rgba(239, 68, 68, 0.18);
}

.trace-minimap {
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 2px 0 0;
}

.trace-header-minimap {
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 10px;
  display: grid;
  gap: 4px;
  grid-column: 1 / -1;
  margin-top: -2px;
  padding: 4px 6px;
  grid-template-columns: 132px minmax(0, 1fr);
}

.trace-minimap-head,
.span-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: space-between;
}

.trace-header-minimap .trace-minimap-head {
  align-items: flex-start;
  flex-direction: column;
  gap: 1px;
  justify-content: center;
}

.trace-minimap-head span {
  color: var(--text-secondary);
  font-size: 11px;
}

.trace-minimap-head strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.1;
}

.minimap-track {
  background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
  border: 0;
  border-radius: 12px;
  height: 28px;
  margin-top: 0;
  position: relative;
}

.minimap-segment {
  border: 0;
  border-radius: 999px;
  cursor: pointer;
  height: 8px;
  opacity: 0.9;
  position: absolute;
  top: 9px;
}

.minimap-segment.is-error {
  box-shadow: inset 0 0 0 1px rgba(127, 29, 29, 0.14);
}

.minimap-segment.is-selected {
  height: 12px;
  margin-top: -2px;
  box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.12);
}

.trace-insights {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.insight-pill {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  color: #334155;
  cursor: pointer;
  font-size: 10px;
  padding: 3px 7px;
}

.error-pill {
  background: rgba(254, 242, 242, 0.92);
  border-color: rgba(239, 68, 68, 0.18);
  color: #b91c1c;
}

.slow-pill {
  background: rgba(255, 251, 235, 0.94);
  border-color: rgba(245, 158, 11, 0.2);
  color: #b45309;
}

.service-pill {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.14);
  color: #1d4ed8;
  cursor: default;
}

.span-toolbar {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 4px 8px;
}

.span-toolbar :deep(.el-input),
.span-toolbar :deep(.el-select) {
  width: 172px;
}

.span-toolbar :deep(.el-input__wrapper),
.span-toolbar :deep(.el-select__wrapper) {
  min-height: 26px;
}

.span-filter-toggle {
  align-items: center;
  display: flex;
  gap: 4px;
}

.span-filter-label {
  color: #94a3b8;
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
}

.span-filter-segment {
  align-items: center;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  display: inline-flex;
  padding: 2px;
}

.span-filter-option {
  background: transparent;
  border: 0;
  border-radius: 999px;
  color: #94a3b8;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  padding: 4px 7px;
  transition: all 0.2s ease;
}

.span-filter-option:hover {
  color: #64748b;
}

.span-filter-option.is-active {
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
  font-weight: 600;
}

.trace-timeline-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.timeline-axis-row {
  align-items: center;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  border-bottom: 1px solid #e2e8f0;
  color: #94a3b8;
  display: grid;
  font-size: 10px;
  gap: 8px;
  grid-template-columns: 220px minmax(0, 1fr) 64px;
  padding: 5px 8px;
}

.timeline-axis {
  display: flex;
  justify-content: space-between;
}

.timeline-body {
  display: flex;
  flex-direction: column;
}

.timeline-row {
  align-items: center;
  background: #fff;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  cursor: default;
  display: grid;
  gap: 6px;
  grid-template-columns: 220px minmax(0, 1fr) 64px;
  padding: 5px 8px;
  text-align: left;
  width: 100%;
}

.timeline-row:hover {
  background: #f8fafc;
}

.timeline-row.is-error {
  background: rgba(254, 242, 242, 0.52);
}

.timeline-row.is-slow .timeline-duration {
  color: #d97706;
}

.timeline-row.is-selected {
  background: rgba(239, 246, 255, 0.95);
}

.timeline-row.is-critical .operation-cell strong::after {
  color: #2563eb;
  content: '  critical';
  font-size: 10px;
  font-weight: 600;
}

.timeline-label {
  align-items: center;
  display: flex;
  gap: 5px;
  min-width: 0;
}

.expand-mark {
  color: #64748b;
  flex: 0 0 auto;
  font-size: 10px;
}

.service-dot {
  border-radius: 999px;
  flex: 0 0 auto;
  height: 7px;
  width: 7px;
}

.operation-cell {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}

.operation-cell strong {
  font-size: 11px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.operation-cell span {
  color: #64748b;
  font-size: 10px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-track {
  background: repeating-linear-gradient(90deg, rgba(226, 232, 240, 0.72) 0, rgba(226, 232, 240, 0.72) 1px, transparent 1px, transparent 20%);
  border-radius: 999px;
  height: 8px;
  position: relative;
}

.timeline-bar {
  border-radius: 999px;
  height: 8px;
  position: absolute;
  top: 0;
}

.timeline-duration {
  font-size: 10px;
  text-align: right;
}

.timeline-detail {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.72) 0%, #ffffff 100%);
  border-bottom: 1px solid #e2e8f0;
  padding: 6px 8px 8px 18px;
}

.timeline-detail-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 6px;
}

.timeline-detail-grid > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.timeline-detail-grid strong {
  color: #0f172a;
  font-size: 11px;
}

.timeline-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.span-chip {
  background: rgba(15, 118, 110, 0.08);
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-radius: 999px;
  color: #0f766e;
  font-size: 10px;
  padding: 1px 6px;
}

.span-log-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 4px;
}

.span-log-item {
  background: #fff7ed;
  border-radius: 7px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 6px;
}

.span-log-item strong {
  font-size: 10px;
}

.span-log-item span {
  font-size: 10px;
}

.embed-frame {
  border: 0;
  border-radius: 10px;
  height: 500px;
  width: 100%;
}

:deep(.el-table td.el-table__cell),
:deep(.el-table th.el-table__cell) {
  padding: 7px 0;
}

:deep(.el-table .cell) {
  line-height: 1.35;
}

@media (max-width: 1460px) {
  .trace-filter-grid--primary {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.04fr) minmax(110px, 0.4fr);
  }

  .trace-filter-grid--advanced {
    grid-template-columns: minmax(132px, 0.42fr) minmax(132px, 0.42fr) minmax(300px, 1fr) auto;
  }

  .search-action-primary {
    min-width: 78px;
    padding-inline: 10px;
  }

  .search-action-secondary {
    font-size: 12px;
  }
}

@media (max-width: 1280px) {
  .trace-kpi-grid,
  .timeline-detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .trace-query-unified-head {
    align-items: stretch;
    flex-direction: column;
  }

  .trace-filter-grid--primary,
  .trace-filter-grid--advanced {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .advanced-filter-time {
    flex: 1 1 320px;
    width: auto;
  }

  .trace-filter-actions {
    border-left: 0;
    justify-content: flex-start;
    padding-left: 0;
  }

  .trace-header-card,
  .content-grid,
  .topology-layout {
    grid-template-columns: 1fr;
  }

  .trace-header-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .content-grid.has-selected-trace {
    grid-template-columns: 1fr;
  }

  .timeline-axis-row,
  .timeline-row {
    grid-template-columns: 190px minmax(0, 1fr) 68px;
  }

  .traces-panel,
  .detail-panel {
    max-height: none;
    min-height: 0;
  }

  .trace-results,
  .trace-workbench {
    overflow: visible;
    padding-right: 0;
  }
}

@media (max-width: 760px) {
  .hero,
  .section-head,
  .trace-context-actions,
  .trace-query-unified-head {
    align-items: stretch;
    flex-direction: column;
  }

  .trace-filter-datasource-row,
  .trace-filter-service-row {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .trace-inline-filter--time {
    min-width: 0;
  }

  .trace-filter-grid--primary,
  .trace-filter-grid--advanced {
    grid-template-columns: 1fr;
  }

  .trace-filter-grid--toolbar {
    align-items: stretch;
  }

  .trace-inline-filter,
  .trace-inline-filter--compact,
  .trace-inline-filter--time {
    width: 100%;
  }

  .trace-inline-filter__label {
    margin-right: 2px;
  }

  .advanced-filter-control,
  .advanced-filter-number,
  .advanced-filter-time {
    width: 100%;
  }

  .trace-filter-actions {
    gap: 6px;
    margin-left: 0;
    width: 100%;
  }

  .context-copy {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .context-actions {
    justify-content: flex-start;
  }

  .trace-kpi-grid,
  .timeline-detail-grid {
    grid-template-columns: 1fr;
  }

  .trace-result-main {
    padding: 6px 7px;
  }

  .trace-title-row-main,
  .trace-header-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .trace-title-block h3 {
    white-space: normal;
  }

  .trace-header-minimap {
    grid-template-columns: 1fr;
  }

  .trace-header-minimap .trace-minimap-head {
    flex-direction: row;
    justify-content: space-between;
  }

  .trace-meta-row {
    gap: 5px;
  }

  .trace-duration-pill {
    min-width: 40px;
    padding: 3px 6px;
  }

  .span-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .span-toolbar :deep(.el-input),
  .span-toolbar :deep(.el-select) {
    width: 100%;
  }

  .timeline-axis-row,
  .timeline-row {
    display: flex;
    flex-direction: column;
  }

  .timeline-track {
    min-height: 14px;
    width: 100%;
  }
}
.hero.panel { border-radius: 20px; }
</style>



