<template>
  <div v-if="available" class="aiops-widget" :style="fabStyle">
    <transition name="aiops-panel">
      <div v-if="visible" class="aiops-layer">
        <button type="button" class="aiops-backdrop" @click="closePanel" />

        <div class="aiops-panel">
          <div class="aiops-panel-header">
            <div class="header-copy">
              <div class="aiops-title-row">
                <img :src="botAvatar" alt="AIOps bot" class="aiops-header-avatar" />
                <div class="aiops-title">AIOps 智能助手</div>
                <span class="header-badge">{{ bootstrap.provider?.model || bootstrap.provider?.name || '本地规则引擎' }}</span>
                <span class="header-badge runtime" :class="{ safe: !bootstrap.runtime?.allow_action_execution }">
                  {{ runtimeLabel }}
                </span>
              </div>
              <div class="aiops-subtitle">
                {{ analysisOnly ? '当前仅分析，不会触发执行动作' : (bootstrap.welcome_message || '查询资源、告警、分析问题、生成任务草稿') }}
              </div>
            </div>
            <div class="aiops-header-actions">
              <el-button size="small" text @click="handleCreateSession">新会话</el-button>
              <el-button size="small" text @click="closePanel">收起</el-button>
            </div>
          </div>

          <div class="aiops-panel-body">
            <aside class="aiops-session-list">
              <div class="session-list-head">
                <span>会话历史</span>
                <span class="session-count">{{ sessions.length }}</span>
              </div>
              <button
                v-for="session in sessions"
                :key="session.id"
                type="button"
                class="aiops-session-item"
                :class="{ active: currentSessionId === session.id }"
                @click="selectSession(session.id)"
              >
                <span class="session-title">{{ session.title || '新会话' }}</span>
                
              </button>
              <div v-if="!sessions.length" class="session-empty">暂无历史会话</div>
            </aside>

            <section class="aiops-chat-main">
              <div class="chat-toolbar">
                <div class="chat-toolbar-left">
                  <button v-if="isMobile" type="button" class="toolbar-chip" @click="mobileSessionVisible = true">
                    会话 {{ sessions.length }}
                  </button>
                  <div class="session-indicator">
                    <span class="session-indicator-label">{{ currentSession?.title || '新会话' }}</span>
                    <span class="session-indicator-meta">
                      {{ currentSession?.last_message_at ? `活跃于 ${formatDateTime(currentSession.last_message_at)}` : '尚未开始提问' }}
                    </span>
                  </div>
                  <label class="analysis-toggle">
                    <span>只分析</span>
                    <el-switch v-model="analysisOnly" size="small" />
                  </label>
                </div>
                <div class="chat-toolbar-right">
                  <span class="toolbar-hint">
                    {{ analysisOnly ? '提问会自动带上“不要执行”约束' : '具备权限时可生成待执行动作' }}
                  </span>
                </div>
              </div>

              <div class="quick-palette">
                <div v-if="!messages.length && bootstrap.suggested_questions?.length" class="aiops-quick-questions">
                  <button
                    v-for="item in bootstrap.suggested_questions"
                    :key="item"
                    type="button"
                    class="quick-chip"
                    @click="applySuggestedQuestion(item)"
                  >
                    {{ item }}
                  </button>
                </div>
              </div>

              <div class="message-stage">
                <div ref="messageListRef" class="aiops-message-list" v-loading="loading.messages">
                  <div v-if="!renderMessages.length" class="message-empty">
                    <div class="empty-title">可以直接问我</div>
                    <div class="empty-copy">资源现状、未确认告警、关联分析、任务草稿，我都会优先给出平台内证据。</div>
                  </div>

                  <div
                    v-for="(message, index) in renderMessages"
                    :key="message.localKey || message.id"
                    class="message-item"
                    :class="[message.role, { pending: message.pending }]"
                  >
                    <div class="message-meta">
                      <span class="message-role">{{ message.role === 'user' ? '你' : '助手' }}</span>
                      <span class="message-time">{{ formatDateTime(message.created_at) }}</span>
                    </div>

                    <div class="message-bubble">
                      <div v-if="message.role === 'assistant'" class="message-content assistant">
                        <template v-for="(block, blockIndex) in parseAssistantContent(message.content)" :key="`${message.localKey || message.id || index}-${blockIndex}`">
                          <div v-if="block.type === 'heading'" class="rich-heading">{{ block.text }}</div>
                          <div v-else-if="block.type === 'paragraph'" class="rich-paragraph">{{ block.text }}</div>
                          <ul v-else-if="block.type === 'list'" class="rich-list">
                            <li v-for="(item, itemIndex) in block.items" :key="`${blockIndex}-${itemIndex}`" class="rich-list-item">
                              <div class="rich-list-title">{{ item.text }}</div>
                              <ul v-if="item.children?.length" class="rich-sublist">
                                <li v-for="(child, childIndex) in item.children" :key="`${blockIndex}-${itemIndex}-${childIndex}`">{{ child }}</li>
                              </ul>
                            </li>
                          </ul>
                          <pre v-else-if="block.type === 'code'" class="rich-code">{{ block.text }}</pre>
                        </template>
                      </div>
                      <div v-else class="message-content user-content">{{ message.content }}</div>

                      <div v-if="message.citations?.length" class="citation-row">
                        <button
                          v-for="citation in message.citations"
                          :key="`${message.id || message.localKey}-${citation.title}`"
                          type="button"
                          class="citation-chip"
                          @click="jumpToCitation(citation)"
                        >
                          {{ citation.title }}
                        </button>
                      </div>

                      <div v-if="message.pending_action" class="pending-action-card">
                        <div class="pending-title-row">
                          <div class="pending-title">{{ message.pending_action.title }}</div>
                          <span class="pending-risk" :class="message.pending_action.risk_level">{{ message.pending_action.risk_level_display }}</span>
                        </div>
                        <div class="pending-meta">状态：{{ message.pending_action.status_display }}</div>
                        <div v-if="message.pending_action.action_payload" class="pending-detail-grid">
                          <div class="pending-detail-item">
                            <span>目标主机</span>
                            <strong>{{ message.pending_action.action_payload.host_count || 0 }} 台</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>执行方式</span>
                            <strong>{{ message.pending_action.action_payload.execution_mode || '--' }}</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>执行策略</span>
                            <strong>{{ message.pending_action.action_payload.execution_strategy || '--' }}</strong>
                          </div>
                          <div class="pending-detail-item">
                            <span>超时</span>
                            <strong>{{ message.pending_action.action_payload.timeout_seconds || '--' }}s</strong>
                          </div>
                        </div>
                        <div
                          v-if="message.pending_action.action_payload?.payload?.command"
                          class="pending-command"
                        >
                          {{ message.pending_action.action_payload.payload.command }}
                        </div>
                        <div v-if="message.pending_action.status === 'pending'" class="pending-actions">
                          <el-button size="small" type="primary" @click="handleConfirmAction(message.pending_action)">确认执行</el-button>
                          <el-button size="small" @click="handleCancelAction(message.pending_action)">取消</el-button>
                        </div>
                        <div v-else-if="message.pending_action.result_payload?.task_id" class="pending-result">
                          <span>已创建任务 #{{ message.pending_action.result_payload.task_id }}</span>
                          <el-button size="small" text @click="openTaskCenter">查看任务中心</el-button>
                        </div>
                      </div>

                      <div v-else-if="message.metadata?.action_execution_disabled" class="message-state-card">
                        管理员已关闭机器人动作执行，当前只保留分析和任务草稿能力。
                      </div>


                    </div>
                  </div>
                </div>
              </div>

              <div class="aiops-composer">
                <el-input
                  ref="composerRef"
                  v-model="composer"
                  type="textarea"
                  :rows="3"
                  resize="none"
                  :maxlength="2000"
                  show-word-limit
                  placeholder="输入你的问题，Enter 发送，Shift + Enter 换行，Esc 收起"
                  @keydown="handleComposerKeydown"
                />
                <div class="composer-actions">
                  <div class="composer-meta">
                    <span class="composer-tip">Enter 发送，Shift + Enter 换行</span>
                    <span v-if="analysisOnly" class="composer-tip">当前为只分析模式</span>
                    <span v-if="composer.trim()" class="composer-tip">草稿已自动保存</span>
                  </div>
                  <div class="composer-action-group">
                    <el-button text :disabled="!composer.trim()" @click="clearDraft">清空</el-button>
                    <el-button type="primary" :loading="loading.send" :disabled="!composer.trim()" @click="handleSend">
                      发送
                    </el-button>
                  </div>
                </div>
              </div>
            </section>
          </div>

          <transition name="aiops-sheet">
            <div v-if="mobileSessionVisible" class="mobile-session-sheet">
              <div class="mobile-session-head">
                <span>会话历史</span>
                <el-button size="small" text @click="mobileSessionVisible = false">关闭</el-button>
              </div>
              <div class="mobile-session-body">
                <button
                  v-for="session in sessions"
                  :key="`mobile-${session.id}`"
                  type="button"
                  class="aiops-session-item"
                  :class="{ active: currentSessionId === session.id }"
                  @click="selectSession(session.id)"
                >
                  <span class="session-title">{{ session.title || '新会话' }}</span>
                  
                </button>
                <div v-if="!sessions.length" class="session-empty">暂无历史会话</div>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </transition>

    <button
      type="button"
      ref="fabButtonRef"
      class="aiops-fab"
      :class="{ dragging: fabDragging }"
      @pointerdown="handleFabPointerDown"
      @click="toggleVisible"
    >
      <span class="aiops-fab-ring"></span>
      <span class="aiops-fab-core">
        <img :src="botAvatar" alt="AIOps bot" class="aiops-fab-avatar" />
      </span>
      <span class="aiops-fab-label">
        <strong>AIOps</strong>
        <small>智能助手</small>
      </span>
      <span class="aiops-fab-dot"></span>
    </button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  cancelAIOpsAction,
  confirmAIOpsAction,
  createAIOpsSession,
  getAIOpsBootstrap,
  getAIOpsMessages,
  getAIOpsSessions,
  sendAIOpsMessage,
} from '@/api/modules/aiops'
import botAvatar from '@/assets/aiops-bot.svg'
import { useAuthStore } from '@/stores/auth'

