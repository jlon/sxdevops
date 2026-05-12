<template>
  <div class="knowledge-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Share /></el-icon></span>
          <h2>知识图谱</h2>
          <p class="subtitle inline-subtitle">按知识环境聚合可观测性和事件中心线索，形成服务视角的关系地图。</p>
        </div>
      </div>
    </section>

    <section class="panel tabs-panel">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="图谱视图" name="graph">
          <template v-if="activeTab === 'graph'">
            <section class="topology-toolbar">
              <div class="toolbar-main">
                <span class="toolbar-label">
                  <span class="toolbar-label-dot"></span>
                  图谱范围
                </span>
                <el-select v-model="filters.environment" filterable placeholder="环境（必选）" style="width: 160px" @change="handleEnvironmentChange">
                  <el-option v-for="item in graph.filters?.environments || []" :key="item" :label="envLabel(item)" :value="item" />
                </el-select>
                <el-select v-model="filters.system" clearable filterable placeholder="系统" style="width: 180px" @change="loadGraph">
                  <el-option v-for="item in graph.filters?.systems || graph.filters?.business_lines || []" :key="item" :label="item" :value="item" />
                </el-select>
                <el-select v-model="filters.service" clearable filterable placeholder="服务" style="width: 220px" @change="loadGraph">
                  <el-option v-for="item in graph.filters?.services || []" :key="item" :label="item" :value="item" />
                </el-select>
              </div>
              <div class="toolbar-actions">
                <el-button @click="resetFilters">重置筛选</el-button>
                <el-button @click="resetCanvas">重置画布</el-button>
                <el-button type="primary" :loading="loading" @click="loadGraph">
                  <el-icon><RefreshRight /></el-icon>
                  刷新图谱
                </el-button>
              </div>
            </section>

            <div class="topology-kpis">
              <div class="topology-kpi">
                <span class="kpi-label">节点数</span>
                <span class="kpi-value">{{ visibleSummary.node_count }}</span>
              </div>
              <div class="topology-kpi">
                <span class="kpi-label">关系数</span>
                <span class="kpi-value">{{ visibleSummary.edge_count }}</span>
              </div>
              <div class="topology-kpi">
                <span class="kpi-label">服务对象</span>
                <span class="kpi-value">{{ visibleSummary.service_count }}</span>
              </div>
              <div class="topology-kpi">
                <span class="kpi-label">数据源</span>
                <span class="kpi-value">{{ visibleSummary.datasource_count }}</span>
              </div>
            </div>

            <section class="graph-layout">
              <div
                ref="graphPanelRef"
                class="graph-panel"
                :class="{ dragging: graphDrag.active }"
                v-loading="loading"
                @wheel.prevent="handleGraphWheel"
                @mousedown="startGraphDrag"
                @mousemove="handleGraphDrag"
                @mouseup="stopGraphDrag"
                @mouseleave="stopGraphDrag"
              >
                <el-empty
                  v-if="!filters.environment"
                  class="graph-empty"
                  description="请先选择环境，知识图谱只展示指定环境下的可观测性与事件中心数据。"
                />
                <div class="graph-source-note">
                  <el-icon><InfoFilled /></el-icon>
                  <span>仅使用可观测性与事件中心数据生成关系</span>
                </div>
                <div class="graph-legend-card">
                  <div class="legend-title">节点类型</div>
                  <div v-for="item in nodeCategoryStats" :key="item.kind" class="legend-row">
                    <span class="legend-dot" :style="{ background: item.color }"></span>
                    <span>{{ item.label }}</span>
                    <em>{{ item.count }}</em>
                  </div>
                  <div class="legend-divider"></div>
                  <div class="legend-title">关系类型</div>
                  <div v-for="item in visibleRelationLegend" :key="item.key" class="legend-row">
                    <span class="legend-line" :class="`is-${item.key}`"></span>
                    <span>{{ item.label }}</span>
                  </div>
                </div>
                <div class="graph-board-viewport" :style="{ width: `${scaledGraphWidth}px`, height: `${scaledGraphHeight}px` }">
                  <div
                    class="graph-board"
                    :style="{
                      width: `${graphChartWidth}px`,
                      height: `${graphChartHeight}px`,
                      transform: `scale(${graphZoom})`,
                    }"
                  >
                    <svg class="graph-board-edges" :width="graphChartWidth" :height="graphChartHeight">
                      <path
                        v-for="edge in boardEdges"
                        :key="edge.id"
                        :d="edge.path"
                        class="board-edge"
                        :class="`is-${edge.relation}`"
                      />
                    </svg>
                    <section
                      v-for="lane in swimlaneLayout.lanes"
                      :key="lane.kind"
                      class="board-lane"
                      :style="laneStyle(lane)"
                    >
                      <div class="board-lane-title" :style="laneTitleStyle(lane)">
                        <span>{{ lane.label }}</span>
                      </div>
                      <div class="board-lane-body" :style="laneBodyStyle(lane)">
                        <div class="board-lane-count">{{ lane.nodes.length }} 个节点</div>
                        <button
                          v-for="node in lane.nodes"
                          :key="node.id"
                          type="button"
                          class="board-node"
                          :class="{ active: selectedNodeId === node.id }"
                          :style="nodeCardStyle(node)"
                          @click="selectNode(node)"
                        >
                          <span class="board-node-dot" :style="{ background: palette[node.kind] || '#64748b' }"></span>
                          <span v-if="nodeTypeBadge(node)" class="board-node-type">{{ nodeTypeBadge(node) }}</span>
                          <span class="board-node-label">{{ node.label }}</span>
                        </button>
                      </div>
                    </section>
                  </div>
                </div>
              </div>

              <aside class="side-panel">
                <template v-if="selectedNode">
                  <div class="sidebar-header">
                    <div>
                      <div class="side-title">{{ selectedNode.label }}</div>
                      <div class="side-subtitle">{{ selectedNode.category || nodeKindLabel(selectedNode.kind) }}</div>
                    </div>
                    <el-tag>{{ nodeKindLabel(selectedNode.kind) }}</el-tag>
                  </div>
                  <div class="detail-grid">
                    <div class="detail-item">
                      <span>环境</span>
                      <strong>{{ envLabel(selectedNode.environment) }}</strong>
                    </div>
                    <div class="detail-item">
                      <span>系统</span>
                      <strong>{{ selectedNode.system_name || selectedNode.business_line || '-' }}</strong>
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
                  <div class="sidebar-placeholder">
                    <div class="side-title">选择节点查看详情</div>
                    <div class="side-subtitle">点击画布节点查看环境、系统、服务、数据源和跳转入口；拖动画布或滚轮缩放可查看完整拓扑。</div>
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
          </template>
        </el-tab-pane>
        <el-tab-pane label="图谱配置" name="config">
          <AIOpsKnowledgeConfig v-if="activeTab === 'config'" embedded />
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { InfoFilled, RefreshRight, Share } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { getAIOpsKnowledgeGraph } from '@/api/modules/aiops'
import AIOpsKnowledgeConfig from './AIOpsKnowledgeConfig.vue'

