<template>
  <div class="knowledge-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Share /></el-icon></span>
          <h2>知识图谱</h2>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadGraph">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <div class="release-stats">
      <div class="release-stat-card">
        <div class="stat-value">{{ graph.summary?.node_count || 0 }}</div>
        <div class="stat-label">图谱节点</div>
      </div>
      <div class="release-stat-card success-card">
        <div class="stat-value">{{ graph.summary?.edge_count || 0 }}</div>
        <div class="stat-label">关联关系</div>
      </div>
      <div class="release-stat-card warning-card">
        <div class="stat-value">{{ graph.summary?.service_count || 0 }}</div>
        <div class="stat-label">服务对象</div>
      </div>
      <div class="release-stat-card">
        <div class="stat-value">{{ graph.summary?.datasource_count || 0 }}</div>
        <div class="stat-label">数据源</div>
      </div>
    </div>

    <div class="runtime-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>关联关系从现有工单、日志、链路、看板、告警、系统态势、事件墙与可观测性跳转配置自动推导。</span>
    </div>

    <section class="panel toolbar-panel">
      <div class="toolbar-main">
        <el-select v-model="filters.business_line" clearable filterable placeholder="业务线" style="width: 180px" @change="loadGraph">
          <el-option v-for="item in graph.filters?.business_lines || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.environment" clearable filterable placeholder="环境" style="width: 150px" @change="loadGraph">
          <el-option v-for="item in graph.filters?.environments || []" :key="item" :label="envLabel(item)" :value="item" />
        </el-select>
        <el-select v-model="filters.service" clearable filterable placeholder="服务" style="width: 220px" @change="loadGraph">
          <el-option v-for="item in graph.filters?.services || []" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
      <div class="toolbar-actions">
        <el-button size="small" @click="resetFilters">重置筛选</el-button>
      </div>
    </section>

    <section class="graph-layout">
      <div class="graph-panel panel" v-loading="loading">
        <div ref="chartRef" class="graph-chart" />
      </div>

      <aside class="side-panel panel">
        <template v-if="selectedNode">
          <div class="side-title">{{ selectedNode.label }}</div>
          <div class="side-subtitle">{{ selectedNode.category || selectedNode.kind }}</div>
          <div class="detail-grid">
            <div class="detail-item">
              <span>业务线</span>
              <strong>{{ selectedNode.business_line || '-' }}</strong>
            </div>
            <div class="detail-item">
              <span>环境</span>
              <strong>{{ envLabel(selectedNode.environment) }}</strong>
            </div>
            <div class="detail-item">
              <span>服务</span>
              <strong>{{ selectedNode.service || '-' }}</strong>
            </div>
            <div class="detail-item">
              <span>权重</span>
              <strong>{{ selectedNode.metric || 0 }}</strong>
            </div>
          </div>
          <p v-if="selectedNode.description" class="node-desc">{{ selectedNode.description }}</p>
          <div v-if="selectedNode.capabilities?.length" class="capability-list">
            <div class="section-title">关联能力</div>
            <div v-for="item in selectedNode.capabilities" :key="item.name" class="capability-row">
              <span>{{ capabilityLabel(item.name) }}</span>
              <strong>{{ item.count }}</strong>
            </div>
          </div>
          <el-button v-if="selectedNode.route" type="primary" plain @click="openNode(selectedNode)">打开关联页面</el-button>
        </template>

        <template v-else>
          <div class="side-title">关联说明</div>
          <div class="side-subtitle">点击节点查看来源和跳转入口</div>
          <div class="legend-list">
            <div v-for="item in graph.relation_legend || []" :key="item.key" class="legend-row">
              <span class="legend-dot"></span>
              <span>{{ item.label }}</span>
            </div>
          </div>
          <div class="section-title">高关联服务</div>
          <button
            v-for="node in topServices"
            :key="node.id"
            type="button"
            class="service-row"
            @click="selectNode(node)"
          >
            <span>{{ node.label }}</span>
            <em>{{ node.metric }}</em>
          </button>
        </template>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { InfoFilled, RefreshRight, Share } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getAIOpsKnowledgeGraph } from '@/api/modules/aiops'

const router = useRouter()
const chartRef = ref(null)
const loading = ref(false)
const graph = ref({ nodes: [], edges: [], summary: {}, filters: {}, relation_legend: [] })
const selectedNodeId = ref('')
const filters = reactive({ business_line: '', environment: '', service: '' })
let chart = null

const selectedNode = computed(() => graph.value.nodes.find(item => item.id === selectedNodeId.value) || null)
const topServices = computed(() => (graph.value.nodes || [])
  .filter(item => item.kind === 'service')
  .slice()
  .sort((left, right) => Number(right.metric || 0) - Number(left.metric || 0))
  .slice(0, 8))

const categories = [
  { name: '平台能力' },
  { name: '业务线' },
  { name: '环境' },
  { name: '服务' },
  { name: '数据源' },
  { name: '看板' },
  { name: '事件源' },
]

const categoryIndex = {
  workorder: 0,
  logs: 0,
  tracing: 0,
  dashboard: 5,
  alert: 0,
  posture: 0,
  internal_event: 0,
  external_event: 0,
  business: 1,
  environment: 2,
  service: 3,
  datasource: 4,
  event_source: 6,
}

const palette = {
  workorder: '#f59e0b',
  logs: '#0ea5e9',
  tracing: '#8b5cf6',
  dashboard: '#10b981',
  alert: '#ef4444',
  posture: '#14b8a6',
  internal_event: '#64748b',
  external_event: '#f97316',
  business: '#334155',
  environment: '#2563eb',
  service: '#0f766e',
  datasource: '#7c3aed',
  event_source: '#db2777',
}

