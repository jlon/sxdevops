<template>
  <div class="fade-in sql-audit-page">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="sql-header-icon"><el-icon><Tickets /></el-icon></span>
          <h2>SQL 审计</h2>
          <p class="page-desc inline-subtitle">{{ SQL_AUDIT_SUPPORT_TEXT }}</p>
        </div>
      </div>
    </section>

    <div class="neo-tabs theme-blue log-center-tabs">
      <button
        v-for="tab in availableTabs"
        :key="tab.name"
        class="neo-tab-btn"
        :class="{ active: activeTab === tab.name }"
        @click="handleTabChange(tab.name)"
      >
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <SqlDatasources v-if="activeTab === 'datasources'" embedded />
    <SqlOrders v-else-if="activeTab === 'orders'" embedded />
    <SqlQuery v-else-if="activeTab === 'query'" embedded />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Coin, Search, Tickets } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import SqlDatasources from '@/views/SqlDatasources.vue'
import SqlOrders from '@/views/SqlOrders.vue'
import SqlQuery from '@/views/SqlQuery.vue'
import { SQL_AUDIT_SUPPORT_TEXT } from '@/utils/sqlaudit'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeTab = ref('datasources')

const availableTabs = computed(() => {
  const tabs = []
  if (authStore.hasPermission('sqlaudit.datasource.view')) {
    tabs.push({ name: 'datasources', label: '数据源', icon: Coin })
  }
  if (authStore.hasAnyPermission(['sqlaudit.order.view', 'sqlaudit.order.submit', 'sqlaudit.order.review', 'sqlaudit.order.execute'])) {
    tabs.push({ name: 'orders', label: '工单', icon: Tickets })
  }
  if (authStore.hasAnyPermission(['sqlaudit.query.view', 'sqlaudit.query.execute'])) {
    tabs.push({ name: 'query', label: '查询', icon: Search })
  }
  return tabs
})

const normalizeTab = (tab) => {
  if (availableTabs.value.some(item => item.name === tab)) {
    return tab
  }
  return availableTabs.value[0]?.name || 'datasources'
}

watch(
  [() => route.query.tab, availableTabs],
  ([tab]) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) {
      activeTab.value = nextTab
    }
    if (route.query.tab !== nextTab) {
      router.replace({ path: '/sql', query: { ...route.query, tab: nextTab } })
    }
  },
  { immediate: true },
)

const handleTabChange = (tab) => {
  const nextTab = normalizeTab(tab)
  if (activeTab.value !== nextTab) {
    activeTab.value = nextTab
  }
  if (route.query.tab !== nextTab) {
    router.replace({ path: '/sql', query: { ...route.query, tab: nextTab } })
  }
}
</script>

<style scoped>
.panel {
  background: linear-gradient(135deg, rgba(239,246,255,.96) 0%, rgba(236,254,255,.94) 52%, rgba(248,250,252,.98) 100%);
  border: 1px solid rgba(96,165,250,.18);
  border-radius: 24px;
  box-shadow: 0 16px 36px rgba(14,165,233,.08);
  padding: 14px 22px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.release-hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.release-hero-title-inline {
  flex-wrap: wrap;
}

.hero h2 {
  margin: 0;
  color: #0f172a;
}

.sql-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  box-shadow: 0 10px 20px rgba(37,99,235,.2);
}

.log-center-tabs {
  margin-bottom: 20px;
}

.page-desc {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.45;
}

.inline-subtitle {
  max-width: none;
}
</style>
