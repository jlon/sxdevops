<template>
  <div class="aiops-entry-page fade-in">
    <section class="hero panel aiops-entry-hero">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="hero-icon"><el-icon><ChatDotSquare /></el-icon></span>
          <h2>AIOps 智能助手</h2>
          <p class="page-desc inline-subtitle">聚合平台内资源、告警、排障分析与任务草稿能力，统一通过智能助手对话入口使用。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="openWidget">打开智能助手</el-button>
        <el-button v-if="canViewConfig" @click="router.push('/aiops/config')">智能体配置</el-button>
      </div>
    </section>

    <div class="entry-grid">
      <article class="entry-card">
        <h3>资源咨询</h3>
        <p>直接询问主机、部署、容量和最近变化，智能助手会优先基于平台内已有数据回答。</p>
      </article>
      <article class="entry-card">
        <h3>告警分析</h3>
        <p>围绕未确认告警、风险级别和关联对象做快速排查，减少人工切页成本。</p>
      </article>
      <article class="entry-card">
        <h3>排障建议</h3>
        <p>结合资源、告警和运行上下文，先给出分析结论，再生成处理草稿。</p>
      </article>
      <article class="entry-card">
        <h3>任务草稿</h3>
        <p>在具备权限时，支持生成并确认任务中心动作，适合巡检和批量处理场景。</p>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotSquare } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const canViewConfig = computed(() => authStore.hasPermission('aiops.config.view'))

function openWidget() {
  window.dispatchEvent(new Event('sxdevops-aiops-open'))
}

onMounted(() => {
  openWidget()
})
</script>

<style scoped>
.aiops-entry-page{display:flex;flex-direction:column;gap:8px}
.panel{background:linear-gradient(180deg,#fff 0%,#fffdf8 100%);border:1px solid rgba(148,163,184,.16);border-radius:20px;box-shadow:0 12px 28px rgba(15,23,42,.05);padding:14px 16px}
.aiops-entry-hero{display:flex;align-items:center;justify-content:space-between;gap:12px;background:linear-gradient(135deg,#fff7ed 0%,#f8fbff 100%)}
.release-hero-copy{max-width:820px}
.release-hero-title-row{display:flex;align-items:center;gap:12px}
.release-hero-title-inline{flex-wrap:wrap}
.release-hero-title-row h2{margin:0;color:#0f172a}
.hero-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(135deg,#0f766e,#0ea5e9)}
.page-desc.inline-subtitle{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.hero-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.hero-actions :deep(.el-button){min-height:38px;padding:0 16px;border-radius:12px}
.entry-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.entry-card{padding:18px;border-radius:18px;border:1px solid #dbe4f0;background:#fff;box-shadow:0 10px 24px rgba(15,23,42,.05)}
.entry-card h3{margin:0;font-size:16px;color:#0f172a}
.entry-card p{margin:8px 0 0;font-size:13px;line-height:1.75;color:#475569}
@media (max-width: 900px){
  .aiops-entry-hero{flex-direction:column;align-items:flex-start}
  .entry-grid{grid-template-columns:1fr}
}
</style>
