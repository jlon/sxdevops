<template>
  <div class="alerts-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Bell /></el-icon>
          </span>
          <h2>告警中心</h2>
          <p class="page-inline-desc">集中查看、确认与定位告警</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="fetchData" :loading="loading">刷新</el-button>
        <el-button size="small" v-if="canQueryLogs" @click="router.push('/logs/query')">日志查询</el-button>
        <el-button size="small" v-if="canViewTracing" @click="router.push('/observability/tracing')">链路追踪</el-button>
        <el-button size="small" v-if="canViewGrafana" @click="router.push('/observability/grafana')">监控看板</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ total }}</div>
        <div class="stat-label">告警总数</div>
      </div>
      <div class="stat-card release-stat-card danger-card">
        <div class="stat-value">{{ criticalCount }}</div>
        <div class="stat-label">严重告警</div>
      </div>
      <div class="stat-card release-stat-card warning-card">
        <div class="stat-value">{{ warningCount }}</div>
        <div class="stat-label">警告告警</div>
      </div>
      <div class="stat-card release-stat-card success-card">
        <div class="stat-value">{{ acknowledgedCount }}</div>
        <div class="stat-label">已确认</div>
      </div>
    </div>

    <section class="panel">
      <div class="filter-bar">
        <el-input
          v-model="search"
          size="small"
          placeholder="搜索告警标题 / 来源"
          clearable
          style="width: 280px"
          :prefix-icon="Search"
          @input="handleFilterChange"
        />
        <el-select v-model="levelFilter" size="small" placeholder="级别" clearable style="width: 112px" @change="handleFilterChange">
          <el-option label="严重" value="critical" />
          <el-option label="警告" value="warning" />
          <el-option label="信息" value="info" />
        </el-select>
        <el-select v-model="ackFilter" size="small" placeholder="状态" clearable style="width: 112px" @change="handleFilterChange">
          <el-option label="未确认" :value="false" />
          <el-option label="已确认" :value="true" />
        </el-select>
      </div>

      <el-table :data="alerts" stripe size="small" v-loading="loading" style="width: 100%">
        <el-table-column prop="title" label="告警标题" min-width="220" />
        <el-table-column prop="level" label="级别" width="100">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" size="small">{{ row.level_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="140" />
        <el-table-column prop="host_name" label="主机" width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_acknowledged ? 'success' : 'danger'" size="small">
              {{ row.is_acknowledged ? '已确认' : '未确认' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button v-if="canQueryLogs" link type="primary" size="small" @click="openAlertLogs(row)">日志</el-button>
              <el-button v-if="canViewTracing" link type="warning" size="small" @click="openAlertTrace(row)">链路</el-button>
              <el-button v-if="canViewGrafana" link type="success" size="small" @click="openAlertDashboard(row)">大屏</el-button>
              <el-button v-if="canManageAlerts && !row.is_acknowledged" link type="primary" size="small" @click="handleAck(row)">确认</el-button>
              <el-popconfirm v-if="canManageAlerts" title="确认删除该告警吗？" @confirm="handleDelete(row.id)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          small
          v-model:current-page="page"
          :page-size="20"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchData"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { deleteAlert, getAlerts, updateAlert } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const alerts = ref([])
const loading = ref(false)
const search = ref('')
const levelFilter = ref('')
const ackFilter = ref('')
const page = ref(1)
const total = ref(0)

const canManageAlerts = computed(() => authStore.hasPermission('ops.alert.manage'))
const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewTracing = computed(() => authStore.hasPermission('ops.trace.view'))
const canViewGrafana = computed(() => authStore.hasPermission('ops.grafana.view'))
const criticalCount = computed(() => alerts.value.filter((item) => item.level === 'critical').length)
const warningCount = computed(() => alerts.value.filter((item) => item.level === 'warning').length)
const acknowledgedCount = computed(() => alerts.value.filter((item) => item.is_acknowledged).length)

function levelType(level) {
  return { critical: 'danger', warning: 'warning', info: 'info' }[level] || 'info'
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

function applyRouteFilters() {
  search.value = typeof route.query.search === 'string' ? route.query.search.trim() : ''
  levelFilter.value = typeof route.query.level === 'string' ? route.query.level.trim() : ''
  if (route.query.ack === '0') {
    ackFilter.value = false
  } else if (route.query.ack === '1') {
    ackFilter.value = true
  } else {
    ackFilter.value = ''
  }
}

function alertText(row) {
  return [row?.title, row?.source, row?.message, row?.host_name].filter(Boolean).join(' ').toLowerCase()
}

function resolveAlertKeyword(row) {
  return [row?.title, row?.source, row?.host_name].find((item) => typeof item === 'string' && item.trim()) || ''
}

function inferAlertService(row) {
  const candidate = [row?.source, row?.host_name, row?.title, row?.message]
    .find((item) => typeof item === 'string' && item.trim()) || ''
  const matched = candidate.match(/([a-z0-9-]+(?:service|gateway|nginx|member|payment|order))/i)
  return matched?.[1] || ''
}

function inferDashboardKey(row) {
  const text = alertText(row)
  if (/(nginx|ingress|gateway|slb|load.?balanc)/.test(text)) return 'ingress-slo'
  if (/(log|loki|sls|elk|audit)/.test(text)) return 'log-drilldown'
  if (/(cpu|memory|disk|node|host|pod|k8s|network)/.test(text)) return 'infra-overview'
  return 'apm-overview'
}

function openAlertLogs(row) {
  const keyword = resolveAlertKeyword(row)
  router.push({
    path: '/logs',
    query: {
      keyword: keyword || undefined,
      title: row?.title ? `告警 ${row.title}` : undefined,
      autoRun: '1',
      window: '60',
    },
  })
}

function openAlertTrace(row) {
  const keyword = resolveAlertKeyword(row)
  const service = inferAlertService(row)
  router.push({
    path: '/observability/tracing',
    query: {
      keyword: keyword || undefined,
      service: service || undefined,
      window: '60',
    },
  })
}

function openAlertDashboard(row) {
  router.push({
    path: '/observability/grafana',
    query: {
      dashboard: inferDashboardKey(row),
    },
  })
}

function handleFilterChange() {
  page.value = 1
  fetchData()
}

async function fetchData() {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    if (levelFilter.value) params.level = levelFilter.value
    if (ackFilter.value !== '') params.is_acknowledged = ackFilter.value
    const response = await getAlerts(params)
    alerts.value = response.results || response || []
    total.value = response.count || alerts.value.length
  } finally {
    loading.value = false
  }
}

async function handleAck(row) {
  await updateAlert(row.id, { is_acknowledged: true })
  ElMessage.success('告警已确认')
  await fetchData()
}

async function handleDelete(id) {
  await deleteAlert(id)
  ElMessage.success('告警已删除')
  await fetchData()
}

watch(
  () => [route.query.search || '', route.query.level || '', route.query.ack || ''].join('|'),
  async () => {
    applyRouteFilters()
    page.value = 1
    await fetchData()
  }
)

onMounted(async () => {
  applyRouteFilters()
  await fetchData()
})
</script>

<style scoped>
.alerts-page {
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
.filter-bar,
.row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero {
  align-items: center;
  justify-content: space-between;
}

.hero-copy {
  flex-direction: column;
  gap: 4px;
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
  background: linear-gradient(135deg, #dc2626, #f97316);
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

.danger-card {
  background: linear-gradient(135deg, #fee2e2, #fca5a5);
}

.warning-card {
  background: linear-gradient(135deg, #fef3c7, #fdba74);
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

.filter-bar {
  margin-bottom: 8px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

:deep(.el-table td.el-table__cell),
:deep(.el-table th.el-table__cell) {
  padding: 7px 0;
}

:deep(.el-table .cell) {
  line-height: 1.35;
}

@media (max-width: 900px) {
  .release-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .hero,
  .filter-bar,
  .release-stats {
    grid-template-columns: 1fr;
  }

  .hero {
    align-items: stretch;
    flex-direction: column;
  }
}
.hero.panel { border-radius: 20px; }
</style>


