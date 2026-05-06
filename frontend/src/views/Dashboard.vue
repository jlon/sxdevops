<template>
  <div class="fade-in dashboard-page overview-page">
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
      <span class="dashboard-alert-strip__label">平台提醒</span>
      <span v-for="item in alertStripItems" :key="item" class="dashboard-alert-strip__item">{{ item }}</span>
    </div>

    <div class="dashboard-grid">
      <section class="panel pulse-panel">
        <div class="section-head">
          <div>
            <h3>风险焦点</h3>
            <p>把当前最该优先处理的风险集中展示。</p>
          </div>
          <el-button text @click="router.push('/alerts')">告警中心</el-button>
        </div>
        <div class="pulse-grid">
          <div ref="hostChartRef" class="chart-canvas pulse-chart"></div>
          <div class="pulse-side">
            <div class="score-card">
              <span class="score-card__label">当前优先入口</span>
              <strong>{{ primaryRiskAction.name }}</strong>
              <p>{{ primaryRiskAction.reason }}</p>
            </div>
            <div class="pulse-legend">
              <div v-for="item in riskFocusLegend" :key="item.label" class="pulse-legend-item" :class="item.tone">
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
            <h3>值守建议</h3>
            <p>按值班顺序给出首页动作建议。</p>
          </div>
        </div>
        <div class="risk-stack">
          <article v-for="item in dutyCards" :key="item.label" class="risk-card" :class="item.tone">
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
            <p>快速判断 CPU、内存和磁盘是否偏紧。</p>
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
            <p>集中查看发布成功率、在途任务和失败积压。</p>
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
            <p>用最近变更确认交付节奏和异常发布。</p>
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
            <h3>未认领告警</h3>
            <p>保留未认领告警，方便值班快速定位。</p>
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
import { Bell, CircleCheck, Monitor, Promotion } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getDashboardStats } from '@/api/modules/ops'

const router = useRouter()

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

const averagePressure = computed(() => Math.round(
  ((stats.value.hosts?.avg_cpu || 0) + (stats.value.hosts?.avg_memory || 0) + (stats.value.hosts?.avg_disk || 0)) / 3,
))

const stabilityScore = computed(() => {
  const criticalPenalty = (stats.value.alerts?.critical || 0) * 16
  const offlinePenalty = (stats.value.hosts?.offline || 0) * 6
  const failedPenalty = (stats.value.deployments?.failed || 0) * 5
  return Math.max(18, 100 - criticalPenalty - offlinePenalty - failedPenalty)
})

const stabilityCopy = computed(() => {
  if (stabilityScore.value >= 85) return '整体稳定，可继续关注发布节奏和容量变化。'
  if (stabilityScore.value >= 60) return '存在一定波动，建议优先处理风险告警和离线主机。'
  return '当前风险较高，建议立即切换到告警和主机页面排查。'
})

const overviewTone = computed(() => {
  if ((stats.value.alerts?.critical || 0) > 0 || (stats.value.hosts?.offline || 0) >= 3) return { type: 'danger', label: '需要值守' }
  if ((stats.value.alerts?.warning || 0) > 0 || (stats.value.deployments?.failed || 0) > 0) return { type: 'warning', label: '持续关注' }
  return { type: 'success', label: '整体稳定' }
})

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
    label: '未认领告警',
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

const primaryRiskAction = computed(() => {
  if ((stats.value.alerts?.critical || 0) > 0 || (stats.value.alerts?.unacknowledged || 0) > 0) {
    return { name: '告警中心', reason: '先看严重和未认领告警。' }
  }
  if ((stats.value.hosts?.offline || 0) > 0 || (stats.value.hosts?.warning || 0) > 0) {
    return { name: '主机中心', reason: '先查主机连通性和健康状态。' }
  }
  return { name: '发布中心', reason: '优先核对最近发布状态。' }
})

const riskFocusLegend = computed(() => [
  {
    label: '严重告警',
    value: `${stats.value.alerts?.critical || 0} 条`,
    meta: `未认领 ${stats.value.alerts?.unacknowledged || 0} 条`,
    tone: (stats.value.alerts?.critical || 0) > 0 ? 'danger' : (stats.value.alerts?.unacknowledged || 0) > 0 ? 'warning' : 'good',
  },
  {
    label: '离线主机',
    value: `${stats.value.hosts?.offline || 0} 台`,
    meta: `告警主机 ${stats.value.hosts?.warning || 0} 台`,
    tone: (stats.value.hosts?.offline || 0) > 0 ? 'danger' : (stats.value.hosts?.warning || 0) > 0 ? 'warning' : 'good',
  },
  {
    label: '失败发布',
    value: `${stats.value.deployments?.failed || 0} 次`,
    meta: `运行中 ${stats.value.deployments?.running || 0} 个`,
    tone: (stats.value.deployments?.failed || 0) > 0 ? 'warning' : 'good',
  },
])