const STORAGE_SESSION_KEY = 'sxdevops_aiops_current_session'
const STORAGE_VISIBLE_KEY = 'sxdevops_aiops_visible'
const STORAGE_ANALYSIS_KEY = 'sxdevops_aiops_analysis_only'
const STORAGE_DRAFT_PREFIX = 'sxdevops_aiops_draft_'

const router = useRouter()
const authStore = useAuthStore()

const visible = ref(localStorage.getItem(STORAGE_VISIBLE_KEY) === '1')
const analysisOnly = ref(localStorage.getItem(STORAGE_ANALYSIS_KEY) === '1')
const bootstrap = ref({ permissions: {}, suggested_questions: [], runtime: {} })
const sessions = ref([])
const messages = ref([])
const composer = ref('')
const currentSessionId = ref(Number(localStorage.getItem(STORAGE_SESSION_KEY) || '') || null)
const loading = ref({ bootstrap: false, sessions: false, messages: false, send: false })
const pendingAssistantMessage = ref(null)
const messageListRef = ref(null)
const composerRef = ref(null)
const mobileSessionVisible = ref(false)
const isMobile = ref(typeof window !== 'undefined' ? window.innerWidth <= 920 : false)
const fabPosition = ref(null)
const fabDragging = ref(false)
const fabButtonRef = ref(null)
const fabPointerState = {
  pointerId: null,
  startX: 0,
  startY: 0,
  originLeft: 0,
  originTop: 0,
}
let ignoreNextFabClick = false

