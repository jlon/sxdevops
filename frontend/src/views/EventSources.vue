<template>
  <div class="event-source-page fade-in">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Share /></el-icon>
          </span>
          <h2>事件源</h2>
          <span class="hero-tagline">沉淀事件线索辅助问题溯源，支持通过 Webhook 接入 Jira、Jenkins、GitLab 等外部系统</span>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadAll">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button v-if="canManageSources" size="small" type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>
          新建接入
        </el-button>
      </div>
    </section>

    <section class="capability-section">
      <div class="stats-grid release-stats dashboard-stats capability-card-grid">
        <div v-for="item in statCards" :key="item.label" class="stat-card release-stat-card" :class="item.tone">
          <div class="stat-inline">
            <span class="stat-label">{{ item.label }}</span>
            <span class="stat-value">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </section>

    <EventWallTabs />

    <section class="source-board">
      <div class="panel source-map-panel" v-loading="loading">
        <div class="section-head">
          <h3>接入概览</h3>
          <span>{{ filteredSources.length }} 个事件源</span>
        </div>
        <div class="source-filter-bar">
          <button
            v-for="item in kindSummary"
            :key="item.kind"
            type="button"
            class="source-filter-pill"
            :class="{ active: sourceKindFilter === item.kind }"
            @click="sourceKindFilter = sourceKindFilter === item.kind ? '' : item.kind"
          >
            {{ item.label }} <b>{{ item.count }}</b>
          </button>
          <i></i>
          <button
            v-for="item in statusSummary"
            :key="item.status"
            type="button"
            class="source-filter-pill"
            :class="{ active: statusFilter === item.status }"
            @click="statusFilter = statusFilter === item.status ? '' : item.status"
          >
            <em :class="`is-${item.status}`"></em>
            {{ item.label }} <b>{{ item.count }}</b>
          </button>
          <button v-if="sourceKindFilter || statusFilter" type="button" class="source-filter-pill clear" @click="clearAllFilters">清空</button>
        </div>
        <div class="source-card-grid">
          <article
            v-for="item in featuredSources"
            :key="item.code"
            class="source-card"
            :class="[`is-${item.status}`, { disabled: !item.enabled }]"
          >
            <header>
              <div class="source-avatar" :class="`is-${item.source_kind}`">{{ sourceInitial(item) }}</div>
              <span>
                <strong>{{ item.name }}</strong>
                <em>{{ item.code }}</em>
              </span>
              <i class="status-dot" :class="`is-${item.status}`"></i>
            </header>
            <p>{{ item.description || `${typeLabel(item.source_type)} 事件进入故障分析时间线` }}</p>
            <div class="source-meta">
              <span>{{ kindLabel(item.source_kind) }}</span>
              <span>{{ typeLabel(item.source_type) }}</span>
              <span>{{ sourceEventCategoryLabel(item) }}</span>
              <span>{{ statusLabel(item.status) }}</span>
            </div>
            <footer>
              <span>
                <b>{{ item.recent_event_count || 0 }}</b>
                <em>7 天事件</em>
              </span>
              <span>
                <b>{{ formatShortTime(item.last_event_at || item.last_sync_at) }}</b>
                <em>最近写入</em>
              </span>
            </footer>
            <div class="card-actions">
              <el-button size="small" text type="primary" @click="openEvents(item)">看事件</el-button>
              <el-button v-if="canManageSources && item.source_kind === 'external'" size="small" text @click="openEditAccess(item)">编辑</el-button>
              <el-button v-if="item.source_kind === 'external'" size="small" text @click="openSpec(item)">接入规范</el-button>
              <el-button v-if="item.source_kind === 'external'" size="small" text @click="copyEndpoint(item)">复制地址</el-button>
            </div>
          </article>
        </div>
        <el-empty v-if="!loading && !featuredSources.length" description="当前筛选条件下没有事件源" />
      </div>
    </section>

    <el-dialog v-model="sourceDialogVisible" title="新建自定义 Webhook 接入" width="620px" append-to-body destroy-on-close>
      <div class="access-create-tip">
        <strong>接入流程</strong>
        <span>先选择默认事件分类并创建来源，平台会立即生成接收地址和令牌；外部系统只负责 POST 事务事件。</span>
      </div>
      <el-form label-position="top" :model="sourceForm" class="access-create-form">
        <el-form-item label="接入名称">
          <el-input v-model="sourceForm.name" placeholder="例如：内部发布平台" />
        </el-form-item>
        <el-form-item label="接入编码（用于生成 Webhook 地址，创建后不建议修改）">
          <el-input v-model="sourceForm.code" placeholder="例如：internal-release" />
        </el-form-item>
        <el-form-item label="默认事件分类">
          <el-select v-model="sourceForm.event_category" placeholder="请选择接入事件分类" style="width: 100%">
            <el-option v-for="item in eventCategoryOptions" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源系统地址（可选，仅用于备注来源，不是平台接收地址）">
          <el-input v-model="sourceForm.endpoint_url" placeholder="例如：https://release.example.com" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="sourceForm.description" type="textarea" :rows="3" placeholder="说明这个接入会推送哪些事务事件" />
        </el-form-item>
        <div class="access-endpoint-preview">
          <span>创建后的平台接收地址</span>
          <strong>{{ endpointPreview }}</strong>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialogVisible = false">取消</el-button>
        <el-button @click="resetSourceForm">重置</el-button>
        <el-button type="primary" :loading="saving" @click="saveSource">创建并签发令牌</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="specDrawerVisible" title="事件源接入规范" size="660px" append-to-body destroy-on-close>
      <div class="drawer-stack">
        <section class="detail-section detail-section--main">
          <strong>{{ activeSource?.name || '自定义事件源' }}</strong>
          <p>{{ activeSource?.description || '外部系统按统一载荷写入事件墙，进入故障分析时间线。' }}</p>
          <div class="endpoint-line">{{ endpointFor(activeSource) }}</div>
        </section>
        <section class="detail-section">
          <h4>必填字段</h4>
          <div class="chip-wrap">
            <span v-for="item in ingestSpec.required_fields || []" :key="item">{{ item }}</span>
          </div>
        </section>
        <section class="detail-section">
          <h4>推荐字段</h4>
          <div class="chip-wrap">
            <span v-for="item in ingestSpec.recommended_fields || []" :key="item">{{ item }}</span>
          </div>
        </section>
        <section class="detail-section">
          <h4>事件分类结构</h4>
          <div class="category-spec-list">
            <div v-for="item in ingestSpec.event_categories || eventCategoryOptions" :key="item.key">
              <strong>{{ item.label }}</strong>
              <span>{{ item.description || '-' }}</span>
              <em>必填：{{ (item.required_fields || []).join(' / ') || 'title / event_category' }}</em>
            </div>
          </div>
        </section>
        <section class="detail-section">
          <h4>字段映射</h4>
          <div class="mapping-list">
            <span v-for="entry in mappingEntries(activeSource || {})" :key="entry">{{ entry }}</span>
            <em v-if="!mappingEntries(activeSource || {}).length">暂无字段映射</em>
          </div>
        </section>
        <section class="detail-section">
          <h4>示例载荷</h4>
          <pre>{{ prettyJson(ingestSpec.example || {}) }}</pre>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="editDialogVisible" title="编辑事件源接入" width="620px" append-to-body destroy-on-close>
      <el-form label-position="top" :model="sourceEditForm" class="access-edit-form">
        <el-form-item label="接入编码">
          <el-input v-model="sourceEditForm.code" disabled />
        </el-form-item>
        <el-form-item label="Webhook 接收地址">
          <el-input :model-value="endpointFor(editingSource)" readonly>
            <template #append>
              <el-button @click="copyEndpoint(editingSource)">复制</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="接入名称">
          <el-input v-model="sourceEditForm.name" />
        </el-form-item>
        <el-form-item label="默认事件分类">
          <el-select v-model="sourceEditForm.event_category" style="width: 100%">
            <el-option v-for="item in eventCategoryOptions" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源系统地址（可选，仅备注）">
          <el-input v-model="sourceEditForm.endpoint_url" placeholder="例如：https://release.example.com" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="sourceEditForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="sourceEditForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditAccess">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tokenDialogVisible" title="接入令牌" width="560px" append-to-body>
      <div class="token-box">
        <span>令牌只在本次签发后展示，请配置到外部系统的请求头。</span>
        <pre>{{ issuedToken }}</pre>
      </div>
      <template #footer>
        <el-button @click="copyToken">复制令牌</el-button>
        <el-button type="primary" @click="tokenDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, RefreshRight, Share } from '@element-plus/icons-vue'
