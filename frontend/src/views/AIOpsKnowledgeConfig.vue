<template>
  <div class="knowledge-config-page">
    <section v-if="!embedded" class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Setting /></el-icon></span>
          <h2>图谱配置</h2>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadData">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button v-if="canManage" type="primary" size="small" @click="openDialog()">
          <el-icon><Plus /></el-icon>
          新增关联
        </el-button>
      </div>
    </section>

    <div class="release-stats">
      <div class="release-stat-card">
        <div class="stat-value">{{ environments.length }}</div>
        <div class="stat-label">图谱环境</div>
      </div>
      <div class="release-stat-card success-card">
        <div class="stat-value">{{ enabledCount }}</div>
        <div class="stat-label">启用中</div>
      </div>
      <div class="release-stat-card warning-card">
        <div class="stat-value">{{ totalBindingCount }}</div>
        <div class="stat-label">关联来源</div>
      </div>
      <div class="release-stat-card">
        <div class="stat-value">{{ catalog.grafana_folders.length }}</div>
        <div class="stat-label">看板目录</div>
      </div>
    </div>

    <div class="runtime-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>知识图谱环境名会作为图谱筛选和后续 AIOps 分析入口，底层数据只从事件中心、监控看板、日志中心、链路追踪和告警中心读取。</span>
    </div>

    <section class="panel">
      <div class="config-actionbar">
        <div>
          <div class="actionbar-title">环境关联配置</div>
          <div class="actionbar-desc">把事件中心、监控看板、日志、链路和告警来源绑定成一个知识图谱环境。</div>
        </div>
        <div class="actionbar-actions">
          <el-button size="small" :loading="loading" @click="loadData">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button v-if="canManage" type="primary" size="small" @click="openDialog()">
            <el-icon><Plus /></el-icon>
            新增关联
          </el-button>
        </div>
      </div>
      <el-table v-loading="loading" :data="environments" row-key="id">
        <el-table-column prop="name" label="图谱环境名" min-width="150">
          <template #default="{ row }">
            <div class="env-name">{{ row.name }}</div>
            <div v-if="row.description" class="env-desc">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="事件中心环境" min-width="170">
          <template #default="{ row }"><TagList :items="row.event_environments" /></template>
        </el-table-column>
        <el-table-column label="监控看板目录" min-width="180">
          <template #default="{ row }"><TagList :items="row.grafana_folder_keys" /></template>
        </el-table-column>
        <el-table-column label="日志数据源" min-width="170">
          <template #default="{ row }"><TagList :items="datasourceNames(row.log_datasource_ids, 'log')" /></template>
        </el-table-column>
        <el-table-column label="链路数据源" min-width="170">
          <template #default="{ row }"><TagList :items="datasourceNames(row.tracing_datasource_ids, 'trace')" /></template>
        </el-table-column>
        <el-table-column label="告警环境" min-width="160">
          <template #default="{ row }"><TagList :items="row.alert_environments" /></template>
        </el-table-column>
        <el-table-column label="基础设施" min-width="190">
          <template #default="{ row }"><TagList :items="infrastructureNames(row)" /></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openDialog(row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="removeEnvironment(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog.visible" :title="dialog.editingId ? '编辑图谱环境' : '新增图谱环境'" width="720px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="128px">
        <el-form-item label="环境名" prop="name">
          <el-input v-model.trim="form.name" placeholder="例如：交易生产 / 核心测试" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model.trim="form.description" maxlength="255" show-word-limit placeholder="可选，说明这个图谱环境绑定的业务范围" />
        </el-form-item>
        <el-form-item label="事件中心环境">
          <el-select v-model="form.event_environments" multiple filterable clearable placeholder="选择一个或多个事件中心环境">
            <el-option v-for="item in catalog.event_environments" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="监控看板目录">
          <el-select v-model="form.grafana_folder_keys" multiple filterable clearable placeholder="选择一个或多个监控看板目录">
            <el-option v-for="item in catalog.grafana_folders" :key="item.key" :label="folderLabel(item)" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="日志数据源">
          <el-select v-model="form.log_datasource_ids" multiple filterable clearable placeholder="选择一个或多个日志中心数据源">
            <el-option v-for="item in catalog.log_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="链路数据源">
          <el-select v-model="form.tracing_datasource_ids" multiple filterable clearable placeholder="选择一个或多个链路追踪数据源">
            <el-option v-for="item in catalog.tracing_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警中心环境">
          <el-select v-model="form.alert_environments" multiple filterable clearable placeholder="选择一个或多个告警中心环境">
            <el-option v-for="item in catalog.alert_environments" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="K8s 集群">
          <el-select v-model="form.k8s_cluster_ids" multiple filterable clearable placeholder="选择此图谱所在的 K8s 集群">
            <el-option v-for="item in catalog.k8s_clusters" :key="item.id" :label="k8sClusterLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <div v-if="selectedK8sClusters.length" class="namespace-config">
          <div class="namespace-config-title">K8s 命名空间范围</div>
          <div v-for="cluster in selectedK8sClusters" :key="cluster.id" class="namespace-row">
            <div class="namespace-cluster">
              <strong>{{ cluster.name }}</strong>
              <span>不选则读取该集群全部命名空间</span>
            </div>
            <el-select
              v-model="form.k8s_namespaces[String(cluster.id)]"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="选择业务服务所在命名空间"
            >
              <el-option v-for="namespace in namespaceOptionsForCluster(cluster)" :key="namespace" :label="namespace" :value="namespace" />
            </el-select>
          </div>
        </div>
        <el-form-item label="Docker 环境">
          <el-select v-model="form.docker_host_ids" multiple filterable clearable placeholder="选择此图谱所在的 Docker 环境">
            <el-option v-for="item in catalog.docker_hosts" :key="item.id" :label="dockerHostLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { InfoFilled, Plus, RefreshRight, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createAIOpsKnowledgeEnvironment,
  deleteAIOpsKnowledgeEnvironment,
  getAIOpsKnowledgeEnvironmentCatalog,
  getAIOpsKnowledgeEnvironments,
  updateAIOpsKnowledgeEnvironment,
} from '@/api/modules/aiops'

