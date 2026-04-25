<template>
  <div class="observability-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><DataLine /></el-icon>
          </span>
          <h2>可观测性平台</h2>
          <p class="page-inline-desc">统一查看日志、告警、链路与看板</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="loadOverview" :loading="loading">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
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
        <h3>模块入口</h3>
        <el-tag size="small" type="info">按当前账号权限显示</el-tag>
      </div>
      <div class="nav-grid">
        <article v-for="item in overview.navigation || []" :key="item.path" class="nav-card" :class="`tone-${item.tone || 'info'}`">
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
          <el-button size="small" type="primary" plain @click="go(item.path)">打开</el-button>
        </article>
      </div>
    </section>

    <section v-if="overview.providers?.length" class="panel">
      <div class="section-head">
        <h3>链路 Provider</h3>
        <el-tag size="small" type="info">OpenTelemetry 兼容</el-tag>
      </div>
      <div class="provider-grid">
        <article v-for="item in overview.providers" :key="item.provider" class="provider-card" :class="{ 'is-active': item.active }">
          <div class="provider-card__head">
            <strong>{{ item.provider_name }}</strong>
            <el-tag size="small" :type="item.source === 'demo' ? 'warning' : 'success'">
              {{ item.source === 'demo' ? '演示' : '实时' }}
            </el-tag>
          </div>
          <span>{{ item.configured ? '查询地址已配置' : '未配置查询地址，自动回退演示数据' }}</span>
          <el-button size="small" link type="primary" @click="openTracingProvider(item)">进入追踪</el-button>
        </article>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel">
        <div class="section-head">
          <h3>模块摘要</h3>
        </div>

        <div class="module-grid">
          <article v-if="overview.modules?.logs" class="module-card">
            <div class="module-head">
              <div class="module-title">
                <el-icon><Search /></el-icon>
                <strong>日志能力</strong>
              </div>
              <el-tag size="small" type="success">已接入</el-tag>
            </div>
            <div class="module-meta">
              <span>数据源总数 {{ overview.modules.logs.datasource_count }}</span>
              <span>启用 {{ overview.modules.logs.enabled_count }}</span>
              <span>默认 {{ overview.modules.logs.default_count }}</span>
            </div>
            <div class="module-actions">
              <el-button size="small" link type="primary" @click="go('/logs')">查看日志</el-button>
              <el-button size="small" v-if="canViewLogDatasources" link @click="go('/logs/datasources')">管理数据源</el-button>
            </div>
          </article>

          <article v-if="overview.modules?.alerts" class="module-card">
            <div class="module-head">
              <div class="module-title">
                <el-icon><Bell /></el-icon>
                <strong>告警中心</strong>
              </div>
              <el-tag size="small" :type="overview.modules.alerts.unacknowledged ? 'danger' : 'success'">
                {{ overview.modules.alerts.unacknowledged ? '待处理' : '稳定' }}
              </el-tag>
            </div>
            <div class="module-meta">
              <span>未确认 {{ overview.modules.alerts.unacknowledged }}</span>
              <span>严重 {{ overview.modules.alerts.critical }}</span>
              <span>警告 {{ overview.modules.alerts.warning }}</span>
            </div>
            <div class="module-actions">
              <el-button size="small" link type="primary" @click="go('/alerts')">查看告警</el-button>
            </div>
          </article>

          <article v-if="overview.modules?.tracing" class="module-card">
            <div class="module-head">
              <div class="module-title">
                <el-icon><Connection /></el-icon>
                <strong>链路追踪</strong>
              </div>
              <el-tag size="small" :type="overview.modules.tracing.source === 'demo' ? 'warning' : 'success'">
                {{ overview.modules.tracing.provider_name || (overview.modules.tracing.source === 'demo' ? '演示模式' : '实时数据') }}
              </el-tag>
            </div>
            <div class="module-meta">
              <span>服务 {{ overview.summary?.service_count || 0 }}</span>
              <span>Trace {{ overview.summary?.trace_count || 0 }}</span>
              <span>错误 {{ overview.summary?.error_count || 0 }}</span>
            </div>
            <div class="module-actions">
              <el-button size="small" link type="primary" @click="openTracingProvider(overview.modules.tracing)">查看链路</el-button>
              <el-button size="small" v-if="canViewTraceDatasources" link @click="go('/observability/tracing/datasources')">链路数据源</el-button>
              <el-button size="small" v-if="overview.modules.tracing.ui_url" link @click="openExternal(overview.modules.tracing.ui_url)">外部打开</el-button>
            </div>
          </article>

          <article v-if="overview.modules?.grafana" class="module-card">
            <div class="module-head">
              <div class="module-title">
                <el-icon><Histogram /></el-icon>
                <strong>监控看板</strong>
              </div>
              <el-tag size="small" :type="overview.modules.grafana.configured ? 'success' : 'warning'">
                {{ overview.modules.grafana.configured ? '已配置' : '待接入' }}
              </el-tag>
            </div>
            <div class="module-meta">
              <span>看板 {{ overview.modules.grafana.dashboard_count }}</span>
              <span>面板 {{ overview.modules.grafana.panel_count }}</span>
              <span>数据源 {{ overview.modules.grafana.datasource_count }}</span>
            </div>
            <div class="module-actions">
              <el-button size="small" link type="primary" @click="go('/observability/grafana')">查看看板</el-button>
              <el-button size="small" v-if="overview.modules.grafana.url" link @click="openExternal(overview.modules.grafana.url)">外部打开</el-button>
            </div>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <h3>平台提醒</h3>
        </div>
        <div class="tips-list">
          <article v-for="item in overview.tips || []" :key="item" class="tip-card">
            <span>{{ item }}</span>
          </article>
        </div>
      </section>
    </div>

    <div class="content-grid">
      <section v-if="overview.recent_alerts?.length" class="panel">
        <div class="section-head">
          <h3>最近告警</h3>
          <el-button size="small" link type="primary" @click="go('/alerts')">查看全部</el-button>
        </div>
        <el-table :data="overview.recent_alerts" stripe size="small" style="width: 100%">
          <el-table-column prop="title" label="标题" min-width="180" />
          <el-table-column prop="level_display" label="级别" width="90">
            <template #default="{ row }">
              <el-tag :type="levelType(row.level)" size="small">{{ row.level_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="120" />
          <el-table-column prop="host_name" label="主机" width="140" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openAlert(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="overview.recent_traces?.length" class="panel">
        <div class="section-head">
          <h3>最近 Trace</h3>
          <el-button size="small" link type="primary" @click="openTracingProvider(overview.modules?.tracing)">查看全部</el-button>
        </div>
        <el-table :data="overview.recent_traces" stripe size="small" style="width: 100%">
          <el-table-column prop="trace_id" label="Trace ID" min-width="170" show-overflow-tooltip />
          <el-table-column prop="service_name" label="服务" min-width="140" />
          <el-table-column label="来源" width="110">
            <template #default="{ row }">{{ row.source_provider || overview.modules?.tracing?.provider_name || '--' }}</template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ row.duration_ms }} ms</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_error ? 'danger' : 'success'">{{ row.is_error ? '错误' : '正常' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="canQueryLogs ? 156 : 88" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openTrace(row)">查看</el-button>
              <el-button v-if="canQueryLogs" link type="warning" @click="openTraceLogs(row)">日志</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, Connection, DataLine, Histogram, RefreshRight, Search } from '@element-plus/icons-vue'
import { getObservabilityOverview } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const overview = ref({ modules: {}, summary: {}, navigation: [], tips: [], recent_alerts: [], recent_traces: [] })
const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewLogDatasources = computed(() => authStore.hasPermission('ops.log.datasource.view'))
const canViewTraceDatasources = computed(() => authStore.hasPermission('ops.trace.datasource.view'))

const statCards = computed(() => [
  { label: '日志数据源', value: overview.value.summary?.datasource_count || 0, tone: '' },
  { label: '待处理告警', value: overview.value.summary?.unacknowledged_alerts || 0, tone: 'danger-card' },
  { label: 'Trace 数', value: overview.value.summary?.trace_count || 0, tone: 'warning-card' },
  { label: 'Grafana 看板', value: overview.value.summary?.dashboard_count || 0, tone: 'success-card' },
])

function levelType(level) {
  return { critical: 'danger', warning: 'warning', info: 'info' }[level] || 'info'
}

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await getObservabilityOverview()
  } finally {
    loading.value = false
  }
}