const available = computed(() => bootstrap.value.enabled && authStore.hasPermission('aiops.chat.view'))
const renderMessages = computed(() => pendingAssistantMessage.value ? [...messages.value, pendingAssistantMessage.value] : messages.value)
const currentSession = computed(() => sessions.value.find(item => item.id === currentSessionId.value) || null)
const fabStyle = computed(() => {
  if (!fabPosition.value || visible.value) return null
  return {
    left: `${fabPosition.value.left}px`,
    top: `${fabPosition.value.top}px`,
    right: 'auto',
    bottom: 'auto',
  }
})
const runtimeLabel = computed(() => {
  if (!bootstrap.value.runtime?.allow_action_execution) return '仅分析/草稿'
  return bootstrap.value.runtime?.require_confirmation ? '执行需确认' : '可直接执行'
})

function normalizeText(value) {
  return String(value || '').replace(/\r\n/g, '\n')
}

function formatDateTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function buildQuestionPayload(raw) {
  const content = raw.trim()
  if (!analysisOnly.value) return content
  if (/不要执行|仅分析|只分析/.test(content)) return content
  return `只做分析，不要执行：${content}`
}

function getDraftStorageKey(sessionId = currentSessionId.value) {
  return `${STORAGE_DRAFT_PREFIX}${sessionId || 'default'}`
}

function persistDraft(sessionId = currentSessionId.value, value = composer.value) {
  localStorage.setItem(getDraftStorageKey(sessionId), value || '')
}

function loadDraft(sessionId = currentSessionId.value) {
  composer.value = localStorage.getItem(getDraftStorageKey(sessionId)) || ''
}

function focusComposer() {
  nextTick(() => {
    composerRef.value?.focus?.()
  })
}