const TagList = defineComponent({
  name: 'TagList',
  props: {
    items: { type: Array, default: () => [] },
  },
  setup(props) {
    return () => {
      const values = (props.items || []).filter(Boolean)
      if (!values.length) return h('span', { class: 'muted' }, '未关联')
      return h('div', { class: 'tag-list' }, values.slice(0, 4).map(item => h(ElTag, { key: String(item), size: 'small', type: 'info' }, () => String(item))).concat(
        values.length > 4 ? [h(ElTag, { key: '__more', size: 'small' }, () => `+${values.length - 4}`)] : [],
      ))
    }
  },
})

defineProps({
  embedded: { type: Boolean, default: false },
})

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('aiops.knowledge.manage'))
const loading = ref(false)
const saving = ref(false)
const formRef = ref(null)
const environments = ref([])
const catalog = reactive({
  event_environments: [],
  grafana_folders: [],
  log_datasources: [],
  tracing_datasources: [],
  alert_environments: [],
  k8s_clusters: [],
  docker_hosts: [],
})
const dialog = reactive({ visible: false, editingId: null })
const form = reactive({
  name: '',
  description: '',
  event_environments: [],
  grafana_folder_keys: [],
  log_datasource_ids: [],
  tracing_datasource_ids: [],
  alert_environments: [],
  k8s_cluster_ids: [],
  k8s_namespaces: {},
  docker_host_ids: [],
  is_enabled: true,
})

const rules = {
  name: [{ required: true, message: '请填写知识图谱环境名', trigger: 'blur' }],
}

