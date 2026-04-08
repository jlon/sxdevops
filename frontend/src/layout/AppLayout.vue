<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <el-icon><Cpu /></el-icon>
        </div>
        <span class="logo-text">SxDevOps</span>
      </div>

      <el-menu
        :default-active="activeMenuPath"
        class="sidebar-nav el-menu-vertical"
        :collapse="appStore.sidebarCollapsed"
        router
        :collapse-transition="false"
      >
        <template v-for="item in visibleMenuItems" :key="item.title">
          <el-sub-menu v-if="item.children?.length" :index="item.menuKey || item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item
              v-for="child in item.children"
              :key="child.menuKey || child.path"
              :index="child.menuKey || child.path"
              :route="child.route || child.path"
            >
              <template #title>
                <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
                <span>{{ child.title }}</span>
              </template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item v-else :index="item.menuKey || item.path" :route="item.route || item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>
              <span>{{ item.title }}</span>
            </template>
          </el-menu-item>
        </template>
      </el-menu>
    </aside>

    <div class="main-area">
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="appStore.toggleSidebar">
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <span class="breadcrumb">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-badge :value="3" :max="99">
            <el-icon :size="20" style="cursor: pointer; color: var(--text-secondary)"><Bell /></el-icon>
          </el-badge>
          <el-dropdown @command="handleUserCommand">
            <div style="display: flex; align-items: center; gap: 8px; cursor: pointer">
              <el-avatar :size="32" style="background: var(--primary)">
                <el-icon><User /></el-icon>
              </el-avatar>
              <div class="user-meta">
                <span class="user-name">{{ authStore.displayName || '未登录' }}</span>
                <span class="user-role">{{ currentRoleLabel }}</span>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="refresh">刷新权限</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <AIOpsChatWidget />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import AIOpsChatWidget from '@/components/aiops/AIOpsChatWidget.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

const menuItems = [
  { path: '/dashboard', title: '仪表盘', icon: 'Odometer', permission: 'ops.dashboard.view' },
  {
    title: 'CMDB',
    icon: 'Files',
    children: [
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=items',
        route: { path: '/cmdb', query: { tab: 'items' } },
        title: '配置项管理',
        icon: 'Grid',
        permission: 'cmdb.ci.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=topology',
        route: { path: '/cmdb', query: { tab: 'topology' } },
        title: '资源地图',
        icon: 'Share',
        permission: 'cmdb.topology.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=cost',
        route: { path: '/cmdb', query: { tab: 'cost' } },
        title: '成本分析',
        icon: 'TrendCharts',
        permission: 'cmdb.cost.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=optimize',
        route: { path: '/cmdb', query: { tab: 'optimize' } },
        title: '资源优化',
        icon: 'Lightning',
        permission: 'cmdb.cost.view',
      },
    ],
  },
  {
    title: '主机中心',
    icon: 'Monitor',
    children: [
      {
        path: '/hosts/assets',
        title: '主机资产',
        icon: 'Monitor',
        anyPermissions: ['ops.host.view', 'ops.host.manage', 'ops.host.terminal'],
      },
      {
        path: '/hosts/tasks',
        title: '任务中心',
        icon: 'Operation',
        permission: 'ops.host.execute',
      },
      {
        path: '/hosts/schedules',
        title: '定时任务',
        icon: 'Timer',
        anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'],
      },
      {
        path: '/hosts/requests',
        title: '主机申请',
        icon: 'Ticket',
        anyPermissions: ['cmdb.request.submit', 'cmdb.request.approve'],
      },
    ],
  },
  {
    title: '多云管理',
    icon: 'MostlyCloudy',
    children: [
      { path: '/multicloud', title: '多云环境', icon: 'MostlyCloudy', permission: 'ops.multicloud.view' },
      { path: '/terraform', title: 'IaC 编排', icon: 'SetUp', permission: 'ops.iac.view' },
    ],
  },
  {
    path: '/deployments',
    title: '应用发布',
    icon: 'Promotion',
    anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
  },
  {
    title: '容器管理',
    icon: 'Box',
    children: [
      { path: '/containers/k8s', title: 'K8s 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      { path: '/containers/docker', title: 'Docker 环境', icon: 'Platform', permission: 'ops.docker.view' },
    ],
  },
  {
    title: '中间件',
    icon: 'DataBoard',
    children: [
      { path: '/middleware/nginx', title: 'Nginx 管理', icon: 'Location', permission: 'ops.nginx.view' },
      { path: '/middleware/redis', title: 'Redis 管理', icon: 'Coin', permission: 'ops.middleware.view' },
      { path: '/middleware/rocketmq', title: 'RocketMQ 管理', icon: 'Promotion', permission: 'ops.middleware.view' },
      { path: '/middleware/elasticsearch', title: 'ES 管理', icon: 'Search', permission: 'ops.middleware.view' },
    ],
  },
  {
    title: '可观测性',
    icon: 'DataLine',
    children: [
      {
        path: '/observability/overview',
        title: '平台总览',
        icon: 'DataLine',
        anyPermissions: ['ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.trace.view', 'ops.grafana.view'],
      },
      { path: '/observability/grafana', title: '监控看板', icon: 'Histogram', permission: 'ops.grafana.view' },
      { path: '/logs', title: '日志中心', icon: 'Search', anyPermissions: ['ops.log.query', 'ops.log.datasource.view'] },
      { path: '/observability/tracing', title: '链路追踪', icon: 'Connection', permission: 'ops.trace.view' },
      { path: '/alerts', title: '告警中心', icon: 'Bell', permission: 'ops.alert.view' },
    ],
  },
  {
    title: '事件墙',
    icon: 'Tickets',
    children: [
      { path: '/events/overview', title: '事件总览', icon: 'DataLine', permission: 'eventwall.view' },
      { path: '/events/wall', title: '事件流', icon: 'Tickets', permission: 'eventwall.view' },
    ],
  },
  {
    path: '/marketplace',
    title: '工具市场',
    icon: 'Shop',
    anyPermissions: ['marketplace.template.view', 'marketplace.deployment.view', 'marketplace.deployment.manage'],
  },
  {
    path: '/sql',
    title: 'SQL 审计',
    icon: 'DataAnalysis',
    anyPermissions: [
      'sqlaudit.datasource.view',
      'sqlaudit.order.view',
      'sqlaudit.order.submit',
      'sqlaudit.order.review',
      'sqlaudit.order.execute',
      'sqlaudit.query.view',
      'sqlaudit.query.execute',
    ],
  },
  {
    path: '/users',
    title: '用户管理',
    icon: 'User',
    anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view'],
  },
  {
    title: 'AIOps',
    icon: 'ChatDotSquare',
    children: [
      { path: '/aiops/chat', title: '智能助手', icon: 'Service', permission: 'aiops.chat.view' },
      { path: '/aiops/config', title: '机器人配置', icon: 'Tools', permission: 'aiops.config.view' },
    ],
  },
]