function handleResize() {
  isMobile.value = window.innerWidth <= 920
  if (!isMobile.value) {
    mobileSessionVisible.value = false
  }
  if (fabPosition.value) {
    fabPosition.value = clampFabPosition(fabPosition.value.left, fabPosition.value.top)
  }
}

function getFabOffsets() {
  return isMobile.value ? { right: 12, bottom: 12 } : { right: 24, bottom: 24 }
}

function getFabRect() {
  const fabEl = fabButtonRef.value
  if (!fabEl) return { width: 132, height: 58 }
  const rect = fabEl.getBoundingClientRect()
  return { width: rect.width, height: rect.height }
}

function clampFabPosition(left, top) {
  const { width, height } = getFabRect()
  const minX = 8
  const minY = 8
  const maxX = Math.max(minX, window.innerWidth - width - 8)
  const maxY = Math.max(minY, window.innerHeight - height - 8)
  return {
    left: Math.min(Math.max(left, minX), maxX),
    top: Math.min(Math.max(top, minY), maxY),
  }
}

function resetFabPosition() {
  fabPosition.value = null
  fabDragging.value = false
}

function handleFabPointerMove(event) {
  if (fabPointerState.pointerId !== event.pointerId) return
  const deltaX = event.clientX - fabPointerState.startX
  const deltaY = event.clientY - fabPointerState.startY
  if (!fabDragging.value && Math.hypot(deltaX, deltaY) < 6) return
  fabDragging.value = true
  fabPosition.value = clampFabPosition(
    fabPointerState.originLeft + deltaX,
    fabPointerState.originTop + deltaY,
  )
}

function cleanupFabPointerListeners() {
  window.removeEventListener('pointermove', handleFabPointerMove)
  window.removeEventListener('pointerup', handleFabPointerUp)
  window.removeEventListener('pointercancel', handleFabPointerUp)
}

function handleFabPointerUp(event) {
  if (fabPointerState.pointerId !== event.pointerId) return
  if (fabDragging.value) {
    ignoreNextFabClick = true
  }
  fabPointerState.pointerId = null
  cleanupFabPointerListeners()
}

function handleFabPointerDown(event) {
  if (visible.value) return
  const fabEl = event.currentTarget
  fabButtonRef.value = fabEl
  const rect = fabEl.getBoundingClientRect()
  fabPointerState.pointerId = event.pointerId
  fabPointerState.startX = event.clientX
  fabPointerState.startY = event.clientY
  fabPointerState.originLeft = fabPosition.value?.left ?? rect.left
  fabPointerState.originTop = fabPosition.value?.top ?? rect.top
  fabDragging.value = false
  window.addEventListener('pointermove', handleFabPointerMove)
  window.addEventListener('pointerup', handleFabPointerUp)
  window.addEventListener('pointercancel', handleFabPointerUp)
}

function parseAssistantContent(content) {
  const source = normalizeText(content).trim()
  if (!source) return [{ type: 'paragraph', text: '' }]

  const blocks = []
  const lines = source.split('\n')
  let paragraphLines = []
  let listItems = []
  let codeLines = []
  let inCode = false

  const pushParagraph = () => {
    if (!paragraphLines.length) return
    blocks.push({ type: 'paragraph', text: paragraphLines.join('\n') })
    paragraphLines = []
  }

  const pushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'list', items: listItems })
    listItems = []
  }

  const pushCode = () => {
    if (!codeLines.length) return
    blocks.push({ type: 'code', text: codeLines.join('\n') })
    codeLines = []
  }

  for (const line of lines) {
    const rawLine = line.replace(/\t/g, '  ')
    const trimmed = rawLine.trim()

    if (trimmed.startsWith('```')) {
      pushParagraph()
      pushList()
      if (inCode) {
        pushCode()
        inCode = false
      } else {
        inCode = true
      }
      continue
    }

    if (inCode) {
      codeLines.push(rawLine)
      continue
    }

    if (!trimmed) {
      pushParagraph()
      pushList()
      continue
    }

    if (/^\*\*.*\*\*$/.test(trimmed)) {
      pushParagraph()
      pushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^\*\*|\*\*$/g, '').trim() })
      continue
    }

    if (/^#{1,6}\s+/.test(trimmed)) {
      pushParagraph()
      pushList()
      blocks.push({ type: 'heading', text: trimmed.replace(/^#{1,6}\s+/, '').trim() })
      continue
    }

    if (/^\s{2,}\S/.test(rawLine) && listItems.length) {
      listItems[listItems.length - 1].children.push(trimmed)
      continue
    }

    if (/^(-|•)\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      pushParagraph()
      listItems.push({
        text: trimmed.replace(/^(-|•)\s+/, '').replace(/^\d+\.\s+/, '').trim(),
        children: [],
      })
      continue
    }

    pushList()
    paragraphLines.push(trimmed)
  }

  pushParagraph()
  pushList()
  pushCode()
  return blocks.length ? blocks : [{ type: 'paragraph', text: source }]
}

async function fetchBootstrap() {
  loading.value.bootstrap = true
  try {
    bootstrap.value = await getAIOpsBootstrap()
  } finally {
    loading.value.bootstrap = false
  }
}

async function fetchSessions() {
  loading.value.sessions = true
  try {
    const response = await getAIOpsSessions()
    sessions.value = response.results || response || []
    if (currentSessionId.value && sessions.value.some(item => item.id === currentSessionId.value)) {
      await selectSession(currentSessionId.value)
      return
    }
    if (sessions.value.length) {
      await selectSession(sessions.value[0].id)
    } else {
      loadDraft(null)
    }
  } finally {
    loading.value.sessions = false
  }
}

async function selectSession(sessionId) {
  currentSessionId.value = sessionId
  localStorage.setItem(STORAGE_SESSION_KEY, String(sessionId))
  mobileSessionVisible.value = false
  loading.value.messages = true
  try {
    messages.value = await getAIOpsMessages(sessionId)
    loadDraft(sessionId)
    await nextTick()
    scrollToBottom(true)
    focusComposer()
  } finally {
    loading.value.messages = false
  }
}

async function handleCreateSession() {
  try {
    const session = await createAIOpsSession({ title: '' })
    sessions.value.unshift(session)
    messages.value = []
    await selectSession(session.id)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '创建会话失败')
  }
}

