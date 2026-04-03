<template>
  <div class="event-wall-page fade-in">
    <section class="hero panel">
      <div class="hero-main">
        <span class="hero-icon">
          <el-icon><Tickets /></el-icon>
        </span>
        <div class="hero-copy">
          <div class="hero-title-row">
            <h2>事件流</h2>
            <p>只看终态结果事件，围绕失败和关键执行动作做定位与审计。</p>
          </div>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="loadEvents" :loading="loading">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <EventWallTabs />

    <section class="scope-shell">
      <div class="scope-tip">先按业务线、环境、应用过滤，再结合模块和结果定位具体问题。</div>
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

    <section class="panel compact-panel">
      <div class="filter-grid">
        <el-select v-model="filters.module" size="small" placeholder="模块" clearable>
          <el-option v-for="item in moduleOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="filters.result" size="small" placeholder="结果" clearable>
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="待处理" value="pending" />
          <el-option label="部分成功" value="partial" />
        </el-select>
        <el-input v-model="filters.actor" size="small" placeholder="操作人" clearable />
        <el-input v-model="filters.correlation_id" size="small" placeholder="关联 ID" clearable />
        <el-input v-model="filters.search" size="small" placeholder="标题 / 资源 / 摘要" clearable />
        <el-select v-model="filters.is_demo" size="small" placeholder="数据范围" clearable>
          <el-option label="全部" value="" />
          <el-option label="仅演示数据" value="true" />
          <el-option label="仅真实数据" value="false" />
        </el-select>
        <el-button size="small" type="primary" @click="applyFilters">查询事件</el-button>
      </div>
    </section>

    <section class="panel compact-panel">
      <div class="timeline-list" v-loading="loading">
        <article v-for="item in events" :key="item.id" class="timeline-item" @click="openDetail(item)">
          <div class="timeline-dot" :class="`timeline-dot--${item.result}`"></div>
          <div class="timeline-card">
            <div class="timeline-head">
              <strong>{{ item.title }}</strong>
              <span>{{ formatTime(item.occurred_at) }}</span>
            </div>
            <p>{{ item.summary }}</p>
            <div class="timeline-meta">
              <el-tag size="small" effect="plain">{{ moduleLabel(item.module) }}</el-tag>
              <el-tag size="small" :type="tagType(item.result)">{{ item.result_display }}</el-tag>
              <span>{{ item.business_line || '-' }}</span>
              <span>{{ item.environment || '-' }}</span>
              <span>{{ item.application || item.resource_name || '-' }}</span>
              <span>{{ item.actor_username || 'system' }}</span>
            </div>
          </div>
        </article>

        <el-empty v-if="!loading && !events.length" description="当前筛选条件下没有事件" />
      </div>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadEvents"
        />
      </div>
    </section>

    <el-drawer
      v-model="drawerVisible"
      title="事件详情"
      size="760px"
      append-to-body
      destroy-on-close
      class="event-detail-drawer"
    >
      <div v-if="activeEvent" class="detail-stack">
        <section class="detail-card">
          <strong>{{ activeEvent.title }}</strong>
          <p>{{ activeEvent.summary }}</p>
          <div class="detail-row"><span>时间</span><span>{{ formatTime(activeEvent.occurred_at) }}</span></div>
          <div class="detail-row"><span>模块</span><span>{{ moduleLabel(activeEvent.module) }}</span></div>
          <div class="detail-row"><span>业务线</span><span>{{ activeEvent.business_line || '-' }}</span></div>
          <div class="detail-row"><span>环境</span><span>{{ activeEvent.environment || '-' }}</span></div>
          <div class="detail-row"><span>应用</span><span>{{ activeEvent.application || '-' }}</span></div>
          <div class="detail-row"><span>操作人</span><span>{{ activeEvent.actor_username || 'system' }}</span></div>
          <div class="detail-row"><span>关联 ID</span><span>{{ activeEvent.correlation_id || '-' }}</span></div>
        </section>

        <section class="detail-card">
          <h4>关联资源</h4>
          <div class="chip-wrap">
            <span v-for="item in activeEvent.related_resources || []" :key="`${item.type}-${item.id}`" class="chip">
              {{ moduleLabel(item.module) }} / {{ item.name || item.type }}
            </span>
          </div>
        </section>

        <section class="detail-card">
          <h4>变更内容</h4>
          <pre>{{ prettyJson(activeEvent.changes || {}) }}</pre>
        </section>

        <section class="detail-card">
          <h4>元数据</h4>
          <pre>{{ prettyJson(activeEvent.metadata || {}) }}</pre>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight, Tickets } from '@element-plus/icons-vue'
