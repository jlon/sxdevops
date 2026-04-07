<template>
  <div class="fade-in dashboard-page overview-page">
    <section class="hero panel dashboard-hero overview-hero">
      <div class="hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="release-header-icon"><el-icon><DataAnalysis /></el-icon></span>
          <h2>运营总览</h2>
          <el-tag size="small" :type="overviewTone.type" effect="light">{{ overviewTone.label }}</el-tag>
        </div>
        <p class="hero-intro">围绕主机健康、告警压力、资源利用率和交付动态整理首页视图，保持信息清晰、节奏紧凑，适合日常运维与值班巡检。</p>
        <div class="hero-signal-strip">
          <div v-for="item in heroSignals" :key="item.label" class="hero-signal-chip">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </div>
      <div class="hero-actions">
        <div class="hero-brief">
          <span class="hero-brief__label">当前稳定度</span>
          <strong>{{ stabilityScore }}</strong>
          <p>{{ stabilityCopy }}</p>
        </div>
        <div class="hero-button-group">
          <el-button :loading="loading" @click="handleRefresh">
            <el-icon><RefreshRight /></el-icon>
            刷新数据
          </el-button>
          <el-button type="primary" @click="router.push('/alerts')">
            <el-icon><Bell /></el-icon>
            进入告警中心
          </el-button>
        </div>
      </div>
    </section>

    <div class="stats-grid release-stats dashboard-stats">
      <article v-for="card in summaryCards" :key="card.label" class="stat-card release-stat-card" :class="card.tone">
        <div class="stat-card-top">
          <span class="stat-icon-shell">
            <el-icon><component :is="card.icon" /></el-icon>
          </span>
          <span class="metric-badge">{{ card.badge }}</span>
        </div>
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-meta">{{ card.meta }}</div>
      </article>
    </div>

    <div v-if="alertStripItems.length" class="dashboard-alert-strip">
      <span class="dashboard-alert-strip__label">运行提示</span>
      <span v-for="item in alertStripItems" :key="item" class="dashboard-alert-strip__item">{{ item }}</span>
    </div>

    <div class="dashboard-grid">
      <section class="panel pulse-panel">
        <div class="section-head">
          <div>
            <h3>平台脉搏</h3>
            <p>用主机在线情况和告警密度快速判断当前是否需要介入。</p>
          </div>
          <el-button text @click="router.push('/hosts/assets')">主机中心</el-button>
        </div>
        <div class="pulse-grid">
          <div ref="hostChartRef" class="chart-canvas pulse-chart"></div>
          <div class="pulse-side">
            <div class="score-card">
              <span class="score-card__label">总体判断</span>
              <strong>{{ overviewTone.label }}</strong>
              <p>{{ stabilityCopy }}</p>
            </div>
            <div class="pulse-legend">
              <div v-for="item in hostStatusCards" :key="item.label" class="pulse-legend-item" :class="item.tone">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.meta }}</small>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel risk-panel">
        <div class="section-head compact">
          <div>
            <h3>风险焦点</h3>
            <p>首页只保留最值得优先处理的几类风险对象。</p>
          </div>
        </div>
        <div class="risk-stack">
          <article v-for="item in riskCards" :key="item.label" class="risk-card" :class="item.tone">
            <div class="risk-card__top">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
            <p>{{ item.description }}</p>
          </article>
        </div>
      </section>

      <section class="panel resource-panel">
        <div class="section-head compact">
          <div>
            <h3>资源态势</h3>
            <p>查看平台平均 CPU、内存和磁盘利用率，判断容量是否偏紧。</p>
          </div>
        </div>
        <div class="resource-layout">
          <div ref="resourceChartRef" class="chart-canvas resource-chart"></div>
          <div class="resource-meters">
            <div v-for="item in resourceMeters" :key="item.label" class="resource-meter">
              <div class="resource-meter__head">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
              <el-progress :percentage="item.percentage" :show-text="false" :stroke-width="10" :color="item.color" />
            </div>
          </div>
        </div>
      </section>

      <section class="panel execution-panel">
        <div class="section-head compact">
          <div>
            <h3>交付驾驶舱</h3>
            <p>把发布成功率、运行中任务和失败积压集中展示。</p>
          </div>
          <el-button text @click="router.push('/deployments')">发布中心</el-button>
        </div>
        <div class="execution-hero">
          <div class="execution-rate">
            <span>发布成功率</span>
            <strong>{{ deploymentSuccessRate }}%</strong>
          </div>
          <el-progress :percentage="deploymentSuccessRate" :show-text="false" :stroke-width="12" color="#22c55e" />
        </div>
        <div class="execution-list">
          <div class="execution-item">
            <span>运行中发布</span>
            <strong>{{ stats.deployments?.running || 0 }}</strong>
          </div>
          <div class="execution-item muted">
            <span>失败发布</span>
            <strong>{{ stats.deployments?.failed || 0 }}</strong>
          </div>
          <div class="execution-item muted">
            <span>历史发布总量</span>
            <strong>{{ stats.deployments?.total || 0 }}</strong>
          </div>
        </div>
      </section>

      <section class="panel table-panel deployments-panel">
        <div class="section-head compact">
          <div>
            <h3>最近发布</h3>
            <p>最近 10 条环境变更，用来确认交付节奏和异常发布。</p>
          </div>
        </div>
        <el-table :data="stats.recent_deploys || []" stripe size="small" style="width: 100%">
          <el-table-column prop="app_name" label="应用" min-width="160" show-overflow-tooltip />
          <el-table-column prop="version" label="版本" width="92" />
          <el-table-column prop="environment_display" label="环境" width="92" />
          <el-table-column label="状态" width="98">
            <template #default="{ row }">
              <el-tag size="small" :type="deploymentStatusType(row.status)" effect="light">{{ row.status_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="deployer" label="执行人" width="110" show-overflow-tooltip />
          <el-table-column label="时间" width="168">
            <template #default="{ row }">{{ formatDateTime(row.deployed_at) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel table-panel alerts-panel">
        <div class="section-head compact">
          <div>
            <h3>未确认告警</h3>
            <p>高风险未确认告警保持常驻首页，方便值班时快速定位。</p>
          </div>
        </div>
        <el-table :data="stats.recent_alerts || []" stripe size="small" style="width: 100%">
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="alertLevelType(row.level)" effect="light">{{ row.level_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="110" show-overflow-tooltip />
          <el-table-column prop="host_name" label="主机" width="120" show-overflow-tooltip />
          <el-table-column label="时间" width="168">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Bell, CircleCheck, DataAnalysis, Monitor, Promotion, RefreshRight } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getDashboardStats } from '@/api/modules/ops'

const router = useRouter()

const loading = ref(false)
const stats = ref({})
const hostChartRef = ref(null)
const resourceChartRef = ref(null)
let hostChart = null
let resourceChart = null

const hostAvailability = computed(() => {
  const total = stats.value.hosts?.total || 0
  const online = stats.value.hosts?.online || 0
  return total ? Math.round((online / total) * 100) : 0
})

const deploymentSuccessRate = computed(() => {
  const total = stats.value.deployments?.total || 0
  const success = stats.value.deployments?.success || 0
  return total ? Math.round((success / total) * 100) : 0
})

const stabilityScore = computed(() => {
  const criticalPenalty = (stats.value.alerts?.critical || 0) * 16
  const offlinePenalty = (stats.value.hosts?.offline || 0) * 6
  const failedPenalty = (stats.value.deployments?.failed || 0) * 5
  return Math.max(18, 100 - criticalPenalty - offlinePenalty - failedPenalty)
})

const stabilityCopy = computed(() => {
  if (stabilityScore.value >= 85) return '整体稳定，可继续关注发布节奏和容量变化。'
  if (stabilityScore.value >= 60) return '存在一定波动，建议优先确认风险告警和离线主机。'
  return '当前风险较高，建议立即切换到告警和主机页面排查。'
})

const overviewTone = computed(() => {
  if ((stats.value.alerts?.critical || 0) > 0 || (stats.value.hosts?.offline || 0) >= 3) return { type: 'danger', label: '需要值守' }
  if ((stats.value.alerts?.warning || 0) > 0 || (stats.value.deployments?.failed || 0) > 0) return { type: 'warning', label: '持续关注' }
  return { type: 'success', label: '整体稳定' }
})

const heroSignals = computed(() => [
  { label: '稳定度', value: stabilityScore.value },
  { label: '主机可用率', value: `${hostAvailability.value}%` },
  { label: '交付成功率', value: `${deploymentSuccessRate.value}%` },
])

const summaryCards = computed(() => [
  {
    label: '主机总量',
    value: stats.value.hosts?.total || 0,
    meta: `在线 ${stats.value.hosts?.online || 0} / 离线 ${stats.value.hosts?.offline || 0}`,
    badge: '资源池',
    tone: 'context-card',
    icon: Monitor,
  },
  {
    label: '可用率',
    value: `${hostAvailability.value}%`,
    meta: `告警态主机 ${stats.value.hosts?.warning || 0} 台`,
    badge: '健康度',
    tone: 'success-card',
    icon: CircleCheck,
  },
  {
    label: '运行中发布',
    value: stats.value.deployments?.running || 0,
    meta: `失败 ${stats.value.deployments?.failed || 0} / 总计 ${stats.value.deployments?.total || 0}`,
    badge: '交付中',
    tone: 'warning-card',
    icon: Promotion,
  },
  {
    label: '未确认告警',
    value: stats.value.alerts?.unacknowledged || 0,
    meta: `严重 ${stats.value.alerts?.critical || 0} / 警告 ${stats.value.alerts?.warning || 0}`,
    badge: '风险面',
    tone: 'danger-card',
    icon: Bell,
  },
])

const hostStatusCards = computed(() => [
  {
    label: '在线主机',
    value: stats.value.hosts?.online || 0,
    meta: '当前可正常服务',
    tone: 'good',
  },
  {
    label: '告警主机',
    value: stats.value.hosts?.warning || 0,
    meta: '存在性能或健康波动',
    tone: 'warning',
  },
  {
    label: '离线主机',
    value: stats.value.hosts?.offline || 0,
    meta: '建议尽快确认采集和网络',
    tone: 'danger',
  },
])

const resourceMeters = computed(() => [
  { label: 'CPU', value: formatPercent(stats.value.hosts?.avg_cpu), percentage: Number(stats.value.hosts?.avg_cpu || 0), color: '#4f46e5' },
  { label: '内存', value: formatPercent(stats.value.hosts?.avg_memory), percentage: Number(stats.value.hosts?.avg_memory || 0), color: '#0ea5a5' },
  { label: '磁盘', value: formatPercent(stats.value.hosts?.avg_disk), percentage: Number(stats.value.hosts?.avg_disk || 0), color: '#f97316' },
])

const alertStripItems = computed(() => {
  const items = []
  if ((stats.value.alerts?.critical || 0) > 0) items.push(`存在 ${stats.value.alerts.critical} 条严重告警，建议优先进入告警中心确认。`)
  if ((stats.value.hosts?.offline || 0) > 0) items.push(`当前有 ${stats.value.hosts.offline} 台主机离线，需要排查连通性或采集状态。`)
  if ((stats.value.deployments?.failed || 0) > 0) items.push(`最近发布存在 ${stats.value.deployments.failed} 次失败记录，建议复盘变更影响。`)
  if ((stats.value.hosts?.avg_cpu || 0) >= 70) items.push(`平台平均 CPU 已到 ${formatPercent(stats.value.hosts.avg_cpu)}，需关注资源峰值。`)
  return items.slice(0, 3)
})

const riskCards = computed(() => [
  {
    label: '严重告警',
    value: `${stats.value.alerts?.critical || 0} 条`,
    description: (stats.value.alerts?.critical || 0) > 0 ? '存在需要即时响应的高风险告警。' : '当前没有严重级别告警。',
    tone: 'danger',
  },
  {
    label: '离线主机',
    value: `${stats.value.hosts?.offline || 0} 台`,
    description: (stats.value.hosts?.offline || 0) > 0 ? '建议先核查采集链路、SSH 连通性或实例状态。' : '主机在线性表现稳定。',
    tone: 'warning',
  },
  {
    label: '失败发布',
    value: `${stats.value.deployments?.failed || 0} 次`,
    description: (stats.value.deployments?.failed || 0) > 0 ? '近期变更存在失败记录，需关注回滚和审批链路。' : '近期没有明显交付失败积压。',
    tone: 'neutral',
  },
  {
    label: '平均资源压力',
    value: `${Math.round(((stats.value.hosts?.avg_cpu || 0) + (stats.value.hosts?.avg_memory || 0) + (stats.value.hosts?.avg_disk || 0)) / 3)}%`,
    description: '用三项平均利用率估算平台当前资源紧张程度。',
    tone: 'info',
  },
])

function formatPercent(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function formatDateTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function alertLevelType(level) {
  const map = { critical: 'danger', warning: 'warning', info: 'info' }
  return map[level] || 'info'
}

function deploymentStatusType(status) {
  const map = {
    running: 'success',
    deploying: 'warning',
    stopped: 'info',
    removed: 'info',
    failed: 'danger',
    rejected: 'danger',
  }
  return map[status] || 'info'
}

function renderHostChart() {
  if (!hostChartRef.value) return
  hostChart?.dispose()
  hostChart = echarts.init(hostChartRef.value)
  hostChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    color: ['#22c55e', '#f59e0b', '#ef4444'],
    legend: { bottom: 0, icon: 'circle', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748b' } },
    series: [{
      type: 'pie',
      radius: ['50%', '74%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 10, borderColor: '#ffffff', borderWidth: 4 },
      label: { formatter: '{b}\n{c}', fontSize: 12, color: '#334155' },
      data: [
        { value: stats.value.hosts?.online || 0, name: '在线' },
        { value: stats.value.hosts?.warning || 0, name: '告警' },
        { value: stats.value.hosts?.offline || 0, name: '离线' },
      ],
    }],
    graphic: [{
      type: 'group',
      left: 'center',
      top: '34%',
      children: [
        { type: 'text', style: { text: `${hostAvailability.value}%`, fontSize: 30, fontWeight: 700, fill: '#0f172a', textAlign: 'center' }, left: -30 },
        { type: 'text', style: { text: '主机可用率', fontSize: 12, fill: '#64748b', textAlign: 'center' }, top: 38, left: -25 },
      ],
    }],
  })
}

function renderResourceChart() {
  if (!resourceChartRef.value) return
  resourceChart?.dispose()
  resourceChart = echarts.init(resourceChartRef.value)
  resourceChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 12, right: 20, top: 12, bottom: 12, containLabel: true },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#64748b' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.22)' } },
    },
    yAxis: {
      type: 'category',
      data: ['CPU', '内存', '磁盘'],
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#334155' },
    },
    series: [{
      type: 'bar',
      barWidth: 16,
      data: [
        { value: stats.value.hosts?.avg_cpu || 0, itemStyle: { color: '#4f46e5', borderRadius: [0, 10, 10, 0] } },
        { value: stats.value.hosts?.avg_memory || 0, itemStyle: { color: '#0ea5a5', borderRadius: [0, 10, 10, 0] } },
        { value: stats.value.hosts?.avg_disk || 0, itemStyle: { color: '#f97316', borderRadius: [0, 10, 10, 0] } },
      ],
      label: { show: true, position: 'right', color: '#334155', formatter: '{c}%' },
    }],
  })
}