const route = useRoute()
const router = useRouter()
const chartRef = ref(null)
const graphPanelRef = ref(null)
const loading = ref(false)
const graph = ref({ nodes: [], edges: [], summary: {}, filters: {}, relation_legend: [] })
const selectedNodeId = ref('')
const activeTab = ref(route.query.tab === 'config' ? 'config' : 'graph')
const filters = reactive({ environment: '', system: '', service: '' })
const DEFAULT_GRAPH_ZOOM = 0.84
const MIN_GRAPH_ZOOM = 0.5
const MAX_GRAPH_ZOOM = 1.35
const NODE_DOT_RADIUS = 24
const NODE_DOT_CENTER_OFFSET = 32
const hiddenNodeKinds = new Set(['environment', 'external_event'])
const graphZoom = ref(DEFAULT_GRAPH_ZOOM)
const graphDrag = reactive({ active: false, x: 0, y: 0, scrollLeft: 0, scrollTop: 0 })
let chart = null

const graphNodes = computed(() => (graph.value.nodes || []).filter(node => {
  if (hiddenNodeKinds.has(node.kind)) return false
  return !String(node.id || '').startsWith('capability:')
}))
const graphNodeById = computed(() => new Map((graph.value.nodes || []).map(node => [node.id, node])))
const graphEdges = computed(() => (graph.value.edges || []).filter(edge => {
  const source = graphNodeById.value.get(edge.source)
  const target = graphNodeById.value.get(edge.target)
  if (!source || !target) return false
  const kinds = new Set([source.kind, target.kind])
  return edge.relation === 'system_service' && kinds.has('system') && kinds.has('service')
}))
const visibleSummary = computed(() => {
  const kindCounts = graphNodes.value.reduce((acc, node) => {
    acc[node.kind] = (acc[node.kind] || 0) + 1
    return acc
  }, {})
  return {
    node_count: graphNodes.value.length,
    edge_count: graphEdges.value.length,
    service_count: kindCounts.service || 0,
    datasource_count: kindCounts.datasource || 0,
  }
})
const selectedNode = computed(() => graphNodes.value.find(item => item.id === selectedNodeId.value) || null)
const topServices = computed(() => graphNodes.value
  .filter(item => item.kind === 'service')
  .slice()
  .sort((left, right) => Number(right.metric || 0) - Number(left.metric || 0))
  .slice(0, 8))
