<template>
  <div class="observability-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Connection /></el-icon>
          </span>
          <h2>链路追踪</h2>
          <p class="page-inline-desc">按服务、Trace 与时间窗口查看调用链</p>
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
        <el-button size="small" v-if="tracing.ui_url || tracing.oap_url" type="primary" @click="openTracingUi">
          外部打开
        </el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div v-for="item in statCards" :key="item.label" class="stat-card release-stat-card" :class="item.tone">
        <div class="stat-value">{{ item.value }}</div>
        <div class="stat-label">{{ item.label }}</div>
      </div>
    </div>

    <div class="runtime-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ runtimeHint }}</span>
    </div>

    <section class="panel">
      <div class="section-head">
        <h3>Trace 查询</h3>
        <div class="section-head-tags">
          <el-tag size="small" type="info">{{ tracing.status_text || '待接入' }}</el-tag>
          <el-tag size="small" :type="tracing.source === 'skywalking' ? 'success' : 'warning'">
            {{ tracing.source === 'skywalking' ? '实时数据' : '演示数据' }}
          </el-tag>
        </div>
      </div>

      <div class="toolbar-grid">
        <el-select v-model="filters.serviceId" size="small" clearable filterable placeholder="选择服务">
          <el-option v-for="item in services" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="filters.traceState" size="small" placeholder="Trace 状态">
          <el-option label="全部状态" value="ALL" />
          <el-option label="正常链路" value="SUCCESS" />
          <el-option label="错误链路" value="ERROR" />
        </el-select>
        <el-select v-model="filters.durationMinutes" size="small" placeholder="查询窗口">
          <el-option v-for="item in durationOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="filters.sortBy" size="small" placeholder="排序方式">
          <el-option label="最近开始" value="latest" />
          <el-option label="最慢优先" value="slowest" />
          <el-option label="错误优先" value="errors" />
        </el-select>
        <el-input size="small" v-model.trim="filters.keyword" placeholder="关键字 / 接口 / 服务名" clearable />
        <el-input size="small" v-model.trim="filters.traceId" placeholder="指定 Trace ID" clearable />
        <el-input-number size="small" v-model="filters.limit" :min="5" :max="50" :step="5" />
      </div>

      <div class="toolbar-actions">
        <el-button size="small" type="primary" @click="runSearch()" :loading="loading.search">查询 Trace</el-button>
        <el-button size="small" @click="resetFilters">重置条件</el-button>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <h3>调用拓扑</h3>
        <div class="section-head-tags">
          <el-tag size="small" type="success">节点 {{ topology.node_count || 0 }}</el-tag>
          <el-tag size="small" type="warning">调用 {{ topology.call_count || 0 }}</el-tag>
        </div>
      </div>
      <div class="topology-layout">
        <div ref="topologyChartRef" class="topology-chart" />
        <div class="topology-side">
          <div class="topology-list">
            <article v-for="item in topologyHighlights" :key="item.id" class="topology-item">
              <strong>{{ item.name }}</strong>
              <span>{{ item.layer }}</span>
            </article>
          </div>
        </div>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel traces-panel">
        <div class="section-head">
          <h3>链路列表</h3>
          <el-tag size="small" type="info">命中 {{ searchSummary.match_count || displayTraces.length }} 条</el-tag>
        </div>

        <el-empty v-if="!displayTraces.length && !loading.search" description="当前条件下未找到 Trace。" />

        <el-table v-else :data="displayTraces" stripe size="small" v-loading="loading.search" style="width: 100%">
          <el-table-column prop="trace_id" label="Trace ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="服务" min-width="150">
            <template #default="{ row }">{{ row.service_name || serviceNameById(row.service_id) || '--' }}</template>
          </el-table-column>
          <el-table-column label="入口接口" min-width="220">
            <template #default="{ row }">{{ (row.endpoint_names || []).join(' / ') || '--' }}</template>
          </el-table-column>
          <el-table-column label="耗时" width="110">
            <template #default="{ row }">
              <span :class="{ 'slow-text': row.duration_ms >= slowThreshold }">{{ formatDuration(row.duration_ms) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_error ? 'danger' : 'success'">{{ row.is_error ? '错误' : '正常' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="180">
            <template #default="{ row }">{{ formatTime(row.start) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="148" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="selectTrace(row)">查看</el-button>
              <el-button v-if="canQueryLogs" link type="warning" @click="openLogsForTrace(row)">关联日志</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel detail-panel">
        <div class="section-head">
          <h3>Trace 详情</h3>
          <div class="section-head-tags">
            <el-tag v-if="selectedTraceId" size="small" type="warning">{{ selectedTraceId }}</el-tag>
            <el-button size="small" v-if="canQueryLogs && selectedTraceId" link type="primary" @click="openLogsForTrace({ trace_id: selectedTraceId, service_name: traceDetail?.service_name })">
              关联日志
            </el-button>
          </div>
        </div>

        <el-empty v-if="!traceDetail && !loading.detail" description="选择一条 Trace 后查看 Span 详情。" />

        <template v-else>
          <div class="detail-summary" v-loading="loading.detail">
            <div class="detail-kpi">
              <span>服务数</span>
              <strong>{{ traceDetail?.services?.length || 0 }}</strong>
            </div>
            <div class="detail-kpi">
              <span>Span 数</span>
              <strong>{{ traceDetail?.span_count || 0 }}</strong>
            </div>
            <div class="detail-kpi">
              <span>错误 Span</span>
              <strong>{{ traceDetail?.error_count || 0 }}</strong>
            </div>
            <div class="detail-kpi">
              <span>总耗时</span>
              <strong>{{ formatDuration(traceDetail?.duration_ms) }}</strong>
            </div>
          </div>

          <div v-if="traceDetail?.spans?.length" class="spotlight-grid">
            <article v-if="errorSpanHighlights.length" class="spotlight-card danger-spotlight">
              <span class="spotlight-title">异常 Span</span>
              <button
                v-for="span in errorSpanHighlights"
                :key="`error-${span.span_id}`"
                type="button"
                class="spotlight-entry"
                @click="focusSpan(span.span_id)"
              >
                <strong>{{ span.endpoint_name || span.service_code }}</strong>
                <span>{{ formatDuration(span.duration_ms) }} · {{ span.service_code || '--' }}</span>
              </button>
            </article>

            <article v-if="slowSpanHighlights.length" class="spotlight-card warning-spotlight">
              <span class="spotlight-title">慢调用Span</span>
              <button
                v-for="span in slowSpanHighlights"
                :key="`slow-${span.span_id}`"
                type="button"
                class="spotlight-entry"
                @click="focusSpan(span.span_id)"
              >
                <strong>{{ span.endpoint_name || span.service_code }}</strong>
                <span>{{ formatDuration(span.duration_ms) }} · {{ span.layer || 'UNSET' }}</span>
              </button>
            </article>

            <article v-if="serviceHighlights.length" class="spotlight-card">
              <span class="spotlight-title">服务分布</span>
              <div class="service-pills">
                <span v-for="item in serviceHighlights" :key="item.service" class="service-pill">
                  {{ item.service }} · {{ item.count }} Span
                </span>
              </div>
            </article>
          </div>

          <div class="chips-section">
            <span class="chips-title">服务</span>
            <div class="chips-wrap">
              <el-tag v-for="item in traceDetail?.services || []" :key="item" size="small" effect="plain">{{ item }}</el-tag>
            </div>
          </div>

          <div class="chips-section">
            <span class="chips-title">端点</span>
            <div class="chips-wrap">
              <el-tag v-for="item in traceDetail?.endpoints || []" :key="item" size="small" type="info" effect="plain">{{ item }}</el-tag>
            </div>
          </div>

          <div class="span-list">
            <article
              v-for="span in traceDetail?.spans || []"
              :id="`span-${selectedTraceId}-${span.span_id}`"
              :key="`${selectedTraceId}-${span.span_id}`"
              class="span-card"
              :class="{ 'is-error': span.is_error, 'is-slow': Number(span.duration_ms || 0) >= slowThreshold }"
            >
              <div class="span-head">
                <div class="span-title">
                  <strong>{{ span.endpoint_name || span.service_code }}</strong>
                  <span>{{ span.service_code }}</span>
                </div>
                <div class="span-tags">
                  <el-tag size="small" effect="plain">{{ span.type || 'Span' }}</el-tag>
                  <el-tag size="small" effect="plain">{{ span.layer || 'UNSET' }}</el-tag>
                  <el-tag v-if="Number(span.duration_ms || 0) >= slowThreshold" size="small" type="warning">慢调用</el-tag>
                  <el-tag size="small" :type="span.is_error ? 'danger' : 'success'">{{ span.is_error ? '错误' : '正常' }}</el-tag>
                </div>
              </div>
              <div class="span-meta">
                <span>实例：{{ span.service_instance_name || '--' }}</span>
                <span>Peer：{{ span.peer || '--' }}</span>
                <span>耗时：{{ formatDuration(span.duration_ms) }}</span>
              </div>
              <div v-if="span.tags?.length" class="span-tags-list">
                <span v-for="tag in span.tags" :key="`${span.span_id}-${tag.key}`" class="span-chip">{{ tag.key }} = {{ tag.value }}</span>
              </div>
              <div v-if="span.logs?.length" class="span-log-list">
                <div v-for="log in span.logs" :key="`${span.span_id}-${log.time}`" class="span-log-item">
                  <strong>{{ formatTime(log.time) }}</strong>
                  <span>{{ formatLog(log.data) }}</span>
                </div>
              </div>
            </article>
          </div>
        </template>
      </section>
    </div>

    <section class="panel embed-panel">
      <div class="section-head">
        <h3>SkyWalking 入口</h3>
        <el-button size="small" v-if="tracing.ui_url || tracing.oap_url" link type="primary" @click="openTracingUi">外部打开</el-button>
      </div>

      <iframe v-if="tracing.embed_url" class="embed-frame" :src="tracing.embed_url" title="SkyWalking" />
      <el-alert
        v-else
        title="当前未配置 SkyWalking UI 地址，仍可使用平台内链路查询和演示数据。"
        type="info"
        show-icon
        :closable="false"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, InfoFilled, RefreshRight } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getObservabilityOverview, getTraceDetail, getTracingCatalog, searchTracing } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

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
const services = ref([])
const traces = ref([])
const traceDetail = ref(null)
const selectedTraceId = ref('')
const topology = ref({})
const searchSummary = ref({})
const topologyChartRef = ref(null)