function renderCharts() {
  renderHostChart()
  renderResourceChart()
}

function handleResize() {
  hostChart?.resize()
  resourceChart?.resize()
}

async function fetchStats(showMessage = false) {
  loading.value = true
  try {
    stats.value = await getDashboardStats()
    await nextTick()
    renderCharts()
    if (showMessage) ElMessage.success('仪表盘已刷新')
  } catch (error) {
    console.error('获取仪表盘统计失败', error)
    ElMessage.error('获取仪表盘数据失败')
  } finally {
    loading.value = false
  }
}

async function handleRefresh() {
  await fetchStats(true)
}

onMounted(async () => {
  await fetchStats()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  hostChart?.dispose()
  resourceChart?.dispose()
})
</script>

<style scoped>
.overview-page {
  --overview-bg: #f5f7fb;
  --overview-panel: #ffffff;
  --overview-panel-strong: #ffffff;
  --overview-border: #dbe4f0;
  --overview-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
  --overview-text: #111827;
  --overview-muted: #475569;
  min-height: 100%;
  padding: 4px 0 24px;
  color: var(--overview-text);
  background: var(--overview-bg);
}

.overview-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  border: 1px solid var(--overview-border);
  border-radius: 24px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  box-shadow: var(--overview-shadow);
}

.hero-copy,
.hero-actions {
  position: relative;
}