const enabledCount = computed(() => environments.value.filter(item => item.is_enabled).length)
const totalBindingCount = computed(() => environments.value.reduce((total, item) => total
  + (item.event_environments?.length || 0)
  + (item.grafana_folder_keys?.length || 0)
  + (item.log_datasource_ids?.length || 0)
  + (item.tracing_datasource_ids?.length || 0)
  + (item.alert_environments?.length || 0)
  + (item.k8s_cluster_ids?.length || 0)
  + (item.docker_host_ids?.length || 0), 0))

const selectedK8sClusters = computed(() => {
  const selected = new Set((form.k8s_cluster_ids || []).map(id => Number(id)))
  return catalog.k8s_clusters.filter(item => selected.has(Number(item.id)))
})

function resetForm(row = null) {
  dialog.editingId = row?.id || null
  form.name = row?.name || ''
  form.description = row?.description || ''
  form.event_environments = [...(row?.event_environments || [])]
  form.grafana_folder_keys = [...(row?.grafana_folder_keys || [])]
  form.log_datasource_ids = [...(row?.log_datasource_ids || [])]
  form.tracing_datasource_ids = [...(row?.tracing_datasource_ids || [])]
  form.alert_environments = [...(row?.alert_environments || [])]
  form.k8s_cluster_ids = [...(row?.k8s_cluster_ids || [])]
  form.k8s_namespaces = { ...(row?.k8s_namespaces || {}) }
  form.docker_host_ids = [...(row?.docker_host_ids || [])]
  form.is_enabled = row?.is_enabled ?? true
}

function hasAnyBinding() {
  return [
    form.event_environments,
    form.grafana_folder_keys,
    form.log_datasource_ids,
    form.tracing_datasource_ids,
    form.alert_environments,
    form.k8s_cluster_ids,
    form.docker_host_ids,
  ].some(items => items.length)
}

function datasourceLabel(item) {
  return `${item.name} / ${item.provider_display || item.provider}`
}

function folderLabel(item) {
  return item.dashboard_count ? `${item.label}（${item.dashboard_count} 个看板）` : item.label
}

function datasourceNames(ids = [], type = 'log') {
  const source = type === 'trace' ? catalog.tracing_datasources : catalog.log_datasources
  const nameMap = new Map(source.map(item => [Number(item.id), item.name]))
  return ids.map(id => nameMap.get(Number(id)) || `ID ${id}`)
}

function k8sClusterLabel(item) {
  return item.api_server ? `${item.name} / ${item.api_server}` : item.name
}

function namespaceOptionsForCluster(cluster) {
  return cluster.namespaces || []
}

function dockerHostLabel(item) {
  return item.ip_address ? `${item.name} / ${item.ip_address}` : item.name
}

function infrastructureNames(row) {
  const k8sMap = new Map(catalog.k8s_clusters.map(item => [Number(item.id), `K8s: ${item.name}`]))
  const dockerMap = new Map(catalog.docker_hosts.map(item => [Number(item.id), `Docker: ${item.name}`]))
  return [
    ...(row.k8s_cluster_ids || []).map((id) => {
      const namespaces = row.k8s_namespaces?.[String(id)] || []
      const suffix = namespaces.length ? ` / ${namespaces.join(', ')}` : ''
      return `${k8sMap.get(Number(id)) || `K8s ID ${id}`}${suffix}`
    }),
    ...(row.docker_host_ids || []).map(id => dockerMap.get(Number(id)) || `Docker ID ${id}`),
  ]
}

async function loadData() {
  loading.value = true
  try {
    const [list, options] = await Promise.all([
      getAIOpsKnowledgeEnvironments(),
      getAIOpsKnowledgeEnvironmentCatalog(),
    ])
    environments.value = Array.isArray(list) ? list : (list.results || [])
    Object.assign(catalog, {
      event_environments: options.event_environments || [],
      grafana_folders: options.grafana_folders || [],
      log_datasources: options.log_datasources || [],
      tracing_datasources: options.tracing_datasources || [],
      alert_environments: options.alert_environments || [],
      k8s_clusters: options.k8s_clusters || [],
      docker_hosts: options.docker_hosts || [],
    })
  } finally {
    loading.value = false
  }
}

