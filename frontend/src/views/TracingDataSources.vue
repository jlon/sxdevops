<template>
  <div class="fade-in tracing-datasource-page" :class="{ 'is-embedded': props.embedded }">
    <section v-if="!props.embedded" class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="trace-header-icon"><el-icon><Connection /></el-icon></span>
          <h2>链路数据源</h2>
          <p class="page-desc inline-subtitle">统一管理 SkyWalking、Tempo、Jaeger、Zipkin 的查询入口和默认配置。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button v-if="canManageTracingDataSources" type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon>
          新增数据源
        </el-button>
      </div>
    </section>

    <div v-else class="embedded-datasource-head">
      <div>
        <h3>链路数据源</h3>
        <span>统一维护 SkyWalking、Tempo、Jaeger、Zipkin 的查询入口和默认配置。</span>
      </div>
      <el-button v-if="canManageTracingDataSources" size="small" type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon>
        新增数据源
      </el-button>
    </div>

    <div class="overview-grid">
      <div class="overview-card warm">
        <span>数据源总数</span>
        <strong>{{ items.length }}</strong>
      </div>
      <div class="overview-card cool">
        <span>启用中的数据源</span>
        <strong>{{ enabledCount }}</strong>
      </div>
      <div class="overview-card accent">
        <span>默认数据源</span>
        <strong>{{ defaultCount }}</strong>
      </div>
      <div class="overview-card neutral">
        <span>覆盖 Provider</span>
        <strong>{{ providerCoverage }}</strong>
      </div>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索名称或描述" clearable style="width: 260px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="providerFilter" clearable placeholder="全部 Provider" style="width: 220px">
          <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
        </el-select>
        <el-switch v-model="enabledOnly" active-text="仅看启用" inactive-text="全部状态" />
      </div>

      <el-table :data="filteredItems" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name-text">{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
            </div>
            <div class="sub-text">{{ row.description || '未填写描述' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Provider" width="200">
          <template #default="{ row }">
            <el-tag :type="providerTagType(row.provider)">{{ providerLabel(row.provider) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接摘要" min-width="320">
          <template #default="{ row }">
            <div class="summary-text">{{ formatSummary(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" :width="canManageTracingDataSources ? 280 : 120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openTracing(row)">打开追踪</el-button>
            <template v-if="canManageTracingDataSources">
              <el-button link type="success" size="small" @click="handleTest(row)" :loading="testingId === row.id">测试连接</el-button>
              <el-button link type="primary" size="small" @click="openDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除该链路数据源吗？" @confirm="handleDelete(row.id)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑链路数据源' : '新增链路数据源'" width="720px" destroy-on-close>
      <el-form :model="form" label-width="120px">
        <el-form-item label="数据源名称">
          <el-input v-model="form.name" placeholder="例如：生产 Tempo" />
        </el-form-item>
        <el-form-item label="Provider">
          <el-select v-model="form.provider" style="width: 100%" @change="onProviderChange">
            <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="例如：生产环境 OpenTelemetry 查询入口" />
        </el-form-item>
        <div class="switch-row">
          <el-switch v-model="form.is_enabled" active-text="启用" inactive-text="停用" />
          <el-switch v-model="form.is_default" active-text="设为默认" inactive-text="普通数据源" />
          <el-switch v-model="form.config.demo_mode" active-text="允许回退演示" inactive-text="严格真实连接" />
        </div>

        <template v-if="form.provider === 'skywalking'">
          <el-form-item label="UI 地址">
            <el-input v-model="form.config.ui_url" placeholder="http://skywalking-ui.example.com" />
          </el-form-item>
          <el-form-item label="OAP 地址">
            <el-input v-model="form.config.oap_url" placeholder="http://skywalking-oap.example.com:12800" />
          </el-form-item>
          <el-form-item label="GraphQL Path">
            <el-input v-model="form.config.graphql_path" placeholder="/graphql" />
          </el-form-item>
          <el-form-item label="默认 Layer">
            <el-input v-model="form.config.default_layer" placeholder="可选，例如 GENERAL" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="UI 地址">
            <el-input v-model="form.config.ui_url" :placeholder="uiPlaceholder(form.provider)" />
          </el-form-item>
          <el-form-item label="查询地址">
            <el-input v-model="form.config.query_url" :placeholder="queryPlaceholder(form.provider)" />
          </el-form-item>
          <el-form-item label="Authorization">
            <el-input v-model="form.config.authorization" show-password :placeholder="secretPlaceholder('authorization')" />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createTracingDataSource,
  deleteTracingDataSource,
  getTracingDataSources,
  getTracingProviders,
  testTracingDataSource,
  updateTracingDataSource,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const keyword = ref('')
const providerFilter = ref('')
const enabledOnly = ref(true)
const items = ref([])
const providers = ref([])
const providerDefaults = ref({})
const secretFlags = ref({})
const form = ref(createEmptyForm())

function createEmptyForm(provider = 'skywalking') {
  return {
    name: '',
    provider,
    description: '',
    is_enabled: true,
    is_default: false,
    config: getProviderDefaults(provider),
  }
}

function getProviderDefaults(provider) {
  const defaults = providerDefaults.value[provider] || {}
  const config = {}
  Object.entries(defaults).forEach(([key, value]) => {
    if (value !== 'configured') config[key] = value
  })
  if (provider === 'skywalking') {
    config.graphql_path = config.graphql_path || '/graphql'
  }
  if (config.demo_mode === undefined) {
    config.demo_mode = true
  }
  return config
}

const enabledCount = computed(() => items.value.filter((item) => item.is_enabled).length)
const defaultCount = computed(() => items.value.filter((item) => item.is_default).length)
const providerCoverage = computed(() => new Set(items.value.map((item) => item.provider)).size)
const filteredItems = computed(() =>
  items.value.filter((item) => {
    if (providerFilter.value && item.provider !== providerFilter.value) return false
    if (enabledOnly.value && !item.is_enabled) return false
    if (!keyword.value) return true
    const text = `${item.name} ${item.description || ''}`.toLowerCase()
    return text.includes(keyword.value.toLowerCase())
  })
)
const canManageTracingDataSources = computed(() => authStore.hasPermission('ops.trace.datasource.manage'))

function providerLabel(provider) {
  return providers.value.find((item) => item.id === provider)?.name || provider
}

function providerTagType(provider) {
  return {
    skywalking: 'success',
    tempo: 'warning',
    jaeger: 'primary',
    zipkin: 'info',
  }[provider] || 'info'
}

function formatSummary(row) {
  const config = row.config || {}
  if (row.provider === 'skywalking') return [config.oap_url, config.ui_url].filter(Boolean).join(' / ') || '未配置 SkyWalking 地址'
  return [config.query_url, config.ui_url].filter(Boolean).join(' / ') || '未配置查询地址'
}

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function uiPlaceholder(provider) {
  return {
    tempo: 'http://grafana.example.com/explore',
    jaeger: 'http://jaeger-ui.example.com',
    zipkin: 'http://zipkin-ui.example.com',
  }[provider] || ''
}

function queryPlaceholder(provider) {
  return {
    tempo: 'http://tempo-query.example.com',
    jaeger: 'http://jaeger-query.example.com',
    zipkin: 'http://zipkin-api.example.com',
  }[provider] || ''
}

function secretPlaceholder(key) {
  return secretFlags.value[key] ? '已配置，留空则保持不变' : '可选'
}

async function fetchProviders() {
  const response = await getTracingProviders()
  providers.value = response.providers || []
  const defaults = {}
  providers.value.forEach((provider) => {
    defaults[provider.id] = provider.defaults || {}
  })
  providerDefaults.value = defaults
}

async function fetchDataSources() {
  loading.value = true
  try {
    const response = await getTracingDataSources()
    items.value = Array.isArray(response) ? response : response.results || []
  } finally {
    loading.value = false
  }
}

function onProviderChange(provider) {
  form.value.config = {
    ...getProviderDefaults(provider),
    ...form.value.config,
  }
  if (provider === 'skywalking') {
    delete form.value.config.query_url
  } else {
    delete form.value.config.oap_url
    delete form.value.config.graphql_path
    delete form.value.config.default_layer
  }
}

function openDialog(row) {
  if (row) {
    editingId.value = row.id
    const config = { ...(row.config || {}) }
    secretFlags.value = {
      authorization: config.authorization === 'configured',
    }
    Object.keys(secretFlags.value).forEach((key) => {
      if (secretFlags.value[key]) config[key] = ''
    })
    form.value = {
      id: row.id,
      name: row.name,
      provider: row.provider,
      description: row.description,
      is_enabled: row.is_enabled,
      is_default: row.is_default,
      config,
    }
  } else {
    editingId.value = null
    secretFlags.value = {}
    form.value = createEmptyForm(providers.value[0]?.id || 'skywalking')
  }
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.name) return ElMessage.warning('请填写数据源名称')
  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      provider: form.value.provider,
      description: form.value.description,
      is_enabled: form.value.is_enabled,
      is_default: form.value.is_default,
      config: form.value.config,
    }
    if (editingId.value) {
      await updateTracingDataSource(editingId.value, payload)
      ElMessage.success('链路数据源已更新')
    } else {
      await createTracingDataSource(payload)
      ElMessage.success('链路数据源已创建')
    }
    dialogVisible.value = false
    await fetchDataSources()
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  await deleteTracingDataSource(id)
  ElMessage.success('链路数据源已删除')
  await fetchDataSources()
}

async function handleTest(row) {
  testingId.value = row.id
  try {
    const response = await testTracingDataSource(row.id)
    if (response.success) ElMessage.success(`${response.message}，发现 ${response.preview_count || 0} 个服务`)
    else ElMessage.error(response.message || '连接测试失败')
  } finally {
    testingId.value = null
  }
}

function openTracing(row) {
  router.push({
    path: '/observability/tracing',
    query: {
      provider: row.provider,
      datasourceId: String(row.id),
    },
  })
}

onMounted(async () => {
  await fetchProviders()
  await fetchDataSources()
})
</script>

<style scoped>
.tracing-datasource-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tracing-datasource-page.is-embedded {
  gap: 8px;
}

.panel,
.table-card {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  padding: 12px 14px;
}

.hero,
.hero-actions,
.overview-grid,
.filter-bar,
.switch-row,
.name-cell {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero {
  align-items: center;
  justify-content: space-between;
}

.embedded-datasource-head {
  align-items: center;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  padding: 10px 12px;
}

.embedded-datasource-head h3 {
  color: #0f172a;
  font-size: 14px;
  margin: 0 0 3px;
}

.embedded-datasource-head span {
  color: var(--text-secondary);
  font-size: 12px;
}

.trace-header-icon {
  align-items: center;
  background: linear-gradient(135deg, #0f766e, #2563eb);
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.overview-card {
  border-radius: 12px;
  min-height: 72px;
  padding: 10px 12px;
}

.overview-card.warm { background: linear-gradient(135deg, #fef3c7, #fdba74); }
.overview-card.cool { background: linear-gradient(135deg, #dbeafe, #93c5fd); }
.overview-card.accent { background: linear-gradient(135deg, #dcfce7, #86efac); }
.overview-card.neutral { background: linear-gradient(135deg, #f1f5f9, #cbd5e1); }

.overview-card span,
.sub-text,
.summary-text {
  color: var(--text-secondary);
  font-size: 12px;
}

.overview-card strong {
  font-size: 22px;
}

.filter-bar {
  margin-bottom: 10px;
}

.switch-row {
  margin: 4px 0 14px;
}

.name-text {
  font-weight: 600;
}

@media (max-width: 960px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .hero {
    align-items: stretch;
    flex-direction: column;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
