<template>
  <div class="observability-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><DataLine /></el-icon>
          </span>
          <h2>可观测性平台</h2>
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
        <h3>核心能力</h3>
      </div>

      <div class="module-grid">
        <article v-if="canViewSystemPosture" class="module-card">
          <div class="module-head">
            <div class="module-title">
              <el-icon><Aim /></el-icon>
              <strong>系统态势</strong>
            </div>
            <el-tag size="small" type="danger">核心总览</el-tag>
          </div>
          <div class="module-meta">
            <span>SLA 健康</span>
            <span>层级下钻</span>
            <span>依赖影响</span>
          </div>
          <div class="module-actions">
            <el-button size="small" link type="primary" @click="go('/observability/system-posture')">打开系统态势</el-button>
          </div>
        </article>

        <article v-if="overview.modules?.logs" class="module-card">
          <div class="module-head">
            <div class="module-title">
              <el-icon><Search /></el-icon>
              <strong>日志能力</strong>
            </div>
            <el-tag size="small" type="success">已接入</el-tag>
          </div>
          <div class="module-meta">
            <span>数据源 {{ overview.modules.logs.datasource_count }}</span>
            <span>启用 {{ overview.modules.logs.enabled_count }}</span>
            <span>默认 {{ overview.modules.logs.default_count }}</span>
          </div>
          <div class="module-actions">
            <el-button size="small" link type="primary" @click="go('/logs')">查看日志</el-button>
            <el-button size="small" v-if="canViewLogDatasources" link @click="go('/logs/datasources')">数据源</el-button>
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
            <span>未认领 {{ overview.modules.alerts.unacknowledged }}</span>
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
            <el-button size="small" v-if="canViewTraceDatasources" link @click="go('/observability/tracing/datasources')">数据源</el-button>
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

    <section v-if="canViewLinks" class="panel">
      <div class="section-head">
        <h3>关联跳转配置</h3>
        <el-tag size="small" type="success">日志 / 链路 / 看板</el-tag>
      </div>
      <ObservabilityDataSourceLinks embedded />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Aim, Bell, Connection, DataLine, Histogram, RefreshRight, Search } from '@element-plus/icons-vue'
import { getObservabilityOverview } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import ObservabilityDataSourceLinks from './ObservabilityDataSourceLinks.vue'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const overview = ref({ modules: {}, summary: {} })
const canViewLogDatasources = computed(() => authStore.hasPermission('ops.log.datasource.view'))
const canViewTraceDatasources = computed(() => authStore.hasPermission('ops.trace.datasource.view'))
const canViewLinks = computed(() => authStore.hasPermission('ops.observability.link.view'))
const canViewSystemPosture = computed(() => authStore.hasPermission('ops.observability.firemap.view'))

const statCards = computed(() => [
  { label: '日志数据源', value: overview.value.summary?.datasource_count || 0, tone: '' },
  { label: '待处理告警', value: overview.value.summary?.unacknowledged_alerts || 0, tone: 'danger-card' },
  { label: 'Trace 数', value: overview.value.summary?.trace_count || 0, tone: 'warning-card' },
  { label: 'Grafana 看板', value: overview.value.summary?.dashboard_count || 0, tone: 'success-card' },
])

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
.module-meta {
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

.hero-actions {
  align-items: center;
}

.hero-actions :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
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

.release-stats + .panel,
.release-stats + .table-card {
  margin-top: -8px;
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

.module-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.module-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px;
}

.module-title strong {
  font-size: 14px;
}

.module-meta span {
  color: var(--text-secondary);
  line-height: 1.45;
  margin: 0;
}

.module-card {
  background: linear-gradient(180deg, #fff, #f8fafc);
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

@media (max-width: 1200px) {
  .release-stats,
  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .hero,
  .section-head {
    align-items: stretch;
    flex-direction: column;
  }

  .release-stats,
  .module-grid {
    grid-template-columns: 1fr;
  }
}
.hero.panel { border-radius: 20px; }
</style>