.release-hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.release-hero-title-inline {
  flex-wrap: wrap;
}

.release-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.7);
}

.hero h2 {
  margin: 0;
  color: var(--overview-text);
}

.hero-intro {
  max-width: 700px;
  margin: 12px 0 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--overview-muted);
}

.hero-signal-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
}

.hero-signal-chip {
  min-width: 128px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid #dbe4f0;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.hero-signal-chip span {
  display: block;
  font-size: 12px;
  color: var(--overview-muted);
}

.hero-signal-chip strong {
  display: block;
  margin-top: 8px;
  font-size: 22px;
  line-height: 1;
  color: var(--overview-text);
}

.hero-actions {
  min-width: 280px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 16px;
}

.hero-brief {
  width: 100%;
  padding: 18px;
  border-radius: 18px;
  border: 1px solid #dbe4f0;
  background: #ffffff;
}

.hero-brief__label {
  display: block;
  font-size: 12px;
  color: var(--overview-muted);
}

.hero-brief strong {
  display: block;
  margin-top: 10px;
  font-size: 32px;
  line-height: 1;
  color: var(--overview-text);
}

.hero-brief p {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--overview-muted);
}

.hero-button-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.dashboard-stats {
  margin-bottom: 14px;
}

.release-stat-card {
  position: relative;
  min-height: 120px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--overview-border);
  background: var(--overview-panel-strong);
  box-shadow: var(--overview-shadow);
  overflow: hidden;
}