const activeLaneDefinitions = computed(() => {
  const presentKinds = new Set(graphNodes.value.map(node => node.kind))
  return laneDefinitions.filter(lane => laneKinds(lane).some(kind => presentKinds.has(kind)))
})
const graphChartHeight = computed(() => {
  const nodes = graphNodes.value
  const maxLaneNodes = Math.max(1, ...activeLaneDefinitions.value.map(lane => {
    const kinds = new Set(laneKinds(lane))
    return nodes.filter(node => kinds.has(node.kind)).length
  }))
  return Math.max(640, 200 + maxLaneNodes * 76)
})
const graphChartWidth = computed(() => {
  const lanes = Math.max(activeLaneDefinitions.value.length, 5)
  return Math.max(980, 36 + lanes * 206 + (lanes - 1) * 18)
})
const scaledGraphWidth = computed(() => Math.ceil(graphChartWidth.value * graphZoom.value))
const scaledGraphHeight = computed(() => Math.ceil(graphChartHeight.value * graphZoom.value))
const swimlaneLayout = computed(() => buildSwimlaneLayout())
const boardNodeMap = computed(() => new Map(swimlaneLayout.value.nodes.map(node => [node.id, node])))
const boardEdges = computed(() => graphEdges.value
  .map((edge, index) => {
    const source = boardNodeMap.value.get(edge.source)
    const target = boardNodeMap.value.get(edge.target)
    if (!source || !target) return null
    const leftNode = source.x <= target.x ? source : target
    const rightNode = source.x <= target.x ? target : source
    const sourceX = leftNode.centerX + NODE_DOT_RADIUS
    const targetX = rightNode.centerX - NODE_DOT_RADIUS
    const sourceY = leftNode.centerY
    const targetY = rightNode.centerY
    const midX = (sourceX + targetX) / 2
    return {
      id: `${edge.source}-${edge.target}-${edge.relation || index}`,
      relation: edge.relation || 'default',
      path: `M ${sourceX} ${sourceY} C ${midX} ${sourceY}, ${midX} ${targetY}, ${targetX} ${targetY}`,
    }
  })
  .filter(Boolean))
const nodeCategoryStats = computed(() => {
  const counts = graphNodes.value.reduce((acc, node) => {
    acc[node.kind] = (acc[node.kind] || 0) + 1
    return acc
  }, {})
  return laneDefinitions
    .map((lane) => ({
      kind: lane.kind,
      label: lane.label,
      color: palette[lane.kind] || '#64748b',
      count: laneKinds(lane).reduce((sum, kind) => sum + (counts[kind] || 0), 0),
    }))
    .filter(item => item.count > 0)
})
const visibleRelationLegend = computed(() => {
  const visibleRelationKeys = new Set(boardEdges.value.map(edge => edge.relation))
  return (graph.value.relation_legend || []).filter(item => visibleRelationKeys.has(item.key))
})

const categories = [
  { name: '可观测性' },
  { name: '系统' },
  { name: '服务' },
  { name: '事件源' },
]

const categoryIndex = {
  logs: 0,
  tracing: 0,
  dashboard: 0,
  alert: 0,
  posture: 0,
  internal_event: 0,
  system: 1,
  service: 2,
  datasource: 0,
  event_source: 3,
}

const palette = {
  observability: '#0ea5e9',
  logs: '#0ea5e9',
  tracing: '#8b5cf6',
  dashboard: '#10b981',
  alert: '#ef4444',
  posture: '#14b8a6',
  internal_event: '#64748b',
  system: '#334155',
  service: '#0f766e',
  datasource: '#7c3aed',
  event_source: '#db2777',
}

const LANE_TINTS = [
  { fill: 'rgba(59, 130, 246, 0.13)', border: 'rgba(59, 130, 246, 0.28)' },
  { fill: 'rgba(16, 185, 129, 0.13)', border: 'rgba(16, 185, 129, 0.28)' },
  { fill: 'rgba(245, 158, 11, 0.13)', border: 'rgba(245, 158, 11, 0.28)' },
  { fill: 'rgba(236, 72, 153, 0.11)', border: 'rgba(236, 72, 153, 0.26)' },
  { fill: 'rgba(14, 165, 233, 0.13)', border: 'rgba(14, 165, 233, 0.28)' },
]

