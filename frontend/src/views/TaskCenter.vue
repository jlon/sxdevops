<template>
  <div class="fade-in task-workbench-page">
    <section class="task-hero panel">
      <div class="task-title-row">
        <span class="task-header-icon"><el-icon><Operation /></el-icon></span>
        <h2>任务中心</h2>
        <p class="inline-subtitle">统一承接资源底座、人工下发、AIOps 生成、计划调度和事件中心联动的待执行任务。</p>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="reloadOverview">刷新</el-button>
      </div>
    </section>

    <div class="stats-grid task-stats">
      <div v-for="card in summaryCards" :key="card.label" class="release-stat-card" :class="card.tone">
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
        <div class="release-stat-desc">{{ card.desc }}</div>
      </div>
    </div>

    <div class="task-hint-strip">
      <span>资源底座仅作为任务中心执行底座维护，按“环境 -> 系统 -> 执行资源”组织，不再依赖 CMDB 资源树。</span>
      <el-button link type="primary" size="small" @click="router.push('/events/sources')">查看事件源</el-button>
    </div>

    <div class="neo-tabs theme-purple task-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="neo-tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <TaskResourceBase v-if="activeTab === 'assets'" @tree-updated="handleTreeUpdated" @stats-updated="handleResourceStatsUpdated" />
    <CmdbHostTaskCenter v-else-if="activeTab === 'tasks'" :resource-tree="resourceTree" />
    <CmdbHostScheduleCenter v-else :resource-tree="resourceTree" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Monitor, Operation, Timer } from '@element-plus/icons-vue'
import TaskResourceBase from '@/components/tasks/TaskResourceBase.vue'
import CmdbHostTaskCenter from '@/components/cmdb/CmdbHostTaskCenter.vue'
import CmdbHostScheduleCenter from '@/components/cmdb/CmdbHostScheduleCenter.vue'
import { getHostTaskScheduleStats, getHostTaskStats, getTaskResourceStats, getTaskResourceTree } from '@/api/modules/ops'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const activeTab = ref('tasks')
const resourceTree = ref([])
const resourceStats = ref({ total: 0, host: 0, k8s: 0, active: 0 })
const taskStats = ref({ total: 0, running: 0, pending: 0, success_rate: 0, aiops_pending: 0, high_risk: 0, failed: 0, by_target_type: {} })
const scheduleStats = ref({ total: 0, enabled: 0, due_soon: 0, success_rate: 0 })

const tabs = [
  { key: 'assets', label: '资源底座', icon: Monitor },
  { key: 'tasks', label: '任务工作台', icon: Operation },
  { key: 'schedules', label: '计划任务', icon: Timer },
]

const summaryCards = computed(() => [
  { label: '执行资源', value: resourceStats.value.total || 0, desc: '任务中心独立维护的主机与 K8s 执行资源', tone: '' },
  { label: '可用资源', value: resourceStats.value.active || 0, desc: '当前可被任务下发选择的资源数量', tone: 'success-card' },
  { label: '待执行', value: taskStats.value.pending || 0, desc: 'AIOps、人工或调度生成后等待执行的任务', tone: 'warning-card' },
  { label: '执行中', value: taskStats.value.running || 0, desc: '当前仍在执行器中的任务实例', tone: '' },
  { label: 'AIOps 任务', value: taskStats.value.aiops_pending || 0, desc: '由智能助手生成并等待处理的任务', tone: 'info-card' },
  { label: 'K8s 任务', value: taskStats.value.by_target_type?.k8s || 0, desc: '通过 K8s API 执行的非主机任务', tone: 'success-card' },
])

function normalizeTree(list = []) {
  return list.map(env => ({
    ...env,
    treeKey: `environment:${env.id}`,
    children: (env.children || []).map(system => ({ ...system, treeKey: `system:${system.id}`, children: [] })),
  }))
}

function handleTreeUpdated(tree) {
  resourceTree.value = normalizeTree(tree)
}