function openDialog(row = null) {
  resetForm(row)
  dialog.visible = true
}

async function submitForm() {
  await formRef.value?.validate()
  if (!hasAnyBinding()) {
    ElMessage.warning('请至少选择一个事件中心、看板目录、日志、链路、告警、K8s 集群或 Docker 环境来源')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      description: form.description,
      event_environments: form.event_environments,
      grafana_folder_keys: form.grafana_folder_keys,
      log_datasource_ids: form.log_datasource_ids,
      tracing_datasource_ids: form.tracing_datasource_ids,
      alert_environments: form.alert_environments,
      k8s_cluster_ids: form.k8s_cluster_ids,
      k8s_namespaces: form.k8s_namespaces,
      docker_host_ids: form.docker_host_ids,
      is_enabled: form.is_enabled,
    }
    if (dialog.editingId) {
      await updateAIOpsKnowledgeEnvironment(dialog.editingId, payload)
    } else {
      await createAIOpsKnowledgeEnvironment(payload)
    }
    ElMessage.success('知识图谱环境已保存')
    dialog.visible = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function removeEnvironment(row) {
  await ElMessageBox.confirm(`确认删除知识图谱环境「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteAIOpsKnowledgeEnvironment(row.id)
  ElMessage.success('已删除')
  await loadData()
}

onMounted(loadData)

watch(() => [...form.k8s_cluster_ids], (ids) => {
  const selected = new Set(ids.map(id => String(id)))
  Object.keys(form.k8s_namespaces || {}).forEach((clusterId) => {
    if (!selected.has(clusterId)) {
      delete form.k8s_namespaces[clusterId]
    }
  })
  ids.forEach((id) => {
    const key = String(id)
    if (!Array.isArray(form.k8s_namespaces[key])) {
      form.k8s_namespaces[key] = []
    }
  })
})
</script>

<style scoped>
.knowledge-config-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
  padding: 12px 14px;
}

.hero,
.hero-title-row,
.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hero {
  justify-content: space-between;
}

.hero-title-row h2 {
  margin: 0;
  color: #0f172a;
}

.hero-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, #0f766e, #2563eb);
}

.release-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.release-stat-card {
  min-height: 72px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: #fff;
}

.success-card {
  background: linear-gradient(180deg, #ecfdf5 0%, #fff 100%);
}

.warning-card {
  background: linear-gradient(180deg, #fff7ed 0%, #fff 100%);
}

.stat-value {
  color: #0f172a;
  font-size: 24px;
  font-weight: 800;
}

.stat-label,
.env-desc,
.muted {
  color: #64748b;
  font-size: 13px;
}

.runtime-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(14, 165, 233, 0.18);
  border-radius: 12px;
  background: linear-gradient(90deg, #eff6ff, #f0fdfa);
  color: #0f766e;
}

.namespace-config {
  margin: -4px 0 16px 128px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.78);
}

.namespace-config-title {
  margin-bottom: 8px;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
}

.namespace-row {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.namespace-row + .namespace-row {
  margin-top: 8px;
}

.namespace-cluster {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #64748b;
  font-size: 11px;
}

.namespace-cluster strong {
  color: #0f172a;
  font-size: 12px;
}

.env-name {
  color: #0f172a;
  font-weight: 700;
}

.config-actionbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.actionbar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.actionbar-desc {
  margin-top: 2px;
  color: #64748b;
  font-size: 13px;
}

.actionbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tag-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

:deep(.el-select) {
  width: 100%;
}

@media (max-width: 900px) {
  .release-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .namespace-config {
    margin-left: 0;
  }

  .namespace-row {
    grid-template-columns: 1fr;
  }

  .config-actionbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