const laneDefinitions = [
  { kind: 'system', label: '系统' },
  { kind: 'service', label: '服务' },
  { kind: 'observability', label: '可观测性', kinds: ['datasource', 'dashboard', 'logs', 'tracing'] },
  { kind: 'alert', label: '告警' },
  { kind: 'posture', label: '系统态势' },
  { kind: 'event_source', label: '事件源' },
  { kind: 'internal_event', label: '内部事件' },
]

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
    logs: '日志',
    tracing: '链路',
    dashboards: '看板',
    alerts: '告警',
    posture: '系统态势',
    internal_events: '内部事件',
    external_events: '外部事件',
  }[value] || value
}

function nodeKindLabel(value) {
  return {
    observability: '可观测性',
    logs: '日志',
    tracing: '链路',
    dashboard: '看板',
    alert: '告警',
    posture: '系统态势',
    internal_event: '内部事件',
    external_event: '外部事件',
    environment: '环境',
    system: '系统',
    service: '服务',
    datasource: '数据源',
    event_source: '事件源',
  }[value] || value || '-'
}

function laneKinds(lane) {
  return lane.kinds || [lane.kind]
}

function nodeLaneKind(node) {
  const lane = laneDefinitions.find(item => laneKinds(item).includes(node.kind))
  return lane?.kind || node.kind
}

function nodeTypeBadge(node) {
  if (!['datasource', 'dashboard', 'logs', 'tracing'].includes(node.kind)) return ''
  const category = String(node.category || '')
  if (node.kind === 'dashboard') return '看板'
  if (node.kind === 'logs' || category.includes('日志')) return '日志'
  if (node.kind === 'tracing' || category.includes('链路')) return '链路'
  return '数据源'
}

function nodeSize(node) {
  const base = node.kind === 'system' ? 50 : node.kind === 'service' ? 42 : node.kind === 'environment' ? 44 : 32
  return Math.min(base + Math.sqrt(Number(node.metric || 0)) * 3, 68)
}