function envLabel(value) {
  return {
    prod: '生产',
    test: '测试',
    dev: '开发',
    staging: '预发',
    production: '生产',
    testing: '测试',
    development: '开发',
  }[value] || value || '-'
}

function capabilityLabel(value) {
  return {
    workorders: '工单',
    logs: '日志',
    tracing: '链路',
    dashboards: '看板',
    alerts: '告警',
    posture: '系统态势',
    internal_events: '内部事件',
    external_events: '外部事件',
  }[value] || value
}

function nodeSize(node) {
  const base = node.kind === 'service' ? 34 : node.kind === 'business' ? 42 : node.kind === 'environment' ? 34 : 28
  return Math.min(base + Math.sqrt(Number(node.metric || 0)) * 3, 62)
}

function buildOption() {
  const data = (graph.value.nodes || []).map(node => ({
    id: node.id,
    name: node.label,
    value: node.metric || 0,
    category: categoryIndex[node.kind] ?? 0,
    symbolSize: nodeSize(node),
    itemStyle: { color: palette[node.kind] || '#64748b' },
    label: {
      show: ['business', 'environment', 'service'].includes(node.kind) || Number(node.metric || 0) >= 4,
      formatter: '{b}',
    },
    node,
  }))
  const links = (graph.value.edges || []).map(edge => ({
    source: edge.source,
    target: edge.target,
    value: edge.weight || 1,
    label: { show: false, formatter: edge.label },
    lineStyle: {
      width: Math.min(1 + Number(edge.weight || 1) * 0.4, 4),
      opacity: edge.relation === 'observability_link' ? 0.78 : 0.38,
      curveness: edge.relation === 'observability_link' ? 0.18 : 0.08,
    },
    edge,
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        if (params.dataType === 'edge') return `${params.data.edge.label}<br/>${params.data.source} -> ${params.data.target}`
        const node = params.data.node || {}
        return `${node.label}<br/>${node.category || node.kind}<br/>${node.description || ''}`
      },
    },
    legend: [{ top: 8, left: 'center', data: categories.map(item => item.name) }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      categories,
      data,
      links,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 8,
      force: {
        repulsion: 220,
        edgeLength: [80, 160],
        gravity: 0.08,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 4 },
      },
      label: {
        color: '#0f172a',
        fontWeight: 600,
      },
    }],
  }
}

function renderGraph() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
    chart.on('click', params => {
      if (params.dataType === 'node') {
        selectNode(params.data.node)
      }
    })
  }
  chart.setOption(buildOption(), true)
  chart.resize()
}

async function loadGraph() {
  loading.value = true
  try {
    const params = {}
    if (filters.business_line) params.business_line = filters.business_line
    if (filters.environment) params.environment = filters.environment
    if (filters.service) params.service = filters.service
    graph.value = await getAIOpsKnowledgeGraph(params)
    if (selectedNodeId.value && !graph.value.nodes.some(item => item.id === selectedNodeId.value)) {
      selectedNodeId.value = ''
    }
    await nextTick()
    renderGraph()
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.business_line = ''
  filters.environment = ''
  filters.service = ''
  selectedNodeId.value = ''
  loadGraph()
}

function selectNode(node) {
  selectedNodeId.value = node?.id || ''
}

function openNode(node) {
  if (!node?.route) return
  router.push(node.route)
}

function resizeGraph() {
  chart?.resize()
}

watch(() => graph.value.nodes.length, () => nextTick(renderGraph))

onMounted(() => {
  window.addEventListener('resize', resizeGraph)
  loadGraph()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeGraph)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.knowledge-page {
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

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-title-row,
.hero-actions,
.toolbar-main,
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
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

.stat-value {
  color: #0f172a;
  font-size: 24px;
  font-weight: 800;
}

.stat-label {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
}

.success-card {
  background: linear-gradient(180deg, #ecfdf5 0%, #fff 100%);
}

.warning-card {
  background: linear-gradient(180deg, #fff7ed 0%, #fff 100%);
}

.runtime-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid rgba(14, 165, 233, 0.18);
  border-radius: 12px;
  background: #f0f9ff;
  color: #0369a1;
  font-size: 13px;
}

.toolbar-panel {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 12px;
  min-height: 640px;
}

.graph-panel {
  min-height: 640px;
  padding: 0;
  overflow: hidden;
}

.graph-chart {
  width: 100%;
  height: 640px;
}

.side-panel {
  min-width: 0;
}

.side-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.side-subtitle,
.node-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.detail-item,
.capability-row,
.service-row,
.legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 10px;
  background: #fff;
}

.detail-item {
  flex-direction: column;
  align-items: flex-start;
}

.detail-item span,
.section-title {
  color: #64748b;
  font-size: 12px;
}

.detail-item strong,
.capability-row strong {
  color: #0f172a;
  font-size: 13px;
}

.section-title {
  margin: 14px 0 8px;
  font-weight: 700;
}

.capability-list,
.legend-list {
  margin-bottom: 12px;
}

.legend-row {
  justify-content: flex-start;
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ea5e9;
}

.service-row {
  width: 100%;
  margin-bottom: 8px;
  color: #0f172a;
  cursor: pointer;
}

.service-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.service-row em {
  color: #64748b;
  font-style: normal;
}

@media (max-width: 1100px) {
  .release-stats,
  .graph-layout {
    grid-template-columns: 1fr;
  }

  .graph-chart {
    height: 520px;
  }
}
</style>