import {
  createEventSource,
  getEventSourceIngestSpec,
  getEventSourceSummary,
  getEventSources,
  issueEventSourceToken,
  updateEventSource,
} from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const sources = ref([])
const summary = ref({})
const ingestSpec = ref({})
const statusFilter = ref('')
const sourceKindFilter = ref('')
const specDrawerVisible = ref(false)
const sourceDialogVisible = ref(false)
const editDialogVisible = ref(false)
const tokenDialogVisible = ref(false)
const activeSource = ref(null)
const editingSource = ref(null)
const issuedToken = ref('')
const sourceForm = reactive({ name: '', code: '', description: '', endpoint_url: '', event_category: 'ops_transaction' })
const sourceEditForm = reactive({ code: '', name: '', description: '', endpoint_url: '', event_category: 'ops_transaction', enabled: false })

const canManageSources = computed(() => authStore.hasPermission('eventwall.source.manage'))
const eventCategoryOptions = [
  { key: 'application_release', label: '应用发布', description: '应用发布、回滚、启停、下线和流水线发布类事件。' },
  { key: 'db_change', label: 'DB变更', description: 'SQL 上线、数据库结构变更、数据修复和执行结果类事件。' },
  { key: 'config_change', label: '配置变更', description: '配置发布、参数调整、网络策略、域名路由和中间件配置类事件。' },
  { key: 'ops_transaction', label: '运维事务', description: '权限开通、网络配置、机器申请释放和通用运维处理类事件。' },
  { key: 'task_center', label: '任务调度', description: '平台内任务中心与外部自动化任务平台推送的任务执行、定时编排和批量处理事件。' },
]
const statCards = computed(() => [
  { value: `来源 ${summary.value.total_sources || 0}`, label: '事件源总数', tone: '' },
  { value: `内置 ${summary.value.builtin_sources || 0}`, label: '平台内置源', tone: 'success-card' },
  { value: `启用 ${summary.value.external_enabled || 0}`, label: '外部启用源', tone: 'warning-card' },
  { value: `入库 ${summary.value.recent_events_7d || 0}`, label: '7 天入库事件', tone: 'danger-card' },
])
const filteredSources = computed(() => {
  return sources.value.filter((item) => {
    if (sourceKindFilter.value && item.source_kind !== sourceKindFilter.value) return false
    if (statusFilter.value && item.status !== statusFilter.value) return false
    return true
  })
})
const featuredSources = computed(() => {
  return [...filteredSources.value]
    .sort((a, b) => {
      const statusWeight = { warning: 0, not_configured: 1, disabled: 2, healthy: 3 }
      const statusDelta = (statusWeight[a.status] ?? 9) - (statusWeight[b.status] ?? 9)
      if (statusDelta !== 0) return statusDelta
      return (b.recent_event_count || 0) - (a.recent_event_count || 0)
    })
})
const kindSummary = computed(() => [
  { kind: 'builtin', label: '平台内置', count: sources.value.filter(source => source.source_kind === 'builtin').length },
  { kind: 'external', label: '外部接入', count: sources.value.filter(source => source.source_kind === 'external').length },
])
const statusSummary = computed(() => {
  return [
    { status: 'healthy', label: '健康' },
    { status: 'warning', label: '待关注' },
    { status: 'not_configured', label: '未配置' },
    { status: 'disabled', label: '已停用' },
  ].map((item) => {
    const count = sources.value.filter(source => source.status === item.status).length
    return { ...item, count }
  })
})
const endpointPreview = computed(() => endpointFor({ code: sourceForm.code.trim() || '{code}' }))