function hexToRgba(hex, alpha = 1) {
  const normalized = String(hex || '#64748b').replace('#', '')
  const value = normalized.length === 3
    ? normalized.split('').map(char => char + char).join('')
    : normalized.padEnd(6, '0').slice(0, 6)
  const number = Number.parseInt(value, 16)
  const red = (number >> 16) & 255
  const green = (number >> 8) & 255
  const blue = number & 255
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`
}

function getLaneTint(name = '') {
  let hash = 0
  for (let index = 0; index < name.length; index += 1) {
    hash = (hash * 31 + name.charCodeAt(index)) >>> 0
  }
  return LANE_TINTS[hash % LANE_TINTS.length]
}

function buildSwimlaneLayout() {
  const nodes = graphNodes.value
  const lanes = activeLaneDefinitions.value
  const headerY = 22
  const bodyY = 76
  const leftPadding = 18
  const laneGap = 18
  const laneWidth = 206
  const nodeStep = 76
  const laneNodes = []
  let cursorX = leftPadding

  const positionedLanes = lanes.map((lane, laneIndex) => {
    const color = palette[lane.kind] || '#64748b'
    const tint = getLaneTint(lane.label)
    const kinds = new Set(laneKinds(lane))
    const laneItems = nodes
      .filter(node => kinds.has(node.kind))
      .map((node, index) => {
        const centerX = cursorX + laneWidth / 2
        const cardY = 72 + index * nodeStep
        const positioned = {
          ...node,
          x: centerX,
          centerX,
          centerY: bodyY + cardY + NODE_DOT_CENTER_OFFSET,
          cardY,
          color: palette[node.kind] || color,
        }
        laneNodes.push(positioned)
        return positioned
      })
    const positionedLane = {
      ...lane,
      x: cursorX,
      y: bodyY,
      titleY: headerY,
      width: laneWidth,
      height: graphChartHeight.value - bodyY - 28,
      color,
      tint,
      index: laneIndex,
      nodes: laneItems,
    }
    cursorX += laneWidth + laneGap
    return positionedLane
  })

  return { lanes: positionedLanes, nodes: laneNodes }
}

function laneStyle(lane) {
  return {
    left: `${lane.x}px`,
    top: '0px',
    width: `${lane.width}px`,
    height: `${graphChartHeight.value}px`,
    '--lane-color': lane.color,
  }
}

function laneTitleStyle(lane) {
  return {
    top: `${lane.titleY}px`,
    borderColor: 'rgba(59, 130, 246, 0.28)',
    boxShadow: 'none',
  }
}

function laneBodyStyle(lane) {
  const topColor = lane.index % 2 === 0 ? 'rgba(255, 255, 255, 0.90)' : 'rgba(248, 250, 252, 0.92)'
  return {
    top: `${lane.y}px`,
    height: `${lane.height}px`,
    background: `linear-gradient(180deg, ${topColor} 0%, ${lane.tint.fill} 100%)`,
    borderColor: lane.tint.border,
    boxShadow: 'none',
  }
}

function nodeCardStyle(node) {
  return {
    top: `${node.cardY}px`,
    '--node-color': node.color,
  }
}

function buildLaneLayout() {
  const nodes = graphNodes.value
  const lanes = activeLaneDefinitions.value
  const width = Math.max(graphChartWidth.value, chartRef.value?.clientWidth || 980)
  const height = graphChartHeight.value
  const leftPadding = 18
  const headerY = 18
  const headerHeight = 44
  const bodyY = 86
  const laneGap = 16
  const laneWidth = 206
  const nodeStep = 82
  const laneMap = new Map()
  let cursorX = leftPadding

  lanes.forEach((lane, index) => {
    const kinds = new Set(laneKinds(lane))
    const laneNodes = nodes.filter(node => kinds.has(node.kind))
    laneMap.set(lane.kind, { ...lane, index, x: cursorX, width: laneWidth, nodes: laneNodes })
    cursorX += laneWidth + laneGap
  })

  const positionedNodes = nodes.map((node) => {
    const lane = laneMap.get(nodeLaneKind(node)) || laneMap.values().next().value || { x: leftPadding, width: laneWidth, nodes: [] }
    const index = Math.max(lane.nodes.findIndex(item => item.id === node.id), 0)
    const x = lane.x + lane.width / 2
    const y = bodyY + 86 + index * nodeStep
    return { ...node, x, y }
  })

  const laneGraphics = lanes.map((lane) => {
    const item = laneMap.get(lane.kind)
    const color = palette[lane.kind] || '#64748b'
    return {
      type: 'group',
      silent: true,
      z: -10,
      children: [
        {
          type: 'rect',
          shape: { x: item.x, y: headerY, width: item.width, height: headerHeight, r: 22 },
          style: {
            fill: 'rgba(255,255,255,0.94)',
            stroke: hexToRgba(color, 0.32),
            lineWidth: 1.5,
            shadowBlur: 16,
            shadowColor: 'rgba(15,23,42,0.08)',
          },
        },
        {
          type: 'text',
          style: {
            x: item.x + item.width / 2,
            y: headerY + 28,
            text: lane.label,
            fill: '#0f172a',
            font: '800 17px sans-serif',
            align: 'center',
          },
        },
        {
          type: 'rect',
          shape: { x: item.x, y: bodyY, width: item.width, height: height - bodyY - 28, r: 20 },
          style: {
            fill: hexToRgba(color, 0.12),
            stroke: hexToRgba(color, 0.22),
            lineWidth: 1.2,
            shadowBlur: 18,
            shadowColor: hexToRgba(color, 0.12),
          },
        },
        {
          type: 'text',
          style: {
            x: item.x + item.width / 2,
            y: bodyY + (height - bodyY - 28) / 2,
            text: lane.label,
            fill: hexToRgba(color, 0.08),
            font: '900 28px sans-serif',
            align: 'center',
          },
        },
        {
          type: 'rect',
          shape: { x: item.x + 14, y: bodyY + 12, width: 72, height: 24, r: 12 },
          style: {
            fill: 'rgba(255,255,255,0.78)',
            stroke: 'rgba(255,255,255,0.68)',
          },
        },
        {
          type: 'text',
          style: {
            x: item.x + 28,
            y: bodyY + 29,
            text: `${item.nodes.length} 个节点`,
            fill: '#475569',
            font: '700 12px sans-serif',
          },
        },
      ],
    }
  })

  return { nodes: positionedNodes, graphics: laneGraphics }
}

function buildOption() {
  const { nodes, graphics } = buildLaneLayout()
  const data = nodes.map(node => ({
    id: node.id,
    name: node.label,
    value: node.metric || 0,
    category: categoryIndex[node.kind] ?? 0,
    x: node.x,
    y: node.y,
    fixed: true,
    symbolSize: nodeSize(node),
    itemStyle: {
      color: palette[node.kind] || '#64748b',
      borderColor: '#ffffff',
      borderWidth: 3,
      shadowBlur: 16,
      shadowColor: hexToRgba(palette[node.kind] || '#64748b', 0.24),
    },
    label: {
      show: true,
      formatter: '{b}',
      position: 'bottom',
      distance: 8,
      color: '#0f172a',
      backgroundColor: 'rgba(255,255,255,0.94)',
      borderColor: 'rgba(148,163,184,0.18)',
      borderWidth: 1,
      borderRadius: 10,
      padding: [5, 10],
      shadowBlur: 8,
      shadowColor: 'rgba(15,23,42,0.08)',
    },
    emphasis: {
      label: { show: true },
      itemStyle: {
        shadowBlur: 18,
        shadowColor: 'rgba(15, 23, 42, 0.22)',
      },
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
      color: edge.relation === 'observability_link' ? '#0ea5e9' : '#94a3b8',
    },
    edge,
  }))

  return {
    backgroundColor: 'transparent',
    graphic: graphics,
    tooltip: {
      trigger: 'item',
      borderWidth: 0,
      backgroundColor: 'rgba(255, 255, 255, 0.98)',
      textStyle: { color: '#0f172a' },
      extraCssText: 'box-shadow:0 18px 30px rgba(15,23,42,.12);border-radius:12px;padding:10px 12px;',
      formatter: params => {
        if (params.dataType === 'edge') return `${params.data.edge.label}<br/>${params.data.source} -> ${params.data.target}`
        const node = params.data.node || {}
        return `${node.label}<br/>${node.category || node.kind}<br/>${node.description || ''}`
      },
    },
    series: [{
      type: 'graph',
      layout: 'none',
      roam: false,
      draggable: false,
      categories,
      data,
      links,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 8,
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 4 },
      },
      label: {
        color: '#0f172a',
        fontWeight: 600,
        fontSize: 12,
      },
      labelLayout: {
        hideOverlap: false,
      },
    }],
  }
}

function renderGraph() {
  if (activeTab.value !== 'graph' || !chartRef.value) return
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
  if (activeTab.value !== 'graph') return
  loading.value = true
  try {
    const params = {}
    if (filters.environment) params.environment = filters.environment
    if (filters.system) params.system = filters.system
    if (filters.service) params.service = filters.service
    graph.value = await getAIOpsKnowledgeGraph(params)
    if (!filters.environment && graph.value.filters?.environments?.length) {
      filters.environment = graph.value.filters.environments[0]
      await loadGraph()
      return
    }
    if (selectedNodeId.value && !graphNodes.value.some(item => item.id === selectedNodeId.value)) {
      selectedNodeId.value = ''
    }
    await nextTick()
    renderGraph()
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.system = ''
  filters.service = ''
  selectedNodeId.value = ''
  loadGraph()
}

function resetCanvas() {
  selectedNodeId.value = ''
  graphZoom.value = DEFAULT_GRAPH_ZOOM
  graphPanelRef.value?.scrollTo({ left: 0, top: 0, behavior: 'smooth' })
}

function setGraphZoom(nextZoom, event) {
  const panel = graphPanelRef.value
  const currentZoom = graphZoom.value
  const zoom = Math.min(MAX_GRAPH_ZOOM, Math.max(MIN_GRAPH_ZOOM, Number(nextZoom.toFixed(2))))
  if (zoom === currentZoom) return

  if (!event || !panel) {
    graphZoom.value = zoom
    return
  }

  const rect = panel.getBoundingClientRect()
  const cursorX = event.clientX - rect.left
  const cursorY = event.clientY - rect.top
  const logicalX = (panel.scrollLeft + cursorX) / currentZoom
  const logicalY = (panel.scrollTop + cursorY) / currentZoom
  graphZoom.value = zoom
  nextTick(() => {
    panel.scrollLeft = logicalX * zoom - cursorX
    panel.scrollTop = logicalY * zoom - cursorY
  })
}

function handleGraphWheel(event) {
  const delta = event.deltaY > 0 ? -0.08 : 0.08
  setGraphZoom(graphZoom.value + delta, event)
}

function startGraphDrag(event) {
  if (event.button !== 0) return
  if (event.target?.closest?.('button, a, input, textarea, .graph-legend-card, .graph-source-note')) return
  const panel = graphPanelRef.value
  if (!panel) return
  graphDrag.active = true
  graphDrag.x = event.clientX
  graphDrag.y = event.clientY
  graphDrag.scrollLeft = panel.scrollLeft
  graphDrag.scrollTop = panel.scrollTop
  event.preventDefault()
}

function handleGraphDrag(event) {
  if (!graphDrag.active) return
  const panel = graphPanelRef.value
  if (!panel) return
  panel.scrollLeft = graphDrag.scrollLeft - (event.clientX - graphDrag.x)
  panel.scrollTop = graphDrag.scrollTop - (event.clientY - graphDrag.y)
}

function stopGraphDrag() {
  graphDrag.active = false
}

function handleEnvironmentChange() {
  filters.system = ''
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

function disposeGraph() {
  chart?.dispose()
  chart = null
}

function handleTabChange(tabName) {
  const nextQuery = { ...route.query }
  if (tabName === 'config') {
    nextQuery.tab = 'config'
  } else {
    delete nextQuery.tab
  }
  router.replace({ path: '/aiops/knowledge', query: nextQuery })
  if (tabName === 'config') {
    disposeGraph()
  } else if (tabName === 'graph') {
    nextTick(() => {
      if (graph.value.nodes.length || filters.environment) {
        renderGraph()
      } else {
        loadGraph()
      }
    })
  }
}

watch(() => graph.value.nodes.length, () => nextTick(renderGraph))

watch(
  () => route.query.tab,
  (value) => {
    const nextTab = value === 'config' ? 'config' : 'graph'
    if (activeTab.value !== nextTab) {
      activeTab.value = nextTab
      if (nextTab === 'config') {
        disposeGraph()
      } else {
        nextTick(renderGraph)
      }
    }
  },
)

onMounted(() => {
  window.addEventListener('resize', resizeGraph)
  if (activeTab.value === 'graph') loadGraph()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeGraph)
  disposeGraph()
})
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #0f172a;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
  padding: 12px 14px;
}

.tabs-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tabs-panel :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-title-row,
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

.subtitle {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.inline-subtitle {
  padding-left: 2px;
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

.topology-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.toolbar-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(241, 245, 249, 0.96) 100%);
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}

.toolbar-label-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(180deg, #0ea5e9 0%, #14b8a6 100%);
  box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12);
}

.topology-kpis {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.topology-kpi {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}

.kpi-label {
  color: #64748b;
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.kpi-value {
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}

.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 14px;
  min-height: 640px;
}

.graph-panel,
.side-panel {
  position: relative;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 22px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  overflow: hidden;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.10);
}

.graph-panel {
  min-height: 640px;
  overflow: auto;
  cursor: grab;
  background:
    linear-gradient(rgba(148, 163, 184, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.07) 1px, transparent 1px),
    linear-gradient(rgba(59, 130, 246, 0.10) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59, 130, 246, 0.10) 1px, transparent 1px),
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.08), transparent 28%),
    radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.08), transparent 30%),
    linear-gradient(180deg, #f8fbff 0%, #f1f7fd 100%);
  background-size: 22px 22px, 22px 22px, 88px 88px, 88px 88px, auto, auto, auto;
  scrollbar-width: thin;
}

.graph-panel.dragging {
  cursor: grabbing;
  user-select: none;
}

.graph-panel::before {
  display: none;
}

.graph-panel :deep(.el-loading-mask) {
  border-radius: 20px;
  background: rgba(248, 250, 252, 0.72);
}

.graph-chart {
  min-width: 100%;
  height: 640px;
}

.graph-board-viewport {
  position: relative;
  min-width: 100%;
  overflow: hidden;
}

.graph-board {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
}

.graph-board-edges {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

.board-edge {
  fill: none;
  stroke: rgba(139, 92, 246, 0.34);
  stroke-width: 1.5;
  stroke-linecap: round;
}

.board-edge.is-system_service {
  stroke: rgba(139, 92, 246, 0.36);
}

.board-edge.is-observability_link {
  stroke: rgba(14, 165, 233, 0.86);
  stroke-dasharray: none;
  stroke-width: 2.8;
}

.board-edge.is-event_context {
  stroke: rgba(249, 115, 22, 0.68);
  stroke-dasharray: 11 8;
}

.board-lane {
  position: absolute;
  z-index: 2;
}

.board-lane-title {
  position: absolute;
  left: 0;
  right: 0;
  z-index: 7;
  height: 34px;
  border: 1px solid rgba(59, 130, 246, 0.28);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.98);
  color: #0f172a;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 600;
}

.board-lane-title::before {
  display: none;
}

.board-lane-body {
  position: absolute;
  left: 0;
  right: 0;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  overflow: hidden;
}

.board-lane-body::after {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.28) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.28) 1px, transparent 1px);
  background-size: 28px 28px;
  pointer-events: none;
}

.board-lane-body::before {
  display: none;
}

.board-lane-count {
  position: absolute;
  top: 14px;
  left: 16px;
  z-index: 5;
  padding: 3px 9px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.90);
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.board-node {
  position: absolute;
  left: 50%;
  z-index: 6;
  width: 156px;
  min-height: 78px;
  padding: 8px 10px 9px;
  border: 0;
  background: transparent;
  color: #0f172a;
  transform: translateX(-50%);
  cursor: pointer;
  font: inherit;
  transition: filter 0.16s ease, transform 0.16s ease;
}

.board-node-dot {
  width: 48px;
  height: 48px;
  margin: 0 auto 10px;
  border: 2px solid rgba(255, 255, 255, 0.98);
  border-radius: 50%;
  display: block;
  position: relative;
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.12);
}

.board-node-dot::before {
  content: "";
  position: absolute;
  inset: -22px;
  z-index: -1;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--node-color) 18%, transparent) 0%,
    color-mix(in srgb, var(--node-color) 10%, transparent) 36%,
    transparent 70%
  );
  pointer-events: none;
}

.board-node-type {
  position: absolute;
  top: 46px;
  left: 50%;
  z-index: 2;
  padding: 1px 6px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
  color: #475569;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.35;
  transform: translateX(-50%);
  pointer-events: none;
}

.board-node-label {
  max-width: 148px;
  margin: 0 auto;
  padding: 5px 10px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.98);
  display: block;
  overflow: hidden;
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
  box-shadow: none;
}

.board-node:hover,
.board-node.active {
  z-index: 12;
  filter: saturate(1.08);
}

.board-node:hover .board-node-dot,
.board-node.active .board-node-dot {
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.98), 0 0 0 5px color-mix(in srgb, var(--node-color) 18%, transparent);
}

.board-node:hover .board-node-dot::before,
.board-node.active .board-node-dot::before {
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--node-color) 24%, transparent) 0%,
    color-mix(in srgb, var(--node-color) 13%, transparent) 38%,
    transparent 72%
  );
}

.board-node.active .board-node-label {
  border-color: color-mix(in srgb, var(--node-color) 38%, rgba(148, 163, 184, 0.24));
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.15);
}

.graph-empty {
  position: absolute;
  inset: 0;
  z-index: 8;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(248, 250, 252, 0.76);
}

.graph-source-note {
  position: absolute;
  bottom: 14px;
  left: 14px;
  z-index: 9;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
  color: #0f172a;
  font-size: 12px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.10);
}

.graph-legend-card {
  position: absolute;
  bottom: 14px;
  right: 14px;
  z-index: 9;
  min-width: 166px;
  max-width: 210px;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.97);
  color: #334155;
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
}

.side-panel {
  min-width: 0;
  padding: 18px;
  color: #0f172a;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.sidebar-placeholder {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.side-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
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
  gap: 10px;
  margin-top: 12px;
}

.detail-item,
.capability-row,
.service-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.95);
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

.legend-title {
  margin-bottom: 8px;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
}

.legend-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: #475569;
  font-size: 12px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.legend-line {
  display: inline-block;
  width: 22px;
  border-top: 2px solid #94a3b8;
}

.legend-line.is-system_service {
  border-color: #8b5cf6;
}

.legend-line.is-observability_link {
  border-color: #0ea5e9;
}

.legend-line.is-event_context {
  border-color: #f97316;
  border-top-style: dashed;
}

.legend-divider {
  height: 1px;
  margin: 10px 0;
  background: rgba(148, 163, 184, 0.2);
}

.legend-row em {
  color: #64748b;
  font-style: normal;
}

.service-row {
  width: 100%;
  margin-bottom: 8px;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: border-color 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
}

.service-row:hover {
  transform: translateY(-1px);
  border-color: rgba(14, 165, 233, 0.28);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
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
  .graph-layout {
    grid-template-columns: 1fr;
  }

  .graph-chart {
    height: 520px;
  }

  .graph-panel {
    min-height: 520px;
  }
}

@media (max-width: 720px) {
  .graph-legend-card,
  .graph-source-note {
    position: static;
    margin: 10px 10px 0;
  }

  .graph-chart {
    height: 480px;
  }
}
</style>
