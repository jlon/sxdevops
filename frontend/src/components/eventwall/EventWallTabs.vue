<template>
  <section class="event-tabs-shell">
    <button
      v-for="item in tabs"
      :key="item.path"
      type="button"
      class="event-tab"
      :class="{ active: route.path === item.path }"
      @click="go(item.path)"
    >
      <span class="event-tab__title">{{ item.title }}</span>
      <span class="event-tab__desc">{{ item.desc }}</span>
    </button>
  </section>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const tabs = [
  { path: '/events/overview', title: '事件总览', desc: '总量、风险与活跃对象' },
  { path: '/events/wall', title: '事件流', desc: '筛选关键操作明细' },
]

function go(path) {
  if (route.path !== path) {
    router.push({ path, query: { ...route.query } })
  }
}
</script>

<style scoped>
.event-tabs-shell {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: -4px;
  padding: 4px;
  border-radius: 18px;
  background: rgba(255, 255, 255, .88);
  border: 1px solid rgba(226, 232, 240, .95);
  box-shadow: 0 14px 30px rgba(15, 23, 42, .05);
}

.event-tab {
  position: relative;
  min-height: 58px;
  padding: 8px 11px 8px 13px;
  border: 1px solid rgba(148, 163, 184, .12);
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 3px;
  text-align: left;
  cursor: pointer;
  transition: .18s ease box-shadow, .18s ease transform, .18s ease border-color, .18s ease background;
}

.event-tab::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(15, 118, 110, .12) 0%, rgba(234, 88, 12, .03) 100%);
}

.event-tab:hover {
  transform: translateY(-1px);
  border-color: rgba(59, 130, 246, .24);
  box-shadow: 0 12px 20px rgba(37, 99, 235, .08);
}

.event-tab.active {
  border-color: rgba(59, 130, 246, .28);
  background: linear-gradient(180deg, #fdfefe 0%, #eef6ff 100%);
  box-shadow: 0 14px 24px rgba(59, 130, 246, .1);
}

.event-tab.active::after {
  background: linear-gradient(180deg, #0f766e 0%, #ea580c 100%);
}

.event-tab__title {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.1;
  color: #0f172a;
}

.event-tab__desc {
  font-size: 11px;
  line-height: 1.35;
  color: #64748b;
}

@media (max-width: 960px) {
  .event-tabs-shell {
    grid-template-columns: 1fr;
  }
}
</style>



