<template>
  <div class="observability-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Histogram /></el-icon>
          </span>
          <h2>监控看板</h2>
          <p class="page-inline-desc">集中查看 Grafana 看板</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="loadOverview" :loading="loading">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button size="small" v-if="canViewTracing" @click="router.push('/observability/tracing')">链路追踪</el-button>
        <el-button size="small" v-if="canQueryLogs" @click="router.push('/logs/query')">日志查询</el-button>
        <el-button size="small" v-if="canViewAlerts" @click="router.push('/alerts')">告警中心</el-button>
        <el-button size="small" v-if="grafana.url" type="primary" @click="openGrafana">外部打开</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div v-for="item in statCards" :key="item.label" class="stat-card release-stat-card" :class="item.tone">
        <div class="stat-value">{{ item.value }}</div>
        <div class="stat-label">{{ item.label }}</div>
      </div>
    </div>

    <section class="panel">
      <div class="section-head">
        <h3>看板筛选</h3>
        <el-tag size="small" :type="grafana.configured ? 'success' : 'warning'">{{ grafana.status_text || '待接入' }}</el-tag>
      </div>
      <div class="toolbar-grid">
        <el-input size="small" v-model.trim="filters.keyword" placeholder="按看板名称或说明搜索" clearable />
        <el-select size="small" v-model="filters.tag" clearable placeholder="按标签筛选">
          <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel">
        <div class="section-head">
          <h3>推荐看板</h3>
          <el-tag size="small" type="info">共 {{ filteredDashboards.length }} 个</el-tag>
        </div>

        <div class="dashboard-groups">
          <section v-for="group in groupedDashboards" :key="group.key" class="dashboard-group">
            <div class="group-head">
              <strong>{{ group.label }}</strong>
              <span>{{ group.hint }}</span>
            </div>
            <div class="dashboard-grid">
              <article
                v-for="item in group.items"
                :key="item.key"
                class="dashboard-card"
                :class="{ active: selectedDashboard?.key === item.key }"
                @click="selectDashboard(item)"
              >
                <div class="dashboard-top">
                  <div>
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.description }}</p>
                  </div>
                  <el-tag size="small" effect="plain">{{ item.panel_count }} Panels</el-tag>
                </div>
                <div class="dashboard-tags">
                  <span v-for="tag in item.tags" :key="`${item.key}-${tag}`" class="dashboard-chip">{{ tag }}</span>
                </div>
                <div class="dashboard-actions">
                  <el-button size="small" v-if="item.url" link type="primary" @click.stop="openExternal(item.url)">外部打开</el-button>
                  <el-button size="small" v-else link disabled>等待配置 URL</el-button>
                </div>
              </article>
            </div>
          </section>
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <h3>当前看板</h3>
          <el-tag v-if="selectedDashboard" size="small" type="warning">{{ selectedDashboard.title }}</el-tag>
        </div>

        <el-empty v-if="!selectedDashboard" description="当前筛选条件下没有可选看板。" />

        <template v-else>
          <div class="selected-card">
            <strong>{{ selectedDashboard.title }}</strong>
            <p>{{ selectedDashboard.description }}</p>
            <div class="dashboard-tags">
              <span v-for="tag in selectedDashboard.tags" :key="`${selectedDashboard.key}-${tag}`" class="dashboard-chip">
                {{ tag }}
              </span>
            </div>
          </div>

          <iframe
            v-if="selectedDashboard.url"
            class="embed-frame"
            :src="selectedDashboard.url"
            :title="selectedDashboard.title"
          />
          <el-alert
            v-else
            title="当前未配置 `GRAFANA_URL` 或默认看板路径，暂时仅展示推荐看板信息。"
            type="info"
            show-icon
            :closable="false"
          />
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Histogram, RefreshRight } from '@element-plus/icons-vue'
import { getObservabilityOverview } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const overview = ref({ modules: {}, summary: {}, tips: [] })
const filters = reactive({
  keyword: '',
  tag: '',
})
const selectedKey = ref('')

const grafana = computed(() => overview.value.modules?.grafana || {})
const dashboards = computed(() => grafana.value.dashboards || [])
const tagOptions = computed(() => Array.from(new Set(dashboards.value.flatMap((item) => item.tags || []))))

const filteredDashboards = computed(() => {
  const keyword = filters.keyword.toLowerCase()
  return dashboards.value.filter((item) => {
    const matchesKeyword = !keyword || `${item.title} ${item.description}`.toLowerCase().includes(keyword)
    const matchesTag = !filters.tag || (item.tags || []).includes(filters.tag)
    return matchesKeyword && matchesTag
  })
})

function dashboardGroupMeta(item) {
  const text = `${item.key} ${item.title} ${item.description} ${(item.tags || []).join(' ')}`.toLowerCase()
  if (/(log|audit|loki|sls|elk)/.test(text)) return { key: 'logs', label: '日志排障', hint: '面向日志回放、审计与错误定位' }
  if (/(nginx|ingress|gateway|availability|latency)/.test(text)) return { key: 'ingress', label: '入口与可用性', hint: '关注入口流量、延迟和 SLO' }
  if (/(infra|node|cpu|memory|pod|disk)/.test(text)) return { key: 'infra', label: '基础设施', hint: '覆盖主机、节点和资源使用情况' }
  return { key: 'apm', label: '应用与链路', hint: '优先查看链路、吞吐和错误趋势' }
}