async function ensureSession() {
  if (currentSessionId.value) return currentSessionId.value
  const session = await createAIOpsSession({ title: '' })
  sessions.value.unshift(session)
  currentSessionId.value = session.id
  localStorage.setItem(STORAGE_SESSION_KEY, String(session.id))
  messages.value = []
  return session.id
}

async function handleSend() {
  if (!composer.value.trim() || loading.value.send) return

  const rawContent = composer.value
  const sessionId = await ensureSession()
  const content = buildQuestionPayload(rawContent)

  composer.value = ''
  persistDraft(sessionId, '')
  loading.value.send = true
  pendingAssistantMessage.value = {
    localKey: `pending-${Date.now()}`,
    role: 'assistant',
    pending: true,
    content: '正在分析平台数据，请稍等...',
    created_at: new Date().toISOString(),
  }

  await nextTick()
  scrollToBottom(true)

  try {
    const response = await sendAIOpsMessage(sessionId, { content })
    messages.value.push(response.user_message)
    messages.value.push(response.assistant_message)
    pendingAssistantMessage.value = null
    await fetchSessions()
    await nextTick()
    scrollToBottom(true)
    focusComposer()
  } catch (error) {
    composer.value = rawContent
    persistDraft(sessionId, rawContent)
    ElMessage.error(error?.response?.data?.detail || '发送失败，请稍后重试')
  } finally {
    loading.value.send = false
    pendingAssistantMessage.value = null
  }
}

async function handleConfirmAction(action) {
  try {
    const result = await confirmAIOpsAction(action.id)
    ElMessage.success(`已创建任务 ${result.task_name}`)
    await selectSession(currentSessionId.value)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '确认执行失败')
  }
}

async function handleCancelAction(action) {
  try {
    await cancelAIOpsAction(action.id)
    ElMessage.success('已取消待执行动作')
    await selectSession(currentSessionId.value)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '取消动作失败')
  }
}

function jumpToCitation(citation) {
  if (!citation?.path) return
  router.push({ path: citation.path, query: citation.query || {} })
  closePanel()
}

function applySuggestedQuestion(text) {
  composer.value = text
  persistDraft()
  focusComposer()
}

function clearDraft() {
  composer.value = ''
  persistDraft(currentSessionId.value, '')
  focusComposer()
}

function handleComposerKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closePanel()
    return
  }
  if (event.key !== 'Enter') return
  if (event.shiftKey) return
  event.preventDefault()
  handleSend()
}

function scrollToBottom(force = false) {
  const el = messageListRef.value
  if (!el) return
  if (!force) {
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (!nearBottom && !loading.value.send) return
  }
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

async function copyMessage(content) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content || '')
      ElMessage.success('已复制消息')
      return
    }
    throw new Error('clipboard unavailable')
  } catch (error) {
    ElMessage.error('当前环境不支持复制，请手动选择文本')
  }
}

function reuseMessage(content) {
  composer.value = content || ''
  persistDraft()
  focusComposer()
}

