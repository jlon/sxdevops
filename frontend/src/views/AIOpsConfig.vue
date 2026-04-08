<template>
  <div class="aiops-config-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><ChatDotSquare /></el-icon></span>
          <h2>运维智能体配置</h2>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading.page" @click="loadAll">刷新</el-button>
        <el-button size="small" type="primary" :loading="saving.config" @click="saveConfig">保存策略</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ providers.length }}</div>
        <div class="stat-label">模型提供商</div>
      </div>
      <div class="stat-card release-stat-card success-card">
        <div class="stat-value">{{ enabledMcpCount }}</div>
        <div class="stat-label">启用中的 MCP</div>
      </div>
      <div class="stat-card release-stat-card warning-card">
        <div class="stat-value">{{ enabledSkillCount }}</div>
        <div class="stat-label">启用中的 Skill</div>
      </div>
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ auditOverview.sessions_today || 0 }}</div>
        <div class="stat-label">今日会话数</div>
      </div>
    </div>

    <div class="runtime-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>模型 Key 加密保存；高风险动作默认二次确认；MCP 与 Skill 受控接入。</span>
    </div>

    <section class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="智能体策略" name="strategy" />
        <el-tab-pane label="模型提供商" name="providers" />
        <el-tab-pane label="MCP" name="mcp" />
        <el-tab-pane label="Skill" name="skills" />
        <el-tab-pane label="审计" name="audit" />
      </el-tabs>

      <template v-if="activeTab === 'strategy'">
        <div class="config-grid">
          <div class="config-section">
            <div class="section-title">基础策略</div>
            <el-form :model="configForm" label-width="118px">
              <el-form-item label="默认提供商">
                <el-select v-model="configForm.default_provider_id" clearable style="width:100%">
                  <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="欢迎语">
                <el-input v-model="configForm.welcome_message" />
              </el-form-item>
              <el-form-item label="建议问题">
                <el-select v-model="configForm.suggested_questions" multiple filterable allow-create default-first-option style="width:100%" />
              </el-form-item>
              <el-form-item label="系统提示语">
                <el-input v-model="configForm.system_prompt" type="textarea" :rows="8" />
              </el-form-item>
            </el-form>
          </div>
          <div class="config-section">
            <div class="section-title">运行与安全</div>
            <div class="switch-list">
              <div class="switch-item">
                <span>启用机器人</span>
                <el-switch v-model="configForm.is_enabled" />
              </div>
              <div class="switch-item">
                <span>允许执行动作</span>
                <el-switch v-model="configForm.allow_action_execution" />
              </div>
              <div class="switch-item">
                <span>执行前确认</span>
                <el-switch v-model="configForm.require_confirmation" />
              </div>
              <div class="switch-item">
                <span>展示证据来源</span>
                <el-switch v-model="configForm.show_evidence" />
              </div>
              <div class="switch-item">
                <span>允许关联分析</span>
                <el-switch v-model="configForm.allow_analysis" />
              </div>
            </div>
            <el-form :model="configForm" label-width="118px" style="margin-top:8px;">
              <el-form-item label="历史消息窗口">
                <el-input-number v-model="configForm.max_history_messages" :min="4" :max="40" />
              </el-form-item>
            </el-form>
          </div>
        </div>
        <div class="audit-section">
          <div class="section-title">最近会话</div>
          <el-table :data="auditSessions.slice(0, 6)" stripe size="small">
            <el-table-column prop="title" label="会话标题" min-width="180" />
            <el-table-column prop="username" label="用户" width="120" />
            <el-table-column prop="message_count" label="消息数" width="90" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="last_message_at" label="最后消息" min-width="180" />
          </el-table>
        </div>
        <div class="audit-section">
          <div class="section-title">最近工具调用</div>
          <el-table :data="auditTools.slice(0, 8)" stripe size="small">
            <el-table-column prop="tool_name" label="工具" width="180" />
            <el-table-column prop="username" label="用户" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="latency_ms" label="耗时(ms)" width="110" />
            <el-table-column prop="created_at" label="时间" min-width="180" />
          </el-table>
        </div>
        <div class="audit-section">
          <div class="section-title">最近动作</div>
          <el-table :data="auditActions.slice(0, 8)" stripe size="small">
            <el-table-column prop="title" label="动作标题" min-width="180" />
            <el-table-column prop="risk_level_display" label="风险" width="100" />
            <el-table-column prop="status_display" label="状态" width="120" />
            <el-table-column prop="confirmed_by" label="确认人" width="120" />
            <el-table-column prop="updated_at" label="更新时间" min-width="180" />
          </el-table>
        </div>
      </template>

      <template v-else-if="activeTab === 'providers'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openProviderDialog()">新增提供商</el-button>
        </div>
        <el-table :data="providers" stripe>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="provider_type" label="类型" width="150" />
          <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
          <el-table-column prop="default_model" label="默认模型" width="160" />
          <el-table-column label="Key" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.has_api_key ? 'success' : 'info'">{{ row.has_api_key ? '已配置' : '未配置' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openProviderDialog(row)">编辑</el-button>
              <el-button link type="success" @click="handleTestProvider(row)">测试</el-button>
              <el-button link type="danger" @click="handleDeleteProvider(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'mcp'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openMcpDialog()">新增 MCP</el-button>
        </div>
        <el-table :data="mcpServers" stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="server_type" label="类型" width="120" />
          <el-table-column prop="endpoint_or_command" label="地址或命令" min-width="240" show-overflow-tooltip />
          <el-table-column label="启用" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openMcpDialog(row)">编辑</el-button>
              <el-button link type="danger" @click="handleDeleteMcp(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'skills'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openSkillDialog()">新增 Skill</el-button>
        </div>
        <el-table :data="skills" stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="slug" label="标识" width="140" />
          <el-table-column prop="source_type" label="来源" width="120" />
          <el-table-column prop="description" label="描述" min-width="240" />
          <el-table-column label="启用" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openSkillDialog(row)">编辑</el-button>
              <el-button link type="danger" @click="handleDeleteSkill(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else>
        <div class="audit-grid">
          <div class="audit-card">
            <span>今日会话</span>
            <strong>{{ auditOverview.sessions_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>今日消息</span>
            <strong>{{ auditOverview.messages_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>今日动作</span>
            <strong>{{ auditOverview.actions_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>失败动作</span>
            <strong>{{ auditOverview.failed_actions_today || 0 }}</strong>
          </div>
        </div>
      </template>
    </section>

    <el-dialog v-model="providerDialogVisible" :title="providerForm.id ? '编辑提供商' : '新增提供商'" width="760px" destroy-on-close>
      <el-form :model="providerForm" label-width="102px">
        <el-form-item label="名称"><el-input v-model="providerForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="providerForm.provider_type" style="width:100%"><el-option label="OpenAI Compatible" value="openai_compatible" /></el-select></el-form-item>
        <el-form-item label="Base URL"><el-input v-model="providerForm.base_url" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="providerForm.api_key" type="password" show-password placeholder="留空则保留原值" /></el-form-item>
        <div class="dialog-grid">
          <el-form-item label="默认模型"><el-input v-model="providerForm.default_model" /></el-form-item>
          <el-form-item label="备用模型"><el-input v-model="providerForm.backup_model" /></el-form-item>
          <el-form-item label="温度"><el-input-number v-model="providerForm.temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
          <el-form-item label="最大 Tokens"><el-input-number v-model="providerForm.max_tokens" :min="100" :max="16000" :step="100" /></el-form-item>
          <el-form-item label="超时"><el-input-number v-model="providerForm.timeout_seconds" :min="5" :max="120" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="providerForm.is_enabled" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.provider" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mcpDialogVisible" :title="mcpForm.id ? '编辑 MCP' : '新增 MCP'" width="680px" destroy-on-close>
      <el-form :model="mcpForm" label-width="102px">
        <el-form-item label="名称"><el-input v-model="mcpForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="mcpForm.server_type" style="width:100%"><el-option label="HTTP" value="http" /><el-option label="STDIO" value="stdio" /><el-option label="Demo" value="demo" /></el-select></el-form-item>
        <el-form-item label="地址或命令"><el-input v-model="mcpForm.endpoint_or_command" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="mcpForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="工具白名单"><el-select v-model="mcpForm.tool_whitelist" multiple filterable allow-create default-first-option style="width:100%" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="mcpForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mcpDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.mcp" @click="saveMcp">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="skillDialogVisible" :title="skillForm.id ? '编辑 Skill' : '新增 Skill'" width="760px" destroy-on-close>
      <el-form :model="skillForm" label-width="102px">
        <div class="dialog-grid">
          <el-form-item label="名称"><el-input v-model="skillForm.name" /></el-form-item>
          <el-form-item label="标识"><el-input v-model="skillForm.slug" /></el-form-item>
        </div>
        <el-form-item label="来源"><el-select v-model="skillForm.source_type" style="width:100%"><el-option label="内置内容" value="inline" /><el-option label="本地文件" value="local" /></el-select></el-form-item>
        <el-form-item label="描述"><el-input v-model="skillForm.description" /></el-form-item>
        <el-form-item label="允许角色"><el-select v-model="skillForm.allowed_role_codes" multiple filterable allow-create default-first-option style="width:100%" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="skillForm.content" type="textarea" :rows="8" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="skillForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="skillDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.skill" @click="saveSkill">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ChatDotSquare, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAIOpsMcpServer,
  createAIOpsProvider,
  createAIOpsSkill,
  deleteAIOpsMcpServer,
  deleteAIOpsProvider,
  deleteAIOpsSkill,
  getAIOpsAuditActions,
  getAIOpsAuditOverview,
  getAIOpsAuditSessions,
  getAIOpsAuditToolInvocations,
  getAIOpsConfig,
  getAIOpsMcpServers,
  getAIOpsProviders,
  getAIOpsSkills,
  testAIOpsProvider,
  updateAIOpsConfig,
  updateAIOpsMcpServer,
  updateAIOpsProvider,
  updateAIOpsSkill,
} from '@/api/modules/aiops'

const activeTab = ref('strategy')
const loading = reactive({ page: false })
const saving = reactive({ config: false, provider: false, mcp: false, skill: false })

const providers = ref([])
const mcpServers = ref([])
const skills = ref([])
const auditOverview = ref({})
const auditSessions = ref([])
const auditTools = ref([])
const auditActions = ref([])

const configForm = reactive({
  default_provider_id: null,
  system_prompt: '',
  welcome_message: '',
  suggested_questions: [],
  is_enabled: true,
  allow_action_execution: true,
  require_confirmation: true,
  show_evidence: true,
  allow_analysis: true,
  max_history_messages: 12,
})

const providerDialogVisible = ref(false)
const mcpDialogVisible = ref(false)
const skillDialogVisible = ref(false)

const providerForm = reactive({})
const mcpForm = reactive({})
const skillForm = reactive({})

const enabledMcpCount = computed(() => mcpServers.value.filter(item => item.is_enabled).length)
const enabledSkillCount = computed(() => skills.value.filter(item => item.is_enabled).length)

function resetProviderForm() {
  Object.assign(providerForm, {
    id: null,
    name: '',
    provider_type: 'openai_compatible',
    base_url: '',
    api_key: '',
    default_model: '',
    backup_model: '',
    temperature: 0.2,
    max_tokens: 1200,
    timeout_seconds: 30,
    is_enabled: true,
  })
}

function resetMcpForm() {
  Object.assign(mcpForm, {
    id: null,
    name: '',
    server_type: 'http',
    endpoint_or_command: '',
    description: '',
    tool_whitelist: [],
    is_enabled: true,
  })
}

function resetSkillForm() {
  Object.assign(skillForm, {
    id: null,
    name: '',
    slug: '',
    source_type: 'inline',
    description: '',
    content: '',
    allowed_role_codes: [],
    is_enabled: true,
  })
}

function applyConfig(payload = {}) {
  Object.assign(configForm, {
    default_provider_id: payload.default_provider?.id || null,
    system_prompt: payload.system_prompt || '',
    welcome_message: payload.welcome_message || '',
    suggested_questions: payload.suggested_questions || [],
    is_enabled: payload.is_enabled ?? true,
    allow_action_execution: payload.allow_action_execution ?? true,
    require_confirmation: payload.require_confirmation ?? true,
    show_evidence: payload.show_evidence ?? true,
    allow_analysis: payload.allow_analysis ?? true,
    max_history_messages: payload.max_history_messages || 12,
  })
}

async function loadAll() {
  loading.page = true
  try {
    const [config, providerData, mcpData, skillData, auditData, sessionData, toolData, actionData] = await Promise.all([
      getAIOpsConfig(),
      getAIOpsProviders(),
      getAIOpsMcpServers(),
      getAIOpsSkills(),
      getAIOpsAuditOverview(),
      getAIOpsAuditSessions(),
      getAIOpsAuditToolInvocations(),
      getAIOpsAuditActions(),
    ])
    applyConfig(config)
    providers.value = providerData || []
    mcpServers.value = mcpData || []
    skills.value = skillData || []
    auditOverview.value = auditData || {}
    auditSessions.value = sessionData.results || sessionData || []
    auditTools.value = toolData.results || toolData || []
    auditActions.value = actionData.results || actionData || []
  } finally {
    loading.page = false
  }
}

async function saveConfig() {
  saving.config = true
  try {
    await updateAIOpsConfig({ ...configForm })
    ElMessage.success('智能体策略已保存')
    await loadAll()
  } finally {
    saving.config = false
  }
}

function openProviderDialog(row) {
  resetProviderForm()
  if (row) Object.assign(providerForm, row, { api_key: '' })
  providerDialogVisible.value = true
}

async function saveProvider() {
  saving.provider = true
  try {
    const payload = { ...providerForm }
    if (!payload.api_key) delete payload.api_key
    if (providerForm.id) await updateAIOpsProvider(providerForm.id, payload)
    else await createAIOpsProvider(payload)
    providerDialogVisible.value = false
    ElMessage.success('模型提供商已保存')
    await loadAll()
  } finally {
    saving.provider = false
  }
}

async function handleTestProvider(row) {
  const result = await testAIOpsProvider(row.id)
  ElMessage.success(result.message)
  await loadAll()
}

async function handleDeleteProvider(row) {
  await ElMessageBox.confirm(`确认删除模型提供商 ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsProvider(row.id)
  ElMessage.success('模型提供商已删除')
  await loadAll()
}

function openMcpDialog(row) {
  resetMcpForm()
  if (row) Object.assign(mcpForm, row)
  mcpDialogVisible.value = true
}

async function saveMcp() {
  saving.mcp = true
  try {
    if (mcpForm.id) await updateAIOpsMcpServer(mcpForm.id, { ...mcpForm })
    else await createAIOpsMcpServer({ ...mcpForm })
    mcpDialogVisible.value = false
    ElMessage.success('MCP 配置已保存')
    await loadAll()
  } finally {
    saving.mcp = false
  }
}

async function handleDeleteMcp(row) {
  await ElMessageBox.confirm(`确认删除 MCP ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsMcpServer(row.id)
  ElMessage.success('MCP 已删除')
  await loadAll()
}

function openSkillDialog(row) {
  resetSkillForm()
  if (row) Object.assign(skillForm, row)
  skillDialogVisible.value = true
}

async function saveSkill() {
  saving.skill = true
  try {
    if (skillForm.id) await updateAIOpsSkill(skillForm.id, { ...skillForm })
    else await createAIOpsSkill({ ...skillForm })
    skillDialogVisible.value = false
    ElMessage.success('Skill 已保存')
    await loadAll()
  } finally {
    saving.skill = false
  }
}

async function handleDeleteSkill(row) {
  await ElMessageBox.confirm(`确认删除 Skill ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsSkill(row.id)
  ElMessage.success('Skill 已删除')
  await loadAll()
}

onMounted(async () => {
  resetProviderForm()
  resetMcpForm()
  resetSkillForm()
  await loadAll()
})
</script>

<style scoped>
.aiops-config-page{display:flex;flex-direction:column;gap:8px}
.panel{background:linear-gradient(180deg,#fff 0%,#fffdf8 100%);border:1px solid rgba(148,163,184,.16);border-radius:20px;box-shadow:0 12px 28px rgba(15,23,42,.05);padding:14px 16px}
.hero,.hero-copy,.hero-title-row,.hero-actions,.config-grid,.switch-list,.section-toolbar,.audit-grid{display:flex;gap:8px}
.hero-actions{align-items:center;flex-wrap:wrap}
.hero-actions :deep(.el-button){min-height:38px;padding:0 16px;border-radius:12px}
.hero{align-items:center;justify-content:space-between;background:linear-gradient(135deg,#fff7ed 0%,#f0fdf4 100%)}
.hero-title-row{align-items:center}.hero-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(135deg,#0f766e,#0ea5e9)}.hero h2{margin:0;font-size:24px}
.stats-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.release-stat-card{padding:14px 16px;border-radius:16px;background:linear-gradient(145deg,#ffffff 0%,#f6faff 100%);border:1px solid rgba(148,163,184,.16);box-shadow:0 12px 26px rgba(15,23,42,.05)}.stat-value{font-size:28px;font-weight:700;color:#0f172a}.stat-label{margin-top:6px;color:#64748b;font-size:13px}.success-card{background:linear-gradient(145deg,#f0fdf4 0%,#ecfeff 100%)}.warning-card{background:linear-gradient(145deg,#fff7ed 0%,#fffbeb 100%)}
.runtime-strip{display:flex;align-items:center;gap:0;padding:8px 11px;border-radius:10px;background:linear-gradient(90deg,rgba(59,130,246,.08) 0%,rgba(14,165,233,.04) 100%);color:#64748b;border:1px solid rgba(59,130,246,.14);font-size:12px;line-height:1.45;margin-top:-10px}.runtime-strip :deep(.el-icon){display:none}
.config-grid{align-items:flex-start}.config-section{flex:1;padding:8px 0}.section-title{font-size:14px;font-weight:700;color:#0f172a;margin-bottom:8px}.switch-list{flex-direction:column}.switch-item{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}
.section-toolbar{justify-content:flex-end;margin-bottom:8px}.dialog-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 10px}.audit-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.audit-card{padding:16px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;display:flex;flex-direction:column;gap:8px}.audit-card strong{font-size:28px;color:#0f172a}
.audit-section{margin-top:8px}
@media (max-width: 960px){.stats-grid,.audit-grid,.dialog-grid{grid-template-columns:1fr}.config-grid{flex-direction:column}}
.hero.panel { border-radius: 20px; }
</style>