function go(path) {
  if (path) router.push(path)
}

function openTracingProvider(provider) {
  router.push({
    path: '/observability/tracing',
    query: {
      ...(provider?.provider ? { provider: provider.provider } : {}),
      ...(provider?.datasource_id ? { datasourceId: String(provider.datasource_id) } : {}),
    },
  })
}

function openAlert(row) {
  if (!row) return
  router.push({
    path: '/alerts',
    query: {
      search: row.title || '',
      level: row.level || '',
      ack: row.is_acknowledged === false ? '0' : undefined,
    },
  })
}

function openTrace(row) {
  if (!row?.trace_id) return
  router.push({
    path: '/observability/tracing',
    query: {
      traceId: row.trace_id,
      service: row.service_name || row.service_id || '',
      provider: row.source_provider || overview.value.modules?.tracing?.provider || '',
      datasourceId: overview.value.modules?.tracing?.datasource_id ? String(overview.value.modules.tracing.datasource_id) : '',
    },
  })
}

function openTraceLogs(row) {
  if (!row?.trace_id) return
  router.push({
    path: '/logs/query',
    query: {
      traceId: row.trace_id,
      service: row.service_name || row.service_id || '',
      provider: row.source_provider || overview.value.modules?.tracing?.provider || '',
      datasourceId: overview.value.modules?.tracing?.datasource_id ? String(overview.value.modules.tracing.datasource_id) : '',
      autoRun: '1',
    },
  })
}