function resolveReusablePrompt(index, message) {
  if (message.role === 'user') return message.content || ''
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (renderMessages.value[cursor]?.role === 'user') {
      return renderMessages.value[cursor].content || ''
    }
  }
  return ''
}

function openTaskCenter() {
  router.push('/hosts/tasks')
  closePanel()
}

async function handleOpenRequest() {
  resetFabPosition()
  visible.value = true
  localStorage.setItem(STORAGE_VISIBLE_KEY, '1')
  if (!bootstrap.value.enabled && !loading.value.bootstrap) {
    await fetchBootstrap()
  }
  if (!sessions.value.length && bootstrap.value.enabled) {
    await fetchSessions()
    return
  }
  loadDraft()
  await nextTick()
  scrollToBottom(true)
  focusComposer()
}

function closePanel() {
  visible.value = false
  mobileSessionVisible.value = false
  localStorage.setItem(STORAGE_VISIBLE_KEY, '0')
}

function handleGlobalKeydown(event) {
  if (event.key !== 'Escape' || !visible.value) return
  if (mobileSessionVisible.value) {
    mobileSessionVisible.value = false
    return
  }
  closePanel()
}

async function toggleVisible() {
  if (ignoreNextFabClick) {
    ignoreNextFabClick = false
    return
  }
  if (!visible.value) {
    resetFabPosition()
  }
  visible.value = !visible.value
  localStorage.setItem(STORAGE_VISIBLE_KEY, visible.value ? '1' : '0')
  if (visible.value) {
    if (!sessions.value.length) {
      await fetchSessions()
    } else {
      loadDraft()
      await nextTick()
      scrollToBottom(true)
      focusComposer()
    }
  } else {
    mobileSessionVisible.value = false
  }
}

watch(() => renderMessages.value.length, async () => {
  await nextTick()
  scrollToBottom()
})

watch(analysisOnly, value => {
  localStorage.setItem(STORAGE_ANALYSIS_KEY, value ? '1' : '0')
})

watch(composer, value => {
  persistDraft(currentSessionId.value, value)
})

watch(visible, value => {
  if (value) {
    nextTick(() => {
      focusComposer()
    })
  } else {
    }
})

onMounted(async () => {
  if (!authStore.isAuthenticated) return
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('sxdevops-aiops-open', handleOpenRequest)
  await fetchBootstrap()
  if (visible.value) {
    await fetchSessions()
  }
})

onBeforeUnmount(() => {
  cleanupFabPointerListeners()
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('sxdevops-aiops-open', handleOpenRequest)
})
</script>