import { getEventWallEvents, getEventWallFilterOptions } from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const drawerVisible = ref(false)
const events = ref([])
const activeEvent = ref(null)
const total = ref(0)
const page = ref(1)
const pageSize = 24
const filterOptions = ref({ business_lines: [], environments: [], applications: [] })
const scopeFilters = reactive({
  business_line: '',
  environment: '',
  application: '',
})
const filters = reactive({
  module: '',
  result: '',
  actor: '',
  search: '',
  correlation_id: '',
  resource_id: '',
  is_demo: '',
})

const moduleOptions = [
  { label: '运维', value: 'ops' },
  { label: 'SQL 审计', value: 'sqlaudit' },
  { label: '多云', value: 'multicloud' },
  { label: 'RBAC', value: 'rbac' },
  { label: '工具市场', value: 'marketplace' },
  { label: 'CMDB', value: 'cmdb' },
]

function moduleLabel(value) {
  return moduleOptions.find(item => item.value === value)?.label || value
}

function tagType(result) {
  return {
    success: 'success',
    failed: 'danger',
    rejected: 'warning',
    pending: 'info',
    partial: 'warning',
  }[result] || 'info'
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2)
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

function openDetail(item) {
  activeEvent.value = item
  drawerVisible.value = true
}

function applyFilters() {
  page.value = 1
  loadEvents()
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

async function loadFilterOptions() {
  filterOptions.value = await getEventWallFilterOptions()
}

async function loadEvents() {
  loading.value = true
  try {
    const response = await getEventWallEvents({
      page: page.value,
      page_size: pageSize,
      ...buildScopeParams(),
      module: filters.module || undefined,
      result: filters.result || undefined,
      actor: filters.actor || undefined,
      search: filters.search || undefined,
      correlation_id: filters.correlation_id || undefined,
      resource_id: filters.resource_id || undefined,
      is_demo: filters.is_demo || undefined,
      days: 30,
    })
    events.value = response.results || []
    total.value = response.count || 0
  } finally {
    loading.value = false
  }
}

watch(
  () => route.query,
  () => {
    syncScopeFromRoute()
    filters.module = typeof route.query.module === 'string' ? route.query.module : ''
    filters.result = typeof route.query.result === 'string' ? route.query.result : ''
    filters.actor = typeof route.query.actor === 'string' ? route.query.actor : ''
    filters.correlation_id = typeof route.query.correlation_id === 'string' ? route.query.correlation_id : ''
    filters.resource_id = typeof route.query.resource_id === 'string' ? route.query.resource_id : ''
    loadEvents()
  },
  { deep: true },
)

onMounted(async () => {
  syncScopeFromRoute()
  filters.module = typeof route.query.module === 'string' ? route.query.module : ''
  filters.result = typeof route.query.result === 'string' ? route.query.result : ''
  filters.actor = typeof route.query.actor === 'string' ? route.query.actor : ''
  filters.correlation_id = typeof route.query.correlation_id === 'string' ? route.query.correlation_id : ''
  filters.resource_id = typeof route.query.resource_id === 'string' ? route.query.resource_id : ''
  await loadFilterOptions()
  await loadEvents()
})
</script>

<style scoped>
.event-wall-page { display: flex; flex-direction: column; gap: 8px; }
.panel { background: linear-gradient(180deg, #fffefa 0%, #ffffff 48%, #f8fafc 100%); border: 1px solid rgba(148, 163, 184, .16); border-radius: 20px; box-shadow: 0 12px 28px rgba(15, 23, 42, .05); padding: 12px 14px; }
.compact-panel { padding-top: 10px; padding-bottom: 10px; }
.hero, .hero-main, .hero-actions, .timeline-head, .timeline-meta, .detail-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.hero-title-row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.hero-icon { align-items: center; background: linear-gradient(135deg, #0f766e, #ea580c); border-radius: 16px; color: #fff; display: inline-flex; height: 42px; justify-content: center; width: 42px; box-shadow: 0 10px 18px rgba(15, 118, 110, .16); }
.hero h2 { margin: 0; font-size: 23px; line-height: 1.1; }
.hero p { color: var(--text-secondary); margin: 0; font-size: 13px; }
.scope-shell { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border-radius: 18px; border: 1px solid rgba(226, 232, 240, .9); background: linear-gradient(180deg, rgba(255, 255, 255, .96), rgba(248, 250, 252, .92)); box-shadow: 0 12px 26px rgba(15, 23, 42, .04); }
.scope-tip { color: #64748b; font-size: 12px; line-height: 1.4; }
.scope-grid { display: grid; grid-template-columns: 1.2fr 1fr 1.4fr auto auto; gap: 8px; }
.filter-grid { display: grid; gap: 8px; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.timeline-list { display: flex; flex-direction: column; gap: 8px; min-height: 180px; }
.timeline-item { cursor: pointer; display: flex; gap: 10px; }
.timeline-dot { border-radius: 999px; box-shadow: 0 0 0 4px rgba(148, 163, 184, .12); height: 10px; margin-top: 9px; width: 10px; }
.timeline-dot--success { background: #10b981; }
.timeline-dot--failed { background: #ef4444; }
.timeline-dot--pending, .timeline-dot--partial, .timeline-dot--rejected { background: #f59e0b; }
.timeline-card { background: linear-gradient(180deg, #ffffff, #fffaf5); border: 1px solid #e2e8f0; border-radius: 14px; flex: 1; padding: 10px 12px; }
.timeline-card strong { font-size: 14px; line-height: 1.35; }
.timeline-card p {
  color: var(--text-secondary);
  line-height: 1.45;
  margin: 5px 0;
  font-size: 13px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.timeline-meta { color: var(--text-secondary); font-size: 12px; column-gap: 8px; row-gap: 4px; }
.pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.detail-stack { display: flex; flex-direction: column; gap: 10px; }
.detail-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 12px 13px; }
.detail-card h4, .detail-card p, .detail-card strong { margin: 0 0 8px; }
.detail-card p { color: var(--text-secondary); line-height: 1.6; }
.detail-card pre { background: #0f172a; border-radius: 12px; color: #e2e8f0; font-size: 12px; overflow: auto; padding: 10px; white-space: pre-wrap; }
.chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: #fff7ed; border: 1px solid #fdba74; border-radius: 999px; color: #9a3412; font-size: 12px; padding: 5px 9px; }
:deep(.event-detail-drawer) { max-width: calc(100vw - 24px); }
:deep(.event-detail-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 16px 18px 10px;
  border-bottom: 1px solid rgba(226, 232, 240, .9);
}
:deep(.event-detail-drawer .el-drawer__body) {
  padding: 14px 18px 18px;
  overflow: auto;
  background: linear-gradient(180deg, #fffdfa 0%, #f8fafc 100%);
}
@media (min-width: 761px) {
  :deep(.event-detail-drawer) {
    height: calc(100% - 20px) !important;
    margin: 10px 10px 10px auto;
    border-radius: 20px 0 0 20px;
    overflow: hidden;
  }
}
@media (max-width: 1200px) {
  .filter-grid,
  .scope-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .filter-grid,
  .scope-grid { grid-template-columns: 1fr; }
  .hero-title-row { align-items: flex-start; }
  :deep(.event-detail-drawer) {
    width: calc(100vw - 12px) !important;
    max-width: none;
    height: calc(100% - 12px) !important;
    margin: 6px 6px 6px auto;
    border-radius: 16px 0 0 16px;
    overflow: hidden;
  }
  :deep(.event-detail-drawer .el-drawer__header) { padding: 14px 14px 10px; }
  :deep(.event-detail-drawer .el-drawer__body) { padding: 12px 14px 14px; }
}
</style>