const groupedDashboards = computed(() => {
  const groups = new Map()
  filteredDashboards.value.forEach((item) => {
    const meta = dashboardGroupMeta(item)
    if (!groups.has(meta.key)) {
      groups.set(meta.key, { ...meta, items: [] })
    }
    groups.get(meta.key).items.push(item)
  })
  return [...groups.values()]
})

const selectedDashboard = computed(() => filteredDashboards.value.find((item) => item.key === selectedKey.value) || filteredDashboards.value[0] || null)

const statCards = computed(() => [
  { label: '推荐看板', value: grafana.value.dashboard_count || 0, tone: '' },
  { label: '总面板数', value: grafana.value.panel_count || 0, tone: 'warning-card' },
  { label: '数据源数', value: grafana.value.datasource_count || 0, tone: 'success-card' },
  { label: '接入状态', value: grafana.value.configured ? '已接入' : '待配置', tone: 'danger-card' },
])

const canViewTracing = computed(() => authStore.hasPermission('ops.trace.view'))
const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewAlerts = computed(() => authStore.hasPermission('ops.alert.view'))

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await getObservabilityOverview()
  } finally {
    loading.value = false
  }
}

function selectDashboard(item) {
  selectedKey.value = item?.key || ''
}

function syncFromRoute() {
  filters.keyword = typeof route.query.keyword === 'string' ? route.query.keyword.trim() : ''
  filters.tag = typeof route.query.tag === 'string' ? route.query.tag.trim() : ''
  selectedKey.value = typeof route.query.dashboard === 'string' ? route.query.dashboard.trim() : ''
}

function syncRouteQuery() {
  const currentQuery = {
    dashboard: selectedKey.value || undefined,
    keyword: filters.keyword || undefined,
    tag: filters.tag || undefined,
  }
  const nextFingerprint = JSON.stringify(currentQuery)
  const currentFingerprint = JSON.stringify({
    dashboard: typeof route.query.dashboard === 'string' ? route.query.dashboard : undefined,
    keyword: typeof route.query.keyword === 'string' ? route.query.keyword : undefined,
    tag: typeof route.query.tag === 'string' ? route.query.tag : undefined,
  })
  if (nextFingerprint === currentFingerprint) return
  router.replace({
    path: route.path,
    query: currentQuery,
  })
}

function openExternal(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function openGrafana() {
  openExternal(grafana.value.url || selectedDashboard.value?.url)
}

watch(
  () => filteredDashboards.value,
  (items) => {
    if (!items.length) {
      selectedKey.value = ''
      return
    }
    if (!items.some((item) => item.key === selectedKey.value)) {
      selectedKey.value = items[0].key
    }
  },
  { immediate: true }
)

watch(
  () => [route.query.dashboard || '', route.query.keyword || '', route.query.tag || ''].join('|'),
  syncFromRoute,
  { immediate: true }
)

watch(
  () => [selectedKey.value, filters.keyword, filters.tag].join('|'),
  () => {
    syncRouteQuery()
  }
)

onMounted(loadOverview)
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
.toolbar-grid,
.dashboard-top,
.dashboard-tags,
.dashboard-actions {
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
  background: linear-gradient(135deg, #f59e0b, #ea580c);
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

.success-card {
  background: linear-gradient(135deg, #dcfce7, #86efac);
}

.danger-card {
  background: linear-gradient(135deg, #fee2e2, #fecaca);
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
  grid-template-columns: minmax(0, 1.35fr) 180px;
}

.content-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
}

.dashboard-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dashboard-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-head span {
  color: var(--text-secondary);
  font-size: 12px;
}

.dashboard-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dashboard-card,
.selected-card {
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.02), rgba(249, 115, 22, 0.08));
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}

.dashboard-card {
  cursor: pointer;
  transition: 0.2s ease;
}

.dashboard-card.active {
  border-color: #f59e0b;
  box-shadow: 0 10px 24px rgba(245, 158, 11, 0.14);
}

.dashboard-top {
  align-items: flex-start;
  justify-content: space-between;
}

.dashboard-top strong,
.selected-card strong {
  display: block;
  font-size: 14px;
  margin-bottom: 4px;
}

.dashboard-top p,
.selected-card p {
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.dashboard-chip {
  background: rgba(249, 115, 22, 0.1);
  border: 1px solid rgba(249, 115, 22, 0.12);
  border-radius: 999px;
  color: #c2410c;
  font-size: 12px;
  padding: 3px 8px;
}

.embed-frame {
  border: 0;
  border-radius: 10px;
  height: 560px;
  margin-top: 8px;
  width: 100%;
}

@media (max-width: 1200px) {
  .release-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid,
  .toolbar-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .hero,
  .section-head {
    align-items: stretch;
    flex-direction: column;
  }

  .release-stats {
    grid-template-columns: 1fr;
  }
}
.hero.panel { border-radius: 20px; }
</style>