let topologyChart = null

const filters = reactive({
  serviceId: '',
  traceState: 'ALL',
  durationMinutes: 30,
  keyword: '',
  traceId: '',
  limit: 20,
  sortBy: 'latest',
})

const durationOptions = [
  { label: '最近 15 分钟', value: 15 },
  { label: '最近 30 分钟', value: 30 },
  { label: '最近 1 小时', value: 60 },
  { label: '最近 6 小时', value: 360 },
]

const slowThreshold = 800

const statCards = computed(() => [
  { label: '接入服务', value: services.value.length || overview.value.summary?.service_count || 0, tone: '' },
  { label: '命中链路', value: searchSummary.value.match_count || traces.value.length || 0, tone: 'warning-card' },
  { label: '错误链路', value: searchSummary.value.error_match_count || 0, tone: 'danger-card' },
  { label: '拓扑调用', value: topology.value.call_count || 0, tone: 'success-card' },
])

const runtimeHint = computed(() => {
  if (tracing.value.warning) return tracing.value.warning
  return overview.value.tips?.[0] || '未接入 SkyWalking 时自动回退到演示数据。'
})

const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewAlerts = computed(() => authStore.hasPermission('ops.alert.view'))
const canViewGrafana = computed(() => authStore.hasPermission('ops.grafana.view'))

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

