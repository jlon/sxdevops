<template>
  <div class="event-wall-page fade-in">
    <section class="hero panel">
      <div class="hero-main">
        <span class="hero-icon">
          <el-icon><Tickets /></el-icon>
        </span>
        <div class="hero-copy">
          <div class="hero-title-row">
            <h2>事件总览</h2>
            <p>聚焦终态结果事件，优先暴露失败发布和高风险执行，服务问题定位与操作审计。</p>
          </div>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="loadOverview" :loading="loading">
          <el-icon><RefreshRight /></el-icon>
          刷新概览
        </el-button>
        <el-button size="small" type="primary" @click="go('/events/wall')">进入事件流</el-button>
      </div>
    </section>

    <EventWallTabs />

    <section class="scope-shell">
      <div class="scope-tip">先按业务线、环境、应用缩小范围，再看失败事件和高风险执行。</div>
      <div class="scope-grid">
        <el-select v-model="scopeFilters.business_line" size="small" placeholder="业务线" clearable>
          <el-option v-for="item in filterOptions.business_lines || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="scopeFilters.environment" size="small" placeholder="环境" clearable>
          <el-option v-for="item in filterOptions.environments || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="scopeFilters.application" size="small" placeholder="应用" clearable filterable>
          <el-option v-for="item in filterOptions.applications || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button size="small" type="primary" :loading="loading" @click="applyScopeFilters">筛选</el-button>
        <el-button size="small" @click="resetScopeFilters">重置</el-button>
      </div>
    </section>

    <div class="stats-grid">
      <article v-for="item in statCards" :key="item.label" class="stat-card" :class="item.tone">
        <span class="stat-kicker">{{ item.kicker }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
        <span class="stat-label">{{ item.label }}</span>
      </article>
    </div>

    <div class="runtime-strip runtime-strip--top">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ overview.tips?.[0] || '当前总览只统计终态结果事件，适合排查失败发布和关键执行动作。' }}</span>
    </div>

    <div class="dual-panel-grid">
      <section class="panel compact-panel">
        <div class="section-head">
          <h3>最近活跃环境</h3>
        </div>
        <div class="compact-list">
          <button
            v-for="item in overview.top_scopes || []"
            :key="`${item.business_line}-${item.environment}`"
            type="button"
            class="compact-item"
            @click="openScope(item)"
          >
            <div class="compact-item-main">
              <strong>{{ item.label }}</strong>
            </div>
            <div class="compact-item-side">
              <strong>{{ item.count }}</strong>
              <span>次</span>
            </div>
          </button>
        </div>
      </section>

      <section class="panel compact-panel">
        <div class="section-head">
          <h3>活跃操作人</h3>
        </div>
        <div class="compact-list">
          <button
            v-for="item in overview.top_actors || []"
            :key="item.actor_username || 'system'"
            type="button"
            class="compact-item"
            :class="{ 'compact-item--disabled': !item.actor_username }"
            :disabled="!item.actor_username"
            @click="openActor(item.actor_username)"
          >
            <div class="compact-item-main">
              <strong>{{ item.actor_username || 'system' }}</strong>
            </div>
            <div class="compact-item-side">
              <strong>{{ item.count }}</strong>
              <span>次</span>
            </div>
          </button>
        </div>
      </section>
    </div>

    <section class="focus-card focus-card--danger">
      <div class="focus-head">
        <div>
          <strong>最近失败事件</strong>
        </div>
        <div class="focus-head-actions">
          <span class="focus-total">{{ overview.priority_events?.length || 0 }} 条</span>
          <el-button size="small" text @click="openFocus({ result: 'failed' })">查看失败事件</el-button>
        </div>
      </div>
      <div class="focus-list">
        <button
          v-for="item in overview.priority_events || []"
          :key="item.id"
          type="button"
          class="focus-item"
          @click="openEvent(item)"
        >
          <div class="focus-item-top">
            <strong>{{ item.title }}</strong>
            <time>{{ formatTime(item.occurred_at) }}</time>
          </div>
          <div class="focus-item-meta">
            <span class="focus-chip">{{ moduleLabel(item.module) }}</span>
            <span class="focus-chip" :class="`focus-chip--${item.result}`">{{ item.result_display }}</span>
            <span>{{ item.business_line || '-' }} / {{ item.environment || '-' }}</span>
            <span>{{ item.application || item.resource_name || '-' }}</span>
            <span>{{ item.actor_username || 'system' }}</span>
          </div>
        </button>
        <div v-if="!(overview.priority_events || []).length" class="focus-empty">当前范围内没有重点事件</div>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel compact-panel">
        <div class="section-head">
          <h3>模块热度</h3>
          <el-button size="small" link type="primary" @click="go('/events/wall')">查看事件流</el-button>
        </div>
        <div class="compact-list">
          <button
            v-for="item in overview.modules || []"
            :key="item.module"
            type="button"
            class="compact-item"
            @click="openFocus({ module: item.module })"
          >
            <div class="compact-item-main">
              <strong>{{ moduleLabel(item.module) }}</strong>
            </div>
            <div class="compact-item-side">
              <strong>{{ item.count }}</strong>
              <span>次</span>
            </div>
          </button>
        </div>
      </section>
    </div>

  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { InfoFilled, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { getEventWallFilterOptions, getEventWallOverview } from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const overview = ref({
  summary: {},
  modules: [],
  top_actors: [],
  top_scopes: [],
  priority_events: [],
  tips: [],
})
const filterOptions = ref({ business_lines: [], environments: [], applications: [] })
const scopeFilters = reactive({
  business_line: '',
  environment: '',
  application: '',
})

const statCards = computed(() => [
  { label: '近 7 天事件', kicker: 'Volume', value: overview.value.summary?.total_7d || 0, tone: 'tone-neutral' },
  { label: '失败事件', kicker: 'Risk', value: overview.value.summary?.failed_7d || 0, tone: 'tone-danger' },
  { label: '待处理链路', kicker: 'Pending', value: overview.value.summary?.pending_7d || 0, tone: 'tone-warning' },
  { label: '活跃对象', kicker: 'Assets', value: overview.value.summary?.tracked_resources_7d || 0, tone: 'tone-success' },
])

function moduleLabel(value) {
  return {
    ops: '运维',
    sqlaudit: 'SQL 审计',
    multicloud: '多云',
    rbac: 'RBAC',
    marketplace: '工具市场',
    cmdb: 'CMDB',
  }[value] || value
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function syncScopeFromRoute() {
  scopeFilters.business_line = typeof route.query.business_line === 'string' ? route.query.business_line : ''
  scopeFilters.environment = typeof route.query.environment === 'string' ? route.query.environment : ''
  scopeFilters.application = typeof route.query.application === 'string' ? route.query.application : ''
}

function buildScopeParams() {
  return {
    business_line: scopeFilters.business_line || undefined,
    environment: scopeFilters.environment || undefined,
    application: scopeFilters.application || undefined,
  }
}

async function loadFilterOptions() {
  filterOptions.value = await getEventWallFilterOptions()
}

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await getEventWallOverview(buildScopeParams())
  } finally {
    loading.value = false
  }
}