.release-stat-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 48%, #0ea5e9 100%);
}

.release-stat-card::after {
  content: '';
  position: absolute;
  right: -18px;
  bottom: -26px;
  width: 88px;
  height: 88px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(191,219,254,.45) 0%, rgba(191,219,254,0) 72%);
}

.success-card::before {
  background: linear-gradient(90deg, #86efac 0%, #22c55e 52%, #10b981 100%);
}

.warning-card::before {
  background: linear-gradient(90deg, #fde68a 0%, #f59e0b 52%, #f97316 100%);
}

.danger-card::before {
  background: linear-gradient(90deg, #fecaca 0%, #ef4444 52%, #f97316 100%);
}

.success-card::after {
  background: radial-gradient(circle, rgba(187,247,208,.52) 0%, rgba(187,247,208,0) 72%);
}

.warning-card::after {
  background: radial-gradient(circle, rgba(254,240,138,.52) 0%, rgba(254,240,138,0) 72%);
}

.danger-card::after {
  background: radial-gradient(circle, rgba(254,202,202,.56) 0%, rgba(254,202,202,0) 72%);
}

.stat-card-top {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.stat-icon-shell {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  color: #1d4ed8;
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.stat-value,
.stat-label,
.stat-meta {
  position: relative;
  z-index: 1;
}

.stat-value {
  margin-top: 18px;
  font-size: 28px;
  line-height: 1;
  font-weight: 700;
  color: var(--overview-text);
}

.stat-label {
  margin-top: 10px;
  font-size: 13px;
  color: #334155;
}

.stat-meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--overview-muted);
}

.dashboard-alert-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border-radius: 16px;
  border: 1px solid #fed7aa;
  background: #fff7ed;
  box-shadow: none;
  flex-wrap: wrap;
}

.dashboard-alert-strip__label {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #c2410c;
  background: rgba(255, 237, 213, 0.92);
}

.dashboard-alert-strip__item {
  font-size: 12px;
  line-height: 1.6;
  color: #9a3412;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.9fr);
  gap: 16px;
}

.panel {
  border-radius: 18px;
  border: 1px solid var(--overview-border);
  background: var(--overview-panel);
  box-shadow: var(--overview-shadow);
}

.pulse-panel,
.risk-panel,
.resource-panel,
.execution-panel,
.table-panel {
  padding: 18px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-head.compact {
  margin-bottom: 14px;
}

.section-head h3 {
  margin: 0;
  font-size: 16px;
  color: var(--overview-text);
  font-weight: 700;
}

.section-head p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--overview-muted);
}

.pulse-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) 260px;
  gap: 16px;
  align-items: center;
}