function canAccess(item) {
  if (item.permission) return authStore.hasPermission(item.permission)
  if (item.anyPermissions) return authStore.hasAnyPermission(item.anyPermissions)
  return true
}

const visibleMenuItems = computed(() => menuItems
  .map((item) => {
    if (!item.children) return item
    const children = item.children.filter(canAccess)
    return { ...item, children }
  })
  .filter((item) => item.children ? item.children.length > 0 : canAccess(item)))

const normalizedMenuPath = computed(() => {
  if (route.path.startsWith('/sql')) {
    return '/sql'
  }
  if (route.path.startsWith('/events/')) {
    return route.path
  }
  if (route.path.startsWith('/logs/')) {
    return '/logs'
  }
  if (route.path === '/cmdb') {
    const currentTab = typeof route.query.tab === 'string' ? route.query.tab : 'items'
    return `/cmdb?tab=${currentTab}`
  }
  return route.path
})

const activeMenuPath = computed(() => {
  return normalizedMenuPath.value
})

const currentTitle = computed(() => {
  const currentPath = normalizedMenuPath.value
  for (const item of visibleMenuItems.value) {
    if ((item.menuKey || item.path) === currentPath) return item.title
    if (item.children) {
      const child = item.children.find((entry) => (entry.menuKey || entry.path) === currentPath)
      if (child) return `${item.title} / ${child.title}`
    }
  }
  return route.meta.title || ''
})

const currentRoleLabel = computed(() => {
  const roles = authStore.currentUser?.roles || []
  if (!roles.length) return '无角色'
  return roles.map(role => role.name).join(' / ')
})

async function handleUserCommand(command) {
  if (command === 'refresh') {
    await authStore.reloadProfile()
    ElMessage.success('权限已刷新')
    return
  }
  if (command === 'logout') {
    await authStore.logout()
    router.replace('/login')
  }
}
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
}
</style>