const resourceMeters = computed(() => [
  { label: 'CPU', value: formatPercent(stats.value.hosts?.avg_cpu), percentage: Number(stats.value.hosts?.avg_cpu || 0), color: '#4f46e5' },
  { label: '内存', value: formatPercent(stats.value.hosts?.avg_memory), percentage: Number(stats.value.hosts?.avg_memory || 0), color: '#0ea5a5' },
  { label: '磁盘', value: formatPercent(stats.value.hosts?.avg_disk), percentage: Number(stats.value.hosts?.avg_disk || 0), color: '#f97316' },
])

const alertStripItems = computed(() => {
  const items = []
  if ((stats.value.alerts?.critical || 0) > 0) items.push(`存在 ${stats.value.alerts.critical} 条严重告警，建议优先进入告警中心处理。`)
  if ((stats.value.hosts?.offline || 0) > 0) items.push(`当前有 ${stats.value.hosts.offline} 台主机离线，需要排查连通性或采集状态。`)
  if ((stats.value.deployments?.failed || 0) > 0) items.push(`最近发布存在 ${stats.value.deployments.failed} 次失败记录，建议复盘变更影响。`)
  if ((stats.value.hosts?.avg_cpu || 0) >= 70) items.push(`平台平均 CPU 已到 ${formatPercent(stats.value.hosts.avg_cpu)}，需关注资源峰值。`)
  return items.slice(0, 3)
})