.chart-canvas {
  width: 100%;
}

.pulse-chart {
  height: 290px;
}

.pulse-side,
.pulse-legend,
.resource-meters,
.risk-stack,
.execution-list {
  display: grid;
  gap: 12px;
}

.score-card {
  padding: 16px;
  border-radius: 16px;
  background: #f8fbff;
  border: 1px solid #dbeafe;
}

.score-card__label {
  display: block;
  font-size: 12px;
  color: var(--overview-muted);
}

.score-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  color: var(--overview-text);
}

.score-card p {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--overview-muted);
}

.pulse-legend-item {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.pulse-legend-item.good {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.pulse-legend-item.warning {
  border-color: #fde68a;
  background: #fffbeb;
}

.pulse-legend-item.danger {
  border-color: #fecaca;
  background: #fef2f2;
}

.pulse-legend-item span,
.pulse-legend-item small {
  display: block;
}

.pulse-legend-item span {
  font-size: 12px;
  color: var(--overview-muted);
}

.pulse-legend-item strong {
  display: block;
  margin-top: 6px;
  font-size: 24px;
  line-height: 1;
  color: var(--overview-text);
}

.pulse-legend-item small {
  margin-top: 6px;
  font-size: 11px;
  color: #64748b;
}

.risk-card {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.risk-card.danger {
  border-color: #fecaca;
  background: #fef2f2;
}

.risk-card.warning {
  border-color: #fde68a;
  background: #fffbeb;
}

.risk-card.info {
  border-color: #bae6fd;
  background: #f0f9ff;
}

.risk-card.neutral {
  border-color: rgba(226, 232, 240, 0.95);
}

.risk-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #334155;
}

.risk-card__top strong {
  font-size: 20px;
  color: var(--overview-text);
}

.risk-card p {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--overview-muted);
}

.resource-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 14px;
  align-items: center;
}