const topologyHighlights = computed(() =>
  (topology.value.nodes || [])
    .slice(0, 8)
    .map((item) => ({
      id: item.id,
      name: item.name,
      layer: Array.isArray(item.layers) && item.layers.length ? item.layers.join(', ') : item.type || 'SERVICE',
    }))
)

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

function parseTimeValue(value) {
  if (!value) return 0
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 0 : date.getTime()
}

function serviceNameById(serviceId) {
  return services.value.find((item) => item.id === serviceId)?.name || ''
}

function formatDuration(value) {
  return `${Number(value || 0)} ms`
}

function formatTime(value) {
  if (!value) return '--'
  if (typeof value === 'number') {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatLog(items = []) {
  return items.map((item) => `${item.key}: ${item.value}`).join(' | ')
}

function focusSpan(spanId) {
  if (spanId === undefined || spanId === null || !selectedTraceId.value) return
  nextTick(() => {
    document.getElementById(`span-${selectedTraceId.value}-${spanId}`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  })
}

function resetFilters() {
  filters.traceState = 'ALL'
  filters.durationMinutes = 30
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
  if (!Number.isFinite(raw) || raw <= 0) return 30
  return raw
}

async function loadOverview() {
  overview.value = await getObservabilityOverview()
}

async function loadCatalog() {
  loading.catalog = true
  try {
    const response = await getTracingCatalog()
    tracing.value = response.tracing || {}
    services.value = response.services || []
    topology.value = response.topology || {}
    searchSummary.value = response.summary || {}
    traces.value = response.recent_traces || []
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
    const response = await searchTracing({
      service_id: filters.serviceId,
      trace_state: filters.traceState,
      duration_minutes: filters.durationMinutes,
      keyword: filters.keyword,
      trace_id: filters.traceId,
      limit: filters.limit,
    })
    tracing.value = response.tracing || tracing.value
    services.value = response.services || services.value
    traces.value = response.traces || []
    searchSummary.value = response.summary || {}
    if (selectFirst && traces.value.length) {
      await selectTrace(traces.value[0])
    } else if (!traces.value.length) {
      selectedTraceId.value = ''
      traceDetail.value = null
    }
  } finally {
    loading.search = false
  }
}

async function applyRouteTracePreset(force = false) {
  const traceId = typeof route.query.traceId === 'string' ? route.query.traceId.trim() : ''
  if (!traceId) return false
  if (!force && filters.traceId === traceId) return false
  filters.traceId = traceId
  filters.keyword = typeof route.query.keyword === 'string' ? route.query.keyword.trim() : ''
  filters.serviceId = serviceIdFromRouteValue(typeof route.query.service === 'string' ? route.query.service.trim() : '')
  filters.durationMinutes = routeWindowMinutes()
  filters.traceState = 'ALL'
  await runSearch(true)
  return true
}

async function loadTrace(traceId) {
  if (!traceId) return
  loading.detail = true
  try {
    const response = await getTraceDetail(traceId)
    tracing.value = response.tracing || tracing.value
    traceDetail.value = response.trace || null
    selectedTraceId.value = traceId
  } finally {
    loading.detail = false
  }
}

async function selectTrace(row) {
  if (!row?.trace_id) return
  await loadTrace(row.trace_id)
}

async function refreshAll() {
  await loadOverview()
  await loadCatalog()
  if (services.value.length) {
    await runSearch(false)
  }
}

function openTracingUi() {
  const url = tracing.value.ui_url || tracing.value.oap_url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function openLogsForTrace(row) {
  if (!canQueryLogs.value || !row?.trace_id) return
  router.push({
    path: '/logs/query',
    query: {
      traceId: row.trace_id,
      service: row.service_name || row.service_id || '',
      window: String(filters.durationMinutes || 60),
      autoRun: '1',
    },
  })
}

function renderTopology() {
  if (!topologyChartRef.value) return
  if (!topologyChart) topologyChart = echarts.init(topologyChartRef.value)

  const nodes = (topology.value.nodes || []).map((item, index) => ({
    id: item.id,
    name: item.name,
    value: item.name,
    symbolSize: 42,
    itemStyle: {
      color: ['#2563eb', '#0f766e', '#ea580c', '#7c3aed'][index % 4],
    },
  }))

  const links = (topology.value.calls || []).map((item) => ({
    source: item.source,
    target: item.target,
    lineStyle: { color: '#94a3b8', width: 2 },
  }))

  topologyChart.setOption(
    {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          force: { repulsion: 210, edgeLength: 120 },
          label: { show: true, color: '#0f172a', fontSize: 12 },
          data: nodes,
          links,
          lineStyle: { opacity: 0.9, curveness: 0.08 },
        },
      ],
    },
    true
  )
}

function handleResize() {
  topologyChart?.resize()
}

watch(
  () => topology.value,
  async () => {
    await nextTick()
    renderTopology()
  }
)

onMounted(async () => {
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
  () => [route.query.traceId || '', route.query.service || '', route.query.keyword || ''].join('|'),
  async (value, previous) => {
    if (!value || value === previous) return
    await applyRouteTracePreset()
  }
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
.toolbar-actions,
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

.release-stats {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.release-stat-card {
  border-radius: 12px;
  min-height: 72px;
  padding: 10px 12px;
}

.warning-card {
  background: linear-gradient(135deg, #fef3c7, #fdba74);
}

.danger-card {
  background: linear-gradient(135deg, #fee2e2, #fca5a5);
}

.success-card {
  background: linear-gradient(135deg, #dcfce7, #86efac);
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
}

.stat-label {
  color: #475569;
  font-size: 12px;
  margin-top: 4px;
}

.runtime-strip {
  align-items: center;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.08) 0%, rgba(14, 165, 233, 0.04) 100%);
  border: 1px solid rgba(59, 130, 246, 0.14);
  border-radius: 10px;
  color: #64748b;
  display: flex;
  font-size: 12px;
  gap: 0;
  line-height: 1.45;
  margin-top: -10px;
  padding: 8px 11px;
}

.runtime-strip :deep(.el-icon) {
  display: none;
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

.toolbar-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.toolbar-actions {
  margin-top: 8px;
}

.topology-layout {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.45fr) 240px;
}

.topology-chart {
  height: 240px;
}

.topology-side {
  display: flex;
  flex-direction: column;
}

.topology-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.topology-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
}

.topology-item span,
.chips-title,
.detail-kpi span,
.span-title span,
.span-meta,
.span-log-item span {
  color: var(--text-secondary);
  font-size: 12px;
}

.content-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.85fr);
}

.slow-text {
  color: #dc2626;
  font-weight: 600;
}

.detail-summary {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 8px;
}

.spotlight-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 8px;
}

.detail-kpi {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
}

.spotlight-card {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
}

.danger-spotlight {
  background: linear-gradient(180deg, rgba(254, 242, 242, 0.96) 0%, #fff 100%);
  border-color: rgba(239, 68, 68, 0.24);
}

.warning-spotlight {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.96) 0%, #fff 100%);
  border-color: rgba(245, 158, 11, 0.24);
}

.spotlight-title {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.spotlight-entry {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  text-align: left;
}

.spotlight-entry strong {
  color: #0f172a;
}

.spotlight-entry span {
  color: var(--text-secondary);
  font-size: 12px;
}

.service-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.service-pill {
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 999px;
  color: #1d4ed8;
  font-size: 12px;
  padding: 4px 8px;
}

.chips-section {
  margin-bottom: 8px;
}

.chips-title {
  display: block;
  margin-bottom: 4px;
}

.span-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.span-card {
  background: #fcfcfd;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px;
}

.span-card.is-error {
  border-color: rgba(239, 68, 68, 0.24);
}

.span-card.is-slow {
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.18);
}

.span-head {
  align-items: flex-start;
  justify-content: space-between;
}

.span-title {
  flex-direction: column;
  gap: 2px;
}

.span-chip {
  background: rgba(15, 118, 110, 0.08);
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-radius: 999px;
  color: #0f766e;
  font-size: 12px;
  padding: 3px 8px;
}

.span-log-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.span-log-item {
  background: #fff7ed;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
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

@media (max-width: 1280px) {
  .release-stats,
  .detail-summary,
  .spotlight-grid,
  .toolbar-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid,
  .topology-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .hero,
  .section-head {
    align-items: stretch;
    flex-direction: column;
  }

  .release-stats,
  .detail-summary,
  .spotlight-grid,
  .toolbar-grid {
    grid-template-columns: 1fr;
  }
}
.hero.panel { border-radius: 20px; }
</style>