const dutyCards = computed(() => [
  {
    label: '先看哪里',
    value: primaryRiskAction.value.name,
    description: `本班建议先进入${primaryRiskAction.value.name}，${primaryRiskAction.value.reason}`,
    tone: (stats.value.alerts?.critical || 0) > 0 ? 'danger' : (stats.value.hosts?.offline || 0) > 0 ? 'warning' : 'info',
  },
  {
    label: '值班待办',
    value: `${(stats.value.alerts?.unacknowledged || 0) + (stats.value.hosts?.offline || 0) + (stats.value.deployments?.failed || 0)} 项`,
    description: `先清未认领告警 ${stats.value.alerts?.unacknowledged || 0} 项，再看离线主机 ${stats.value.hosts?.offline || 0} 台，最后复核失败发布 ${stats.value.deployments?.failed || 0} 次。`,
    tone: ((stats.value.alerts?.unacknowledged || 0) + (stats.value.hosts?.offline || 0) + (stats.value.deployments?.failed || 0)) > 0 ? 'warning' : 'info',
  },
  {
    label: '容量巡检',
    value: `${averagePressure.value}%`,
    description: averagePressure.value >= 70 ? '平均资源已偏高，建议核对 CPU、内存、磁盘峰值，并继续下钻热点主机。' : '当前平均资源水位平稳，按例行巡检节奏关注即可。',
    tone: averagePressure.value >= 80 ? 'danger' : averagePressure.value >= 70 ? 'warning' : 'info',
  },
  {
    label: '变更窗口',
    value: `${stats.value.deployments?.running || 0} 个`,
    description: (stats.value.deployments?.failed || 0) > 0 ? `近期有 ${stats.value.deployments?.failed || 0} 次失败发布，建议把失败时间点和当前告警、主机异常一起对照复盘。` : '近期没有明显失败积压，值班时重点盯住运行中发布进度和变更窗口。',
    tone: (stats.value.deployments?.failed || 0) > 0 ? 'danger' : (stats.value.deployments?.running || 0) > 0 ? 'warning' : 'neutral',
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
    tooltip: { trigger: 'item', formatter: '{b}: {c}' },
    color: ['#ef4444', '#f59e0b', '#8b5cf6', '#0ea5a5'],
    legend: { bottom: 0, icon: 'circle', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748b' } },
    series: [{
      type: 'pie',
      radius: ['50%', '74%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 10, borderColor: '#ffffff', borderWidth: 4 },
      label: { formatter: '{b}\n{c}', fontSize: 12, color: '#334155' },
      data: [
        { value: Math.max(1, (stats.value.alerts?.critical || 0) * 4 + (stats.value.alerts?.unacknowledged || 0)), name: '告警风险' },
        { value: Math.max(1, (stats.value.hosts?.offline || 0) * 3 + (stats.value.hosts?.warning || 0)), name: '主机风险' },
        { value: Math.max(1, (stats.value.deployments?.failed || 0) * 3 + (stats.value.deployments?.running || 0)), name: '发布风险' },
        { value: Math.max(1, Math.round(averagePressure.value / 10)), name: '资源压力' },
      ],
    }],
    graphic: [{
      type: 'group',
      left: 'center',
      top: '34%',
      children: [
        { type: 'text', style: { text: overviewTone.value.label, fontSize: 24, fontWeight: 700, fill: '#0f172a', textAlign: 'center' }, left: -44 },
        { type: 'text', style: { text: `稳定度 ${stabilityScore.value}`, fontSize: 12, fill: '#64748b', textAlign: 'center' }, top: 36, left: -33 },
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
  try {
    stats.value = await getDashboardStats()
    await nextTick()
    renderCharts()
    if (showMessage) ElMessage.success('仪表盘已刷新')
  } catch (error) {
    console.error('获取仪表盘统计失败', error)
    ElMessage.error('获取仪表盘数据失败')
  }
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

.dashboard-stats {
  margin-bottom: 8px;
}

.release-stat-card {
  position: relative;
  min-height: 128px;
  padding: 18px 18px 17px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.96);
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  box-shadow:
    0 8px 20px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.92);
  overflow: hidden;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}

.release-stat-card::before {
  content: '';
  position: absolute;
  top: 14px;
  left: 18px;
  width: 34px;
  height: 3px;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa 0%, #3b82f6 100%);
}

.release-stat-card::after {
  content: '';
  position: absolute;
  right: -20px;
  bottom: -24px;
  width: 78px;
  height: 78px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(191,219,254,.22) 0%, rgba(191,219,254,0) 72%);
}

.release-stat-card:hover {
  transform: translateY(-2px);
  border-color: rgba(191, 219, 254, 0.98);
  box-shadow:
    0 12px 28px rgba(37, 99, 235, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.92);
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

.context-card {
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
}

.success-card {
  background: linear-gradient(180deg, #ffffff 0%, #f7fcf9 100%);
}

.warning-card {
  background: linear-gradient(180deg, #ffffff 0%, #fffaf4 100%);
}

.danger-card {
  background: linear-gradient(180deg, #ffffff 0%, #fff7f7 100%);
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
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f5f9ff;
  color: #3b82f6;
  border: 1px solid rgba(219, 234, 254, 0.95);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.94);
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: auto;
  height: auto;
  padding: 0;
  border-radius: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #8a94a6;
  background: transparent;
  border: none;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  white-space: nowrap;
  line-height: 1.05;
}

.stat-value,
.stat-label,
.stat-meta {
  position: relative;
  z-index: 1;
}

.stat-value {
  margin-top: 20px;
  font-size: 29px;
  line-height: 1.02;
  font-weight: 700;
  color: var(--overview-text);
  letter-spacing: -0.02em;
}

.stat-label {
  margin-top: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.stat-meta {
  margin-top: 7px;
  font-size: 12px;
  color: #7b8794;
  line-height: 1.6;
}

.success-card .stat-icon-shell {
  background: #f1fbf6;
  color: #10b981;
  border-color: rgba(187, 247, 208, 0.95);
}

.warning-card .stat-icon-shell {
  background: #fffaf0;
  color: #f59e0b;
  border-color: rgba(254, 240, 138, 0.95);
}

.danger-card .stat-icon-shell {
  background: #fff5f5;
  color: #ef4444;
  border-color: rgba(254, 202, 202, 0.96);
}

.success-card .metric-badge {
  color: #10b981;
}

.warning-card .metric-badge {
  color: #f59e0b;
}

.danger-card .metric-badge {
  color: #ef4444;
}

.dashboard-alert-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  padding: 12px 16px;
  border-radius: 16px;
  border: 1px solid #dbeafe;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f8ff 100%);
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
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.96);
}

.dashboard-alert-strip__item {
  font-size: 12px;
  line-height: 1.6;
  color: #33527f;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.9fr);
  gap: 8px;
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
  margin-bottom: 8px;
}

.section-head.compact {
  margin-bottom: 8px;
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
  gap: 8px;
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
  gap: 8px;
}

.score-card {
  padding: 12px 14px;
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
  margin-top: 6px;
  font-size: 22px;
  color: var(--overview-text);
}

.score-card p {
  margin: 5px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--overview-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  border-color: rgba(226, 232, 240, 0.95);
  background: #f8fafc;
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
  margin-bottom: 8px;
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

@media (max-width: 768px) {
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