function handleResourceStatsUpdated(stats) {
  resourceStats.value = stats || resourceStats.value
}

async function reloadOverview() {
  loading.value = true
  try {
    const [tree, resources, tasks, schedules] = await Promise.all([
      getTaskResourceTree(),
      getTaskResourceStats(),
      getHostTaskStats(),
      getHostTaskScheduleStats(),
    ])
    resourceTree.value = normalizeTree(tree || [])
    resourceStats.value = resources || resourceStats.value
    taskStats.value = tasks || taskStats.value
    scheduleStats.value = schedules || scheduleStats.value
  } finally {
    loading.value = false
  }
}

function syncTabFromRoute() {
  const next = String(route.query.tab || 'tasks')
  activeTab.value = tabs.some(item => item.key === next) ? next : 'tasks'
}

watch(() => route.query.tab, syncTabFromRoute, { immediate: true })
watch(activeTab, (tab) => {
  if (route.query.tab !== tab) {
    const query = { ...route.query }
    if (tab === 'tasks') delete query.tab
    else query.tab = tab
    router.replace({ path: '/tasks', query })
  }
})

onMounted(reloadOverview)
</script>

<style scoped>
.task-workbench-page{display:flex;flex-direction:column;gap:8px}.panel{background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid #dbe4f0;border-radius:20px;box-shadow:0 14px 34px rgba(15,23,42,.06);padding:14px 22px}.task-hero{display:flex;gap:12px;justify-content:space-between;align-items:center;background:linear-gradient(135deg,#f0fdf4 0%,#f8fbff 58%,#fff7ed 100%)}.task-title-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.task-title-row h2{margin:0;color:#0f172a}.inline-subtitle{margin:0;font-size:13px;color:#475569;line-height:1.45}.task-header-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:20px;color:#fff;background:linear-gradient(135deg,#0f766e,#2563eb);box-shadow:0 10px 20px rgba(37,99,235,.16)}.hero-actions{display:flex;align-items:center;gap:8px}.stats-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.release-stat-card{position:relative;min-height:78px;background:linear-gradient(145deg,#ffffff 0%,#f6faff 100%);border:1px solid rgba(148,163,184,.18);border-radius:12px;box-shadow:0 16px 34px rgba(15,23,42,.06);text-align:left;padding:12px 14px;overflow:hidden}.release-stat-card::after{content:'';position:absolute;right:-26px;bottom:-32px;width:106px;height:106px;border-radius:50%;background:radial-gradient(circle,rgba(37,99,235,.15) 0%,rgba(37,99,235,0) 70%)}.warning-card::after{background:radial-gradient(circle,rgba(245,158,11,.2) 0%,rgba(245,158,11,0) 70%)}.success-card::after{background:radial-gradient(circle,rgba(16,185,129,.18) 0%,rgba(16,185,129,0) 70%)}.danger-card::after{background:radial-gradient(circle,rgba(239,68,68,.18) 0%,rgba(239,68,68,0) 70%)}.info-card::after{background:radial-gradient(circle,rgba(14,165,233,.18) 0%,rgba(14,165,233,0) 70%)}.stat-value{font-size:24px;line-height:1.05;color:#0f172a;font-weight:700}.stat-label{margin-top:4px;color:#64748b;font-size:13px}.release-stat-desc{margin-top:6px;color:#64748b;font-size:12px;line-height:1.35}.task-hint-strip{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.7);border:1px solid rgba(148,163,184,.14);font-size:12px;color:#64748b}.task-tabs{width:100%;padding:4px;border-radius:12px;background:rgba(255,255,255,.9);border:1px solid rgba(148,163,184,.16);box-shadow:0 12px 26px rgba(15,23,42,.04)}
@media (max-width: 1200px){.stats-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width: 760px){.task-hero,.task-hint-strip{flex-direction:column;align-items:flex-start}.stats-grid{grid-template-columns:1fr}}
</style>
