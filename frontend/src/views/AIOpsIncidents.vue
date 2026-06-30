<template>
  <div class="fade-in incident-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Warning /></el-icon>
          </span>
          <h2>Incident 中心</h2>
          <p class="page-inline-desc">把多条相关告警归并为一个可跟踪的故障工作对象。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading" @click="fetchIncidents">刷新</el-button>
      </div>
    </section>

    <div class="audit-grid incident-stats">
      <div class="audit-card audit-card--inline">
        <div class="stat-label">总数</div>
        <div class="stat-value">{{ pagination.total }}</div>
      </div>
      <div class="audit-card audit-card--inline danger">
        <div class="stat-label">严重</div>
        <div class="stat-value">{{ criticalCount }}</div>
      </div>
      <div class="audit-card audit-card--inline warning">
        <div class="stat-label">未恢复</div>
        <div class="stat-value">{{ openCount }}</div>
      </div>
      <div class="audit-card audit-card--inline success">
        <div class="stat-label">活跃告警</div>
        <div class="stat-value">{{ activeAlertCount }}</div>
      </div>
    </div>

    <section class="panel">
      <div class="toolbar">
        <el-select v-model="filters.status" size="small" clearable placeholder="状态" @change="handleFilterChange">
          <el-option label="新建" value="open" />
          <el-option label="调查中" value="investigating" />
          <el-option label="处置中" value="mitigating" />
          <el-option label="验证中" value="verifying" />
          <el-option label="已恢复" value="resolved" />
          <el-option label="已关闭" value="closed" />
        </el-select>
        <el-select v-model="filters.severity" size="small" clearable placeholder="级别" @change="handleFilterChange">
          <el-option label="严重" value="critical" />
          <el-option label="警告" value="warning" />
          <el-option label="信息" value="info" />
        </el-select>
        <el-input v-model="filters.environment" size="small" clearable placeholder="环境" @input="handleFilterChange" />
        <el-input v-model="filters.service" size="small" clearable placeholder="服务" @input="handleFilterChange" />
        <el-input v-model="filters.search" size="small" clearable placeholder="搜索标题 / 资源 / 归并键" :prefix-icon="Search" @input="handleFilterChange" />
        <el-checkbox v-model="filters.only_open" size="small" @change="handleFilterChange">只看未关闭</el-checkbox>
      </div>

      <el-table :data="incidents" stripe size="small" v-loading="loading" class="data-table">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="Incident" min-width="240">
          <template #default="{ row }">
            <button class="link-title" type="button" @click="openDetail(row)">{{ row.title }}</button>
            <div class="sub-line">{{ row.impact_summary || row.dedupe_key }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="severity" label="级别" width="80">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ row.severity_display || severityText(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status_display || statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="100" />
        <el-table-column prop="service" label="服务" width="140" />
        <el-table-column prop="active_alert_count" label="活跃告警" width="90" />
        <el-table-column prop="alert_count" label="总告警" width="80" />
        <el-table-column prop="last_seen_at" label="最近告警" width="170">
          <template #default="{ row }">{{ formatTime(row.last_seen_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-button v-if="canClose && row.status !== 'closed'" link size="small" @click="closeIncident(row)">关闭</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          small
          v-model:current-page="pagination.page"
          :page-size="pagination.pageSize"
          :total="pagination.total"
          layout="total, prev, pager, next"
          @current-change="fetchIncidents"
        />
      </div>
    </section>

    <el-drawer v-model="detailVisible" size="520px" title="Incident 详情" destroy-on-close>
      <template v-if="selectedIncident">
        <div class="incident-detail-head">
          <div>
            <div class="detail-title">{{ selectedIncident.title }}</div>
            <div class="sub-line">归并键：{{ selectedIncident.dedupe_key }}</div>
          </div>
          <div class="detail-tags">
            <el-tag :type="severityType(selectedIncident.severity)" size="small">{{ selectedIncident.severity_display }}</el-tag>
            <el-tag :type="statusType(selectedIncident.status)" size="small">{{ selectedIncident.status_display }}</el-tag>
          </div>
        </div>

        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="环境">{{ selectedIncident.environment || '-' }}</el-descriptions-item>
          <el-descriptions-item label="集群">{{ selectedIncident.cluster || '-' }}</el-descriptions-item>
          <el-descriptions-item label="命名空间">{{ selectedIncident.namespace || '-' }}</el-descriptions-item>
          <el-descriptions-item label="服务">{{ selectedIncident.service || '-' }}</el-descriptions-item>
          <el-descriptions-item label="资源">{{ selectedIncident.resource || '-' }}</el-descriptions-item>
          <el-descriptions-item label="影响摘要">{{ selectedIncident.impact_summary || '-' }}</el-descriptions-item>
          <el-descriptions-item label="首次触发">{{ formatTime(selectedIncident.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="最近告警">{{ formatTime(selectedIncident.last_seen_at) }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-head compact">
          <h3>主根因假设</h3>
          <span class="toolbar-desc">{{ primaryHypothesis ? primaryHypothesis.status_display : '待生成' }}</span>
        </div>
        <div v-if="primaryHypothesis" class="hypothesis-panel">
          <div class="hypothesis-title-row">
            <div>
              <div class="hypothesis-title">{{ primaryHypothesis.title }}</div>
              <div class="sub-line">{{ primaryHypothesis.root_cause_type_display || primaryHypothesis.root_cause_type }} · {{ formatTime(primaryHypothesis.generated_at) }}</div>
            </div>
            <el-progress
              type="circle"
              :percentage="hypothesisConfidence(primaryHypothesis)"
              :width="48"
              :stroke-width="5"
            />
          </div>
          <div class="hypothesis-summary">{{ primaryHypothesis.summary || '-' }}</div>
          <div class="hypothesis-columns">
            <div>
              <div class="mini-title">证据缺口</div>
              <div v-for="item in primaryHypothesis.missing_evidence || []" :key="item" class="sub-line">- {{ item }}</div>
              <span v-if="!(primaryHypothesis.missing_evidence || []).length" class="detail-empty">暂无</span>
            </div>
            <div>
              <div class="mini-title">下一步检查</div>
              <div v-for="item in primaryHypothesis.recommended_next_checks || []" :key="item" class="sub-line">- {{ item }}</div>
              <span v-if="!(primaryHypothesis.recommended_next_checks || []).length" class="detail-empty">暂无</span>
            </div>
          </div>
        </div>
        <span v-else class="detail-empty">暂无根因假设</span>

        <div class="section-head compact">
          <h3>建议动作</h3>
          <span class="toolbar-desc">{{ incidentActionCount }} 条</span>
        </div>
        <div class="action-list">
          <div v-for="item in selectedIncident.incident_actions || []" :key="item.id" class="action-item">
            <div class="action-main">
              <div class="evidence-title-row">
                <el-tag size="small" :type="actionTypeTag(item.action_type)">{{ item.action_type_display || item.action_type }}</el-tag>
                <el-tag size="small" :type="riskTag(item.risk_level)" effect="plain">{{ item.risk_level_display || item.risk_level }}</el-tag>
                <el-tag size="small" effect="plain">{{ item.status_display || item.status }}</el-tag>
              </div>
              <div class="evidence-summary">{{ item.title }}</div>
              <div v-for="step in item.verification_plan || []" :key="step" class="sub-line">- {{ step }}</div>
              <div v-if="item.pending_action" class="sub-line">审批事项：#{{ item.pending_action }} · {{ item.pending_action_status_display || item.pending_action_status || '待确认' }}</div>
              <div v-if="item.host_task" class="sub-line">任务中心：#{{ item.host_task }} · {{ item.host_task_name || '未命名任务' }} · {{ item.host_task_status || 'pending' }}</div>
              <div v-if="item.result_summary" class="sub-line">结果：{{ item.result_summary }}</div>
            </div>
            <div class="action-controls">
              <el-button
                v-if="canRunIncidentAction(item)"
                type="primary"
                size="small"
                plain
                :loading="runningActionId === item.id"
                @click="runIncidentAction(item)"
              >
                只读补查
              </el-button>
              <el-button
                v-else-if="canMaterializeIncidentAction(item)"
                type="warning"
                size="small"
                plain
                :loading="runningActionId === item.id"
                @click="materializeIncidentAction(item)"
              >
                生成审批
              </el-button>
            </div>
          </div>
          <span v-if="!incidentActionCount" class="detail-empty">暂无建议动作</span>
        </div>

        <div class="section-head compact">
          <h3>只读调查证据</h3>
          <span class="toolbar-desc">{{ evidenceCount }} 条</span>
        </div>
        <div class="evidence-list">
          <div v-for="item in selectedIncident.evidence_items || []" :key="item.id" class="evidence-item">
            <div class="evidence-main">
              <div class="evidence-title-row">
                <el-tag :type="evidenceKindType(item.kind)" size="small">{{ item.kind_display || item.kind }}</el-tag>
                <span class="evidence-source">{{ formatEvidenceSource(item.source) }}</span>
                <el-tag size="small" effect="plain">{{ item.weight_display || item.weight }}</el-tag>
              </div>
              <div class="evidence-summary">{{ item.summary }}</div>
              <div class="sub-line">
                {{ formatTime(item.window_start) }} - {{ formatTime(item.window_end) }}
                <template v-if="item.source_task_public_id"> · 任务 {{ item.source_task_public_id }}</template>
              </div>
            </div>
            <el-button link type="primary" size="small" @click="copyEvidence(item)">复制</el-button>
          </div>
          <span v-if="!evidenceCount" class="detail-empty">暂无只读调查证据</span>
        </div>

        <div class="section-head compact">
          <h3>关联告警</h3>
          <span class="toolbar-desc">{{ selectedIncident.alert_count }} 条</span>
        </div>
        <div class="alert-link-list">
          <div v-for="item in selectedIncident.alert_links || []" :key="item.id" class="alert-link-item">
            <div>
              <div class="alert-link-title">#{{ item.alert_id }} {{ item.alert_title }}</div>
              <div class="sub-line">{{ item.alert_service || item.alert_resource || '-' }} · {{ formatTime(item.alert_last_received_at) }}</div>
            </div>
            <el-tag size="small">{{ item.role_display || item.role }}</el-tag>
          </div>
          <span v-if="!(selectedIncident.alert_links || []).length" class="detail-empty">暂无关联告警</span>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Warning } from '@element-plus/icons-vue'
import { closeAIOpsIncident, getAIOpsIncident, getAIOpsIncidents, materializeAIOpsIncidentAction, runAIOpsIncidentAction } from '@/api/modules/aiops'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const loading = ref(false)
const runningActionId = ref(null)
const incidents = ref([])
const selectedIncident = ref(null)
const detailVisible = ref(false)
const filters = reactive({
  status: '',
  severity: '',
  environment: '',
  service: '',
  search: '',
  only_open: true,
})
const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})

const canClose = computed(() => authStore.hasPermission('aiops.incident.close'))
const canInvestigate = computed(() => authStore.hasPermission('aiops.incident.investigate'))
const canGenerateTask = computed(() => authStore.hasPermission('aiops.task.generate'))
const criticalCount = computed(() => incidents.value.filter(item => item.severity === 'critical').length)
const openCount = computed(() => incidents.value.filter(item => !['resolved', 'closed'].includes(item.status)).length)
const activeAlertCount = computed(() => incidents.value.reduce((sum, item) => sum + Number(item.active_alert_count || 0), 0))
const evidenceCount = computed(() => (selectedIncident.value?.evidence_items || []).length)
const incidentActionCount = computed(() => (selectedIncident.value?.incident_actions || []).length)
const primaryHypothesis = computed(() => {
  const hypotheses = selectedIncident.value?.hypotheses || []
  return hypotheses.find(item => item.status === 'primary') || hypotheses[0] || null
})

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function severityType(value) {
  return ({ critical: 'danger', warning: 'warning', info: 'info' }[value] || 'info')
}

function severityText(value) {
  return ({ critical: '严重', warning: '警告', info: '信息' }[value] || value || '-')
}

function statusType(value) {
  return ({ open: 'danger', investigating: 'warning', mitigating: 'warning', verifying: 'primary', resolved: 'success', closed: 'info' }[value] || 'info')
}

function statusText(value) {
  return ({ open: '新建', investigating: '调查中', mitigating: '处置中', verifying: '验证中', resolved: '已恢复', closed: '已关闭' }[value] || value || '-')
}

function hypothesisConfidence(item) {
  const value = Number(item?.confidence || 0)
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function actionTypeTag(value) {
  return ({ investigate: 'primary', mitigate: 'warning', fix: 'danger', rollback: 'danger', verify: 'success' }[value] || 'info')
}

function riskTag(value) {
  return ({ read_only: 'success', low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[value] || 'info')
}

function evidenceKindType(value) {
  return ({ alert: 'danger', event: 'info', change: 'warning', metric: 'success', log: 'warning', trace: 'primary', k8s: 'success' }[value] || 'info')
}

function formatEvidenceSource(value) {
  return ({
    'builtin.alert_snapshot': '告警快照',
    'builtin.event_timeline': '事件时间线',
  }[value] || value || '-')
}

function canRunIncidentAction(item) {
  return canInvestigate.value
    && item.action_type === 'investigate'
    && item.risk_level === 'read_only'
    && ['proposed', 'failed'].includes(item.status)
}

function canMaterializeIncidentAction(item) {
  return canGenerateTask.value
    && item.risk_level !== 'read_only'
    && !item.pending_action
    && ['proposed', 'failed', 'canceled'].includes(item.status)
}

async function copyEvidence(item) {
  const text = JSON.stringify({
    kind: item.kind,
    source: item.source,
    summary: item.summary,
    scope: item.scope,
    window_start: item.window_start,
    window_end: item.window_end,
  }, null, 2)
  if (!navigator.clipboard?.writeText) {
    ElMessage.warning('当前浏览器不支持直接复制')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('证据已复制')
  } catch (error) {
    ElMessage.warning('复制失败，请检查浏览器权限')
  }
}

function buildParams() {
  const params = {
    page: pagination.page,
    page_size: pagination.pageSize,
  }
  for (const key of ['status', 'severity', 'environment', 'service', 'search']) {
    if (filters[key]) params[key] = filters[key]
  }
  if (filters.only_open) params.only_open = '1'
  return params
}

async function fetchIncidents() {
  loading.value = true
  try {
    const data = await getAIOpsIncidents(buildParams())
    incidents.value = data.results || data || []
    pagination.total = data.count ?? incidents.value.length
    const incidentId = Number(route.query.incident_id || 0)
    if (incidentId && !selectedIncident.value) {
      selectedIncident.value = await getAIOpsIncident(incidentId)
      detailVisible.value = true
    }
  } finally {
    loading.value = false
  }
}

function handleFilterChange() {
  pagination.page = 1
  fetchIncidents()
}

async function openDetail(row) {
  selectedIncident.value = await getAIOpsIncident(row.id)
  detailVisible.value = true
}

async function closeIncident(row) {
  await ElMessageBox.confirm(`确认关闭 Incident #${row.id}？`, '关闭 Incident', { type: 'warning' })
  await closeAIOpsIncident(row.id)
  ElMessage.success('Incident 已关闭')
  await fetchIncidents()
}

async function runIncidentAction(item) {
  if (!selectedIncident.value || runningActionId.value) return
  runningActionId.value = item.id
  try {
    selectedIncident.value = await runAIOpsIncidentAction(selectedIncident.value.id, item.id)
    ElMessage.success('只读补查已完成')
    await fetchIncidents()
  } finally {
    runningActionId.value = null
  }
}

async function materializeIncidentAction(item) {
  if (!selectedIncident.value || runningActionId.value) return
  runningActionId.value = item.id
  try {
    selectedIncident.value = await materializeAIOpsIncidentAction(selectedIncident.value.id, item.id)
    ElMessage.success('审批事项已生成')
    await fetchIncidents()
  } finally {
    runningActionId.value = null
  }
}

onMounted(fetchIncidents)
</script>

<style scoped>
.incident-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.incident-stats {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.incident-detail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.detail-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-tags {
  display: flex;
  gap: 6px;
}

.compact {
  margin-top: 18px;
}

.alert-link-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.alert-link-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--panel-soft-bg);
}

.alert-link-title {
  font-weight: 600;
  color: var(--text-primary);
}

.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.evidence-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--panel-soft-bg);
}

.action-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--panel-soft-bg);
}

.evidence-main {
  min-width: 0;
  flex: 1;
}

.action-main {
  min-width: 0;
  flex: 1;
}

.action-controls {
  display: flex;
  align-items: flex-start;
  flex-shrink: 0;
}

.evidence-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.evidence-source {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.evidence-summary {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.hypothesis-panel {
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--panel-soft-bg);
}

.hypothesis-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.hypothesis-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.hypothesis-summary {
  margin-top: 10px;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.hypothesis-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.mini-title {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.toolbar :deep(.el-input),
.toolbar :deep(.el-select) {
  width: 150px;
}

.toolbar :deep(.el-input:nth-of-type(3)) {
  width: 220px;
}

@media (max-width: 900px) {
  .incident-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .hypothesis-columns {
    grid-template-columns: 1fr;
  }

  .action-item {
    flex-direction: column;
  }

  .action-controls {
    justify-content: flex-start;
  }
}
</style>
