<template>
  <div class="fade-in aiops-audit-page workbench-page-shell">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row">
          <span class="audit-header-icon"><el-icon><Tickets /></el-icon></span>
          <h2>智能体审计</h2>
          <p class="page-inline-desc">集中查看会话、工具调用、模型成本与待执行动作记录。</p>
        </div>
      </div>
    </section>

    <div class="audit-grid audit-overview-grid">
      <button
        v-for="card in overviewCards"
        :key="card.key"
        type="button"
        class="audit-card audit-card--inline audit-card--action"
        :class="[card.tone, { 'is-active': activeTab === card.tab }]"
        @click="switchTab(card.tab)"
      >
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">{{ card.value }}</div>
      </button>
    </div>

    <div class="neo-tabs theme-blue log-center-tabs trace-center-tabs event-tabs-shell audit-tabs">
      <button
        v-for="tab in auditTabs"
        :key="tab.name"
        type="button"
        class="neo-tab-btn audit-tab-btn"
        :class="{ active: activeTab === tab.name }"
        @click="switchTab(tab.name)"
      >
        <el-icon><component :is="tab.icon" /></el-icon>
        <span class="tab-label">{{ tab.label }}</span>
      </button>
    </div>

    <section v-if="activeTab === 'overview'" class="workbench-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">运行概览</span>
          <span class="toolbar-desc">汇总今日活跃、所选时间范围内的模型成本、工具调用与动作状态。</span>
        </div>
        <div class="overview-time-controls">
          <el-date-picker
            v-model="overviewTimeRange"
            class="overview-time-picker"
            size="small"
            type="datetimerange"
            format="YYYY-MM-DD HH:mm"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :clearable="false"
            :shortcuts="overviewTimeShortcuts"
            @change="handleOverviewRangeChange"
          />
          <el-button
            size="small"
            :type="overviewAllTime ? 'primary' : 'default'"
            plain
            @click="selectAllOverviewTime"
          >
            全部时间
          </el-button>
          <el-button class="filter-refresh-btn audit-flat-action-btn" size="small" plain :loading="loading.overview" @click="loadOverview">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
        </div>
      </div>

      <div class="overview-metric-strip">
        <div v-for="item in overviewMetricCards" :key="item.key" class="overview-metric-card">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.desc }}</small>
        </div>
      </div>

      <div class="overview-dashboard-grid">
        <div class="overview-panel overview-panel--model">
          <div class="overview-panel-head">
            <div>
              <span class="section-title">模型成本</span>
              <p>按提供商聚合所选时间范围内的调用、Token 与预估费用。</p>
            </div>
            <el-tag size="small" effect="plain">平均耗时 {{ formatLatency(modelCostSummary.avg_latency_ms) }}</el-tag>
          </div>
          <div class="overview-mini-grid">
            <div class="overview-mini-stat">
              <span>模型调用</span>
              <strong>{{ formatNumber(modelCostSummary.total_calls) }}</strong>
            </div>
            <div class="overview-mini-stat">
              <span>Token</span>
              <strong>{{ formatTokenCount(modelCostSummary.total_tokens) }}</strong>
            </div>
            <div class="overview-mini-stat">
              <span>费用</span>
              <strong>{{ formatModelCostSummary(modelCostSummary) }}</strong>
            </div>
          </div>
          <div class="overview-rank-list">
            <div v-for="item in modelProviderRows" :key="`${item.provider}-${item.cost_currency || 'USD'}`" class="overview-rank-row">
              <div class="overview-rank-main">
                <div class="overview-rank-title">
                  <span>{{ item.provider }}</span>
                  <strong>{{ formatNumber(item.calls) }} 次</strong>
                </div>
                <div class="overview-rank-meta">
                  <span>{{ formatTokenCount(item.tokens) }} Token</span>
                  <span>{{ formatCost(item.estimated_cost_usd, item.cost_currency) }}</span>
                  <span>平均 {{ formatLatency(item.avg_latency_ms) }}</span>
                </div>
                <div class="overview-rank-bar"><span :style="{ width: `${item.percent}%` }"></span></div>
              </div>
            </div>
            <div v-if="!modelProviderRows.length" class="overview-empty">暂无模型调用数据</div>
          </div>
        </div>

        <div class="overview-panel overview-panel--tool">
          <div class="overview-panel-head">
            <div>
              <span class="section-title">工具调用</span>
              <p>观察 MCP 与平台工具的调用频次、平均耗时。</p>
            </div>
            <el-tag size="small" effect="plain">{{ auditOverview.mcp_total || 0 }} 个 MCP</el-tag>
          </div>
          <div class="overview-mini-grid">
            <div class="overview-mini-stat">
              <span>工具调用</span>
              <strong>{{ formatNumber(toolCostSummary.total_calls) }}</strong>
            </div>
            <div class="overview-mini-stat">
              <span>平均耗时</span>
              <strong>{{ formatLatency(toolCostSummary.avg_latency_ms) }}</strong>
            </div>
            <div class="overview-mini-stat">
              <span>启用 MCP</span>
              <strong>{{ formatNumber(auditOverview.mcp_total) }}</strong>
            </div>
          </div>
          <div class="overview-rank-list">
            <div v-for="item in toolRows" :key="item.tool_name" class="overview-rank-row">
              <div class="overview-rank-main">
                <div class="overview-rank-title">
                  <span>{{ item.tool_name || '未命名工具' }}</span>
                  <strong>{{ formatNumber(item.calls) }} 次</strong>
                </div>
                <div class="overview-rank-meta">
                  <span>平均 {{ formatLatency(item.avg_latency_ms) }}</span>
                </div>
                <div class="overview-rank-bar"><span :style="{ width: `${item.percent}%` }"></span></div>
              </div>
            </div>
            <div v-if="!toolRows.length" class="overview-empty">暂无工具调用数据</div>
          </div>
        </div>

        <div class="overview-panel overview-panel--status">
          <div class="overview-panel-head">
            <div>
              <span class="section-title">动作状态</span>
              <p>查看智能体生成动作的确认、执行与失败分布。</p>
            </div>
            <el-tag size="small" effect="plain">{{ formatNumber(actionStatusTotal) }} 个动作</el-tag>
          </div>
          <div class="status-stack">
            <div v-for="item in actionStatusRows" :key="item.status" class="status-row">
              <div class="status-row-head">
                <span>{{ item.label }}</span>
                <strong>{{ formatNumber(item.count) }}</strong>
              </div>
              <div class="status-progress">
                <span :class="`is-${item.tone}`" :style="{ width: `${item.percent}%` }"></span>
              </div>
            </div>
            <div v-if="!actionStatusRows.length" class="overview-empty">暂无动作状态数据</div>
          </div>
        </div>
      </div>
    </section>

    <section v-else class="workbench-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">{{ activeTabMeta.title }}</span>
          <span class="toolbar-desc">{{ activeTabMeta.desc }}</span>
        </div>
        <div class="workbench-card-actions">
          <el-button class="filter-refresh-btn audit-flat-action-btn" size="small" plain :loading="activeLoading" @click="refreshActiveTab">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button
            v-if="activeTab === 'sessions' && canManageAudit"
            class="audit-flat-action-btn"
            type="danger"
            size="small"
            plain
            :disabled="!selectedAuditSessionIds.length"
            @click="handleBatchDeleteAuditSessions"
          >
            <el-icon><Delete /></el-icon>
            批量删除
          </el-button>
          <el-button
            v-if="activeTab === 'tools' && canManageAudit"
            class="audit-flat-action-btn"
            type="danger"
            size="small"
            plain
            :disabled="!selectedAuditToolIds.length"
            @click="handleBatchDeleteAuditTools"
          >
            <el-icon><Delete /></el-icon>
            批量删除
          </el-button>
          <el-button
            v-if="activeTab === 'actions' && canManageAudit"
            class="audit-flat-action-btn"
            type="danger"
            size="small"
            plain
            :disabled="!selectedAuditActionIds.length"
            @click="handleBatchDeleteAuditActions"
          >
            <el-icon><Delete /></el-icon>
            批量删除
          </el-button>
        </div>
      </div>

      <div class="workbench-toolbar workbench-toolbar--history audit-list-toolbar">
        <div class="workbench-toolbar-left">
          <template v-if="activeTab === 'sessions'">
            <el-input v-model="auditFilters.sessions.q" class="audit-filter-search" size="small" clearable placeholder="搜索会话标题" @keyup.enter="applyAuditFilters" />
            <el-input v-model="auditFilters.sessions.username" class="audit-filter-user" size="small" clearable placeholder="用户" @keyup.enter="applyAuditFilters" />
            <el-select v-model="auditFilters.sessions.status" size="small" clearable placeholder="状态" @change="applyAuditFilters">
              <el-option v-for="item in sessionStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-date-picker v-model="auditFilters.sessions.timeRange" class="audit-filter-time" size="small" type="datetimerange" format="YYYY-MM-DD HH:mm" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable @change="applyAuditFilters" />
          </template>
          <template v-else-if="activeTab === 'tools'">
            <el-input v-model="auditFilters.tools.q" class="audit-filter-search" size="small" clearable placeholder="搜索工具 / 会话" @keyup.enter="applyAuditFilters" />
            <el-input v-model="auditFilters.tools.username" class="audit-filter-user" size="small" clearable placeholder="用户" @keyup.enter="applyAuditFilters" />
            <el-select v-model="auditFilters.tools.status" size="small" clearable placeholder="状态" @change="applyAuditFilters">
              <el-option v-for="item in toolStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-date-picker v-model="auditFilters.tools.timeRange" class="audit-filter-time" size="small" type="datetimerange" format="YYYY-MM-DD HH:mm" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable @change="applyAuditFilters" />
          </template>
          <template v-else-if="activeTab === 'models'">
            <el-input v-model="auditFilters.models.q" class="audit-filter-search" size="small" clearable placeholder="搜索供应商 / 模型" @keyup.enter="applyAuditFilters" />
            <el-select v-model="auditFilters.models.status" size="small" clearable placeholder="状态" @change="applyAuditFilters">
              <el-option v-for="item in modelStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="auditFilters.models.purpose" size="small" clearable placeholder="用途" @change="applyAuditFilters">
              <el-option v-for="item in modelPurposeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-date-picker v-model="auditFilters.models.timeRange" class="audit-filter-time" size="small" type="datetimerange" format="YYYY-MM-DD HH:mm" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable @change="applyAuditFilters" />
          </template>
          <template v-else-if="activeTab === 'actions'">
            <el-input v-model="auditFilters.actions.q" class="audit-filter-search" size="small" clearable placeholder="搜索动作 / 会话" @keyup.enter="applyAuditFilters" />
            <el-input v-model="auditFilters.actions.username" class="audit-filter-user" size="small" clearable placeholder="用户" @keyup.enter="applyAuditFilters" />
            <el-select v-model="auditFilters.actions.status" size="small" clearable placeholder="状态" @change="applyAuditFilters">
              <el-option v-for="item in actionFilterStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="auditFilters.actions.risk_level" size="small" clearable placeholder="风险" @change="applyAuditFilters">
              <el-option v-for="item in actionRiskOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-date-picker v-model="auditFilters.actions.timeRange" class="audit-filter-time" size="small" type="datetimerange" format="YYYY-MM-DD HH:mm" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable @change="applyAuditFilters" />
          </template>
        </div>
        <div class="workbench-toolbar-right">
          <el-button size="small" type="primary" plain @click="applyAuditFilters">筛选</el-button>
          <el-button size="small" @click="resetAuditFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-if="activeTab === 'sessions'"
        v-loading="loading.sessions"
        :data="auditSessions"
        stripe
        size="small"
        class="console-table"
        @selection-change="handleAuditSessionSelectionChange"
      >
        <el-table-column v-if="canManageAudit" type="selection" width="42" />
        <el-table-column prop="title" label="会话标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="username" label="用户" width="120" />
        <el-table-column prop="message_count" label="消息数" width="90" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后消息" min-width="180">
          <template #default="{ row }">
            {{ formatDateTimeDisplay(row.last_message_at) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canManageAudit" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleDeleteAuditSession(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeTab === 'tools'"
        v-loading="loading.tools"
        :data="auditTools"
        stripe
        size="small"
        class="console-table"
        @selection-change="handleAuditToolSelectionChange"
      >
        <el-table-column v-if="canManageAudit" type="selection" width="42" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="json-preview">{{ formatJsonCompact({ request_payload: row.request_payload, response_summary: row.response_summary }) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="tool_name" label="工具" min-width="180" show-overflow-tooltip />
        <el-table-column prop="username" label="用户" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTone(row.status)" effect="plain">{{ row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="110">
          <template #default="{ row }">
            {{ formatLatency(row.latency_ms) }}
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">
            {{ formatDateTimeDisplay(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canManageAudit" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleDeleteAuditTool(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeTab === 'models'"
        v-loading="loading.models"
        :data="auditModels"
        stripe
        size="small"
        class="console-table"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="json-preview">{{ formatJsonCompact({ request_summary: row.request_summary, response_summary: row.response_summary }) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="provider_name" label="提供商" min-width="150" show-overflow-tooltip />
        <el-table-column prop="purpose_display" label="用途" width="110" />
        <el-table-column prop="resolved_model" label="模型" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTone(row.status)" effect="plain">{{ row.status_display || row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Token" width="110">
          <template #default="{ row }">
            {{ formatTokenCount(row.total_tokens) }}
          </template>
        </el-table-column>
        <el-table-column label="费用" width="110">
          <template #default="{ row }">
            {{ formatCost(row.estimated_cost_usd, row.estimated_cost_currency) }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="110">
          <template #default="{ row }">
            {{ formatLatency(row.latency_ms) }}
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="170">
          <template #default="{ row }">
            {{ formatDateTimeDisplay(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canManageAudit" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleDeleteAuditModel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeTab === 'actions'"
        v-loading="loading.actions"
        :data="auditActions"
        stripe
        size="small"
        class="console-table"
        @selection-change="handleAuditActionSelectionChange"
      >
        <el-table-column v-if="canManageAudit" type="selection" width="42" />
        <el-table-column prop="title" label="动作标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="风险" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="riskTone(row.risk_level)" effect="plain">{{ row.risk_level_display || row.risk_level || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTone(row.status)" effect="plain">{{ row.status_display || row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="confirmed_by" label="确认人" width="120" />
        <el-table-column label="更新时间" min-width="180">
          <template #default="{ row }">
            {{ formatDateTimeDisplay(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="关联任务" width="110">
          <template #default="{ row }">
            <el-button v-if="getActionTaskId(row)" link type="primary" @click="goTaskWorkbenchTask(row)">查看任务</el-button>
            <span v-else class="muted-text">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="canManageAudit" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleDeleteAuditAction(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <div class="pagination-size-control">
          <span class="audit-page-size-label">每页</span>
          <el-select v-model="activePageSize" class="audit-page-size-select" size="small" @change="handleAuditPageSizeChange">
            <el-option v-for="size in auditPageSizeOptions" :key="size" :label="`${size} 条`" :value="size" />
          </el-select>
        </div>
        <el-pagination :current-page="activePagination.page" :page-size="activePagination.pageSize" :total="activePagination.total" layout="total, prev, pager, next" @current-change="loadActiveTabPage" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotSquare, Connection, Cpu, Delete, Promotion, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  bulkDeleteAIOpsAuditActions,
  bulkDeleteAIOpsAuditSessions,
  bulkDeleteAIOpsAuditToolInvocations,
  deleteAIOpsAuditAction,
  deleteAIOpsAuditModelInvocation,
  deleteAIOpsAuditSession,
  deleteAIOpsAuditToolInvocation,
  getAIOpsAuditActions,
  getAIOpsAuditCosts,
  getAIOpsAuditModelInvocations,
  getAIOpsAuditOverview,
  getAIOpsAuditSessions,
  getAIOpsAuditToolInvocations,
} from '@/api/modules/aiops'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeTab = ref('overview')
const auditOverview = ref({})
const auditCosts = ref({})
const auditSessions = ref([])
const auditTools = ref([])
const auditModels = ref([])
const auditActions = ref([])
const selectedAuditSessionIds = ref([])
const selectedAuditToolIds = ref([])
const selectedAuditActionIds = ref([])
const loading = reactive({
  overview: false,
  sessions: false,
  tools: false,
  models: false,
  actions: false,
})
const AUDIT_DEFAULT_PAGE_SIZE = 20
const auditPageSizeOptions = [20, 50, 100]
const auditSessionPagination = reactive({ page: 1, pageSize: AUDIT_DEFAULT_PAGE_SIZE, total: 0 })
const auditToolPagination = reactive({ page: 1, pageSize: AUDIT_DEFAULT_PAGE_SIZE, total: 0 })
const auditModelPagination = reactive({ page: 1, pageSize: AUDIT_DEFAULT_PAGE_SIZE, total: 0 })
const auditActionPagination = reactive({ page: 1, pageSize: AUDIT_DEFAULT_PAGE_SIZE, total: 0 })
const auditFilters = reactive({
  sessions: { q: '', username: '', status: '', timeRange: [] },
  tools: { q: '', username: '', status: '', timeRange: [] },
  models: { q: '', status: '', purpose: '', timeRange: [] },
  actions: { q: '', username: '', status: '', risk_level: '', timeRange: [] },
})
const sessionStatusOptions = [
  { label: '进行中', value: 'active' },
  { label: '已归档', value: 'archived' },
]
const toolStatusOptions = [
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '待处理', value: 'pending' },
]
const modelStatusOptions = [
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
]
const modelPurposeOptions = [
  { label: '聊天规划', value: 'chat_planning' },
  { label: '回答整形', value: 'answer_formatting' },
  { label: '参数抽取', value: 'parameter_extraction' },
  { label: '模型探测', value: 'model_probe' },
  { label: '连接测试', value: 'connection_test' },
]
const actionFilterStatusOptions = [
  { label: '待确认', value: 'pending' },
  { label: '已确认', value: 'confirmed' },
  { label: '已执行', value: 'executed' },
  { label: '执行失败', value: 'failed' },
  { label: '已取消', value: 'canceled' },
]
const actionRiskOptions = [
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
  { label: '极高', value: 'critical' },
]
const OVERVIEW_DEFAULT_DAYS = 7
const overviewAllTime = ref(false)
const overviewRecentDays = ref(OVERVIEW_DEFAULT_DAYS)
const overviewTimeRange = ref(buildRecentTimeRange(OVERVIEW_DEFAULT_DAYS))
const overviewTimeShortcuts = [
  { text: '最近 1 天', value: () => buildRecentTimeRange(1) },
  { text: '最近 7 天', value: () => buildRecentTimeRange(7) },
  { text: '最近 14 天', value: () => buildRecentTimeRange(14) },
  { text: '最近 30 天', value: () => buildRecentTimeRange(30) },
  { text: '最近 90 天', value: () => buildRecentTimeRange(90) },
]

const auditTabs = [
  { name: 'overview', label: '运行概览', icon: Tickets, title: '运行概览', desc: '汇总今日使用与所选时间范围成本。' },
  { name: 'sessions', label: '会话', icon: ChatDotSquare, title: '会话记录', desc: '查看智能助手会话、用户与消息数量。' },
  { name: 'tools', label: '工具调用', icon: Connection, title: '工具调用', desc: '追踪 MCP、平台工具与只读查询调用明细。' },
  { name: 'models', label: '模型调用', icon: Cpu, title: '模型调用', desc: '查看模型用途、Token、耗时与预估费用。' },
  { name: 'actions', label: '待执行动作', icon: Promotion, title: '待执行动作', desc: '审计待确认、已执行、失败和被策略拦截的动作。' },
]
const validTabs = auditTabs.map(item => item.name)
const canManageAudit = computed(() => authStore.hasPermission('aiops.audit.manage'))
const modelCostSummary = computed(() => auditCosts.value?.model || {})
const toolCostSummary = computed(() => auditCosts.value?.tools || {})
const overviewCards = computed(() => ([
  { key: 'sessions', label: '今日会话', value: auditOverview.value.sessions_today || 0, tab: 'sessions', tone: '' },
  { key: 'messages', label: '今日消息', value: auditOverview.value.messages_today || 0, tab: 'sessions', tone: 'audit-card--success' },
  { key: 'actions', label: '今日动作', value: auditOverview.value.actions_today || 0, tab: 'actions', tone: 'audit-card--warning' },
  { key: 'models', label: '模型调用', value: auditOverview.value.model_calls_today || 0, tab: 'models', tone: 'audit-card--danger' },
]))
const overviewMetricCards = computed(() => ([
  {
    key: 'model-calls',
    label: '模型调用',
    value: formatNumber(modelCostSummary.value.total_calls),
    desc: `平均 ${formatLatency(modelCostSummary.value.avg_latency_ms)} / 次`,
  },
  {
    key: 'model-tokens',
    label: 'Token',
    value: formatTokenCount(modelCostSummary.value.total_tokens),
    desc: `Prompt ${formatTokenCount(modelCostSummary.value.prompt_tokens)} / Completion ${formatTokenCount(modelCostSummary.value.completion_tokens)}`,
  },
  {
    key: 'model-cost',
    label: '预估模型费用',
    value: formatModelCostSummary(modelCostSummary.value),
    desc: '按模型调用记录估算',
  },
  {
    key: 'tool-calls',
    label: '工具调用',
    value: formatNumber(toolCostSummary.value.total_calls),
    desc: `平均 ${formatLatency(toolCostSummary.value.avg_latency_ms)} / 次`,
  },
]))
const modelProviderRows = computed(() => {
  const rows = Array.isArray(modelCostSummary.value.by_provider) ? modelCostSummary.value.by_provider : []
  const maxCalls = Math.max(...rows.map(item => toNumber(item.calls)), 1)
  return rows.slice(0, 6).map(item => ({
    ...item,
    percent: Math.max(6, Math.round((toNumber(item.calls) / maxCalls) * 100)),
  }))
})
const toolRows = computed(() => {
  const rows = Array.isArray(toolCostSummary.value.by_tool) ? toolCostSummary.value.by_tool : []
  const maxCalls = Math.max(...rows.map(item => toNumber(item.calls)), 1)
  return rows.slice(0, 6).map(item => ({
    ...item,
    percent: Math.max(6, Math.round((toNumber(item.calls) / maxCalls) * 100)),
  }))
})
const actionStatusRows = computed(() => {
  const rows = Array.isArray(auditOverview.value.action_status) ? auditOverview.value.action_status : []
  const order = ['pending', 'confirmed', 'executed', 'failed', 'canceled']
  const total = rows.reduce((sum, item) => sum + toNumber(item.count), 0)
  return rows
    .map(item => ({
      status: item.status || 'unknown',
      label: actionStatusLabel(item.status),
      count: toNumber(item.count),
      tone: actionStatusTone(item.status),
      percent: total ? Math.max(6, Math.round((toNumber(item.count) / total) * 100)) : 0,
    }))
    .sort((left, right) => {
      const leftIndex = order.includes(left.status) ? order.indexOf(left.status) : order.length
      const rightIndex = order.includes(right.status) ? order.indexOf(right.status) : order.length
      return leftIndex - rightIndex
    })
})
const actionStatusTotal = computed(() => actionStatusRows.value.reduce((sum, item) => sum + item.count, 0))
const activeTabMeta = computed(() => auditTabs.find(item => item.name === activeTab.value) || auditTabs[0])
const activeLoading = computed(() => Boolean(loading[activeTab.value]))
const activePagination = computed(() => {
  if (activeTab.value === 'tools') return auditToolPagination
  if (activeTab.value === 'models') return auditModelPagination
  if (activeTab.value === 'actions') return auditActionPagination
  return auditSessionPagination
})
const activePageSize = computed({
  get: () => activePagination.value.pageSize,
  set: size => setAuditPageSize(size),
})

function toNumber(value) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function buildRecentTimeRange(days) {
  const end = new Date()
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000)
  return [start, end]
}

function formatDateTimeParam(value) {
  if (!value) return ''
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function formatDateTimeDisplay(value) {
  if (!value) return '-'
  const date = value instanceof Date ? value : new Date(value)
  if (!Number.isNaN(date.getTime())) {
    const pad = number => String(number).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  }
  const text = String(value).trim()
  return text ? text.replace('T', ' ').replace(/\.\d+.*$/, '').replace(/(?:Z|[+-]\d{2}:?\d{2})$/, '') : '-'
}

function buildOverviewCostParams() {
  if (overviewAllTime.value) return { range: 'all' }
  if (overviewRecentDays.value) return { days: overviewRecentDays.value }
  const [start, end] = Array.isArray(overviewTimeRange.value) ? overviewTimeRange.value : []
  const startParam = formatDateTimeParam(start)
  const endParam = formatDateTimeParam(end)
  if (startParam && endParam) {
    return { start: startParam, end: endParam }
  }
  return { days: OVERVIEW_DEFAULT_DAYS }
}

function appendTimeRangeParams(params, range) {
  const [start, end] = Array.isArray(range) ? range : []
  const startParam = formatDateTimeParam(start)
  const endParam = formatDateTimeParam(end)
  if (startParam) params.start = startParam
  if (endParam) params.end = endParam
}

function compactParams(params) {
  return Object.fromEntries(Object.entries(params).reduce((entries, [key, value]) => {
    const normalized = typeof value === 'string' ? value.trim() : value
    if (normalized === '' || normalized === null || normalized === undefined) return entries
    if (Array.isArray(normalized) && !normalized.length) return entries
    entries.push([key, normalized])
    return entries
  }, []))
}

function auditPageSize(tab) {
  if (tab === 'tools') return auditToolPagination.pageSize
  if (tab === 'models') return auditModelPagination.pageSize
  if (tab === 'actions') return auditActionPagination.pageSize
  return auditSessionPagination.pageSize
}

function buildAuditListParams(tab, page = 1) {
  const base = { page, page_size: auditPageSize(tab) }
  if (tab === 'sessions') {
    const filters = auditFilters.sessions
    appendTimeRangeParams(base, filters.timeRange)
    return compactParams({ ...base, q: filters.q, username: filters.username, status: filters.status })
  }
  if (tab === 'tools') {
    const filters = auditFilters.tools
    appendTimeRangeParams(base, filters.timeRange)
    return compactParams({ ...base, q: filters.q, username: filters.username, status: filters.status })
  }
  if (tab === 'models') {
    const filters = auditFilters.models
    appendTimeRangeParams(base, filters.timeRange)
    return compactParams({ ...base, q: filters.q, status: filters.status, purpose: filters.purpose })
  }
  const filters = auditFilters.actions
  appendTimeRangeParams(base, filters.timeRange)
  return compactParams({ ...base, q: filters.q, username: filters.username, status: filters.status, risk_level: filters.risk_level })
}

function clearAuditFilterGroup(group) {
  Object.keys(group).forEach((key) => {
    group[key] = Array.isArray(group[key]) ? [] : ''
  })
}

function applyAuditFilters() {
  return loadActiveTabPage(1)
}

function resetAuditFilters() {
  if (!auditFilters[activeTab.value]) return
  clearAuditFilterGroup(auditFilters[activeTab.value])
  return loadActiveTabPage(1)
}

function setAuditPageSize(size) {
  activePagination.value.pageSize = Math.min(Math.max(Number(size) || AUDIT_DEFAULT_PAGE_SIZE, AUDIT_DEFAULT_PAGE_SIZE), 100)
}

function handleAuditPageSizeChange(size) {
  setAuditPageSize(size)
  return loadActiveTabPage(1)
}

async function handleOverviewRangeChange() {
  overviewAllTime.value = false
  overviewRecentDays.value = inferRecentDaysFromRange(overviewTimeRange.value)
  await loadOverview()
}

async function selectAllOverviewTime() {
  overviewAllTime.value = true
  overviewRecentDays.value = null
  await loadOverview()
}

function inferRecentDaysFromRange(range) {
  if (!Array.isArray(range) || range.length !== 2) return null
  const [start, end] = range
  const startDate = start instanceof Date ? start : new Date(start)
  const endDate = end instanceof Date ? end : new Date(end)
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null
  const now = Date.now()
  const endDelta = Math.abs(now - endDate.getTime())
  const diffDays = (endDate.getTime() - startDate.getTime()) / (24 * 60 * 60 * 1000)
  if (endDelta > 10 * 60 * 1000) return null
  return [1, 7, 14, 30, 90].find(days => Math.abs(diffDays - days) < 0.02) || null
}

function formatNumber(value) {
  return toNumber(value).toLocaleString('zh-CN')
}

function formatTokenCount(value) {
  const numberValue = Math.round(toNumber(value))
  if (Math.abs(numberValue) < 1000000) return formatNumber(numberValue)
  const millionValue = numberValue / 1000000
  const digits = Math.abs(millionValue) < 10 ? 2 : 1
  return `${millionValue.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')}M`
}

function normalizeCostCurrency(currency) {
  return String(currency || '').toUpperCase() === 'CNY' ? 'CNY' : 'USD'
}

function currencySymbol(currency) {
  return normalizeCostCurrency(currency) === 'CNY' ? '¥' : '$'
}

function formatCost(value, currency = 'USD') {
  const numberValue = toNumber(value)
  const symbol = currencySymbol(currency)
  if (!numberValue) return `${symbol}0`
  return `${symbol}${numberValue.toFixed(numberValue < 1 ? 4 : 2)}`
}

function formatModelCostSummary(summary = {}) {
  const byCurrency = Array.isArray(summary.by_currency) ? summary.by_currency.filter(item => toNumber(item.estimated_cost_usd)) : []
  if (byCurrency.length > 1) {
    return byCurrency
      .map(item => formatCost(item.estimated_cost_usd, item.currency))
      .join(' / ')
  }
  const currency = byCurrency[0]?.currency || summary.cost_currency || 'USD'
  return formatCost(summary.estimated_cost_usd, currency)
}

function formatLatency(value) {
  const numberValue = Math.round(toNumber(value))
  return numberValue ? `${formatNumber(numberValue)} ms` : '-'
}

function actionStatusLabel(status) {
  const labels = {
    pending: '待确认',
    confirmed: '已确认',
    executed: '已执行',
    failed: '执行失败',
    canceled: '已取消',
  }
  return labels[status] || status || '未知'
}

function actionStatusTone(status) {
  if (status === 'failed') return 'danger'
  if (status === 'pending') return 'warning'
  if (status === 'executed' || status === 'confirmed') return 'success'
  return 'muted'
}

function normalizeTab(tab) {
  const value = Array.isArray(tab) ? tab[0] : tab
  return validTabs.includes(value) ? value : 'overview'
}

function syncRouteTab(tab) {
  const nextTab = normalizeTab(tab)
  if (route.query.tab !== nextTab) {
    return router.replace({ path: route.path, query: { ...route.query, tab: nextTab } })
  }
  return Promise.resolve()
}

function switchTab(tab) {
  const nextTab = normalizeTab(tab)
  activeTab.value = nextTab
  syncRouteTab(nextTab)
}

function getActionTaskId(action) {
  const value = action?.result_payload?.task_id || action?.result_payload?.created_task_id || action?.result_payload?.host_task_id
  return value ? String(value) : ''
}

function goTaskWorkbenchTask(action) {
  const taskId = getActionTaskId(action)
  if (!taskId) return
  router.push({
    path: '/tasks/workbench',
    query: {
      taskTab: 'history',
      taskId,
      source: 'aiopsAudit',
    },
  })
}

function formatJsonCompact(value) {
  try {
    return JSON.stringify(value || {}, null, 2)
  } catch (error) {
    return String(value || '')
  }
}

function statusTone(status) {
  if (['success', 'completed', 'confirmed', 'executed'].includes(status)) return 'success'
  if (['failed', 'error', 'canceled', 'rejected'].includes(status)) return 'danger'
  if (['pending', 'draft', 'running'].includes(status)) return 'warning'
  return 'info'
}

function riskTone(risk) {
  if (['high', 'critical'].includes(risk)) return 'danger'
  if (risk === 'medium') return 'warning'
  return 'info'
}

async function loadOverview() {
  loading.overview = true
  try {
    const [overviewData, costData] = await Promise.all([
      getAIOpsAuditOverview({ skipErrorMessage: true }),
      getAIOpsAuditCosts(buildOverviewCostParams(), { skipErrorMessage: true }),
    ])
    auditOverview.value = overviewData || {}
    auditCosts.value = costData || {}
  } finally {
    loading.overview = false
  }
}

async function loadAuditSessions(page = 1, config = {}) {
  loading.sessions = true
  try {
    const data = await getAIOpsAuditSessions(buildAuditListParams('sessions', page), config)
    auditSessionPagination.page = page
    auditSessionPagination.total = data.count || 0
    auditSessions.value = data.results || data || []
    selectedAuditSessionIds.value = []
  } catch (error) {
    const message = String(error?.response?.data?.detail || '')
    if (page > 1 && message.includes('无效页面')) return loadAuditSessions(page - 1, config)
    throw error
  } finally {
    loading.sessions = false
  }
}

async function loadAuditTools(page = 1, config = {}) {
  loading.tools = true
  try {
    const data = await getAIOpsAuditToolInvocations(buildAuditListParams('tools', page), config)
    auditToolPagination.page = page
    auditToolPagination.total = data.count || 0
    auditTools.value = data.results || data || []
    selectedAuditToolIds.value = []
  } catch (error) {
    const message = String(error?.response?.data?.detail || '')
    if (page > 1 && message.includes('无效页面')) return loadAuditTools(page - 1, config)
    throw error
  } finally {
    loading.tools = false
  }
}

async function loadAuditModels(page = 1, config = {}) {
  loading.models = true
  try {
    const data = await getAIOpsAuditModelInvocations(buildAuditListParams('models', page), config)
    auditModelPagination.page = page
    auditModelPagination.total = data.count || 0
    auditModels.value = data.results || data || []
  } catch (error) {
    const message = String(error?.response?.data?.detail || '')
    if (page > 1 && message.includes('无效页面')) return loadAuditModels(page - 1, config)
    throw error
  } finally {
    loading.models = false
  }
}

async function loadAuditActions(page = 1, config = {}) {
  loading.actions = true
  try {
    const data = await getAIOpsAuditActions(buildAuditListParams('actions', page), config)
    auditActionPagination.page = page
    auditActionPagination.total = data.count || 0
    auditActions.value = data.results || data || []
    selectedAuditActionIds.value = []
  } catch (error) {
    const message = String(error?.response?.data?.detail || '')
    if (page > 1 && message.includes('无效页面')) return loadAuditActions(page - 1, config)
    throw error
  } finally {
    loading.actions = false
  }
}

function loadActiveTabPage(page = 1) {
  if (activeTab.value === 'tools') return loadAuditTools(page)
  if (activeTab.value === 'models') return loadAuditModels(page)
  if (activeTab.value === 'actions') return loadAuditActions(page)
  return loadAuditSessions(page)
}

async function refreshActiveTab() {
  if (activeTab.value === 'overview') return loadOverview()
  await Promise.all([loadOverview(), loadActiveTabPage(activePagination.value.page)])
}

function handleAuditSessionSelectionChange(rows) {
  selectedAuditSessionIds.value = rows.map(item => item.id)
}

function handleAuditToolSelectionChange(rows) {
  selectedAuditToolIds.value = rows.map(item => item.id)
}

function handleAuditActionSelectionChange(rows) {
  selectedAuditActionIds.value = rows.map(item => item.id)
}

async function handleDeleteAuditSession(row) {
  await ElMessageBox.confirm(`确认删除会话《${row.title}》吗？该操作不可恢复。`, '删除确认', { type: 'warning' })
  const shouldFallbackPage = auditSessions.value.length === 1 && auditSessionPagination.page > 1
  await deleteAIOpsAuditSession(row.id)
  ElMessage.success('会话已删除')
  await Promise.all([loadOverview(), loadAuditSessions(shouldFallbackPage ? auditSessionPagination.page - 1 : auditSessionPagination.page)])
}

async function handleBatchDeleteAuditSessions() {
  if (!selectedAuditSessionIds.value.length) return
  await ElMessageBox.confirm(`确认批量删除已选中的 ${selectedAuditSessionIds.value.length} 个会话吗？该操作不可恢复。`, '批量删除确认', { type: 'warning' })
  const shouldFallbackPage = selectedAuditSessionIds.value.length === auditSessions.value.length && auditSessionPagination.page > 1
  const deletedCount = selectedAuditSessionIds.value.length
  await bulkDeleteAIOpsAuditSessions(selectedAuditSessionIds.value)
  ElMessage.success(`已删除 ${deletedCount} 个会话`)
  await Promise.all([loadOverview(), loadAuditSessions(shouldFallbackPage ? auditSessionPagination.page - 1 : auditSessionPagination.page)])
}

async function handleDeleteAuditTool(row) {
  await ElMessageBox.confirm(`确认删除工具调用《${row.tool_name}》吗？该操作不可恢复。`, '删除确认', { type: 'warning' })
  const shouldFallbackPage = auditTools.value.length === 1 && auditToolPagination.page > 1
  await deleteAIOpsAuditToolInvocation(row.id)
  ElMessage.success('工具调用已删除')
  await Promise.all([loadOverview(), loadAuditTools(shouldFallbackPage ? auditToolPagination.page - 1 : auditToolPagination.page)])
}

async function handleBatchDeleteAuditTools() {
  if (!selectedAuditToolIds.value.length) return
  const shouldFallbackPage = selectedAuditToolIds.value.length === auditTools.value.length && auditToolPagination.page > 1
  const deletedCount = selectedAuditToolIds.value.length
  await ElMessageBox.confirm(`确认批量删除已选中的 ${deletedCount} 个工具调用吗？该操作不可恢复。`, '批量删除确认', { type: 'warning' })
  await bulkDeleteAIOpsAuditToolInvocations(selectedAuditToolIds.value)
  ElMessage.success(`已删除 ${deletedCount} 个工具调用`)
  await Promise.all([loadOverview(), loadAuditTools(shouldFallbackPage ? auditToolPagination.page - 1 : auditToolPagination.page)])
}

async function handleDeleteAuditModel(row) {
  await ElMessageBox.confirm(`确认删除模型调用《${row.resolved_model || row.requested_model || '-'}》吗？该操作不可恢复。`, '删除确认', { type: 'warning' })
  const shouldFallbackPage = auditModels.value.length === 1 && auditModelPagination.page > 1
  await deleteAIOpsAuditModelInvocation(row.id)
  ElMessage.success('模型调用已删除')
  await Promise.all([loadOverview(), loadAuditModels(shouldFallbackPage ? auditModelPagination.page - 1 : auditModelPagination.page)])
}

async function handleDeleteAuditAction(row) {
  await ElMessageBox.confirm(`确认删除动作《${row.title}》吗？该操作不可恢复。`, '删除确认', { type: 'warning' })
  const shouldFallbackPage = auditActions.value.length === 1 && auditActionPagination.page > 1
  await deleteAIOpsAuditAction(row.id)
  ElMessage.success('动作已删除')
  await Promise.all([loadOverview(), loadAuditActions(shouldFallbackPage ? auditActionPagination.page - 1 : auditActionPagination.page)])
}

async function handleBatchDeleteAuditActions() {
  if (!selectedAuditActionIds.value.length) return
  const shouldFallbackPage = selectedAuditActionIds.value.length === auditActions.value.length && auditActionPagination.page > 1
  const deletedCount = selectedAuditActionIds.value.length
  await ElMessageBox.confirm(`确认批量删除已选中的 ${deletedCount} 个动作吗？该操作不可恢复。`, '批量删除确认', { type: 'warning' })
  await bulkDeleteAIOpsAuditActions(selectedAuditActionIds.value)
  ElMessage.success(`已删除 ${deletedCount} 个动作`)
  await Promise.all([loadOverview(), loadAuditActions(shouldFallbackPage ? auditActionPagination.page - 1 : auditActionPagination.page)])
}

watch(
  () => route.query.tab,
  async (tab) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
    if (route.query.tab !== nextTab) {
      await syncRouteTab(nextTab)
      return
    }
    if (nextTab === 'overview') {
      await loadOverview()
    } else {
      await loadActiveTabPage(activePagination.value.page)
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.aiops-audit-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel,
.workbench-card {
  background: linear-gradient(180deg, rgba(255,255,255,.98) 0%, rgba(250,252,255,.96) 100%);
  border: 1px solid rgba(15,23,42,.08);
  border-radius: 18px;
  box-shadow: 0 8px 24px rgba(15,23,42,.04);
  padding: 14px 16px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 0;
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border-color: rgba(36,91,219,.09);
}

.release-hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.release-hero-copy {
  min-width: 0;
}

.hero h2 {
  color: #0f172a;
  font-size: 23px;
  margin: 0;
}

.page-inline-desc {
  color: #475569;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  transform: translateY(1px);
}

.audit-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #245bdb;
  background: linear-gradient(180deg,#f3f7ff 0%,#ebf2ff 100%);
  border: 1px solid rgba(36,91,219,.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.8);
}

.hero.panel {
  border-radius: 20px;
}

.audit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.audit-card {
  border-radius: 14px;
  border: 1px solid rgba(15,23,42,.08);
  background: linear-gradient(180deg,rgba(255,255,255,.98) 0%,rgba(252,253,255,.94) 100%);
  box-shadow: 0 4px 14px rgba(15,23,42,.03);
}

.audit-card--inline {
  min-height: 68px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.audit-card .stat-label {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.audit-card .stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #1f2329;
}

.audit-card--warning {
  background: linear-gradient(180deg,#fffdfa 0%,#ffffff 100%);
}

.audit-card--success {
  background: linear-gradient(180deg,#fbfffd 0%,#ffffff 100%);
}

.audit-card--danger {
  background: linear-gradient(180deg,#fffafb 0%,#ffffff 100%);
}

.audit-card--action {
  cursor: pointer;
  text-align: left;
}

.audit-card--action:hover {
  border-color: rgba(36,91,219,.16);
  box-shadow: 0 10px 20px rgba(36,91,219,.06);
}

.audit-card--action.is-active {
  border-color: rgba(36,91,219,.24);
  background: linear-gradient(180deg,#f4f7ff 0%,#ffffff 100%);
  box-shadow: 0 0 0 1px rgba(36,91,219,.05),0 12px 22px rgba(36,91,219,.08);
}

.audit-tabs {
  display: flex;
  width: 100%;
  margin-bottom: 0;
  padding: 3px;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.audit-tab-btn {
  min-height: 38px;
  padding: 0 18px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #4e5969;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
  gap: 6px;
}

.audit-tab-btn:hover {
  background: rgba(51,112,255,.06);
}

.audit-tabs.theme-blue .audit-tab-btn.active {
  color: #245bdb;
  background: #e8f0ff;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
}

.audit-tab-btn .el-icon {
  margin: 0;
  font-size: 15px;
}

.audit-tab-btn .tab-label {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.1;
}

.section-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.toolbar-head {
  display: inline-flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.toolbar-title,
.section-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.toolbar-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

.workbench-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.overview-time-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.overview-time-picker {
  width: 330px;
}

.overview-time-picker :deep(.el-range-separator) {
  color: #94a3b8;
  font-size: 12px;
}

.filter-refresh-btn {
  min-height: 28px;
}

.audit-flat-action-btn {
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  box-shadow: none;
}

.audit-flat-action-btn :deep(.el-icon),
.audit-flat-action-btn .el-icon {
  margin-right: 4px;
  font-size: 14px;
}

.audit-flat-action-btn.el-button--danger.is-plain {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.18);
  background: rgba(254, 242, 242, 0.72);
}

.audit-flat-action-btn.el-button--danger.is-plain:hover {
  color: #b91c1c;
  border-color: rgba(220, 38, 38, 0.28);
  background: rgba(254, 226, 226, 0.86);
}

.audit-flat-action-btn.is-disabled,
.audit-flat-action-btn.is-disabled:hover {
  color: #94a3b8;
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(248, 250, 252, 0.8);
}

.audit-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.88));
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.03);
}

.audit-list-toolbar .workbench-toolbar-left,
.audit-list-toolbar .workbench-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.audit-list-toolbar .workbench-toolbar-left {
  flex: 1 1 auto;
}

.audit-list-toolbar .workbench-toolbar-right {
  flex: 0 0 auto;
  justify-content: flex-end;
}

.audit-list-toolbar :deep(.el-input),
.audit-list-toolbar :deep(.el-select) {
  width: 112px;
}

.audit-filter-search {
  width: 220px !important;
}

.audit-filter-user {
  width: 112px !important;
}

.audit-filter-time {
  width: 310px !important;
}

.audit-page-size-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.audit-page-size-select {
  width: 94px !important;
}

.overview-metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.overview-metric-card {
  min-height: 74px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(15,23,42,.08);
  background: linear-gradient(180deg, rgba(255,255,255,.98) 0%, rgba(248,251,255,.94) 100%);
  box-shadow: 0 4px 14px rgba(15,23,42,.03);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}

.overview-metric-card span {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.overview-metric-card strong {
  color: #0f172a;
  font-size: 22px;
  font-weight: 760;
  line-height: 1.1;
}

.overview-metric-card small {
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.35;
}

.overview-dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(0, .96fr);
  gap: 10px;
}

.overview-panel {
  min-width: 0;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(15,23,42,.08);
  background: linear-gradient(180deg, rgba(255,255,255,.99) 0%, rgba(249,251,253,.96) 100%);
  box-shadow: 0 4px 14px rgba(15,23,42,.03);
}

.overview-panel--status {
  grid-column: 1 / -1;
}

.overview-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.overview-panel-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.overview-mini-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.overview-mini-stat {
  min-height: 56px;
  padding: 9px 10px;
  border-radius: 12px;
  border: 1px solid rgba(148,163,184,.18);
  background: rgba(248,250,252,.8);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}

.overview-mini-stat span {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.overview-mini-stat strong {
  color: #111827;
  font-size: 16px;
  font-weight: 760;
  line-height: 1.15;
}

.overview-rank-list,
.status-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.overview-rank-row {
  min-height: 54px;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(148,163,184,.16);
  background: rgba(255,255,255,.78);
}

.overview-rank-main {
  min-width: 0;
}

.overview-rank-title,
.overview-rank-meta,
.status-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.overview-rank-title span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1f2937;
  font-size: 13px;
  font-weight: 700;
}

.overview-rank-title strong,
.status-row-head strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 760;
  white-space: nowrap;
}

.overview-rank-meta {
  justify-content: flex-start;
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  flex-wrap: wrap;
}

.overview-rank-bar,
.status-progress {
  height: 5px;
  margin-top: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226,232,240,.78);
}

.overview-rank-bar span,
.status-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%);
}

.status-row {
  padding: 9px 10px;
  border-radius: 12px;
  border: 1px solid rgba(148,163,184,.16);
  background: rgba(255,255,255,.78);
}

.status-row-head span {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.status-progress .is-warning {
  background: linear-gradient(90deg, #fbbf24 0%, #f59e0b 100%);
}

.status-progress .is-success {
  background: linear-gradient(90deg, #34d399 0%, #10b981 100%);
}

.status-progress .is-danger {
  background: linear-gradient(90deg, #fb7185 0%, #ef4444 100%);
}

.status-progress .is-muted {
  background: linear-gradient(90deg, #cbd5e1 0%, #94a3b8 100%);
}

.overview-empty {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed rgba(148,163,184,.32);
  border-radius: 12px;
  color: #94a3b8;
  font-size: 12px;
  background: rgba(248,250,252,.6);
}

.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.console-table {
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.console-table :deep(th.el-table__cell) {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
}

.json-preview {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
  margin: 0;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.55;
}

.pagination-row {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 10px;
}

.pagination-size-control {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 860px) {
  .overview-metric-strip,
  .overview-dashboard-grid {
    grid-template-columns: 1fr;
  }

  .section-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .overview-time-controls {
    justify-content: flex-start;
    width: 100%;
  }

  .overview-time-picker {
    width: 100%;
  }

  .audit-list-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .audit-list-toolbar .workbench-toolbar-left,
  .audit-list-toolbar .workbench-toolbar-right {
    justify-content: flex-start;
    width: 100%;
  }

  .audit-list-toolbar :deep(.el-input),
  .audit-list-toolbar :deep(.el-select),
  .audit-filter-search,
  .audit-filter-user,
  .audit-filter-time {
    width: 100% !important;
  }

  .pagination-row {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 760px) {
  .hero {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