.resource-chart {
  height: 250px;
}

.resource-meter {
  padding: 12px 14px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.resource-meter__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--overview-muted);
}

.resource-meter__head strong {
  font-size: 16px;
  color: var(--overview-text);
}

.execution-hero {
  padding: 16px;
  border-radius: 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.execution-rate {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.execution-rate span {
  font-size: 12px;
  color: var(--overview-muted);
}

.execution-rate strong {
  font-size: 34px;
  line-height: 1;
  color: var(--overview-text);
}

.execution-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #334155;
  font-size: 13px;
}

.execution-item strong {
  font-size: 18px;
  color: var(--overview-text);
}

.execution-item.muted strong {
  font-size: 16px;
}

.deployments-panel,
.alerts-panel {
  min-height: 340px;
}

:deep(.el-button:not(.el-button--primary)) {
  --el-button-bg-color: #ffffff;
  --el-button-border-color: #cbd5e1;
  --el-button-text-color: #334155;
  --el-button-hover-bg-color: #eff6ff;
  --el-button-hover-text-color: #0f172a;
  --el-button-hover-border-color: #93c5fd;
}

:deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #1d4ed8;
  --el-button-hover-border-color: #1d4ed8;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: rgba(255,255,255,0);
  --el-table-border-color: #e2e8f0;
  --el-table-header-bg-color: #f8fafc;
  --el-table-row-hover-bg-color: #eff6ff;
  --el-table-text-color: #334155;
  --el-table-header-text-color: #475569;
}

:deep(.el-table::before),
:deep(.el-table__inner-wrapper::before) {
  display: none;
}

:deep(.el-table th.el-table__cell),
:deep(.el-table tr) {
  background: transparent;
}

:deep(.el-progress-bar__outer) {
  background: #e2e8f0;
}

@media (max-width: 1180px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .pulse-grid,
  .resource-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .overview-hero {
    flex-direction: column;
  }

  .hero-actions {
    align-items: flex-start;
  }

  .hero-button-group {
    justify-content: flex-start;
  }
}

@media (max-width: 768px) {
  .hero-signal-strip,
  .release-stats {
    grid-template-columns: 1fr;
  }

  .pulse-panel,
  .risk-panel,
  .resource-panel,
  .execution-panel,
  .table-panel {
    padding: 14px;
  }

  .pulse-chart {
    height: 280px;
  }
}
</style>