<style scoped>
.aiops-widget{position:fixed;right:24px;bottom:24px;z-index:80}
.aiops-layer{position:fixed;inset:0;z-index:79;overflow:hidden}
.aiops-backdrop{position:absolute;inset:0;border:none;background:rgba(15,23,42,.12);backdrop-filter:blur(4px);cursor:pointer}
.aiops-fab{position:relative;z-index:81;display:flex;align-items:center;gap:9px;min-width:132px;height:58px;padding:7px 12px 7px 7px;border:none;border-radius:999px;background:linear-gradient(135deg,#ffffff 0%,#f7fbff 100%);box-shadow:0 12px 24px rgba(59,130,246,.12);cursor:grab;border:1px solid #bdd5fb;transition:transform .18s ease,box-shadow .18s ease;touch-action:none;user-select:none}
.aiops-fab:hover{transform:translateY(-2px);box-shadow:0 16px 30px rgba(59,130,246,.16)}
.aiops-fab.dragging{cursor:grabbing;transform:none;box-shadow:0 18px 34px rgba(59,130,246,.2)}
.aiops-fab-ring{position:absolute;inset:-2px;border-radius:999px;border:1px solid rgba(59,130,246,.16);box-shadow:0 0 0 1px rgba(255,255,255,.92);pointer-events:none}
.aiops-fab-core{position:relative;display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:20px;background:linear-gradient(145deg,#eef5ff 0%,#f6fbff 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.96),0 8px 16px rgba(59,130,246,.08)}
.aiops-fab-avatar{width:30px;height:30px;display:block}
.aiops-fab-label{display:flex;flex-direction:column;align-items:flex-start;line-height:1.1;position:relative;z-index:1}
.aiops-fab-label strong{font-size:13px;color:#0f172a}
.aiops-fab-label small{margin-top:2px;font-size:10px;color:#64748b}
.aiops-fab-dot{position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(255,255,255,.96),0 0 0 5px rgba(34,197,94,.1)}
.aiops-panel{position:absolute;right:24px;bottom:88px;width:980px;max-width:calc(100vw - 36px);height:min(760px,calc(100vh - 120px));display:flex;flex-direction:column;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid #dbe4f0;border-radius:24px;box-shadow:0 26px 56px rgba(15,23,42,.18);overflow:hidden}
.aiops-panel-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #e2e8f0;background:linear-gradient(135deg,#fff7ed 0%,#f0f9ff 100%)}
.header-copy{min-width:0}
.aiops-title-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.aiops-header-avatar{width:38px;height:38px;display:block;flex:0 0 auto}
.aiops-title{font-size:16px;font-weight:700;color:#0f172a}
.header-badge{padding:4px 10px;border-radius:999px;background:#ecfeff;color:#0f766e;font-size:12px;white-space:nowrap}
.header-badge.runtime{background:#e0f2fe;color:#075985}
.header-badge.runtime.safe{background:#ecfccb;color:#3f6212}
.aiops-subtitle{margin-top:4px;font-size:11px;color:#64748b;line-height:1.4}
.aiops-header-actions{display:flex;gap:8px}
.aiops-panel-body{display:grid;grid-template-columns:220px 1fr;flex:1;min-height:0}
.aiops-session-list{padding:12px;border-right:1px solid #e2e8f0;background:#f8fafc;overflow:auto;-webkit-overflow-scrolling:touch}
.session-list-head{display:flex;align-items:center;justify-content:space-between;padding:0 4px 10px;color:#475569;font-size:12px}
.session-count{padding:3px 8px;border-radius:999px;background:#e2e8f0}
.aiops-session-item{width:100%;display:block;text-align:left;padding:10px 12px;border:none;border-radius:12px;background:transparent;cursor:pointer;color:#334155;margin-bottom:6px;transition:background .18s ease,box-shadow .18s ease,transform .18s ease}
.aiops-session-item:hover{background:#fff;transform:translateY(-1px)}
.aiops-session-item.active{background:#fff;box-shadow:0 10px 20px rgba(15,23,42,.08)}
.session-title{display:block;font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-empty{font-size:12px;color:#64748b}
.aiops-chat-main{display:flex;flex-direction:column;min-width:0;min-height:0}
.chat-toolbar{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #edf2f7;background:rgba(255,255,255,.82)}
.chat-toolbar-left,.chat-toolbar-right{display:flex;align-items:center;gap:10px;min-width:0}
.toolbar-chip{border:none;border-radius:999px;padding:7px 12px;background:#dbeafe;color:#1d4ed8;cursor:pointer;font-size:12px;font-weight:600}
.session-indicator{display:flex;flex-direction:column;min-width:0;max-width:220px}
.session-indicator-label{font-size:12px;font-weight:700;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-indicator-meta{font-size:12px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.analysis-toggle{display:flex;align-items:center;gap:8px;font-size:12px;color:#334155}
.toolbar-hint{font-size:12px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.quick-palette{padding:8px 12px 0}
.aiops-quick-questions,.aiops-secondary-actions{display:flex;gap:8px;flex-wrap:wrap}
.quick-chip{border:none;border-radius:999px;padding:6px 10px;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease;font-size:12px}
.quick-chip{background:#e0f2fe;color:#075985}
.quick-chip:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(15,23,42,.08)}
.message-stage{position:relative;flex:1;min-height:0;overflow:hidden}
.aiops-message-list{height:100%;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:10px;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}
.message-empty{margin:auto;max-width:380px;text-align:center}
.empty-title{font-size:16px;font-weight:700;color:#0f172a}
.empty-copy{margin-top:8px;color:#64748b;line-height:1.6;font-size:12px}
.message-item{display:flex;flex-direction:column;gap:4px;max-width:92%}
.message-item.user{align-self:flex-end}
.message-item.pending{opacity:.82}
.message-meta{display:flex;align-items:center;gap:6px;color:#64748b;font-size:11px}
.message-item.user .message-meta{justify-content:flex-end}
.message-bubble{padding:10px 12px;border-radius:16px;background:#fff;border:1px solid #e2e8f0;box-shadow:0 8px 18px rgba(15,23,42,.05)}
.message-item.user .message-bubble{background:linear-gradient(135deg,#dbeafe,#f0f9ff)}
.message-content{font-size:13px;line-height:1.5;color:#0f172a;word-break:break-word}
.user-content{white-space:pre-wrap}
.rich-heading{font-size:13px;font-weight:700;color:#0f172a;margin-bottom:6px}
.rich-paragraph{white-space:pre-wrap;color:#334155;font-size:13px}
.rich-paragraph + .rich-paragraph{margin-top:8px}
.rich-list{margin:0;padding-left:16px;color:#334155;font-size:13px}
.rich-list + .rich-paragraph,.rich-paragraph + .rich-list,.rich-heading + .rich-list,.rich-list + .rich-heading{margin-top:10px}
.rich-list-item + .rich-list-item{margin-top:8px}
.rich-list-title{font-weight:600;color:#1e293b;font-size:13px}
.rich-sublist{margin:4px 0 0;padding-left:16px;color:#475569;font-size:12px}
.rich-code{margin:8px 0 0;padding:8px 10px;border-radius:10px;background:#0f172a;color:#e2e8f0;font-size:11px;line-height:1.5;white-space:pre-wrap;overflow:auto}
.citation-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.citation-chip{border:none;border-radius:999px;padding:4px 8px;background:#ecfeff;color:#0f766e;cursor:pointer;font-size:11px}
.pending-action-card{margin-top:10px;padding:10px;border-radius:12px;background:#fff7ed;border:1px solid #fdba74}
.pending-title-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.pending-title{font-weight:700;color:#9a3412}
.pending-risk{padding:4px 8px;border-radius:999px;background:#ffedd5;color:#9a3412;font-size:12px}
.pending-risk.high,.pending-risk.critical{background:#fee2e2;color:#b91c1c}
.pending-meta,.pending-result{margin-top:6px;font-size:11px;color:#7c2d12}
.pending-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.pending-detail-item{padding:8px 10px;border-radius:12px;background:rgba(255,255,255,.7);display:flex;flex-direction:column;gap:4px}
.pending-detail-item span{font-size:12px;color:#9a3412}
.pending-detail-item strong{font-size:12px;color:#7c2d12}
.pending-command{margin-top:8px;padding:8px 10px;border-radius:10px;background:#111827;color:#f8fafc;font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.pending-actions{display:flex;gap:8px;margin-top:10px}
.message-state-card{margin-top:10px;padding:8px 10px;border-radius:12px;background:#f8fafc;border:1px solid #cbd5e1;color:#475569;font-size:11px;line-height:1.5}
.message-actions{display:flex;gap:2px;justify-content:flex-end;margin-top:8px;padding-top:6px;border-top:1px dashed #e2e8f0}
.aiops-composer{padding:10px 12px;border-top:1px solid #e2e8f0;background:#fff}
.composer-actions{display:flex;align-items:center;justify-content:space-between;margin-top:8px}
.composer-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.composer-tip{font-size:11px;color:#64748b}
.composer-action-group{display:flex;align-items:center;gap:8px}
.mobile-session-sheet{display:none}
.aiops-panel-enter-active,.aiops-panel-leave-active{transition:all .18s ease}
.aiops-panel-enter-from,.aiops-panel-leave-to{opacity:0;transform:translateY(10px)}
.aiops-sheet-enter-active,.aiops-sheet-leave-active{transition:all .18s ease}
.aiops-sheet-enter-from,.aiops-sheet-leave-to{opacity:0;transform:translateY(12px)}
@media (max-width: 920px){
  .aiops-widget{right:12px;bottom:12px}
  .aiops-fab{min-width:118px;height:52px;padding:6px 10px 6px 6px}
  .aiops-fab-core{width:38px;height:38px;border-radius:18px}
  .aiops-fab-avatar{width:26px;height:26px}
  .aiops-panel{right:12px;bottom:84px;width:min(100vw - 20px,660px);height:min(84vh,calc(100vh - 116px))}
  .aiops-panel-body{grid-template-columns:1fr}
  .aiops-session-list{display:none}
  .pending-detail-grid{grid-template-columns:1fr}
  .chat-toolbar{flex-direction:column;align-items:flex-start;gap:8px}
  .chat-toolbar-left,.chat-toolbar-right{width:100%;justify-content:space-between}
  .toolbar-hint{max-width:100%}
  .session-indicator{max-width:none;flex:1}
  .mobile-session-sheet{display:flex;position:absolute;left:12px;right:12px;bottom:12px;max-height:45vh;flex-direction:column;border:1px solid #dbe4f0;border-radius:22px;background:#fff;box-shadow:0 20px 48px rgba(15,23,42,.24);overflow:hidden}
  .mobile-session-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #e2e8f0;background:#f8fafc}
  .mobile-session-body{padding:12px;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}
  .composer-actions{flex-direction:column;align-items:stretch;gap:10px}
  .composer-meta{justify-content:space-between}
  .composer-action-group{justify-content:flex-end}
}
</style>