function openExternal(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

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
.module-head,
.module-title,
.module-actions,
.module-meta,
.provider-card__head {
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
  background: linear-gradient(135deg, #0f766e, #2563eb);
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

.nav-grid,
.module-grid,
.provider-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.content-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.nav-card,
.module-card,
.provider-card,
.tip-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px;
}

.nav-card strong,
.module-title strong {
  font-size: 14px;
}

.nav-card p,
.tip-card span,
.module-meta span,
.provider-card span {
  color: var(--text-secondary);
  line-height: 1.45;
  margin: 0;
}

.tone-info {
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.06), rgba(14, 165, 233, 0.05));
}

.tone-warning {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.08), rgba(251, 191, 36, 0.05));
}

.tone-danger {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(248, 113, 113, 0.05));
}

.tone-success {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(45, 212, 191, 0.05));
}

.tone-accent {
  background: linear-gradient(135deg, rgba(234, 88, 12, 0.08), rgba(251, 146, 60, 0.05));
}

.module-card {
  background: linear-gradient(180deg, #fff, #f8fafc);
}

.provider-card {
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.provider-card.is-active {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96) 0%, #fff 100%);
  border-color: rgba(37, 99, 235, 0.34);
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.16);
}

.provider-card__head {
  align-items: center;
  justify-content: space-between;
}

.module-head {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.module-title {
  align-items: center;
}

.module-meta {
  margin-bottom: 6px;
}

.tips-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tip-card {
  background: #f8fafc;
}

:deep(.el-table td.el-table__cell),
:deep(.el-table th.el-table__cell) {
  padding: 7px 0;
}

:deep(.el-table .cell) {
  line-height: 1.35;
}

@media (max-width: 1200px) {
  .release-stats,
  .nav-grid,
  .module-grid,
  .provider-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
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
  .nav-grid,
  .module-grid,
  .provider-grid {
    grid-template-columns: 1fr;
  }
}
.hero.panel { border-radius: 20px; }
</style>