function applyScopeFilters() {
  router.replace({
    path: route.path,
    query: {
      ...route.query,
      business_line: scopeFilters.business_line || undefined,
      environment: scopeFilters.environment || undefined,
      application: scopeFilters.application || undefined,
    },
  })
}

function resetScopeFilters() {
  scopeFilters.business_line = ''
  scopeFilters.environment = ''
  scopeFilters.application = ''
  applyScopeFilters()
}

function go(path) {
  router.push({ path, query: { ...buildScopeParams() } })
}

function openFocus(extraQuery) {
  router.push({
    path: '/events/wall',
    query: {
      ...buildScopeParams(),
      ...extraQuery,
    },
  })
}

function openEvent(row) {
  router.push({
    path: '/events/wall',
    query: {
      ...buildScopeParams(),
      ...(row?.correlation_id ? { correlation_id: row.correlation_id } : { resource_id: row?.resource_id || '' }),
    },
  })
}

function openActor(actorUsername) {
  if (!actorUsername) return
  router.push({
    path: '/events/wall',
    query: {
      ...buildScopeParams(),
      actor: actorUsername,
    },
  })
}

function openScope(item) {
  router.push({
    path: '/events/wall',
    query: {
      ...buildScopeParams(),
      business_line: item?.business_line || undefined,
      environment: item?.environment || undefined,
    },
  })
}

watch(
  () => route.query,
  () => {
    syncScopeFromRoute()
    loadOverview()
  },
  { deep: true },
)

onMounted(async () => {
  syncScopeFromRoute()
  await loadFilterOptions()
  await loadOverview()
})
</script>