function kindLabel(kind) {
  return kind === 'external' ? '外部接入' : '平台内置'
}

function typeLabel(type) {
  return {
    builtin_workorder: '工单系统',
    builtin_task: '任务中心',
    jira: 'Jira',
    jenkins: 'Jenkins',
    argocd: 'ArgoCD',
    gitlab: 'GitLab',
    custom: '自定义事件源',
  }[type] || type || '-'
}

function sourceEventCategoryKey(item) {
  return item?.config?.default_event_category || ''
}

function sourceEventCategoryLabel(item) {
  const key = sourceEventCategoryKey(item)
  if (!key && item?.source_kind === 'builtin') return '多分类'
  return eventCategoryOptions.find(option => option.key === key)?.label || '-'
}

function statusLabel(status) {
  return {
    healthy: '健康',
    warning: '待关注',
    disabled: '已停用',
    not_configured: '未配置',
  }[status] || status || '-'
}

function sourceInitial(item) {
  return String(item?.name || item?.code || '?').trim().slice(0, 1).toUpperCase()
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function mappingEntries(item) {
  return Object.entries(item?.field_mapping || {}).slice(0, 8).map(([from, to]) => `${from} -> ${to}`)
}

function endpointFor(item) {
  const code = item?.code || '{code}'
  return (ingestSpec.value.endpoint_template || '/api/event-sources/{code}/ingest/').replace('{code}', code)
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

async function loadAll() {
  loading.value = true
  try {
    const [sourceResponse, summaryResponse, specResponse] = await Promise.all([
      getEventSources({ page_size: 100 }),
      getEventSourceSummary(),
      getEventSourceIngestSpec(),
    ])
    sources.value = sourceResponse.results || sourceResponse || []
    summary.value = summaryResponse || {}
    ingestSpec.value = specResponse || {}
  } finally {
    loading.value = false
  }
}

function openEvents(item) {
  router.push({ path: '/events/wall', query: { event_source_code: item.code } })
}

function openSpec(item) {
  activeSource.value = item || null
  specDrawerVisible.value = true
}

function openCreateDialog() {
  resetSourceForm()
  sourceDialogVisible.value = true
}

function resetSourceForm() {
  Object.assign(sourceForm, { name: '', code: '', description: '', endpoint_url: '', event_category: 'ops_transaction' })
}

function openEditAccess(item) {
  if (!item || item.source_kind !== 'external') return
  editingSource.value = item
  Object.assign(sourceEditForm, {
    code: item.code,
    name: item.name || '',
    description: item.description || '',
    endpoint_url: item.endpoint_url || '',
    event_category: sourceEventCategoryKey(item) || 'ops_transaction',
    enabled: Boolean(item.enabled),
  })
  editDialogVisible.value = true
}

function clearAllFilters() {
  statusFilter.value = ''
  sourceKindFilter.value = ''
}

async function saveSource() {
  if (!sourceForm.name.trim() || !sourceForm.code.trim() || !sourceForm.event_category) {
    ElMessage.warning('请填写名称、编码和默认事件分类')
    return
  }
  saving.value = true
  try {
    const { event_category, ...formData } = sourceForm
    const createdSource = await createEventSource({
      ...formData,
      source_kind: 'external',
      source_type: 'custom',
      enabled: false,
      status: 'not_configured',
      auth_type: 'webhook',
      config: { default_event_category: event_category, created_from: 'event_source_page' },
      field_mapping: { event_id: 'event_id', event_category: 'event_category', occurred_at: 'occurred_at', title: 'title' },
    })
    const tokenResponse = await issueEventSourceToken(createdSource.code || sourceForm.code.trim())
    issuedToken.value = tokenResponse.token
    tokenDialogVisible.value = true
    sourceDialogVisible.value = false
    ElMessage.success('接入已创建并签发令牌')
    resetSourceForm()
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function saveEditAccess() {
  if (!editingSource.value?.code) return
  if (!sourceEditForm.name.trim() || !sourceEditForm.event_category) {
    ElMessage.warning('请填写接入名称和默认事件分类')
    return
  }
  saving.value = true
  try {
    await updateEventSource(editingSource.value.code, {
      name: sourceEditForm.name.trim(),
      description: sourceEditForm.description,
      endpoint_url: sourceEditForm.endpoint_url,
      enabled: sourceEditForm.enabled,
      config: {
        ...(editingSource.value.config || {}),
        default_event_category: sourceEditForm.event_category,
      },
    })
    editDialogVisible.value = false
    ElMessage.success('接入配置已更新')
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function copyToken() {
  if (!issuedToken.value) return
  await navigator.clipboard.writeText(issuedToken.value)
  ElMessage.success('令牌已复制')
}

async function copyEndpoint(item) {
  await navigator.clipboard.writeText(endpointFor(item))
  ElMessage.success('接入地址已复制')
}

onMounted(loadAll)
</script>

<style scoped>
.event-source-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #1f2329;
}

.panel {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
}

.hero {
  min-height: 68px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.hero-copy,
.hero-title-row,
.hero-actions,
.section-head {
  display: flex;
  align-items: center;
}

.hero-copy {
  gap: 4px;
  flex-wrap: wrap;
}

.hero-title-row {
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-title-row h2 {
  margin: 0;
  font-size: 23px;
  font-weight: 700;
  line-height: 1.1;
}

.hero-tagline {
  color: #646a73;
  font-size: 13px;
  line-height: 1.6;
  max-width: 620px;
}

.hero-icon {
  width: 42px;
  height: 42px;
  border-radius: 16px;
  background: linear-gradient(135deg, #0f766e, #2563eb);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.hero-actions {
  gap: 8px;
}

.hero-actions :deep(.el-button) {
  min-height: 32px;
  border-radius: 10px;
  font-weight: 500;
  padding: 0 14px;
}

.hero.panel {
  border-radius: 20px;
}

.capability-section {
  display: block;
}

.capability-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 0;
}

.release-stat-card {
  min-height: 68px;
  padding: 9px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 6px 18px rgba(31, 35, 41, 0.04);
  display: flex;
  align-items: center;
}

.success-card {
  background: linear-gradient(135deg, #dcfce7, #86efac);
}

.warning-card {
  background: linear-gradient(135deg, #fef3c7, #fdba74);
}

.danger-card {
  background: linear-gradient(135deg, #fee2e2, #fca5a5);
}

.stat-inline {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.stat-label {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.stat-value {
  color: #475569;
  font-size: 13px;
  font-weight: 500;
}

.access-create-tip {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(51, 112, 255, 0.14);
  border-radius: 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.access-create-tip strong {
  color: #1f2329;
  font-size: 14px;
}

.access-create-tip span {
  color: #646a73;
  font-size: 13px;
}

.access-create-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.access-edit-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.access-create-form :deep(.el-form-item:nth-child(5)),
.access-edit-form :deep(.el-form-item:nth-child(2)),
.access-edit-form :deep(.el-form-item:nth-child(5)),
.access-edit-form :deep(.el-form-item:nth-child(6)),
.access-endpoint-preview {
  grid-column: 1 / -1;
}

.access-endpoint-preview {
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.access-endpoint-preview span {
  color: #8f959e;
  font-size: 12px;
}

.access-endpoint-preview strong {
  color: #245bdb;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.source-board {
  margin-top: -6px;
  display: block;
}

.source-map-panel {
  padding: 14px;
}

.source-filter-bar {
  margin-bottom: 10px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.source-filter-bar > i {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: #e5e7eb;
}

.source-filter-pill {
  min-height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #4e5969;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.source-filter-pill:hover,
.source-filter-pill.active {
  background: #e8f0ff;
  color: #245bdb;
}

.source-filter-pill.clear {
  color: #245bdb;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.12);
}

.source-filter-pill b {
  font-size: 12px;
}

.source-filter-pill em {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #8f959e;
  flex: 0 0 auto;
}

.source-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.source-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 6px 18px rgba(31, 35, 41, 0.035);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-card:hover {
  border-color: rgba(51, 112, 255, 0.24);
  background: #f7faff;
}

.source-card.is-warning,
.source-card.is-not_configured {
  border-color: #ffd8a8;
}

.source-card.is-disabled,
.source-card.disabled {
  background: #fbfbfc;
  color: #646a73;
}

.source-card header,
.source-card footer,
.source-meta,
.card-actions {
  display: flex;
  align-items: center;
}

.source-card header {
  gap: 8px;
}

.source-card header span {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.source-card strong,
.source-card em,
.source-card p,
.source-meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-card header em,
.source-card footer em,
.source-meta span {
  color: #8f959e;
  font-size: 12px;
  font-style: normal;
}

.source-avatar {
  width: 30px;
  height: 30px;
  border-radius: 12px;
  background: #e8f0ff;
  color: #245bdb;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 700;
}

.source-avatar.is-external {
  background: #e8f8f3;
  color: #0c8f63;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #8f959e;
  flex: 0 0 auto;
}

.status-dot.is-healthy,
.source-filter-pill em.is-healthy {
  background: #34c759;
}

.status-dot.is-warning,
.source-filter-pill em.is-warning {
  background: #ffb11a;
}

.status-dot.is-not_configured,
.source-filter-pill em.is-not_configured {
  background: #f54a45;
}

.status-dot.is-disabled,
.source-filter-pill em.is-disabled {
  background: #8f959e;
}

.source-card p {
  margin: 0;
  color: #4e5969;
  font-size: 13px;
}

.source-meta {
  gap: 6px;
  flex-wrap: wrap;
}

.source-meta span {
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
}

.source-card footer {
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #eff0f1;
}

.source-card footer span {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.source-card footer b {
  max-width: 120px;
  overflow: hidden;
  color: #1f2329;
  font-size: 14px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-actions {
  min-height: 24px;
  gap: 4px;
  flex-wrap: wrap;
}

.card-actions :deep(.el-button) {
  margin-left: 0;
  padding: 0 4px;
}

.section-head {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.section-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.drawer-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-section {
  padding: 12px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.detail-section--main {
  background: #f7faff;
  border-color: #bacefd;
}

.detail-section p {
  margin: 8px 0;
  color: #646a73;
  line-height: 1.6;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.endpoint-line {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff;
  color: #245bdb;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.chip-wrap,
.mapping-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip-wrap span,
.mapping-list span {
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
  color: #4e5969;
  font-size: 12px;
}

.mapping-list em {
  color: #8f959e;
  font-style: normal;
}

.category-spec-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.category-spec-list div {
  padding: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-spec-list strong {
  color: #1f2329;
}

.category-spec-list span,
.category-spec-list em {
  color: #646a73;
  font-style: normal;
  font-size: 12px;
}

.token-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: #646a73;
}

pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  color: #1f2329;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .capability-card-grid {
    grid-template-columns: 1fr 1fr;
  }

  .source-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 700px) {
  .hero,
  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-tagline {
    max-width: none;
  }

  .capability-card-grid,
  .access-create-form,
  .access-edit-form,
  .source-board,
  .source-card-grid {
    grid-template-columns: 1fr;
  }

}
</style>
