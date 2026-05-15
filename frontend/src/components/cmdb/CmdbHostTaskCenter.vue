<template>
  <div class="task-center-page">
    <div class="inner-tabs">
      <button
        v-for="tab in innerTabs"
        :key="tab.key"
        type="button"
        class="inner-tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        <span class="inner-tab-title">{{ tab.label }}</span>
        <span class="inner-tab-desc">{{ tab.desc }}</span>
      </button>
    </div>

    <div v-if="activeTab === 'history'" class="task-source-grid">
      <button
        v-for="item in sourceCards"
        :key="item.key"
        type="button"
        class="task-source-card"
        :class="{ active: taskFilters.trigger_source === item.source && taskFilters.target_type === (item.targetType || '') }"
        @click="applySourceFilter(item.source, item.targetType || '')"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.desc }}</small>
      </button>
    </div>

    <template v-if="activeTab === 'dispatch'">
      <div class="execution-flow">
        <div class="flow-card active">
          <span class="flow-index">1</span>
          <div class="flow-body">
            <strong>选择执行对象</strong>
            <div class="target-type-segment">
              <button
                v-for="option in targetTypeOptions"
                :key="option.value"
                type="button"
                class="target-type-btn"
                :class="{ active: taskForm.target_type === option.value }"
                @click="selectTargetType(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
          </div>
        </div>
        <div class="flow-card">
          <span class="flow-index">2</span>
          <div class="flow-body">
            <strong>选择执行类型</strong>
            <small>{{ currentExecutionKindLabel }}</small>
          </div>
        </div>
        <div class="flow-card">
          <span class="flow-index">3</span>
          <div class="flow-body">
            <strong>填写参数并执行</strong>
            <small>当前已锁定 {{ selectedTargetCount }} 个执行目标</small>
          </div>
        </div>
      </div>
      <div class="composer-grid">
        <div class="glass-card side-stack">
          <div class="card-head compact-head">
            <span>{{ ui.executionType }}</span>
            <el-tag size="small" type="info">基础类型</el-tag>
          </div>
          <div class="preset-grid execution-type-grid">
            <button
              v-for="option in activeExecutionTypeOptions"
              :key="option.value"
              type="button"
              class="preset-card"
              :class="{ active: executionKind === option.value }"
              @click="applyExecutionKind(option.value)"
            >
              <div class="preset-title">{{ option.label }}</div>
              <div class="preset-desc">{{ option.desc }}</div>
            </button>
          </div>
          <div class="mini-panel">
            <div class="mini-panel-title">{{ ui.dispatchAdvice }}</div>
            <div v-for="item in dispatchAdvice" :key="item" class="mini-bullet">{{ item }}</div>
          </div>
        </div>
        <div class="glass-card">
          <div class="card-head">
            <span>{{ ui.createTask }}</span>
            <div class="task-form-head-actions">
              <el-tag size="small" type="info">{{ ui.selectedTargets }} {{ selectedTargetCount }} {{ ui.unitTarget }}</el-tag>
              <el-button size="small" @click="saveCurrentAsTemplate">{{ ui.saveAsTemplate }}</el-button>
            </div>
          </div>
          <div class="task-inline-tip">{{ ui.tip }}</div>
          <el-form :model="taskForm" label-width="92px" class="task-form">
            <div class="form-row">
              <el-form-item :label="ui.taskName" class="form-col wide">
                <el-input v-model="taskForm.name" :placeholder="ui.taskNamePlaceholder" />
              </el-form-item>
            </div>
            <div class="form-row">
              <el-form-item :label="ui.executionType" class="form-col">
                <el-select v-model="executionKind" style="width: 100%" @change="applyExecutionKind">
                  <el-option v-for="option in activeExecutionTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
              </el-form-item>
              <el-form-item :label="ui.executionMode" class="form-col">
                <el-select v-model="taskForm.execution_mode" style="width: 100%" :disabled="taskForm.task_type === 'run_playbook' || taskForm.target_type === 'k8s'">
                  <el-option v-for="option in executionModeOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item :label="ui.taskDesc">
              <el-input v-model="taskForm.description" :placeholder="ui.taskDescPlaceholder" />
            </el-form-item>
            <div v-if="taskForm.target_type === 'k8s'" class="template-payload-stack">
              <div class="task-inline-tip k8s-cluster-tip">资源底座只负责选择 K8s 集群；命名空间、Pod 名称或工作负载名称在任务参数里填写。</div>
              <el-form-item label="K8s 资源">
                <el-select v-model="selectedK8sResourceId" clearable filterable placeholder="选择资源底座中的 K8s 集群，自动带出集群" style="width:100%" @change="applyK8sResource">
                  <el-option
                    v-for="resource in availableK8sResources"
                    :key="resource.id"
                    :label="k8sResourceLabel(resource)"
                    :value="resource.id"
                  />
                </el-select>
              </el-form-item>
              <div class="form-row">
                <el-form-item label="K8s 集群" class="form-col">
                  <el-select v-model="k8sForm.cluster_id" filterable placeholder="选择目标集群" style="width:100%">
                    <el-option v-for="cluster in k8sClusters" :key="cluster.id" :label="cluster.name" :value="cluster.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="命名空间" class="form-col">
                  <el-input v-model="k8sForm.namespace" placeholder="default / production" />
                </el-form-item>
              </div>
              <div v-if="taskForm.task_type === 'k8s_scale_workload'" class="form-row">
                <el-form-item label="负载类型" class="form-col">
                  <el-select v-model="taskForm.payload.workload_type" style="width:100%">
                    <el-option label="Deployment" value="deployment" />
                    <el-option label="StatefulSet" value="statefulset" />
                  </el-select>
                </el-form-item>
                <el-form-item label="负载名称" class="form-col">
                  <el-input v-model="k8sForm.name" placeholder="例如 api-server" />
                </el-form-item>
                <el-form-item label="副本数" class="form-col">
                  <el-input-number v-model="taskForm.payload.replicas" :min="0" :max="200" style="width:100%" />
                </el-form-item>
              </div>
              <div v-else class="form-row">
                <el-form-item label="Pod 名称" class="form-col">
                  <el-input v-model="k8sForm.name" placeholder="例如 api-server-5f8b7c6d4-r9p2w" />
                </el-form-item>
                <el-form-item label="容器" class="form-col">
                  <el-input v-model="k8sForm.container" placeholder="多容器 Pod 可填写，单容器可留空" />
                </el-form-item>
              </div>
              <el-form-item v-if="taskForm.task_type === 'k8s_pod_exec'" :label="ui.command">
                <el-input v-model="taskForm.payload.command" type="textarea" :rows="4" placeholder="例如：pwd && ls -lah /app" />
              </el-form-item>
              <div class="task-inline-tip">{{ ui.k8sTip }}</div>
            </div>
            <div v-if="taskForm.target_type === 'host'" class="form-row">
              <el-form-item :label="ui.modeHint" class="form-col">
                <div class="detail-kv compact-kv">{{ executionModeHint(taskForm.execution_mode, taskForm.task_type) }}</div>
              </el-form-item>
            </div>
            <div v-if="taskForm.target_type === 'host' && taskForm.task_type === 'service_status'" class="form-row">
              <el-form-item :label="ui.serviceName" class="form-col">
                <el-input v-model="taskForm.payload.service_name" :placeholder="ui.serviceNamePlaceholder" />
              </el-form-item>
              <el-form-item :label="ui.timeout" class="form-col">
                <el-input-number v-model="taskForm.timeout_seconds" :min="5" :max="120" style="width: 100%" />
              </el-form-item>
            </div>
            <div v-else-if="taskForm.target_type === 'host' && taskForm.task_type === 'run_command'" class="form-row">
              <el-form-item :label="ui.command" class="form-col wide">
                <el-input v-model="taskForm.payload.command" type="textarea" :rows="executionKind === 'python' ? 8 : 4" :placeholder="executionKind === 'python' ? ui.pythonPlaceholder : ui.commandPlaceholder" />
              </el-form-item>
            </div>
            <div v-else-if="taskForm.target_type === 'host' && taskForm.task_type === 'run_playbook'" class="template-payload-stack">
              <div class="form-row">
                <el-form-item :label="ui.playbookName" class="form-col">
                  <el-input v-model="taskForm.payload.playbook_name" :placeholder="ui.playbookNamePlaceholder" />
                </el-form-item>
                <el-form-item :label="ui.timeout" class="form-col">
                  <el-input-number v-model="taskForm.timeout_seconds" :min="5" :max="300" style="width: 100%" />
                </el-form-item>
              </div>
              <el-form-item :label="ui.playbookContent">
                <el-input v-model="taskForm.payload.playbook_content" type="textarea" :rows="9" :placeholder="ui.playbookContentPlaceholder" />
              </el-form-item>
            </div>
            <div v-if="taskForm.target_type === 'host' && taskForm.task_type !== 'service_status' && taskForm.task_type !== 'run_playbook'" class="form-row">
              <el-form-item v-if="taskForm.task_type !== 'run_command'" :label="ui.timeout" class="form-col">
                <el-input-number v-model="taskForm.timeout_seconds" :min="5" :max="120" style="width: 100%" />
              </el-form-item>
              <el-form-item :label="taskForm.task_type === 'run_command' ? ui.timeout : ui.strategy" class="form-col">
                <template v-if="taskForm.task_type === 'run_command'">
                  <el-input-number v-model="taskForm.timeout_seconds" :min="5" :max="120" style="width: 100%" />
                </template>
                <template v-else>
                  <el-radio-group v-model="taskForm.execution_strategy">
                    <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                    <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                  </el-radio-group>
                </template>
              </el-form-item>
            </div>
            <div v-if="taskForm.target_type === 'host' && taskForm.task_type === 'run_command'" class="form-row">
              <el-form-item :label="ui.strategy" class="form-col">
                <el-radio-group v-model="taskForm.execution_strategy">
                  <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                  <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                </el-radio-group>
              </el-form-item>
            </div>
            <div v-if="taskForm.target_type === 'host' && taskForm.task_type === 'run_playbook'" class="form-row">
              <el-form-item :label="ui.strategy" class="form-col">
                <el-radio-group v-model="taskForm.execution_strategy">
                  <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                  <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                </el-radio-group>
              </el-form-item>
            </div>
            <template v-if="taskForm.target_type === 'host'">
            <el-divider content-position="left">{{ ui.selectTargets }}</el-divider>
            <div class="toolbar">
              <div class="toolbar-left">
                <el-input v-model="targetFilters.search" :placeholder="ui.searchHostPlaceholder" clearable style="width: 220px" @keyup.enter="fetchTargets">
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
                <el-select v-model="targetFilters.environment" clearable filterable :placeholder="ui.environment" style="width: 140px" @change="handleEnvironmentChange">
                  <el-option v-for="node in envNodes" :key="node.id" :label="node.name" :value="node.id" />
                </el-select>
                <el-select v-model="targetFilters.system" clearable :placeholder="ui.businessLine" style="width: 140px" :disabled="!targetFilters.environment">
                  <el-option v-for="system in currentSystemOptions" :key="system.id" :label="system.name" :value="system.id" />
                </el-select>
                <el-select v-model="targetFilters.status" clearable :placeholder="ui.status" style="width: 110px">
                  <el-option v-for="option in hostStatusOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
                <el-tag size="small" effect="plain" type="info">{{ ui.matchedHosts }} {{ availableHosts.length }} {{ ui.unitHost }}</el-tag>
              </div>
              <div class="toolbar-right">
                <el-button size="small" @click="fetchTargets">{{ ui.queryHosts }}</el-button>
                <el-button size="small" @click="resetTargetFilters">{{ ui.resetFilters }}</el-button>
                <el-button size="small" @click="selectAllCurrent">{{ ui.selectCurrent }}</el-button>
                <el-button size="small" @click="clearSelection">{{ ui.clearSelection }}</el-button>
              </div>
            </div>
            <div v-if="selectedHostIds.length" class="selection-strip">
              <span class="selection-pill">{{ ui.selectedHosts }} {{ selectedHostIds.length }} {{ ui.unitHost }}</span>
              <span class="selection-pill success">{{ ui.onlineHosts }} {{ selectedStats.online }}</span>
              <span class="selection-pill warning">{{ ui.warningHosts }} {{ selectedStats.warning }}</span>
              <span class="selection-pill danger">{{ ui.offlineHosts }} {{ selectedStats.offline }}</span>
            </div>
            <el-table ref="hostTableRef" :data="availableHosts" v-loading="targetLoading" row-key="id" max-height="320" :empty-text="ui.emptyHosts" @selection-change="handleSelectionChange">
              <el-table-column type="selection" width="44" reserve-selection />
              <el-table-column prop="name" :label="ui.hostName" min-width="140" />
              <el-table-column prop="ip_address" :label="ui.ipAddress" width="140" />
              <el-table-column prop="environment_name" :label="ui.environment" width="110" />
              <el-table-column prop="system_name" :label="ui.businessLine" width="120" />
              <el-table-column prop="status_display" :label="ui.status" width="90" />
            </el-table>
            </template>
            <div class="submit-row">
              <div class="submit-tip">{{ ui.submitTip }}</div>
              <div class="submit-actions">
                <el-button :loading="savingTemplate" @click="saveCurrentAsTemplate">{{ ui.saveAsTemplate }}</el-button>
                <el-button type="primary" :loading="submitting" :disabled="!selectedTargetCount" @click="submitTask">
                  <el-icon><VideoPlay /></el-icon>
                  {{ ui.executeNow }}
                </el-button>
              </div>
            </div>
          </el-form>
        </div>
      </div>
    </template>
    <template v-else-if="activeTab === 'library'">
      <div class="glass-card template-list-card">
        <div class="card-head">
          <span>{{ ui.templateLibrary }}</span>
          <div class="task-form-head-actions">
            <el-button size="small" type="primary" @click="openTemplateCreateDialog">{{ ui.newTemplate }}</el-button>
            <el-button link type="primary" :loading="savingTemplate" @click="saveCurrentAsTemplate">{{ ui.saveCurrentConfig }}</el-button>
          </div>
        </div>
        <div class="section-tip section-gap">{{ ui.templateLibraryTip }}</div>
        <div class="toolbar section-gap template-toolbar">
          <div class="toolbar-left">
            <el-input v-model="templateFilters.search" clearable :placeholder="ui.templateSearchPlaceholder" style="width: 240px">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="templateFilters.execution_kind" clearable :placeholder="ui.executionType" style="width: 150px">
              <el-option v-for="option in executionTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-tag size="small" effect="plain" type="info">{{ ui.templateCount }} {{ filteredTemplates.length }}</el-tag>
          </div>
          <div class="toolbar-right">
            <el-button size="small" @click="resetTemplateFilters">{{ ui.resetFilters }}</el-button>
          </div>
        </div>
        <el-table :data="filteredTemplates" v-loading="templateLoading" row-key="id" :empty-text="templates.length ? ui.noTemplateMatch : ui.noTemplates">
          <el-table-column prop="name" :label="ui.taskName" min-width="180" show-overflow-tooltip />
          <el-table-column :label="ui.executionType" width="130">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ templateExecutionKindLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" :label="ui.taskDesc" min-width="240" show-overflow-tooltip />
          <el-table-column :label="ui.executionMode" width="120">
            <template #default="{ row }">{{ executionModeLabel(row.execution_mode, row.execution_mode_display) }}</template>
          </el-table-column>
          <el-table-column :label="ui.strategy" width="110">
            <template #default="{ row }">{{ executionStrategyLabel(row.execution_strategy) }}</template>
          </el-table-column>
          <el-table-column :label="ui.timeout" width="100">
            <template #default="{ row }">{{ row.timeout_seconds }}s</template>
          </el-table-column>
          <el-table-column :label="ui.templateSource" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_builtin ? 'success' : 'info'">{{ row.is_builtin ? ui.builtinTemplate : ui.personalTemplate }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="ui.actions" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" @click="openTemplateDetail(row)">{{ ui.viewTemplate }}</el-button>
              <el-button v-if="!row.is_builtin" link size="small" @click="openTemplateEditDialog(row)">{{ ui.editTemplate }}</el-button>
              <el-button link type="primary" size="small" @click="applyTemplate(row)">{{ ui.applyTemplate }}</el-button>
              <el-button v-if="!row.is_builtin" link type="danger" size="small" @click="removeTemplate(row)">{{ ui.deleteTemplate }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>
    <template v-else>
      <div class="glass-card history-card">
        <div class="card-head history-head">
          <span>{{ ui.history }}</span>
          <div class="history-actions">
            <el-tag size="small" type="info">{{ ui.selectedTasks }} {{ selectedCancelableTaskIds.length }} {{ ui.unitTask }}</el-tag>
            <el-button size="small" :disabled="!selectedCancelableTaskIds.length" @click="handleBatchCancel">{{ ui.batchCancel }}</el-button>
            <el-button size="small" @click="resetTaskFilters">{{ ui.resetFilters }}</el-button>
          </div>
        </div>
        <div class="toolbar history-toolbar">
          <div class="toolbar-left">
            <el-input v-model="taskFilters.search" clearable :placeholder="ui.searchTaskPlaceholder" style="width: 220px" @keyup.enter="fetchTasks">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="taskFilters.execution_kind" clearable :placeholder="ui.executionType" style="width: 140px" @change="fetchTasks">
              <el-option v-for="option in executionTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-select v-model="taskFilters.target_type" clearable :placeholder="ui.targetType" style="width: 120px" @change="fetchTasks">
              <el-option v-for="option in targetTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-select v-model="taskFilters.status" clearable :placeholder="ui.result" style="width: 120px" @change="fetchTasks">
              <el-option v-for="option in taskStatusOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-select v-model="taskFilters.trigger_source" clearable :placeholder="ui.triggerSource" style="width: 130px" @change="fetchTasks">
              <el-option v-for="option in triggerSourceOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-select v-model="taskFilters.risk_level" clearable :placeholder="ui.riskLevel" style="width: 110px" @change="fetchTasks">
              <el-option v-for="option in riskLevelOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </div>
        </div>
        <el-table :data="tasks" v-loading="taskLoading" row-key="id" :empty-text="ui.emptyTasks" @selection-change="handleTaskHistorySelectionChange">
          <el-table-column type="selection" width="44" reserve-selection />
          <el-table-column prop="name" :label="ui.taskName" min-width="180" />
          <el-table-column prop="target_type_display" :label="ui.targetType" width="100" />
          <el-table-column prop="trigger_source_display" :label="ui.triggerSource" width="118" />
          <el-table-column :label="ui.executionType" width="130">
            <template #default="{ row }">{{ templateExecutionKindLabel(row) }}</template>
          </el-table-column>
          <el-table-column :label="ui.riskLevel" width="88">
            <template #default="{ row }"><el-tag size="small" :type="riskTagType(row.risk_level)">{{ row.risk_level_display || '-' }}</el-tag></template>
          </el-table-column>
          <el-table-column :label="ui.executionMode" width="110">
            <template #default="{ row }">{{ executionModeLabel(row.execution_mode, row.execution_mode_display) }}</template>
          </el-table-column>
          <el-table-column prop="created_by" :label="ui.executor" width="100" />
          <el-table-column prop="target_count" :label="ui.targetCount" width="84" />
          <el-table-column :label="ui.result" width="120">
            <template #default="{ row }"><el-tag size="small" :type="taskStatusType(row.status)">{{ row.lifecycle_status_display || row.status_display }}</el-tag></template>
          </el-table-column>
          <el-table-column :label="ui.successFailed" width="120">
            <template #default="{ row }">{{ row.success_count }}/{{ row.failed_count }}</template>
          </el-table-column>
          <el-table-column prop="summary" :label="ui.summary" min-width="240" show-overflow-tooltip />
          <el-table-column :label="ui.finishedAt" width="170">
            <template #default="{ row }">{{ formatDateTime(row.finished_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column :label="ui.actions" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row)">{{ ui.detail }}</el-button>
              <el-button v-if="canExecuteTask(row)" link type="primary" size="small" @click="handleExecuteTask(row)">{{ ui.startTask }}</el-button>
              <el-button link type="success" size="small" :disabled="row.status === 'running'" @click="handleRerun(row)">{{ ui.rerun }}</el-button>
              <el-button v-if="canCancelTask(row)" link type="danger" size="small" @click="handleCancelTask(row)">{{ ui.cancelTask }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-row">
          <el-pagination v-model:current-page="taskPage" :page-size="20" :total="taskTotal" layout="total, prev, pager, next" @current-change="fetchTasks" />
        </div>
      </div>
    </template>
    <el-dialog v-model="templateCreateVisible" :title="templateDialogTitle" width="980px" destroy-on-close append-to-body align-center>
      <div class="template-editor-topbar">
        <div class="section-tip">{{ ui.templateEditorTip }}</div>
      </div>
      <div class="template-editor-overview">
        <div class="template-overview-card">
          <span class="template-overview-label">{{ ui.executionType }}</span>
          <strong>{{ templateDraftTypeLabel }}</strong>
        </div>
        <div class="template-overview-card">
          <span class="template-overview-label">{{ ui.executionMode }}</span>
          <strong>{{ executionModeLabel(templateDraft.execution_mode) }}</strong>
        </div>
        <div class="template-overview-card">
          <span class="template-overview-label">{{ ui.timeout }}</span>
          <strong>{{ templateDraft.timeout_seconds }}s</strong>
        </div>
      </div>
      <div class="template-editor-layout">
        <div class="template-editor-panel template-editor-main">
          <el-form :model="templateDraft" label-width="92px" class="task-form">
            <div class="template-editor-section">
              <div class="template-editor-section-title">{{ ui.editorBasicInfo }}</div>
              <div class="form-row">
                <el-form-item :label="ui.taskName" class="form-col">
                  <el-input v-model="templateDraft.name" :placeholder="ui.taskNamePlaceholder" />
                </el-form-item>
                <el-form-item :label="ui.executionType" class="form-col">
                  <el-select v-model="templateExecutionKind" style="width: 100%" @change="handleTemplateExecutionKindChange">
                    <el-option v-for="option in executionTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
                  </el-select>
                </el-form-item>
              </div>
              <el-form-item :label="ui.taskDesc">
                <el-input v-model="templateDraft.description" type="textarea" :rows="3" :placeholder="ui.taskDescPlaceholder" />
              </el-form-item>
            </div>
            <div class="template-editor-section">
              <div class="template-editor-section-title">{{ ui.editorExecution }}</div>
              <div class="form-row">
                <el-form-item :label="ui.executionMode" class="form-col">
                  <el-select v-model="templateDraft.execution_mode" style="width: 100%" :disabled="templateDraft.task_type === 'run_playbook' || templateDraft.target_type === 'k8s'">
                    <el-option v-for="option in executionModeOptions" :key="option.value" :label="option.label" :value="option.value" />
                  </el-select>
                </el-form-item>
                <el-form-item :label="ui.modeHint" class="form-col">
                  <div class="detail-kv compact-kv">{{ executionModeHint(templateDraft.execution_mode, templateDraft.task_type) }}</div>
                </el-form-item>
              </div>
              <div v-if="templateDraft.task_type === 'service_status'" class="form-row">
                <el-form-item :label="ui.serviceName" class="form-col">
                  <el-input v-model="templateDraft.payload.service_name" :placeholder="ui.serviceNamePlaceholder" />
                </el-form-item>
                <el-form-item :label="ui.timeout" class="form-col">
                  <el-input-number v-model="templateDraft.timeout_seconds" :min="5" :max="120" style="width: 100%" />
                </el-form-item>
              </div>
              <div v-if="templateDraft.task_type !== 'service_status' && templateDraft.task_type !== 'run_command' && templateDraft.task_type !== 'run_playbook'" class="form-row">
                <el-form-item :label="ui.timeout" class="form-col">
                  <el-input-number v-model="templateDraft.timeout_seconds" :min="5" :max="120" style="width: 100%" />
                </el-form-item>
                <el-form-item :label="ui.strategy" class="form-col">
                  <el-radio-group v-model="templateDraft.execution_strategy">
                    <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                    <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                  </el-radio-group>
                </el-form-item>
              </div>
            </div>
            <div class="template-editor-section">
              <div class="template-editor-section-title">{{ ui.editorPayload }}</div>
              <div v-if="templateDraft.task_type === 'run_command'" class="template-payload-stack">
                <el-form-item :label="ui.command" class="form-col wide">
                  <el-input v-model="templateDraft.payload.command" type="textarea" :rows="templateExecutionKind === 'python' ? 10 : 8" :placeholder="templateExecutionKind === 'python' ? ui.pythonPlaceholder : ui.commandPlaceholder" />
                </el-form-item>
                <div class="form-row">
                  <el-form-item :label="ui.timeout" class="form-col">
                    <el-input-number v-model="templateDraft.timeout_seconds" :min="5" :max="120" style="width: 100%" />
                  </el-form-item>
                  <el-form-item :label="ui.strategy" class="form-col">
                    <el-radio-group v-model="templateDraft.execution_strategy">
                      <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                      <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                    </el-radio-group>
                  </el-form-item>
                </div>
              </div>
              <div v-else-if="templateDraft.task_type === 'run_playbook'" class="template-payload-stack">
                <div class="form-row">
                  <el-form-item :label="ui.playbookName" class="form-col">
                    <el-input v-model="templateDraft.payload.playbook_name" :placeholder="ui.playbookNamePlaceholder" />
                  </el-form-item>
                  <el-form-item :label="ui.timeout" class="form-col">
                    <el-input-number v-model="templateDraft.timeout_seconds" :min="5" :max="300" style="width: 100%" />
                  </el-form-item>
                </div>
                <el-form-item :label="ui.playbookContent">
                  <el-input v-model="templateDraft.payload.playbook_content" type="textarea" :rows="12" :placeholder="ui.playbookContentPlaceholder" />
                </el-form-item>
                <el-form-item :label="ui.strategy">
                  <el-radio-group v-model="templateDraft.execution_strategy">
                    <el-radio label="continue">{{ ui.continueOnError }}</el-radio>
                    <el-radio label="stop_on_error">{{ ui.stopOnError }}</el-radio>
                  </el-radio-group>
                </el-form-item>
              </div>
              <div v-else-if="templateDraft.task_type === 'k8s_pod_exec'" class="template-payload-stack">
                <el-form-item :label="ui.command" class="form-col wide">
                  <el-input v-model="templateDraft.payload.command" type="textarea" :rows="8" placeholder="例如：pwd && ls -lah /app" />
                </el-form-item>
                <div class="task-inline-tip">{{ ui.k8sTip }}</div>
              </div>
              <div v-else class="detail-kv">{{ ui.noExtraParams }}</div>
            </div>
          </el-form>
        </div>
        <div class="template-editor-side">
          <div class="template-editor-panel template-editor-preview">
            <div class="card-head compact-head">
              <span>{{ ui.previewTemplate }}</span>
              <el-tag size="small" effect="plain">{{ templateDraftTypeLabel }}</el-tag>
            </div>
            <div class="detail-summary">
              <div class="detail-chip">{{ ui.executionMode }}: {{ executionModeLabel(templateDraft.execution_mode) }}</div>
              <div class="detail-chip">{{ ui.strategy }}: {{ executionStrategyLabel(templateDraft.execution_strategy) }}</div>
              <div class="detail-chip">{{ ui.timeout }}: {{ templateDraft.timeout_seconds }}</div>
            </div>
            <div class="detail-section">
              <div class="detail-section-title">{{ ui.templatePayload }}</div>
              <pre v-if="templateDraft.task_type === 'run_command'" class="detail-code-block">{{ templateDraft.payload.command || '-' }}</pre>
              <template v-else-if="templateDraft.task_type === 'run_playbook'">
                <div class="detail-kv">{{ ui.playbookName }}: {{ templateDraft.payload.playbook_name || '-' }}</div>
                <pre class="detail-code-block template-code-block">{{ templateDraft.payload.playbook_content || '-' }}</pre>
              </template>
              <pre v-else-if="templateDraft.task_type === 'k8s_pod_exec'" class="detail-code-block">{{ templateDraft.payload.command || '-' }}</pre>
              <div v-else-if="templateDraft.task_type === 'service_status'" class="detail-kv">{{ ui.serviceDetail }}: {{ templateDraft.payload.service_name || '-' }}</div>
              <div v-else class="detail-kv">{{ ui.noExtraParams }}</div>
            </div>
            <div class="detail-section">
              <div class="detail-section-title">{{ ui.taskDesc }}</div>
              <div class="detail-kv">{{ templateDraft.description || ui.emptyDesc }}</div>
            </div>
          </div>
          <div class="template-editor-panel template-editor-help">
            <div class="card-head compact-head">
              <span>{{ ui.editorAdvice }}</span>
            </div>
            <div v-for="item in templateEditorAdvice" :key="item" class="mini-bullet">{{ item }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="detail-actions">
          <el-button @click="templateCreateVisible = false">{{ ui.close }}</el-button>
          <el-button type="primary" :loading="creatingTemplate" @click="submitTemplateDraft">{{ templateDialogSubmitText }}</el-button>
        </div>
      </template>
    </el-dialog>
    <el-drawer v-model="templateDetailVisible" :title="ui.templateDetailTitle" size="42%">
      <template v-if="currentTemplate">
        <div class="detail-summary">
          <div class="detail-chip"><strong>{{ currentTemplate.name }}</strong></div>
          <div class="detail-chip">{{ templateExecutionKindLabel(currentTemplate) }}</div>
          <div class="detail-chip">{{ ui.executionMode }}: {{ executionModeLabel(currentTemplate.execution_mode, currentTemplate.execution_mode_display) }}</div>
          <div class="detail-chip">{{ ui.strategy }}: {{ executionStrategyLabel(currentTemplate.execution_strategy) }}</div>
          <div class="detail-chip">{{ ui.timeout }}: {{ currentTemplate.timeout_seconds }}</div>
          <div class="detail-chip">{{ ui.creator }}: {{ currentTemplate.created_by || '-' }}</div>
          <div class="detail-chip">{{ currentTemplate.is_builtin ? ui.builtinTemplate : ui.personalTemplate }}</div>
        </div>
        <div class="detail-desc">{{ currentTemplate.description || ui.emptyDesc }}</div>
        <div class="detail-section">
          <div class="detail-section-title">{{ ui.templatePayload }}</div>
          <pre v-if="currentTemplate.task_type === 'run_command'" class="detail-code-block">{{ currentTemplate.payload?.command || '-' }}</pre>
          <template v-else-if="currentTemplate.task_type === 'run_playbook'">
            <div class="detail-kv">{{ ui.playbookName }}: {{ currentTemplate.payload?.playbook_name || '-' }}</div>
            <pre class="detail-code-block template-code-block">{{ currentTemplate.payload?.playbook_content || '-' }}</pre>
          </template>
          <pre v-else-if="currentTemplate.task_type === 'k8s_pod_exec'" class="detail-code-block">{{ currentTemplate.payload?.command || '-' }}</pre>
          <div v-else-if="currentTemplate.task_type === 'service_status'" class="detail-kv">{{ ui.serviceDetail }}: {{ currentTemplate.payload?.service_name || '-' }}</div>
          <div v-else class="detail-kv">{{ ui.noExtraParams }}</div>
        </div>
        <div v-if="Object.keys(currentTemplate.payload || {}).length" class="detail-section">
          <div class="detail-section-title">{{ ui.templatePayload }} JSON</div>
          <pre class="detail-code-block">{{ formatPayloadJson(currentTemplate.payload) }}</pre>
        </div>
        <div class="detail-kv">{{ ui.createdAt }}: {{ formatDateTime(currentTemplate.created_at) }}</div>
        <div class="detail-actions">
          <el-button @click="templateDetailVisible = false">{{ ui.close }}</el-button>
          <el-button v-if="!currentTemplate.is_builtin" @click="openTemplateEditDialog(currentTemplate)">{{ ui.editTemplate }}</el-button>
          <el-button type="primary" @click="applyTemplate(currentTemplate)">{{ ui.applyTemplate }}</el-button>
        </div>
      </template>
    </el-drawer>
    <el-drawer v-model="detailVisible" :title="ui.detailTitle" size="68%">
      <div v-loading="detailLoading" class="task-detail-shell">
        <template v-if="detailTask">
          <div class="detail-summary">
            <div class="detail-chip"><strong>{{ detailTask.name }}</strong></div>
            <div class="detail-chip">{{ detailTask.target_type_display || ui.hostResource }}</div>
            <div class="detail-chip">{{ detailTask.task_type_display }}</div>
            <div class="detail-chip">{{ ui.executionMode }}: {{ executionModeLabel(detailTask.execution_mode, detailTask.execution_mode_display) }}</div>
            <div class="detail-chip">{{ ui.status }}: {{ detailTask.lifecycle_status_display || detailTask.status_display }}</div>
            <div class="detail-chip">{{ ui.triggerSource }}: {{ detailTask.trigger_source_display || '-' }}</div>
            <div class="detail-chip">{{ ui.riskLevel }}: {{ detailTask.risk_level_display || '-' }}</div>
            <div class="detail-chip">{{ ui.successRate }}: {{ detailTask.success_rate }}%</div>
            <div class="detail-chip">{{ ui.executor }}: {{ detailTask.created_by || '-' }}</div>
            <div class="detail-chip">{{ ui.createdAt }}: {{ formatDateTime(detailTask.created_at) }}</div>
          </div>
          <div class="task-metric-grid">
            <div class="task-metric-card">
              <span class="task-metric-label">{{ ui.targetCount }}</span>
              <strong>{{ detailTask.target_count || 0 }}</strong>
            </div>
            <div class="task-metric-card success">
              <span class="task-metric-label">{{ ui.success }}</span>
              <strong>{{ detailTask.success_count || 0 }}</strong>
            </div>
            <div class="task-metric-card danger">
              <span class="task-metric-label">{{ ui.failed }}</span>
              <strong>{{ detailTask.failed_count || 0 }}</strong>
            </div>
            <div class="task-metric-card warning">
              <span class="task-metric-label">{{ ui.skipped }}</span>
              <strong>{{ detailTask.skipped_count || 0 }}</strong>
            </div>
          </div>
          <div class="detail-section">
            <div class="detail-section-title">{{ ui.summary }}</div>
            <div class="detail-kv">{{ detailTask.summary || detailTask.description || ui.emptyDesc }}</div>
            <div v-if="detailTask.cancel_requested" class="detail-kv danger-text">{{ ui.cancelRequestedBy }}: {{ detailTask.cancel_requested_by || '-' }} | {{ ui.cancelRequestedAt }}: {{ formatDateTime(detailTask.cancel_requested_at) }}</div>
          </div>
          <div class="detail-grid">
            <div class="detail-section">
              <div class="detail-section-title">{{ ui.executionOverview }}</div>
              <div class="detail-kv">{{ ui.strategy }}: {{ executionStrategyLabel(detailTask.execution_strategy) }}</div>
              <div class="detail-kv">{{ ui.timeout }}: {{ detailTask.timeout_seconds || 0 }}s</div>
              <div class="detail-kv">{{ ui.triggerSource }}: {{ detailTask.trigger_source_display || '-' }}</div>
              <div class="detail-kv">{{ ui.startedAt }}: {{ formatDateTime(detailTask.started_at) }}</div>
              <div class="detail-kv">{{ ui.finishedAt }}: {{ formatDateTime(detailTask.finished_at) }}</div>
            </div>
            <div class="detail-section">
              <div class="detail-section-title">{{ detailTask.target_type === 'k8s' ? ui.targetResources : ui.targetHosts }}</div>
              <div v-if="detailTask.target_snapshot?.length" class="target-chip-grid">
                <div v-for="host in detailTask.target_snapshot" :key="`${detailTask.id}-${host.id || host.hostname}`" class="target-host-chip">
                  <strong>{{ host.hostname || host.name || '-' }}</strong>
                  <span>{{ host.ip_address || host.cluster_name || '-' }}</span>
                  <span v-if="host.namespace">{{ host.namespace }}</span>
                </div>
              </div>
              <div v-else class="detail-kv">{{ ui.emptyTargets }}</div>
            </div>
          </div>
          <div class="detail-section">
            <div class="detail-section-title">{{ ui.taskPayload }}</div>
            <pre v-if="detailTask.task_type === 'run_command'" class="detail-code-block">{{ detailTask.payload?.command || '-' }}</pre>
            <template v-else-if="detailTask.task_type === 'run_playbook'">
              <div class="detail-kv">{{ ui.playbookName }}: {{ detailTask.payload?.playbook_name || '-' }}</div>
              <pre class="detail-code-block template-code-block">{{ detailTask.payload?.playbook_content || '-' }}</pre>
            </template>
            <div v-else-if="detailTask.task_type === 'service_status'" class="detail-kv">{{ ui.serviceDetail }}: {{ detailTask.payload?.service_name || '-' }}</div>
            <div v-else class="detail-kv">{{ ui.noExtraParams }}</div>
          </div>
          <div v-if="Object.keys(detailTask.payload || {}).length" class="detail-section">
            <div class="detail-section-title">{{ ui.taskPayload }} JSON</div>
            <pre class="detail-code-block">{{ formatPayloadJson(detailTask.payload) }}</pre>
          </div>
          <div class="detail-section">
            <div class="detail-section-title">{{ ui.executionDetails }}</div>
            <el-table :data="detailTask.executions || []" max-height="520" :empty-text="ui.emptyExecutions">
              <el-table-column prop="host_name" :label="ui.host" min-width="140" />
              <el-table-column prop="target_name" :label="ui.targetResource" min-width="140" />
              <el-table-column prop="host_ip" label="IP" width="140" />
              <el-table-column :label="ui.status" width="100">
                <template #default="{ row }"><el-tag size="small" :type="executionStatusType(row.status)">{{ row.status_display }}</el-tag></template>
              </el-table-column>
              <el-table-column :label="ui.duration" width="90">
                <template #default="{ row }">{{ row.duration_ms }}ms</template>
              </el-table-column>
              <el-table-column prop="command" :label="ui.command" min-width="200" show-overflow-tooltip />
              <el-table-column :label="ui.output" min-width="280">
                <template #default="{ row }"><div class="output-block">{{ row.error_message || row.output || '-' }}</div></template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, VideoPlay } from '@element-plus/icons-vue'
import {
  batchCancelHostTasks,
  cancelHostTask,
  createHostTask,
  createHostTaskTemplate,
  updateHostTaskTemplate,
  deleteHostTaskTemplate,
  executeHostTask,
  getHostTask,
  getHostTaskStats,
  getTaskResourceOptions,
  getHostTaskTemplates,
  getHostTasks,
  rerunHostTask,
} from '@/api/modules/ops'
import { getK8sClusters } from '@/api/modules/container'
const route = useRoute()
const ui = {

  tip: '\u4efb\u52a1\u4e2d\u5fc3\u9002\u5408\u6279\u91cf\u5de1\u68c0\u3001\u7edf\u4e00\u5237\u65b0\u4e0e\u547d\u4ee4\u5206\u53d1\uff1b\u5f53\u524d\u4e3a\u4e32\u884c\u6267\u884c\uff0c\u5efa\u8bae\u5355\u6b21\u63a7\u5236\u5728 20 \u53f0\u4ee5\u5185\u3002',
  presets: '\u4efb\u52a1\u7c7b\u578b',
  quickStart: '\u5feb\u901f\u8d77\u6b65',
  dispatchAdvice: '\u4e0b\u53d1\u5efa\u8bae',
  templateLibrary: '\u6a21\u677f\u5e93',
  templateLibraryTip: '将常用巡检、变更和诊断编排沉淀为模板；任务执行类型只保留 Shell、Python、Ansible Playbook 和 K8s 命令。',
  commandLibrary: '\u5e38\u7528\u547d\u4ee4\u5e93',
  commandTip: '\u5efa\u8bae\u5148\u5728\u6d4b\u8bd5\u73af\u5883\u9a8c\u8bc1',
  libraryAdvice: '\u6a21\u677f\u6cbb\u7406\u5efa\u8bae',
  newTemplate: '\u65b0\u589e\u6a21\u677f',
  editTemplate: '\u7f16\u8f91',
  saveCurrentConfig: '\u4fdd\u5b58\u5f53\u524d\u914d\u7f6e',
  viewTemplate: '\u67e5\u770b\u8be6\u60c5',
  templateEditorTip: '选择基础执行类型后填写脚本或 Playbook 内容，具体巡检/变更动作通过模板名称和参数表达。',
  templateQuickFill: '\u5feb\u6377\u586b\u5145',
  editorBasicInfo: '\u57fa\u7840\u4fe1\u606f',
  editorExecution: '\u6267\u884c\u7b56\u7565',
  editorPayload: '\u6267\u884c\u5185\u5bb9',
  editorAdvice: '\u7f16\u6392\u5efa\u8bae',
  previewTemplate: '\u6a21\u677f\u9884\u89c8',
  templateCount: '\u6a21\u677f\u6570',
  templateSearchPlaceholder: '\u641c\u7d22\u6a21\u677f\u540d\u79f0 / \u8bf4\u660e',
  noTemplateMatch: '\u6682\u65e0\u5339\u914d\u6a21\u677f',
  createTemplateTitle: '\u65b0\u589e\u4efb\u52a1\u6a21\u677f',
  editTemplateTitle: '\u7f16\u8f91\u4efb\u52a1\u6a21\u677f',
  createTemplateSubmit: '\u521b\u5efa',
  updateTemplateSubmit: '\u4fdd\u5b58',
  templateDetailTitle: '\u6a21\u677f\u8be6\u60c5',
  templatePayload: '\u6a21\u677f\u53c2\u6570',
  serviceDetail: '\u670d\u52a1\u540d\u79f0',
  noExtraParams: '\u8be5\u6a21\u677f\u65e0\u9700\u989d\u5916\u53c2\u6570\u3002',
  creator: '\u521b\u5efa\u4eba',
  createdAt: '\u521b\u5efa\u65f6\u95f4',
  commandRequired: '\u8bf7\u586b\u5199\u6267\u884c\u547d\u4ee4',
  playbookRequired: '\u8bf7\u586b\u5199 Playbook \u5185\u5bb9',
  serviceRequired: '\u8bf7\u586b\u5199\u670d\u52a1\u540d\u79f0',
  templateCreated: '\u6a21\u677f\u5df2\u521b\u5efa',
  templateUpdated: '\u6a21\u677f\u5df2\u66f4\u65b0',
  close: '\u5173\u95ed',
  saveAsTemplate: '\u4fdd\u5b58\u4e3a\u6a21\u677f',
  builtinTemplate: '\u5185\u7f6e',
  personalTemplate: '\u6211\u7684',
  templateSource: '来源',
  applyTemplate: '\u5957\u7528',
  deleteTemplate: '\u5220\u9664',
  noTemplates: '\u6682\u65e0\u53ef\u7528\u6a21\u677f',
  createTask: '\u65b0\u5efa\u4efb\u52a1',
  targetType: '目标类型',
  hostResource: '主机资源',
  k8sResource: 'K8s 资源',
  selectedTargets: '已选目标',
  unitTarget: '个',
  selectedHosts: '\u5df2\u9009',
  selectedTasks: '\u5df2\u9009',
  unitHost: '\u53f0',
  unitTask: '\u4e2a\u4efb\u52a1',
  taskName: '\u4efb\u52a1\u540d\u79f0',
  taskNamePlaceholder: '\u4f8b\u5982\uff1a\u751f\u4ea7\u4e3b\u673a\u6279\u91cf\u5de1\u68c0',
  taskType: '\u4efb\u52a1\u7c7b\u578b',
  executionType: '执行类型',
  taskDesc: '\u4efb\u52a1\u8bf4\u660e',
  taskDescPlaceholder: '\u5199\u660e\u8fd9\u6b21\u4e0b\u53d1\u76ee\u7684\u3001\u53d8\u66f4\u7a97\u53e3\u6216\u5de1\u68c0\u8303\u56f4',
  serviceName: '\u670d\u52a1\u540d\u79f0',
  serviceNamePlaceholder: '\u4f8b\u5982 nginx / docker / sshd',
  playbookName: 'Playbook \u540d\u79f0',
  playbookNamePlaceholder: '\u4f8b\u5982 deploy-app.yml',
  playbookContent: 'Playbook \u5185\u5bb9',
  playbookContentPlaceholder: '\u4f8b\u5982\uff1a- hosts: targets\n  gather_facts: false\n  tasks:\n    - name: check service\n      shell: systemctl status nginx',
  timeout: '\u8d85\u65f6(\u79d2)',
  command: '\u6267\u884c\u547d\u4ee4',
  commandPlaceholder: '\u4f8b\u5982\uff1auptime && df -h && free -m',
  pythonPlaceholder: "例如：python3 - <<'PY'\nimport os\nprint(os.uname())\nPY",
  strategy: '\u6267\u884c\u7b56\u7565',
  executionMode: '\u6267\u884c\u65b9\u5f0f',
  sshModeLabel: 'SSH \u76f4\u8fde',
  ansibleModeLabel: 'Ansible \u5206\u53d1',
  modeHint: '\u65b9\u5f0f\u8bf4\u660e',
  sshMode: 'SSH \u76f4\u8fde\u6267\u884c\uff0c\u9002\u5408\u70b9\u72b6\u8bca\u65ad\u4e0e\u63a7\u5236\u7aef\u672a\u5b89\u88c5 Ansible \u7684\u573a\u666f\u3002',
  ansibleMode: 'Ansible \u7edf\u4e00\u5206\u53d1\uff0c\u9002\u5408\u6279\u91cf\u547d\u4ee4\u548c\u6279\u91cf\u5de1\u68c0\uff1b\u63a7\u5236\u7aef\u4e0d\u53ef\u7528\u65f6\u4f1a\u6309\u914d\u7f6e\u56de\u9000 SSH\u3002',
  playbookOnlyAnsible: 'Playbook \u4efb\u52a1\u4ec5\u652f\u6301 Ansible \u6267\u884c\uff0c\u4f1a\u81ea\u52a8\u9501\u5b9a\u4e3a Ansible \u5206\u53d1\u3002',
  continueOnError: '\u5931\u8d25\u7ee7\u7eed',
  stopOnError: '\u5931\u8d25\u5373\u505c',
  selectTargets: '选择执行资源',
  k8sTip: 'K8s 任务会通过集群 API 执行，适合 Pod 重启、Pod 内诊断命令和工作负载伸缩。',
  searchHostPlaceholder: '搜索资源名称 / IP',
  businessLine: '系统',
  environment: '\u73af\u5883',
  status: '\u72b6\u6001',
  matchedHosts: '\u547d\u4e2d',
  queryHosts: '查询资源',
  resetFilters: '\u91cd\u7f6e\u7b5b\u9009',
  selectCurrent: '\u5168\u9009\u5f53\u524d',
  clearSelection: '\u6e05\u7a7a\u9009\u62e9',
  onlineHosts: '\u5728\u7ebf',
  warningHosts: '\u544a\u8b66',
  offlineHosts: '\u79bb\u7ebf',
  hostName: '资源名称',
  ipAddress: 'IP \u5730\u5740',
  submitTip: '下发前请确认执行账号、维护窗口与目标资源范围。',
  executeNow: '\u7acb\u5373\u6267\u884c',
  history: '\u4efb\u52a1\u5386\u53f2',
  searchTaskPlaceholder: '\u641c\u7d22\u4efb\u52a1\u540d\u79f0 / \u6267\u884c\u4eba',
  result: '\u6267\u884c\u7ed3\u679c',
  type: '\u7c7b\u578b',
  executor: '\u6267\u884c\u4eba',
  targetCount: '\u76ee\u6807\u6570',
  successFailed: '\u6210\u529f/\u5931\u8d25',
  summary: '\u6267\u884c\u6458\u8981',
  finishedAt: '\u5b8c\u6210\u65f6\u95f4',
  actions: '\u64cd\u4f5c',
  detail: '\u8be6\u60c5',
  rerun: '\u91cd\u8dd1',
  cancelTask: '\u7ec8\u6b62',
  batchCancel: '\u6279\u91cf\u7ec8\u6b62',
  successRate: '\u6210\u529f\u7387',
  success: '\u6210\u529f',
  failed: '\u5931\u8d25',
  skipped: '\u8df3\u8fc7',
  detailTitle: '\u4efb\u52a1\u8be6\u60c5',
  emptyDesc: '\u6682\u65e0\u989d\u5916\u8bf4\u660e',
  host: '\u4e3b\u673a',
  duration: '\u8017\u65f6',
  output: '\u7ed3\u679c\u8f93\u51fa',
  executionOverview: '\u6267\u884c\u6982\u89c8',
  executionDetails: '\u4e3b\u673a\u6267\u884c\u660e\u7ec6',
  triggerSource: '\u89e6\u53d1\u6765\u6e90',
  riskLevel: '\u98ce\u9669',
  startTask: '\u6267\u884c',
  startedAt: '\u5f00\u59cb\u65f6\u95f4',
  targetHosts: '\u76ee\u6807\u4e3b\u673a',
  targetResources: '目标资源',
  targetResource: '目标资源',
  emptyTargets: '\u6682\u65e0\u76ee\u6807\u4e3b\u673a\u5feb\u7167',
  taskPayload: '\u4efb\u52a1\u53c2\u6570',
  cancelRequestedBy: '\u7ec8\u6b62\u53d1\u8d77\u4eba',
  cancelRequestedAt: '\u7ec8\u6b62\u7533\u8bf7\u65f6\u95f4',
  emptyHosts: '暂无匹配执行资源',
  emptyTasks: '\u6682\u65e0\u4efb\u52a1\u8bb0\u5f55',
  emptyExecutions: '\u6682\u65e0\u6267\u884c\u660e\u7ec6',
  saveTemplateTitle: '\u4fdd\u5b58\u4e3a\u6a21\u677f',
  saveTemplatePrompt: '\u8bf7\u8f93\u5165\u6a21\u677f\u540d\u79f0',
  saveTemplateSuccess: '\u6a21\u677f\u5df2\u4fdd\u5b58',
  deleteTemplateConfirm: '\u786e\u8ba4\u5220\u9664\u8be5\u6a21\u677f\uff1f',
  deleteTemplateSuccess: '\u6a21\u677f\u5df2\u5220\u9664',
  templateApplySuccess: '\u5df2\u5957\u7528\u6a21\u677f',
  snippetApplySuccess: '\u5df2\u586b\u5165\u5e38\u7528\u547d\u4ee4',
  taskExecuted: '\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u6b63\u5728\u540e\u53f0\u6267\u884c',
  taskRerun: '\u4efb\u52a1\u5df2\u91cd\u8dd1\uff0c\u6b63\u5728\u540e\u53f0\u6267\u884c',
  cancelConfirm: '\u786e\u8ba4\u7ec8\u6b62\u8be5\u4efb\u52a1\uff1f',
  cancelBatchConfirm: '\u786e\u8ba4\u6279\u91cf\u7ec8\u6b62\u6240\u9009\u4efb\u52a1\uff1f',
  cancelSuccess: '\u5df2\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42',
  batchCancelSuccess: '\u6279\u91cf\u7ec8\u6b62\u8bf7\u6c42\u5df2\u63d0\u4ea4',
  loadTargetsFailed: '加载执行资源失败',
  loadTemplatesFailed: '\u52a0\u8f7d\u4efb\u52a1\u6a21\u677f\u5931\u8d25',
  loadTasksFailed: '\u52a0\u8f7d\u4efb\u52a1\u5386\u53f2\u5931\u8d25',
  loadTaskDetailFailed: '\u52a0\u8f7d\u4efb\u52a1\u8be6\u60c5\u5931\u8d25',
  saveTemplateFailed: '\u4fdd\u5b58\u4efb\u52a1\u6a21\u677f\u5931\u8d25',
  deleteTemplateFailed: '\u5220\u9664\u4efb\u52a1\u6a21\u677f\u5931\u8d25',
  taskNameRequired: '\u8bf7\u586b\u5199\u4efb\u52a1\u540d\u79f0',
  hostRequired: '请至少选择一个主机资源',
  runCommandConfirm: '\u5c06\u6267\u884c\u6279\u91cf\u547d\u4ee4\uff0c\u8bf7\u786e\u8ba4\u547d\u4ee4\u5185\u5bb9\u548c\u7ef4\u62a4\u7a97\u53e3\u3002',
  overLimitConfirm: '\u76ee\u6807\u4e3b\u673a\u8d85\u8fc7 20 \u53f0\uff0c\u5efa\u8bae\u518d\u6b21\u786e\u8ba4\u5f71\u54cd\u8303\u56f4\u3002',
  confirmExecuteTitle: '\u786e\u8ba4\u6267\u884c\u4efb\u52a1',
  confirmExecute: '\u786e\u8ba4\u6267\u884c',
  executeTaskFailed: '\u4efb\u52a1\u6267\u884c\u5931\u8d25',
  rerunTaskFailed: '\u4efb\u52a1\u91cd\u8dd1\u5931\u8d25',
  cancelTaskFailed: '\u7ec8\u6b62\u4efb\u52a1\u5931\u8d25',
  batchCancelFailed: '\u6279\u91cf\u7ec8\u6b62\u5931\u8d25',
  cancel: '\u53d6\u6d88',
}
const innerTabs = [
  { key: 'dispatch', label: '\u4efb\u52a1\u4e0b\u53d1', desc: '\u9009\u62e9\u76ee\u6807\u4e3b\u673a\u5e76\u7acb\u5373\u6267\u884c' },
  { key: 'library', label: '\u6a21\u677f\u5e93', desc: '维护可复用执行模板' },
  { key: 'history', label: '\u4efb\u52a1\u5386\u53f2', desc: '\u67e5\u770b\u7ed3\u679c\u3001\u91cd\u8dd1\u4e0e\u7ec8\u6b62\u4efb\u52a1' },
]
const taskTypeOptions = [
  { label: '\u6279\u91cf\u547d\u4ee4\u6267\u884c', value: 'run_command' },
  { label: 'Ansible Playbook \u6267\u884c', value: 'run_playbook' },
  { label: 'SSH \u8fde\u901a\u6027\u6821\u9a8c', value: 'check_connection' },
  { label: '\u4e3b\u673a\u4fe1\u606f\u5237\u65b0', value: 'refresh_metrics' },
  { label: '\u670d\u52a1\u72b6\u6001\u5de1\u68c0', value: 'service_status' },
  { label: 'K8s Pod 重启', value: 'k8s_restart_pod' },
  { label: 'K8s Pod 命令执行', value: 'k8s_pod_exec' },
  { label: 'K8s 工作负载伸缩', value: 'k8s_scale_workload' },
]
const executionTypeOptions = [
  { label: 'Shell 脚本', value: 'shell', targetType: 'host', taskType: 'run_command', executionMode: 'ansible', desc: '在主机资源上执行 Shell 命令或脚本片段。' },
  { label: 'Python 脚本', value: 'python', targetType: 'host', taskType: 'run_command', executionMode: 'ansible', desc: '通过 Python 解释器执行诊断、巡检或自动化脚本。' },
  { label: 'Ansible Playbook', value: 'playbook', targetType: 'host', taskType: 'run_playbook', executionMode: 'ansible', desc: '执行结构化 Playbook，适合固化编排流程。' },
  { label: 'K8s 命令', value: 'k8s_command', targetType: 'k8s', taskType: 'k8s_pod_exec', executionMode: 'k8s_api', desc: '通过 K8s API 在目标集群或 Pod 内执行操作。' },
]
const hostTaskTypeOptions = taskTypeOptions.filter(item => !item.value.startsWith('k8s_'))
const k8sTaskTypeOptions = taskTypeOptions.filter(item => item.value.startsWith('k8s_'))
const targetTypeOptions = [
  { label: ui.hostResource, value: 'host' },
  { label: ui.k8sResource, value: 'k8s' },
]
const executionModeOptions = [
  { label: ui.sshModeLabel, value: 'ssh' },
  { label: ui.ansibleModeLabel, value: 'ansible' },
  { label: 'K8s API', value: 'k8s_api' },
]
const hostStatusOptions = [
  { label: '\u5728\u7ebf', value: 'online' },
  { label: '\u79bb\u7ebf', value: 'offline' },
  { label: '\u544a\u8b66', value: 'warning' },
]
const taskStatusOptions = [
  { label: '\u6392\u961f\u4e2d', value: 'pending' },
  { label: '\u6267\u884c\u4e2d', value: 'running' },
  { label: '\u5168\u90e8\u6210\u529f', value: 'success' },
  { label: '\u90e8\u5206\u6210\u529f', value: 'partial' },
  { label: '\u6267\u884c\u5931\u8d25', value: 'failed' },
  { label: '\u5df2\u7ec8\u6b62', value: 'canceled' },
]
const triggerSourceOptions = [
  { label: '\u624b\u52a8\u89e6\u53d1', value: 'manual' },
  { label: 'AIOps \u751f\u6210', value: 'aiops' },
  { label: '\u5b9a\u65f6\u89e6\u53d1', value: 'schedule' },
  { label: '\u4e8b\u4ef6\u4e2d\u5fc3\u89e6\u53d1', value: 'event_center' },
  { label: 'API \u89e6\u53d1', value: 'api' },
]
const riskLevelOptions = [
  { label: '\u4f4e', value: 'low' },
  { label: '\u4e2d', value: 'medium' },
  { label: '\u9ad8', value: 'high' },
  { label: '\u6781\u9ad8', value: 'critical' },
]
const commandSnippets = [
  { key: 'health', title: '\u5065\u5eb7\u5ea6\u5feb\u901f\u6821\u9a8c', scene: '\u53d1\u5e03\u524d', desc: '\u67e5\u770b\u8d1f\u8f7d\u3001\u78c1\u76d8\u3001\u5185\u5b58\u4e0e\u767b\u5f55\u7528\u6237', command: 'hostname && uptime && df -h && free -m && who', name: '\u53d1\u5e03\u524d\u5065\u5eb7\u5ea6\u6821\u9a8c', description: '\u9002\u5408\u53d1\u5e03\u524d\u5feb\u901f\u6838\u67e5\u4e3b\u673a\u5065\u5eb7\u72b6\u6001\u3002', execution_mode: 'ansible', timeout_seconds: 30, execution_strategy: 'stop_on_error' },
  { key: 'network', title: '\u7f51\u7edc\u94fe\u8def\u8bca\u65ad', scene: '\u6545\u969c\u6392\u67e5', desc: '\u67e5\u770b IP\u3001\u8def\u7531\u548c\u7aef\u53e3\u76d1\u542c\u60c5\u51b5', command: 'ip addr && ip route && ss -tunlp | head -20', name: '\u7f51\u7edc\u8fde\u901a\u6392\u67e5', description: '\u9002\u5408\u7f51\u7edc\u6296\u52a8\u3001IP \u6216\u7aef\u53e3\u95ee\u9898\u6392\u67e5\u3002', execution_mode: 'ansible', timeout_seconds: 30, execution_strategy: 'continue' },
  { key: 'logs', title: '\u65e5\u5fd7\u4e0e\u8fdb\u7a0b\u5de1\u68c0', scene: '\u53d1\u5e03\u540e', desc: '\u67e5\u770b\u8fdb\u7a0b\u548c systemd \u6700\u8fd1\u65e5\u5fd7', command: 'ps -ef | head -20 && journalctl -n 100 --no-pager', name: '\u8fdb\u7a0b\u4e0e\u65e5\u5fd7\u5de1\u68c0', description: '\u9002\u5408\u53d1\u5e03\u540e\u5feb\u901f\u786e\u8ba4\u8fdb\u7a0b\u4e0e\u65e5\u5fd7\u3002', execution_mode: 'ansible', timeout_seconds: 45, execution_strategy: 'continue' },
]
const dispatchAdvice = ['\u9ad8\u98ce\u9669\u547d\u4ee4\u5efa\u8bae\u5148\u6309\u4e1a\u52a1\u7ebf\u6216\u73af\u5883\u5206\u6279\u4e0b\u53d1\u3002', '\u547d\u4ee4\u578b\u4efb\u52a1\u4f18\u5148\u4f7f\u7528\u5931\u8d25\u5373\u505c\uff0c\u51cf\u5c11\u653e\u5927\u5f71\u54cd\u3002', '\u4efb\u52a1\u540d\u79f0\u5c3d\u91cf\u5e26\u4e0a\u7a97\u53e3\u3001\u8303\u56f4\u4e0e\u64cd\u4f5c\u76ee\u6807\u3002']
const libraryAdvice = ['\u6a21\u677f\u8bf4\u660e\u91cc\u5199\u6e05\u9002\u7528\u573a\u666f\u3001\u56de\u6eda\u65b9\u6cd5\u548c\u7ef4\u62a4\u7a97\u53e3\u3002', '\u9ad8\u9891\u547d\u4ee4\u4f18\u5148\u6c89\u6dc0\u6210\u6a21\u677f\uff0c\u907f\u514d\u4eba\u5de5\u590d\u5236\u7c98\u8d34\u51fa\u9519\u3002', '\u6279\u91cf\u547d\u4ee4\u5efa\u8bae\u4f18\u5148\u4fdd\u6301\u53ea\u8bfb\uff0c\u53d8\u66f4\u547d\u4ee4\u5355\u72ec\u5ba1\u6279\u3002']
const templateEditorAdvice = ['\u6a21\u677f\u540d\u79f0\u5efa\u8bae\u5e26\u4e0a\u573a\u666f\u3001\u670d\u52a1\u6216\u7a97\u53e3\u4fe1\u606f\uff0c\u65b9\u4fbf\u641c\u7d22\u590d\u7528\u3002', '\u547d\u4ee4\u6a21\u677f\u9002\u5408\u505a\u5feb\u901f\u5de1\u68c0\uff1bPlaybook \u6a21\u677f\u66f4\u9002\u5408\u56fa\u5316\u68c0\u67e5\u6b65\u9aa4\u3002', 'Playbook \u5185\u5bb9\u5efa\u8bae\u4f18\u5148\u4fdd\u6301 gather_facts: false \u548c changed_when: false\uff0c\u51cf\u5c11\u5bf9\u76ee\u6807\u4e3b\u673a\u7684\u6253\u6270\u3002']
const playbookExample = '- hosts: targets\n  gather_facts: false\n  tasks:\n    - name: check app process\n      shell: ps -ef | grep myapp | grep -v grep\n      changed_when: false\n    - name: tail recent log\n      shell: journalctl -u myapp -n 50 --no-pager\n      changed_when: false'
const props = defineProps({ resourceTree: { type: Array, default: () => [] } })
const activeTab = ref('dispatch')
const hostTableRef = ref(null)
const targetLoading = ref(false)
const taskLoading = ref(false)
const templateLoading = ref(false)
const submitting = ref(false)
const savingTemplate = ref(false)
const creatingTemplate = ref(false)
const templateCreateVisible = ref(false)
const templateEditorMode = ref('create')
const editingTemplateId = ref(null)
const lastTemplateDraftType = ref('check_connection')
const templateDetailVisible = ref(false)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailTask = ref(null)
const currentTemplate = ref(null)
const availableHosts = ref([])
const availableK8sResources = ref([])
const k8sClusters = ref([])
const k8sForm = ref({ cluster_id: '', namespace: 'default', name: '', container: '' })
const selectedK8sResourceId = ref('')
const selectedRows = ref([])
const selectedTaskRows = ref([])
const tasks = ref([])
const templates = ref([])
const taskTotal = ref(0)
const taskPage = ref(1)
const taskStats = ref({ total: 0, running: 0, pending: 0, canceled: 0, success_rate: 0, aiops_pending: 0, high_risk: 0, by_source: {} })
const targetFilters = ref({ search: '', environment: '', system: '', status: '' })
const taskFilters = ref({ search: '', target_type: '', execution_kind: '', status: '', trigger_source: '', risk_level: '' })
const templateFilters = ref({ search: '', execution_kind: '' })
const taskForm = ref(defaultTaskForm())
const templateDraft = ref(defaultTemplateDraft())
const executionKind = ref('shell')
const templateExecutionKind = ref('shell')
const presets = [
  { key: 'run_command', title: '\u6279\u91cf\u547d\u4ee4\u6267\u884c', desc: '\u9762\u5411\u8fd0\u7ef4\u53d8\u66f4\u548c\u4e34\u65f6\u5de1\u68c0\u7684\u4e00\u6b21\u6027\u4e0b\u53d1\u3002' },
  { key: 'run_playbook', title: 'Ansible Playbook \u6267\u884c', desc: '\u9002\u5408\u56fa\u5316\u5de1\u68c0\u6b65\u9aa4\u3001\u6279\u91cf\u9884\u68c0\u548c\u7edf\u4e00\u6267\u884c Playbook \u5267\u672c\u3002' },
  { key: 'check_connection', title: 'SSH \u8fde\u901a\u6027\u6821\u9a8c', desc: '\u6279\u91cf\u68c0\u67e5\u8d26\u53f7\u3001\u7aef\u53e3\u548c\u7f51\u7edc\u8fde\u901a\u72b6\u6001\u3002' },
  { key: 'refresh_metrics', title: '\u4e3b\u673a\u4fe1\u606f\u5237\u65b0', desc: '\u7edf\u4e00\u5237\u65b0 CPU\u3001\u5185\u5b58\u3001\u78c1\u76d8\u4e0e\u5728\u7ebf\u72b6\u6001\u3002' },
  { key: 'service_status', title: '\u670d\u52a1\u72b6\u6001\u5de1\u68c0', desc: '\u6309\u670d\u52a1\u540d\u6279\u91cf\u67e5\u770b systemd \u8fd0\u884c\u72b6\u6001\u3002' },
  { key: 'k8s_restart_pod', title: 'K8s Pod 重启', desc: '通过删除 Pod 触发控制器自动重建，适合异常 Pod 快速恢复。' },
  { key: 'k8s_pod_exec', title: 'K8s Pod 命令执行', desc: '在指定 Pod 内执行诊断命令，适合容器内状态排查。' },
  { key: 'k8s_scale_workload', title: 'K8s 工作负载伸缩', desc: '统一调整 Deployment 或 StatefulSet 副本数。' },
]
const envNodes = computed(() => props.resourceTree.filter(item => item.group_type === 'environment'))
const currentSystemOptions = computed(() => (envNodes.value.find(item => item.id === targetFilters.value.environment)?.children || []))
const filteredTemplates = computed(() => {
  const keyword = (templateFilters.value.search || '').trim().toLowerCase()
  return templates.value.filter((item) => {
    const matchKeyword = !keyword || [item.name, item.description, item.created_by, item.task_type_display, item.execution_mode_display].some(value => String(value || '').toLowerCase().includes(keyword))
    const matchType = !templateFilters.value.execution_kind || detectExecutionKind(item) === templateFilters.value.execution_kind
    return matchKeyword && matchType
  })
})
const templateDialogTitle = computed(() => (templateEditorMode.value === 'edit' ? ui.editTemplateTitle : ui.createTemplateTitle))
const templateDialogSubmitText = computed(() => (templateEditorMode.value === 'edit' ? ui.updateTemplateSubmit : ui.createTemplateSubmit))
const templateDraftTypeLabel = computed(() => executionKindLabel(templateExecutionKind.value))
const selectedResourceIds = computed(() => selectedRows.value.map(item => item.id))
const selectedHostIds = selectedResourceIds
const selectedTargetCount = computed(() => taskForm.value.target_type === 'k8s' ? (k8sForm.value.cluster_id && k8sForm.value.name ? 1 : 0) : selectedHostIds.value.length)
const currentTaskTypeLabel = computed(() => taskTypeLabel(taskForm.value.task_type))
const currentExecutionKindLabel = computed(() => executionKindLabel(executionKind.value))
const selectedCancelableTaskIds = computed(() => selectedTaskRows.value.filter(canCancelTask).map(item => item.id))
const selectedStats = computed(() => selectedRows.value.reduce((summary, item) => {
  if (item.status === 'online') summary.online += 1
  if (item.status === 'warning') summary.warning += 1
  if (item.status === 'offline') summary.offline += 1
  return summary
}, { online: 0, offline: 0, warning: 0 }))
const sourceCards = computed(() => {
  const bySource = taskStats.value.by_source || {}
  const byTargetType = taskStats.value.by_target_type || {}
  return [
    { key: 'all', label: '\u5168\u90e8\u4efb\u52a1', source: '', value: taskStats.value.total || 0, desc: '\u7edf\u4e00\u4efb\u52a1\u6c60' },
    { key: 'k8s', label: 'K8s', source: '', targetType: 'k8s', value: byTargetType.k8s || 0, desc: '非主机资源任务' },
    { key: 'aiops', label: 'AIOps', source: 'aiops', value: bySource.aiops || 0, desc: '\u667a\u80fd\u52a9\u624b\u751f\u6210' },
    { key: 'schedule', label: '\u8ba1\u5212\u4efb\u52a1', source: 'schedule', value: bySource.schedule || 0, desc: '\u5b9a\u65f6\u7f16\u6392\u89e6\u53d1' },
    { key: 'manual', label: '\u4eba\u5de5\u4e0b\u53d1', source: 'manual', value: bySource.manual || 0, desc: '\u9875\u9762\u76f4\u63a5\u521b\u5efa' },
  ]
})
const activeTaskTypeOptions = computed(() => taskForm.value.target_type === 'k8s' ? k8sTaskTypeOptions : hostTaskTypeOptions)
const activePresets = computed(() => presets.filter(item => taskForm.value.target_type === 'k8s' ? item.key.startsWith('k8s_') : !item.key.startsWith('k8s_')))
const activeExecutionTypeOptions = computed(() => executionTypeOptions.filter(item => taskForm.value.target_type === 'k8s' ? item.targetType === 'k8s' : item.targetType === 'host'))
function defaultPayload() { return { command: '', script_kind: 'shell', service_name: '', playbook_name: '', playbook_content: '', workload_type: 'deployment', replicas: 1 } }
function defaultTaskForm() { return { name: '', target_type: 'host', task_type: 'run_command', description: '', execution_mode: 'ansible', execution_strategy: 'continue', timeout_seconds: 30, payload: buildPayloadByExecutionKind('shell') } }
function defaultTemplateDraft() { return { name: '', target_type: 'host', task_type: 'run_command', description: '', execution_mode: 'ansible', execution_strategy: 'continue', timeout_seconds: 30, payload: buildPayloadByExecutionKind('shell') } }
function buildPresetPayload(taskType) {
  if (taskType === 'run_command') return { ...defaultPayload(), command: 'uptime && df -h && free -m' }
  if (taskType === 'run_playbook') return { ...defaultPayload(), playbook_name: 'service-health.yml', playbook_content: playbookExample }
  if (taskType === 'service_status') return { ...defaultPayload(), service_name: 'nginx' }
  if (taskType === 'k8s_pod_exec') return { ...defaultPayload(), command: 'pwd && ls -lah /app' }
  if (taskType === 'k8s_scale_workload') return { ...defaultPayload(), workload_type: 'deployment', replicas: 2 }
  return defaultPayload()
}
function buildPayloadByExecutionKind(kind) {
  if (kind === 'python') return { ...defaultPayload(), script_kind: 'python', command: "python3 - <<'PY'\nimport os\nprint(os.uname())\nPY" }
  if (kind === 'playbook') return buildPresetPayload('run_playbook')
  if (kind === 'k8s_command') return buildPresetPayload('k8s_pod_exec')
  return { ...defaultPayload(), script_kind: 'shell', command: 'uptime && df -h' }
}
function handleSelectionChange(rows) { selectedRows.value = rows }
function handleTaskHistorySelectionChange(rows) { selectedTaskRows.value = rows }
function executionStrategyLabel(strategy) { return strategy === 'stop_on_error' ? ui.stopOnError : ui.continueOnError }
function executionModeLabel(mode, display) { return display || executionModeOptions.find(item => item.value === mode)?.label || mode || '-' }
function executionModeHint(mode, taskType) { if (taskType === 'run_playbook') return ui.playbookOnlyAnsible; return mode === 'ansible' ? ui.ansibleMode : ui.sshMode }
function k8sResourceLabel(resource) {
  return [resource.cluster_name || resource.name, resource.environment_name, resource.system_name].filter(Boolean).join(' / ')
}
function detectExecutionKind(source = {}) {
  const taskType = source.task_type || ''
  if (taskType.startsWith('k8s_') || source.target_type === 'k8s') return 'k8s_command'
  if (taskType === 'run_playbook') return 'playbook'
  if (taskType === 'run_command' && source.payload?.script_kind === 'python') return 'python'
  return 'shell'
}
function executionKindLabel(kind) {
  return executionTypeOptions.find(item => item.value === kind)?.label || kind || '-'
}
function templateExecutionKindLabel(template) {
  return executionKindLabel(detectExecutionKind(template))
}
function normalizePayloadByType(taskType, source = {}) {
  if (taskType === 'run_command') return { command: (source.command || '').trim(), script_kind: source.script_kind === 'python' ? 'python' : 'shell' }
  if (taskType === 'run_playbook') return { playbook_name: (source.playbook_name || '').trim(), playbook_content: (source.playbook_content || '').trim() }
  if (taskType === 'service_status') return { service_name: (source.service_name || '').trim() }
  if (taskType === 'k8s_pod_exec') return { command: (source.command || '').trim(), container: (k8sForm.value.container || '').trim() }
  if (taskType === 'k8s_scale_workload') return { workload_type: source.workload_type || 'deployment', replicas: Number(source.replicas || 0) }
  return {}
}
function validatePayloadByType(taskType, payload) {
  if (taskType === 'run_command' && !payload.command) return ElMessage.warning(ui.commandRequired), false
  if (taskType === 'run_playbook' && !payload.playbook_content) return ElMessage.warning(ui.playbookRequired), false
  if (taskType === 'service_status' && !payload.service_name) return ElMessage.warning(ui.serviceRequired), false
  if (taskType === 'k8s_pod_exec' && !payload.command) return ElMessage.warning(ui.commandRequired), false
  if (taskType.startsWith('k8s_') && !k8sForm.value.cluster_id) return ElMessage.warning('请选择 K8s 集群'), false
  if (taskType.startsWith('k8s_') && !k8sForm.value.name) return ElMessage.warning(taskType === 'k8s_scale_workload' ? '请填写工作负载名称' : '请填写 Pod 名称'), false
  return true
}
function normalizePayload() { return normalizePayloadByType(taskForm.value.task_type, taskForm.value.payload || {}) }
function validateTaskPayload(payload) { return validatePayloadByType(taskForm.value.task_type, payload) }
function templatePayloadPreview(template) {
  if (template.task_type === 'run_command') return template.payload?.command || ''
  if (template.task_type === 'run_playbook') return template.payload?.playbook_name || template.payload?.playbook_content || ''
  if (template.task_type === 'service_status') return template.payload?.service_name || ''
  return ''
}
function templatePreviewLabel(template) {
  if (template.task_type === 'run_command') return ui.command
  if (template.task_type === 'run_playbook') return ui.playbookContent
  return ui.serviceDetail
}
function formatPayloadJson(payload) { return JSON.stringify(payload || {}, null, 2) }
function taskTypeLabel(taskType) { return taskTypeOptions.find(item => item.value === taskType)?.label || taskType || '-' }
function buildTemplateDraft(source = {}) {
  const taskType = source.task_type || 'check_connection'
  const targetType = source.target_type || (taskType.startsWith('k8s_') ? 'k8s' : 'host')
  return {
    name: source.name || '',
    target_type: targetType,
    task_type: taskType,
    description: source.description || '',
    execution_mode: source.execution_mode || (targetType === 'k8s' ? 'k8s_api' : (['run_command', 'run_playbook'].includes(taskType) ? 'ansible' : 'ssh')),
    execution_strategy: source.execution_strategy || 'continue',
    timeout_seconds: source.timeout_seconds || 15,
    payload: {
      ...defaultPayload(),
      command: source.payload?.command || '',
      script_kind: source.payload?.script_kind || 'shell',
      service_name: source.payload?.service_name || '',
      playbook_name: source.payload?.playbook_name || '',
      playbook_content: source.payload?.playbook_content || '',
      workload_type: source.payload?.workload_type || 'deployment',
      replicas: source.payload?.replicas ?? 1,
    },
  }
}
function applyTemplate(template) {
  executionKind.value = detectExecutionKind(template)
  taskForm.value = {
    name: template.name,
    target_type: template.target_type || (template.task_type?.startsWith('k8s_') ? 'k8s' : 'host'),
    task_type: template.task_type,
    description: template.description || '',
    execution_mode: template.execution_mode || (template.task_type?.startsWith('k8s_') ? 'k8s_api' : (['run_command', 'run_playbook'].includes(template.task_type) ? 'ansible' : 'ssh')),
    execution_strategy: template.execution_strategy,
    timeout_seconds: template.timeout_seconds,
    payload: {
      ...defaultPayload(),
      command: template.payload?.command || '',
      script_kind: template.payload?.script_kind || detectExecutionKind(template),
      service_name: template.payload?.service_name || '',
      playbook_name: template.payload?.playbook_name || '',
      playbook_content: template.payload?.playbook_content || '',
      workload_type: template.payload?.workload_type || 'deployment',
      replicas: template.payload?.replicas ?? 1,
    },
  }
  activeTab.value = 'dispatch'
  templateDetailVisible.value = false
  ElMessage.success(ui.templateApplySuccess)
}
function applyCommandSnippet(snippet) {
  taskForm.value.task_type = 'run_command'
  taskForm.value.name = snippet.name
  taskForm.value.description = snippet.description
  taskForm.value.execution_mode = snippet.execution_mode || 'ansible'
  taskForm.value.execution_strategy = snippet.execution_strategy
  taskForm.value.timeout_seconds = snippet.timeout_seconds
  taskForm.value.payload = { ...defaultPayload(), command: snippet.command }
  activeTab.value = 'dispatch'
  ElMessage.success(ui.snippetApplySuccess)
}
function canCancelTask(task) { return ['pending', 'running'].includes(task.status) && !task.cancel_requested }
function canExecuteTask(task) { return task.status === 'pending' && !task.cancel_requested }
function riskTagType(risk) { if (risk === 'critical' || risk === 'high') return 'danger'; if (risk === 'medium') return 'warning'; return 'success' }
function applySourceFilter(source, targetType = '') { taskFilters.value.trigger_source = source; taskFilters.value.target_type = targetType; taskPage.value = 1; activeTab.value = 'history'; fetchTasks() }
function handleEnvironmentChange() { targetFilters.value.system = '' }
function selectTargetType(targetType) {
  if (taskForm.value.target_type === targetType) return
  taskForm.value.target_type = targetType
  handleTargetTypeChange()
}
function applyExecutionKind(kind) {
  const option = executionTypeOptions.find(item => item.value === kind) || executionTypeOptions[0]
  executionKind.value = option.value
  taskForm.value.target_type = option.targetType
  taskForm.value.task_type = option.taskType
  taskForm.value.execution_mode = option.executionMode
  taskForm.value.name = option.label
  taskForm.value.description = option.desc
  taskForm.value.timeout_seconds = option.value === 'playbook' ? 60 : 30
  taskForm.value.execution_strategy = option.value === 'shell' || option.value === 'python' || option.value === 'playbook' ? 'stop_on_error' : 'continue'
  taskForm.value.payload = buildPayloadByExecutionKind(option.value)
  if (option.targetType === 'k8s') {
    k8sForm.value = { cluster_id: '', namespace: 'default', name: '', container: '' }
  } else {
    selectedK8sResourceId.value = ''
  }
}
function handleTargetTypeChange() {
  clearSelection()
  if (taskForm.value.target_type === 'k8s') {
    applyExecutionKind('k8s_command')
  } else {
    applyExecutionKind('shell')
  }
}
function handleTaskTypeChange() {
  if (taskForm.value.task_type.startsWith('k8s_')) {
    taskForm.value.target_type = 'k8s'
    taskForm.value.execution_mode = 'k8s_api'
    taskForm.value.payload = { ...defaultPayload(), ...buildPresetPayload(taskForm.value.task_type), ...taskForm.value.payload }
    return
  }
  if (['run_command', 'run_playbook'].includes(taskForm.value.task_type)) taskForm.value.execution_mode = 'ansible'
  if (taskForm.value.task_type !== 'run_command') taskForm.value.payload.command = ''
  if (taskForm.value.task_type !== 'run_playbook') { taskForm.value.payload.playbook_name = ''; taskForm.value.payload.playbook_content = '' }
  if (taskForm.value.task_type !== 'service_status') taskForm.value.payload.service_name = ''
}
function handleTemplateDraftTypeChange() {
  const nextType = templateDraft.value.task_type
  const previousPreset = presets.find(item => item.key === lastTemplateDraftType.value)
  const nextPreset = presets.find(item => item.key === nextType)
  if (nextPreset) {
    if (!templateDraft.value.name || templateDraft.value.name === previousPreset?.title) templateDraft.value.name = nextPreset.title
    if (!templateDraft.value.description || templateDraft.value.description === previousPreset?.desc) templateDraft.value.description = nextPreset.desc
  }
  templateDraft.value.target_type = nextType.startsWith('k8s_') ? 'k8s' : 'host'
  if (['run_command', 'run_playbook'].includes(nextType)) templateDraft.value.execution_mode = 'ansible'
  if (nextType.startsWith('k8s_')) templateDraft.value.execution_mode = 'k8s_api'
  if (nextType !== 'run_command') templateDraft.value.payload.command = ''
  if (nextType !== 'run_playbook') { templateDraft.value.payload.playbook_name = ''; templateDraft.value.payload.playbook_content = '' }
  if (nextType !== 'service_status') templateDraft.value.payload.service_name = ''
  lastTemplateDraftType.value = nextType
}
function handleTemplateExecutionKindChange(kind) {
  const option = executionTypeOptions.find(item => item.value === kind) || executionTypeOptions[0]
  templateExecutionKind.value = option.value
  templateDraft.value.task_type = option.taskType
  templateDraft.value.target_type = option.targetType
  templateDraft.value.execution_mode = option.executionMode
  templateDraft.value.timeout_seconds = option.value === 'playbook' ? 60 : 30
  templateDraft.value.execution_strategy = option.value === 'k8s_command' ? 'continue' : 'stop_on_error'
  templateDraft.value.payload = buildPayloadByExecutionKind(option.value)
  if (!templateDraft.value.name || executionTypeOptions.some(item => item.label === templateDraft.value.name)) {
    templateDraft.value.name = option.label
  }
  if (!templateDraft.value.description || executionTypeOptions.some(item => item.desc === templateDraft.value.description)) {
    templateDraft.value.description = option.desc
  }
  lastTemplateDraftType.value = option.taskType
}
function applyTemplatePresetToDraft(preset) {
  templateDraft.value.task_type = preset.key
  templateDraft.value.target_type = preset.key.startsWith('k8s_') ? 'k8s' : 'host'
  templateDraft.value.name = preset.title
  templateDraft.value.description = preset.desc
  templateDraft.value.execution_mode = preset.key.startsWith('k8s_') ? 'k8s_api' : (['run_command', 'run_playbook'].includes(preset.key) ? 'ansible' : 'ssh')
  templateDraft.value.timeout_seconds = preset.key === 'run_playbook' ? 60 : preset.key === 'run_command' ? 30 : 15
  templateDraft.value.execution_strategy = ['run_command', 'run_playbook'].includes(preset.key) ? 'stop_on_error' : 'continue'
  templateDraft.value.payload = buildPresetPayload(preset.key)
  lastTemplateDraftType.value = preset.key
}
function openTemplateCreateDialog() {
  templateEditorMode.value = 'create'
  editingTemplateId.value = null
  templateExecutionKind.value = 'shell'
  templateDraft.value = buildTemplateDraft({
    task_type: 'run_command',
    name: 'Shell 脚本',
    description: '在主机资源上执行 Shell 命令或脚本片段。',
    execution_mode: 'ansible',
    execution_strategy: 'stop_on_error',
    timeout_seconds: 30,
    payload: buildPayloadByExecutionKind('shell'),
  })
  lastTemplateDraftType.value = templateDraft.value.task_type
  templateCreateVisible.value = true
}
function openTemplateEditDialog(template) {
  templateEditorMode.value = 'edit'
  editingTemplateId.value = template.id
  templateDraft.value = buildTemplateDraft(template)
  templateExecutionKind.value = detectExecutionKind(template)
  lastTemplateDraftType.value = templateDraft.value.task_type
  templateCreateVisible.value = true
}
function openTemplateDetail(template) {
  currentTemplate.value = { ...template, payload: { ...defaultPayload(), ...(template.payload || {}) } }
  templateDetailVisible.value = true
}
function resetTemplateFilters() { templateFilters.value = { search: '', execution_kind: '' } }
function applyPreset(preset) {
  taskForm.value.task_type = preset.key
  taskForm.value.target_type = preset.key.startsWith('k8s_') ? 'k8s' : 'host'
  taskForm.value.name = preset.title
  taskForm.value.description = preset.desc
  taskForm.value.execution_mode = preset.key.startsWith('k8s_') ? 'k8s_api' : (['run_command', 'run_playbook'].includes(preset.key) ? 'ansible' : 'ssh')
  taskForm.value.timeout_seconds = preset.key === 'run_playbook' ? 60 : preset.key === 'run_command' ? 30 : 15
  taskForm.value.execution_strategy = ['run_command', 'run_playbook'].includes(preset.key) ? 'stop_on_error' : 'continue'
  taskForm.value.payload = buildPresetPayload(preset.key)
}
function taskStatusType(status) { if (status === 'success') return 'success'; if (status === 'partial') return 'warning'; if (status === 'failed' || status === 'canceled') return 'danger'; return 'info' }
function executionStatusType(status) { if (status === 'success') return 'success'; if (status === 'failed' || status === 'canceled') return 'danger'; if (status === 'running' || status === 'partial') return 'warning'; return 'info' }
function formatDateTime(value) { return value ? value.replace('T', ' ').slice(0, 19) : '-' }
async function fetchTargets() {
  targetLoading.value = true
  try {
    const res = await getTaskResourceOptions({ ...targetFilters.value, resource_type: 'host' })
    availableHosts.value = Array.isArray(res) ? res : (res.results || [])
  } catch (error) {
    ElMessage.error(ui.loadTargetsFailed)
  } finally {
    targetLoading.value = false
  }
}
async function fetchStats() {
  try {
    const res = await getHostTaskStats()
    taskStats.value = {
      total: res?.total || 0,
      running: res?.running || 0,
      pending: res?.pending || 0,
      canceled: res?.canceled || 0,
      success_rate: res?.success_rate || 0,
      aiops_pending: res?.aiops_pending || 0,
      high_risk: res?.high_risk || 0,
      by_source: res?.by_source || {},
      by_target_type: res?.by_target_type || {},
    }
  } catch (error) {}
}
async function fetchK8sClusters() {
  try { k8sClusters.value = await getK8sClusters() } catch (error) { k8sClusters.value = [] }
}
async function fetchK8sResources() {
  try {
    const res = await getTaskResourceOptions({ resource_type: 'k8s', status: 'active' })
    availableK8sResources.value = Array.isArray(res) ? res : (res.results || [])
  } catch (error) {
    availableK8sResources.value = []
  }
}
function applyK8sResource(resourceId) {
  const resource = availableK8sResources.value.find(item => item.id === resourceId)
  if (!resource) return
  k8sForm.value.cluster_id = resource.cluster || ''
  k8sForm.value.namespace = k8sForm.value.namespace || 'default'
}
async function fetchTemplates() {
  templateLoading.value = true
  try {
    const res = await getHostTaskTemplates()
    templates.value = res.results || res || []
  } catch (error) {
    ElMessage.error(ui.loadTemplatesFailed)
  } finally {
    templateLoading.value = false
  }
}
async function fetchTasks() {
  taskLoading.value = true
  try {
    const taskTypeFilter = executionTypeOptions.find(item => item.value === taskFilters.value.execution_kind)?.taskType
    const res = await getHostTasks({
      page: taskPage.value,
      search: taskFilters.value.search || undefined,
      target_type: taskFilters.value.target_type || undefined,
      task_type: taskTypeFilter || undefined,
      status: taskFilters.value.status || undefined,
      trigger_source: taskFilters.value.trigger_source || undefined,
      risk_level: taskFilters.value.risk_level || undefined,
    })
    tasks.value = res.results || res
    taskTotal.value = res.count || tasks.value.length
  } catch (error) {
    ElMessage.error(ui.loadTasksFailed)
  } finally {
    taskLoading.value = false
  }
}
function selectAllCurrent() { hostTableRef.value?.clearSelection(); availableHosts.value.forEach(row => hostTableRef.value?.toggleRowSelection(row, true)) }
function clearSelection() { hostTableRef.value?.clearSelection(); selectedRows.value = [] }
function resetTargetFilters() { targetFilters.value = { search: '', environment: '', system: '', status: '' }; clearSelection(); fetchTargets() }
function resetTaskFilters() { taskFilters.value = { search: '', target_type: '', execution_kind: '', status: '', trigger_source: '', risk_level: '' }; taskPage.value = 1; selectedTaskRows.value = []; fetchTasks() }
async function submitTemplateDraft() {
  const payload = normalizePayloadByType(templateDraft.value.task_type, templateDraft.value.payload || {})
  if (!templateDraft.value.name) return ElMessage.warning(ui.taskNameRequired)
  if (!validatePayloadByType(templateDraft.value.task_type, payload)) return
  const submitPayload = {
    name: templateDraft.value.name,
    target_type: templateDraft.value.target_type,
    task_type: templateDraft.value.task_type,
    description: templateDraft.value.description,
    payload,
    execution_mode: templateDraft.value.execution_mode,
    execution_strategy: templateDraft.value.execution_strategy,
    timeout_seconds: templateDraft.value.timeout_seconds,
  }
  creatingTemplate.value = true
  try {
    const saved = templateEditorMode.value === 'edit'
      ? await updateHostTaskTemplate(editingTemplateId.value, submitPayload)
      : await createHostTaskTemplate(submitPayload)
    ElMessage.success(templateEditorMode.value === 'edit' ? ui.templateUpdated : ui.templateCreated)
    templateCreateVisible.value = false
    currentTemplate.value = saved
    templateDetailVisible.value = true
    await fetchTemplates()
  } catch (error) {
    ElMessage.error(error?.response?.data?.payload || error?.response?.data?.detail || ui.saveTemplateFailed)
  } finally { creatingTemplate.value = false }
}
async function openDetail(task) {
  detailVisible.value = true
  detailLoading.value = true
  detailTask.value = task
  try {
    detailTask.value = await getHostTask(task.id)
  } catch (error) {
    detailVisible.value = false
    ElMessage.error(ui.loadTaskDetailFailed)
  } finally {
    detailLoading.value = false
  }
}
async function saveCurrentAsTemplate() {
  const payload = normalizePayload()
  if (!validateTaskPayload(payload)) return
  let templateName = taskForm.value.name || currentExecutionKindLabel.value || ''
  try {
    const { value } = await ElMessageBox.prompt(ui.saveTemplatePrompt, ui.saveTemplateTitle, { confirmButtonText: ui.saveAsTemplate, cancelButtonText: ui.cancel, inputValue: templateName, inputValidator: value => !!String(value || '').trim() })
    templateName = String(value || '').trim()
  } catch (error) { return }
  savingTemplate.value = true
  try {
    const created = await createHostTaskTemplate({ name: templateName, target_type: taskForm.value.target_type, task_type: taskForm.value.task_type, description: taskForm.value.description, payload, execution_mode: taskForm.value.execution_mode, execution_strategy: taskForm.value.execution_strategy, timeout_seconds: taskForm.value.timeout_seconds })
    ElMessage.success(ui.saveTemplateSuccess)
    await fetchTemplates()
    currentTemplate.value = created
    templateDetailVisible.value = true
    activeTab.value = 'library'
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || ui.saveTemplateFailed)
  } finally { savingTemplate.value = false }
}
async function removeTemplate(template) {
  try {
    await ElMessageBox.confirm(ui.deleteTemplateConfirm, ui.deleteTemplate, { type: 'warning', confirmButtonText: ui.deleteTemplate, cancelButtonText: ui.cancel })
  } catch (error) { return }
  try {
    await deleteHostTaskTemplate(template.id)
    ElMessage.success(ui.deleteTemplateSuccess)
    if (currentTemplate.value?.id === template.id) {
      currentTemplate.value = null
      templateDetailVisible.value = false
    }
    await fetchTemplates()
  } catch (error) { ElMessage.error(ui.deleteTemplateFailed) }
}
async function submitTask() {
  if (!taskForm.value.name) return ElMessage.warning(ui.taskNameRequired)
  if (taskForm.value.target_type === 'host' && !selectedHostIds.value.length) return ElMessage.warning(ui.hostRequired)
  const payload = normalizePayload()
  if (!validateTaskPayload(payload)) return
  const targetSummary = taskForm.value.target_type === 'k8s'
    ? `K8s：${k8sClusters.value.find(item => item.id === k8sForm.value.cluster_id)?.name || k8sForm.value.cluster_id}/${k8sForm.value.namespace || 'default'}/${k8sForm.value.name}`
    : `目标资源：${selectedHostIds.value.length} 个`
  const confirmLines = [`\u4efb\u52a1\u540d\u79f0\uff1a${taskForm.value.name}`, targetSummary, `\u6267\u884c\u7c7b\u578b\uff1a${currentExecutionKindLabel.value}`, `\u6267\u884c\u65b9\u5f0f\uff1a${executionModeLabel(taskForm.value.execution_mode)}`]
  if (taskForm.value.task_type === 'run_command') confirmLines.push(ui.runCommandConfirm)
  if (selectedHostIds.value.length > 20) confirmLines.push(ui.overLimitConfirm)
  try {
    await ElMessageBox.confirm(confirmLines.join('<br>'), ui.confirmExecuteTitle, { type: 'warning', dangerouslyUseHTMLString: true, confirmButtonText: ui.confirmExecute, cancelButtonText: ui.cancel })
  } catch (error) { return }
  submitting.value = true
  try {
    const submitPayload = {
      name: taskForm.value.name,
      target_type: taskForm.value.target_type,
      task_type: taskForm.value.task_type,
      description: taskForm.value.description,
      execution_mode: taskForm.value.execution_mode,
      execution_strategy: taskForm.value.execution_strategy,
      timeout_seconds: taskForm.value.timeout_seconds,
      selection_filters: { ...targetFilters.value },
      payload,
    }
    if (taskForm.value.target_type === 'k8s') {
      submitPayload.k8s_targets = [{
        cluster_id: k8sForm.value.cluster_id,
        namespace: k8sForm.value.namespace || 'default',
        name: k8sForm.value.name,
        kind: taskForm.value.task_type === 'k8s_scale_workload' ? taskForm.value.payload.workload_type : 'pod',
        container: k8sForm.value.container || '',
      }]
    } else {
      submitPayload.resource_ids = selectedHostIds.value
    }
    const task = await createHostTask(submitPayload)
    ElMessage.success(ui.taskExecuted)
    detailTask.value = task
    detailVisible.value = true
    taskForm.value = defaultTaskForm()
    applyPreset(presets.find(item => item.key === 'check_connection') || presets[0])
    clearSelection()
    activeTab.value = 'history'
    await Promise.all([fetchStats(), fetchTasks()])
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || ui.executeTaskFailed)
  } finally { submitting.value = false }
}
async function handleRerun(task) {
  try {
    const result = await rerunHostTask(task.id)
    ElMessage.success(ui.taskRerun)
    detailTask.value = result
    detailVisible.value = true
    await Promise.all([fetchStats(), fetchTasks()])
  } catch (error) { ElMessage.error(ui.rerunTaskFailed) }
}
async function handleExecuteTask(task) {
  try {
    await ElMessageBox.confirm(`确认执行任务「${task.name}」？`, ui.confirmExecuteTitle, { type: 'warning', confirmButtonText: ui.confirmExecute, cancelButtonText: ui.cancel })
  } catch (error) { return }
  try {
    const result = await executeHostTask(task.id)
    ElMessage.success(ui.taskExecuted)
    detailTask.value = result
    detailVisible.value = true
    await Promise.all([fetchStats(), fetchTasks()])
  } catch (error) { ElMessage.error(error?.response?.data?.detail || ui.executeTaskFailed) }
}
async function handleCancelTask(task) {
  try {
    await ElMessageBox.confirm(ui.cancelConfirm, ui.cancelTask, { type: 'warning', confirmButtonText: ui.cancelTask, cancelButtonText: ui.cancel })
  } catch (error) { return }
  try {
    await cancelHostTask(task.id)
    ElMessage.success(ui.cancelSuccess)
    await Promise.all([fetchStats(), fetchTasks()])
    if (detailVisible.value && detailTask.value?.id === task.id) await openDetail(task)
  } catch (error) { ElMessage.error(error?.response?.data?.detail || ui.cancelTaskFailed) }
}
async function handleBatchCancel() {
  if (!selectedCancelableTaskIds.value.length) return
  try {
    await ElMessageBox.confirm(ui.cancelBatchConfirm, ui.batchCancel, { type: 'warning', confirmButtonText: ui.batchCancel, cancelButtonText: ui.cancel })
  } catch (error) { return }
  try {
    const result = await batchCancelHostTasks({ ids: selectedCancelableTaskIds.value })
    ElMessage.success(result?.detail || ui.batchCancelSuccess)
    selectedTaskRows.value = []
    await Promise.all([fetchStats(), fetchTasks()])
  } catch (error) { ElMessage.error(error?.response?.data?.detail || ui.batchCancelFailed) }
}
async function reloadAll() {
  await Promise.all([fetchStats(), fetchTargets(), fetchTasks(), fetchTemplates(), fetchK8sClusters(), fetchK8sResources()])
}
onMounted(async () => {
  if (route.query.target === 'k8s') {
    applyExecutionKind('k8s_command')
  } else {
    applyExecutionKind('shell')
  }
  await reloadAll()
})
</script>
<style scoped>
.task-center-page{display:flex;flex-direction:column;gap:4px}

.inner-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:-2px;padding:3px;border-radius:18px;background:linear-gradient(180deg,rgba(255,255,255,.92) 0%,rgba(248,250,252,.82) 100%);border:1px solid rgba(148,163,184,.12);box-shadow:0 10px 22px rgba(15,23,42,.04)}.inner-tab-btn{position:relative;min-height:60px;padding:8px 11px 8px 13px;border:1px solid rgba(148,163,184,.1);border-radius:14px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:3px;text-align:left;cursor:pointer;transition:.2s ease box-shadow,.2s ease transform,.2s ease border-color,.2s ease background;box-shadow:0 8px 18px rgba(15,23,42,.035);overflow:hidden}.inner-tab-btn::after{content:'';position:absolute;inset:0 auto 0 0;width:3px;border-radius:14px;background:linear-gradient(180deg,rgba(96,165,250,.14) 0%,rgba(56,189,248,.02) 100%)}.inner-tab-btn:hover{transform:translateY(-1px);border-color:rgba(96,165,250,.28);box-shadow:0 12px 22px rgba(37,99,235,.08)}.inner-tab-btn.active{border-color:rgba(59,130,246,.28);background:linear-gradient(180deg,#fdfefe 0%,#eef6ff 100%);box-shadow:0 14px 24px rgba(59,130,246,.11)}.inner-tab-btn.active::after{background:linear-gradient(180deg,#3b82f6 0%,#22c55e 100%)}.inner-tab-title{font-size:13px;font-weight:700;color:#0f172a;line-height:1.1}.inner-tab-btn.active .inner-tab-title{color:#111827}.inner-tab-desc{font-size:11px;color:#64748b;line-height:1.35}
.task-source-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:4px 0}.task-source-card{min-height:74px;padding:10px 12px;border:1px solid rgba(148,163,184,.16);border-radius:12px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);display:flex;flex-direction:column;align-items:flex-start;gap:4px;cursor:pointer;text-align:left;box-shadow:0 10px 22px rgba(15,23,42,.04);transition:.2s ease border-color,.2s ease transform,.2s ease box-shadow}.task-source-card:hover,.task-source-card.active{border-color:rgba(37,99,235,.32);box-shadow:0 14px 26px rgba(37,99,235,.08);transform:translateY(-1px)}.task-source-card span{color:#64748b;font-size:12px}.task-source-card strong{color:#0f172a;font-size:22px;line-height:1}.task-source-card small{color:#94a3b8;font-size:11px;line-height:1.35}
.execution-flow{display:grid;grid-template-columns:1.2fr .9fr .9fr;gap:10px;margin:2px 0 12px}.flow-card{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border:1px solid rgba(148,163,184,.18);border-radius:16px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);box-shadow:0 12px 26px rgba(15,23,42,.05)}.flow-card.active{border-color:rgba(37,99,235,.32);box-shadow:0 14px 28px rgba(37,99,235,.08)}.flow-index{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:999px;background:#2563eb;color:#fff;font-size:12px;font-weight:700;flex:0 0 auto}.flow-body{display:flex;flex-direction:column;gap:7px;min-width:0}.flow-body strong{color:#0f172a;font-size:13px}.flow-body small{color:#64748b;font-size:12px;line-height:1.4}.target-type-segment{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.target-type-btn{height:30px;padding:0 12px;border:1px solid rgba(148,163,184,.24);border-radius:999px;background:#fff;color:#475569;font-size:12px;cursor:pointer;transition:.18s ease border-color,.18s ease background,.18s ease color,.18s ease box-shadow}.target-type-btn:hover{border-color:rgba(37,99,235,.35);color:#1d4ed8}.target-type-btn.active{border-color:#2563eb;background:#2563eb;color:#fff;box-shadow:0 8px 18px rgba(37,99,235,.18)}.k8s-cluster-tip{margin-bottom:0}
.glass-card{background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(148,163,184,.18);border-radius:18px;box-shadow:0 16px 34px rgba(15,23,42,.07);padding:14px 16px}.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;font-weight:600;color:#0f172a}.compact-head{margin-bottom:8px}
.composer-grid{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px}.library-grid{grid-template-columns:minmax(0,1.2fr) minmax(320px,.8fr)}.side-stack{display:flex;flex-direction:column;gap:8px}.task-form-head-actions,.history-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.preset-grid,.template-grid,.snippet-grid{display:grid;gap:10px}.preset-card,.snippet-card,.template-card{padding:14px;border:1px solid rgba(148,163,184,.18);border-radius:14px;background:linear-gradient(145deg,#ffffff 0%,#f6faff 100%);box-shadow:0 10px 24px rgba(15,23,42,.04);text-align:left;transition:transform .2s ease, box-shadow .2s ease, border-color .2s ease}.preset-card,.snippet-card{cursor:pointer}.preset-card:hover,.snippet-card:hover,.template-card:hover{border-color:rgba(96,165,250,.35);box-shadow:0 16px 30px rgba(37,99,235,.1);transform:translateY(-2px)}.preset-card.active{border-color:#3b82f6;box-shadow:0 18px 32px rgba(59,130,246,.14)}
.preset-title{color:#0f172a;font-weight:600}.preset-desc,.template-desc,.section-tip{margin-top:6px;color:#64748b;font-size:12px;line-height:1.5}.section-gap{margin-bottom:10px}.template-title-row,.snippet-title-row,.template-action-row,.template-tag-row{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.template-meta-row{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:8px;color:#64748b;font-size:12px}.template-preview{margin-top:10px;padding:10px 12px;border-radius:12px;background:rgba(15,23,42,.03);border:1px dashed rgba(148,163,184,.26)}.template-preview-label{display:block;margin-bottom:6px;color:#64748b;font-size:12px}.template-preview-code{display:block;color:#0f172a;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all}.snippet-scene{color:#2563eb;font-size:12px;background:rgba(59,130,246,.12);border-radius:999px;padding:2px 8px}.snippet-command{display:block;margin-top:8px;padding:8px 10px;border-radius:10px;background:#0f172a;color:#e2e8f0;font-size:12px;white-space:pre-wrap;word-break:break-all}.inline-empty{padding:12px 4px;color:#94a3b8;font-size:12px;text-align:center}
.mini-panel{padding:14px;border-radius:14px;background:rgba(248,250,252,.88);border:1px solid rgba(148,163,184,.16)}.mini-panel-title{font-size:13px;font-weight:600;color:#0f172a;margin-bottom:10px}.mini-bullet{position:relative;padding-left:14px;color:#64748b;font-size:12px;line-height:1.7}.mini-bullet::before{content:'';position:absolute;left:0;top:8px;width:6px;height:6px;border-radius:50%;background:#60a5fa}.task-inline-tip{margin-bottom:8px;padding:8px 11px;border-radius:10px;background:linear-gradient(90deg, rgba(59,130,246,.08) 0%, rgba(14,165,233,.04) 100%);border:1px solid rgba(59,130,246,.14);color:#64748b;font-size:12px;line-height:1.45}
.task-form{margin-top:4px}.form-row{display:flex;gap:12px}.form-col{flex:1}.form-col.wide{flex:1 1 100%}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:8px}.toolbar-left,.toolbar-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.selection-strip{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}.selection-pill{padding:6px 10px;border-radius:999px;background:rgba(59,130,246,.1);color:#2563eb;font-size:12px}.selection-pill.success{background:rgba(16,185,129,.14);color:#047857}.selection-pill.warning{background:rgba(245,158,11,.14);color:#b45309}.selection-pill.danger{background:rgba(239,68,68,.14);color:#b91c1c}
.submit-row{margin-top:8px;display:flex;justify-content:space-between;align-items:center;gap:12px}.submit-tip{color:#64748b;font-size:12px}.submit-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.template-toolbar{margin-bottom:8px}.template-editor-topbar{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}.template-editor-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.template-editor-label{color:#64748b;font-size:12px}.template-editor-chip{padding:6px 10px;border:none;border-radius:999px;background:rgba(59,130,246,.08);color:#2563eb;font-size:12px;cursor:pointer;transition:.2s ease background,.2s ease transform}.template-editor-chip:hover{background:rgba(59,130,246,.14);transform:translateY(-1px)}.template-editor-overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:8px}.template-overview-card{padding:12px 14px;border-radius:14px;background:linear-gradient(180deg,#fff 0%,#f4f8ff 100%);border:1px solid rgba(148,163,184,.16);box-shadow:0 10px 20px rgba(15,23,42,.04)}.template-overview-label{display:block;margin-bottom:6px;color:#64748b;font-size:12px}.template-editor-layout{display:grid;grid-template-columns:minmax(0,1.28fr) minmax(280px,.72fr);gap:14px}.template-editor-main{min-width:0}.template-editor-side{display:flex;flex-direction:column;gap:12px}.template-editor-panel{padding:14px;border-radius:16px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(148,163,184,.14)}.template-editor-section + .template-editor-section{margin-top:8px}.template-editor-section-title{margin-bottom:8px;color:#0f172a;font-size:13px;font-weight:600}.template-payload-stack{display:flex;flex-direction:column;gap:12px}.template-editor-help{background:linear-gradient(180deg,#f8fbff 0%,#f3f7fd 100%)}.template-editor-preview{align-self:start}.template-code-block{margin-top:8px;max-height:320px;overflow:auto}.history-card{min-width:0}.history-head{margin-bottom:8px}.history-toolbar{margin:8px 0}
.pagination-row{display:flex;justify-content:flex-end;margin-top:8px}.task-detail-shell{display:flex;flex-direction:column;gap:8px}.detail-summary{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:0}.detail-chip{padding:7px 12px;border-radius:999px;background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.14);color:#1e3a8a;font-size:12px;line-height:1.4}.detail-desc{margin-bottom:8px;color:#64748b;font-size:13px}.task-metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.task-metric-card{padding:12px 14px;border-radius:14px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(148,163,184,.16);box-shadow:0 10px 20px rgba(15,23,42,.04)}.task-metric-card.success{background:linear-gradient(180deg,#f0fdf4 0%,#f7fee7 100%)}.task-metric-card.danger{background:linear-gradient(180deg,#fff1f2 0%,#fef2f2 100%)}.task-metric-card.warning{background:linear-gradient(180deg,#fffbeb 0%,#fefce8 100%)}.task-metric-label{display:block;margin-bottom:6px;color:#64748b;font-size:12px}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.detail-section{display:flex;flex-direction:column;gap:8px;margin-bottom:0;padding:14px;border-radius:14px;background:rgba(248,250,252,.88);border:1px solid rgba(148,163,184,.16)}.detail-section-title{margin-bottom:0;color:#0f172a;font-size:13px;font-weight:600}.detail-kv{color:#475569;font-size:13px;line-height:1.7}.compact-kv{padding:7px 0;min-height:32px}.detail-code-block{margin:0;padding:12px;border-radius:12px;background:#0f172a;color:#e2e8f0;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word}.detail-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:8px}.danger-text{color:#b91c1c}.target-chip-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.target-host-chip{display:flex;flex-direction:column;gap:4px;padding:10px 12px;border-radius:12px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(148,163,184,.16)}.target-host-chip strong{color:#0f172a;font-size:13px}.target-host-chip span{color:#64748b;font-size:12px}.output-block{max-height:120px;overflow:auto;white-space:pre-wrap;word-break:break-word;padding:10px 12px;border-radius:12px;background:#0f172a;color:#e2e8f0;font-family:Consolas,Monaco,monospace;font-size:12px;line-height:1.6}
@media (max-width: 1100px) { .composer-grid,.library-grid,.inner-tabs,.task-source-grid,.execution-flow,.template-editor-layout,.template-editor-overview,.task-metric-grid,.detail-grid,.target-chip-grid{grid-template-columns:1fr} }
@media (max-width: 900px) { .form-row,.submit-row,.template-title-row,.template-action-row{flex-direction:column;align-items:stretch} }
</style>