<style scoped>
.event-wall-page { display: flex; flex-direction: column; gap: 8px; }
.panel { background: linear-gradient(180deg, #fffdfa 0%, #ffffff 50%, #f8fafc 100%); border: 1px solid rgba(148, 163, 184, .16); border-radius: 20px; box-shadow: 0 12px 28px rgba(15, 23, 42, .05); padding: 12px 14px; }
.compact-panel { padding-top: 10px; padding-bottom: 10px; }
.hero, .hero-main, .hero-actions, .section-head, .risk-head, .focus-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.hero-title-row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.hero-copy p, .risk-card p, .risk-card span { color: var(--text-secondary); margin: 0; line-height: 1.5; }
.hero-icon { align-items: center; background: linear-gradient(135deg, #0f766e, #ea580c); border-radius: 16px; color: #fff; display: inline-flex; height: 42px; justify-content: center; width: 42px; box-shadow: 0 10px 18px rgba(234, 88, 12, .18); }
.hero h2, .section-head h3 { margin: 0; }
.hero h2 { font-size: 23px; line-height: 1.1; }
.hero-copy p { font-size: 13px; }
.scope-shell { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border-radius: 18px; border: 1px solid rgba(226, 232, 240, .9); background: linear-gradient(180deg, rgba(255, 255, 255, .96), rgba(248, 250, 252, .92)); box-shadow: 0 12px 26px rgba(15, 23, 42, .04); }
.scope-tip { color: #64748b; font-size: 12px; line-height: 1.4; }
.scope-grid { display: grid; grid-template-columns: 1.2fr 1fr 1.4fr auto auto; gap: 8px; }
.dual-panel-grid { display: grid; gap: 8px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.stats-grid { display: grid; gap: 8px; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.stat-card { border-radius: 14px; color: #0f172a; display: flex; flex-direction: column; justify-content: center; gap: 2px; min-height: 64px; padding: 9px 12px; }
.stat-kicker { font-size: 10px; letter-spacing: .08em; opacity: .7; text-transform: uppercase; }
.stat-value { font-size: 21px; line-height: 1; }
.stat-label { color: #334155; font-size: 11px; line-height: 1.3; }
.tone-neutral { background: linear-gradient(135deg, #fff7ed, #ffedd5); }
.tone-danger { background: linear-gradient(135deg, #fee2e2, #fecaca); }
.tone-warning { background: linear-gradient(135deg, #fef3c7, #fed7aa); }
.tone-success { background: linear-gradient(135deg, #dcfce7, #bbf7d0); }
.focus-card { padding: 12px 14px; border-radius: 18px; border: 1px solid rgba(226, 232, 240, .9); background: linear-gradient(180deg, rgba(255, 255, 255, .98), rgba(248, 250, 252, .94)); box-shadow: 0 12px 26px rgba(15, 23, 42, .05); }
.focus-card--danger { background: linear-gradient(180deg, #fff7f7, #fff1f2); }
.focus-head strong { display: block; color: #0f172a; }
.focus-head-actions { display: flex; align-items: center; gap: 10px; }
.focus-total { color: #b91c1c; font-size: 13px; font-weight: 700; }
.focus-list { display: flex; flex-direction: column; gap: 6px; }
.focus-item { padding: 8px 10px; border: 1px solid rgba(226, 232, 240, .9); border-radius: 12px; background: rgba(255, 255, 255, .88); text-align: left; cursor: pointer; transition: .18s ease border-color, .18s ease transform, .18s ease box-shadow; display: flex; flex-direction: column; gap: 5px; }
.focus-item:hover { transform: translateY(-1px); border-color: rgba(59, 130, 246, .25); box-shadow: 0 10px 18px rgba(37, 99, 235, .08); }
.focus-item-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.focus-item-top strong { color: #0f172a; font-size: 13px; line-height: 1.35; }
.focus-item-top time { color: #64748b; font-size: 11px; white-space: nowrap; }
.focus-item-meta { display: flex; align-items: center; gap: 6px 8px; flex-wrap: wrap; color: #64748b; font-size: 11px; line-height: 1.35; }
.focus-chip { display: inline-flex; align-items: center; height: 20px; padding: 0 7px; border-radius: 999px; background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; font-size: 11px; }
.focus-chip--failed { background: #fef2f2; color: #b91c1c; border-color: #fca5a5; }
.focus-chip--partial { background: #fffbeb; color: #b45309; border-color: #fcd34d; }
.focus-empty { color: #94a3b8; font-size: 12px; padding: 10px 2px; }
.runtime-strip { align-items: center; background: linear-gradient(90deg, rgba(234, 88, 12, .10), rgba(15, 118, 110, .08)); border: 1px solid rgba(234, 88, 12, .14); border-radius: 12px; color: #0f172a; display: flex; gap: 8px; padding: 8px 11px; font-size: 12px; }
.runtime-strip--top { margin-top: -7px; }
.content-grid { display: grid; gap: 8px; grid-template-columns: 1fr; }
.compact-list { display: flex; flex-direction: column; gap: 6px; }
.compact-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
  text-align: left;
  cursor: pointer;
  transition: .18s ease border-color, .18s ease transform, .18s ease box-shadow;
}
.compact-item:hover { border-color: rgba(59, 130, 246, .24); box-shadow: 0 10px 18px rgba(37, 99, 235, .08); transform: translateY(-1px); }
.compact-item-main { min-width: 0; }
.compact-item-main strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.compact-item-side {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  color: #64748b;
  flex-shrink: 0;
}
.compact-item-side strong { color: #c2410c; font-size: 18px; font-weight: 700; line-height: 1; }
.compact-item-side span { font-size: 11px; }
.compact-item--disabled { cursor: default; opacity: .72; }
.compact-item--disabled:hover { border-color: #e2e8f0; box-shadow: none; transform: none; }
:deep(.el-table .cell) { padding-top: 4px; padding-bottom: 4px; }
@media (max-width: 1180px) {
  .stats-grid,
  .dual-panel-grid,
  .content-grid,
  .scope-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 760px) {
  .stats-grid,
  .dual-panel-grid,
  .content-grid,
  .scope-grid { grid-template-columns: 1fr; }
  .hero-title-row { align-items: flex-start; }
}
</style>

