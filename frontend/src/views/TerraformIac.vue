<template>
  <div class="fade-in terraform-page">
    <section class="hero panel terraform-header">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="title-icon">
            <el-icon><SetUp /></el-icon>
          </span>
          <h2>IaC 编排</h2>
          <p class="page-subtitle inline-subtitle">基于 Terraform 实现。按模块完成云资源编排，生成阿里云 / 华为云 Terraform 工程文件，并支持执行与同步 CMDB。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button v-if="canManageIac" class="new-plan-button" type="primary" @click="resetForm">
          <el-icon><Plus /></el-icon> 新建方案
        </el-button>
      </div>
    </section>

    <div class="workspace-banner" :class="{ active: hasActiveWorkspace }">
      <el-icon class="workspace-banner-icon"><FolderOpened /></el-icon>
      <span v-if="hasActiveWorkspace">目前正在处理“{{ currentWorkingSchemeName }}”方案</span>
      <span v-else>请打开已有方案或新建方案，然后再继续编排、预览、执行与同步 CMDB。</span>
    </div>

    <el-tabs v-model="activeWorkspaceTab" class="module-tabs">
      <el-tab-pane name="stacks">
        <template #label>
          <div class="tab-label">
            <span>方案列表</span>
            <em>{{ stacks.length }}</em>
          </div>
        </template>

        <div class="table-card stack-table-card">
          <div class="section-head">
            <div>
              <span>方案列表</span>
              <div class="workspace-hint">先从这里载入已有方案，或点击右上角新建一个全新的编排方案。</div>
            </div>
            <el-button link type="primary" @click="fetchStacks"><el-icon><RefreshRight /></el-icon> 刷新</el-button>
          </div>

          <el-table :data="stacks" stripe v-loading="listLoading" style="width: 100%">
            <el-table-column prop="name" label="方案" min-width="160" />
            <el-table-column prop="provider_label" label="云厂商" width="110" />
            <el-table-column label="区域 / 可用区" min-width="180"><template #default="{ row }">{{ row.region }} / {{ row.zone }}</template></el-table-column>
            <el-table-column label="资源数" width="90"><template #default="{ row }">{{ row.resource_count || 0 }}</template></el-table-column>
            <el-table-column label="最近执行" width="140"><template #default="{ row }"><el-tag size="small" :type="statusTagType(row.last_execution_status)">{{ row.last_execution_status || '未执行' }}</el-tag></template></el-table-column>
            <el-table-column label="最近同步 CMDB" width="180"><template #default="{ row }">{{ formatTime(row.last_cmdb_sync_at) }}</template></el-table-column>
            <el-table-column prop="updated_by" label="更新人" width="110" />
            <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="loadStack(row.id)">查看方案</el-button>
                <el-button link type="success" size="small" @click="handleDownloadTemplate(row)">下载工程</el-button>
                <el-popconfirm v-if="canManageIac" title="确认删除该 Terraform 方案？" @confirm="handleDelete(row)">
                  <template #reference><el-button link type="danger" size="small">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane name="design">
        <template #label>
          <div class="tab-label">
            <span>方案设计</span>
            <em>{{ currentSections.length }}</em>
          </div>
        </template>

        <div class="table-card form-card">
          <div class="section-head workspace-header">
            <div>
              <span>方案设计</span>
              <div class="workspace-hint">按模块填写资源参数，最后一步直接生成并跳转到预览。</div>
            </div>
            <el-button v-if="canManageIac" type="primary" :loading="rendering" @click="handleRender">
              <el-icon><MagicStick /></el-icon> 生成配置并预览
            </el-button>
          </div>

          <el-tabs v-model="activeDesignTab" class="design-tabs" stretch>
            <el-tab-pane name="basic">
              <template #label>
                <div class="design-tab-label">
                  <span>{{ designTabMetaMap.basic.label }}</span>
                  <small>{{ designTabMetaMap.basic.helper }}</small>
                  <el-tag size="small" :type="designTabMetaMap.basic.tagType">{{ designTabMetaMap.basic.statusText }}</el-tag>
                </div>
              </template>

              <div class="section-head">
                <span>基础配置</span>
                <el-tag size="small" type="info">敏感凭证仅在导出或执行时输入，不落库</el-tag>
              </div>

              <el-form :model="form" label-width="120px">
                <el-form-item label="方案名称" required :error="fieldError('name', '方案名称')">
                  <el-input v-model="form.name" placeholder="例如：prod-web-baseline" />
                </el-form-item>
                <el-form-item label="方案描述">
                  <el-input v-model="form.description" type="textarea" :rows="2" placeholder="描述基础设施用途或交付场景" />
                </el-form-item>
                <el-form-item label="云厂商" required :error="fieldError('cloud_provider', '云厂商')">
                  <el-select v-model="form.cloud_provider" style="width: 100%" @change="handleProviderChange">
                    <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </el-form-item>
                <el-form-item label="区域" required :error="fieldError('region', '区域')">
                  <el-select v-model="form.region" filterable style="width: 100%" @change="handleRegionChange">
                    <el-option v-for="item in currentRegions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </el-form-item>
                <el-form-item label="可用区" required :error="fieldError('zone', '可用区')">
                  <el-select
                    v-if="currentZones.length"
                    v-model="form.zone"
                    filterable
                    allow-create
                    default-first-option
                    style="width: 100%"
                  >
                    <el-option v-for="item in currentZones" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                  <el-input v-else v-model="form.zone" placeholder="例如：cn-hangzhou-h / cn-north-4a" />
                </el-form-item>
              </el-form>

              <div v-if="currentProviderMeta" class="provider-tip">
                <div class="provider-title">{{ currentProviderMeta.label }}</div>
                <div class="provider-desc">{{ currentProviderMeta.description }}</div>
              </div>

              <div v-if="metadataSection" class="config-section">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">{{ metadataSection.label }}</div>
                    <div class="config-section-desc">{{ sectionDescription(metadataSection.key) }}</div>
                  </div>
                </div>

                <el-form :model="form" label-width="120px">
                  <el-form-item
                    v-for="field in metadataSection.fields"
                    :key="field.path"
                    :label="field.label"
                    :required="isFieldRequired(field.path, { sectionKey: metadataSection.key })"
                    :error="fieldError(field.path, field.label, { sectionKey: metadataSection.key })"
                  >
                    <el-select
                      v-if="field.type === 'select'"
                      :model-value="getConfigValue(field.path)"
                      style="width: 100%"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    >
                      <el-option v-for="option in field.options || []" :key="option.value || option" :label="option.label || option" :value="option.value || option" />
                    </el-select>
                    <el-input
                      v-else
                      :model-value="getConfigValue(field.path)"
                      :placeholder="field.placeholder || ''"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                  </el-form-item>
                </el-form>
              </div>
            </el-tab-pane>

            <el-tab-pane name="network">
              <template #label>
                <div class="design-tab-label">
                  <span>{{ designTabMetaMap.network.label }}</span>
                  <small>{{ designTabMetaMap.network.helper }}</small>
                  <el-tag size="small" :type="designTabMetaMap.network.tagType">{{ designTabMetaMap.network.statusText }}</el-tag>
                </div>
              </template>

              <div v-if="networkSection" class="config-section">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">{{ networkSection.label }}</div>
                    <div class="config-section-desc">{{ sectionDescription(networkSection.key) }}</div>
                  </div>
                </div>

                <el-form :model="form" label-width="120px">
                  <el-form-item
                    v-for="field in networkSection.fields"
                    :key="field.path"
                    :label="field.label"
                    :required="isFieldRequired(field.path, { sectionKey: networkSection.key })"
                    :error="fieldError(field.path, field.label, { sectionKey: networkSection.key })"
                  >
                    <el-input
                      v-if="field.type === 'ports'"
                      :model-value="formatPorts(getConfigValue(field.path))"
                      :placeholder="field.placeholder || '22,80,443'"
                      @update:model-value="value => setPortsValue(field.path, value)"
                    />
                    <el-input
                      v-else
                      :model-value="getConfigValue(field.path)"
                      :placeholder="field.placeholder || ''"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                  </el-form-item>
                </el-form>
              </div>

              <div class="resource-switcher">
                <div class="section-head inline-head">
                  <span>网络附加资源</span>
                  <el-tag size="small" type="info">非必选</el-tag>
                </div>
                <div class="resource-switcher-grid">
                  <button
                    v-for="section in networkOptionalSections"
                    :key="section.key"
                    type="button"
                    class="resource-switch-card"
                    :class="{ active: activeSectionKey === section.key, disabled: !isSectionEnabled(section) }"
                    @click="activeSectionKey = section.key"
                  >
                    <div class="resource-switch-head">
                      <div>
                        <div class="resource-switch-title">{{ section.label }}</div>
                        <div class="resource-switch-desc">{{ sectionDescription(section.key) }}</div>
                      </div>
                      <el-switch
                        :model-value="Boolean(getConfigValue(`resources.${section.key}.enabled`))"
                        @click.stop
                        @update:model-value="value => setConfigValue(`resources.${section.key}.enabled`, value)"
                      />
                    </div>
                    <div class="resource-switch-name">{{ sectionResourceName(section) }}</div>
                  </button>
                </div>
              </div>

              <div v-if="activeNetworkOptionalSection" class="config-section" :class="{ 'section-disabled': !isSectionEnabled(activeNetworkOptionalSection) }">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">{{ activeNetworkOptionalSection.label }}</div>
                    <div class="config-section-desc">{{ sectionDescription(activeNetworkOptionalSection.key) }}</div>
                  </div>
                  <el-tag :type="isSectionEnabled(activeNetworkOptionalSection) ? 'success' : 'info'" size="small">
                    {{ isSectionEnabled(activeNetworkOptionalSection) ? '已启用' : '可选资源' }}
                  </el-tag>
                </div>

                <el-form :model="form" label-width="120px">
                  <el-form-item
                    v-for="field in activeNetworkOptionalSection.fields"
                    :key="field.path"
                    :label="field.label"
                    :required="isFieldRequired(field.path, { sectionKey: activeNetworkOptionalSection.key })"
                    :error="fieldError(field.path, field.label, { sectionKey: activeNetworkOptionalSection.key })"
                  >
                    <el-switch
                      v-if="field.type === 'switch'"
                      :model-value="Boolean(getConfigValue(field.path))"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                    <el-select
                      v-else-if="field.type === 'select'"
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeNetworkOptionalSection, field)"
                      style="width: 100%"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    >
                      <el-option v-for="option in field.options || []" :key="option.value || option" :label="option.label || option" :value="option.value || option" />
                    </el-select>
                    <el-input-number
                      v-else-if="field.type === 'number'"
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeNetworkOptionalSection, field)"
                      :min="field.min ?? 0"
                      :max="field.max ?? 100000"
                      controls-position="right"
                      style="width: 100%"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                    <el-input
                      v-else
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeNetworkOptionalSection, field)"
                      :placeholder="field.placeholder || ''"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                  </el-form-item>
                </el-form>
              </div>
            </el-tab-pane>

            <el-tab-pane name="compute">
              <template #label>
                <div class="design-tab-label">
                  <span>{{ designTabMetaMap.compute.label }}</span>
                  <small>{{ designTabMetaMap.compute.helper }}</small>
                  <el-tag size="small" :type="designTabMetaMap.compute.tagType">{{ designTabMetaMap.compute.statusText }}</el-tag>
                </div>
              </template>

              <div v-if="computeSection" class="config-section">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">服务器配置</div>
                    <div class="config-section-desc">{{ sectionDescription(computeSection.key) }}</div>
                  </div>
                  <el-button type="primary" plain @click="addServer">新增服务器</el-button>
                </div>

                <div class="multi-card-list">
                  <div v-for="(server, index) in computeInstances" :key="serverCardKey(server, index)" class="multi-config-card">
                    <div class="multi-config-head">
                      <div>
                        <div class="multi-config-title">服务器 {{ index + 1 }}</div>
                        <div class="multi-config-desc">{{ server.instance_name || `未命名服务器 ${index + 1}` }}</div>
                      </div>
                      <el-button text type="danger" :disabled="computeInstances.length === 1" @click="removeServer(index)">删除</el-button>
                    </div>

                    <el-form :model="server" label-width="120px">
                      <el-form-item
                        v-for="field in computeInstanceFields"
                        :key="`${index}-${field.path}`"
                        :label="field.label"
                        required
                        :error="serverFieldError(server, field)"
                      >
                        <el-select
                          v-if="field.type === 'select'"
                          :model-value="getServerFieldValue(server, field)"
                          style="width: 100%"
                          @update:model-value="value => updateServerField(index, field, value)"
                        >
                          <el-option v-for="option in field.options || []" :key="option.value || option" :label="option.label || option" :value="option.value || option" />
                        </el-select>
                        <el-input-number
                          v-else-if="field.type === 'number'"
                          :model-value="getServerFieldValue(server, field)"
                          :min="field.min ?? 0"
                          :max="field.max ?? 100000"
                          controls-position="right"
                          style="width: 100%"
                          @update:model-value="value => updateServerField(index, field, value)"
                        />
                        <el-input
                          v-else
                          :model-value="getServerFieldValue(server, field)"
                          :placeholder="field.placeholder || ''"
                          @update:model-value="value => updateServerField(index, field, value)"
                        />
                      </el-form-item>
                    </el-form>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane name="database">
              <template #label>
                <div class="design-tab-label">
                  <span>{{ designTabMetaMap.database.label }}</span>
                  <small>{{ designTabMetaMap.database.helper }}</small>
                  <el-tag size="small" :type="designTabMetaMap.database.tagType">{{ designTabMetaMap.database.statusText }}</el-tag>
                </div>
              </template>

              <div class="resource-switcher">
                <div class="section-head inline-head">
                  <span>数据库资源</span>
                  <el-tag size="small" type="success">按需启用</el-tag>
                </div>
                <div class="resource-switcher-grid">
                  <button
                    v-for="section in databaseSections"
                    :key="section.key"
                    type="button"
                    class="resource-switch-card"
                    :class="{ active: activeSectionKey === section.key, disabled: !isSectionEnabled(section) }"
                    @click="activeSectionKey = section.key"
                  >
                    <div class="resource-switch-head">
                      <div>
                        <div class="resource-switch-title">{{ section.label }}</div>
                        <div class="resource-switch-desc">{{ sectionDescription(section.key) }}</div>
                      </div>
                      <el-switch
                        :model-value="Boolean(getConfigValue(`resources.${section.key}.enabled`))"
                        @click.stop
                        @update:model-value="value => setConfigValue(`resources.${section.key}.enabled`, value)"
                      />
                    </div>
                    <div class="resource-switch-name">{{ sectionResourceName(section) }}</div>
                  </button>
                </div>
              </div>

              <div v-if="activeDatabaseSection" class="config-section" :class="{ 'section-disabled': !isSectionEnabled(activeDatabaseSection) }">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">{{ activeDatabaseSection.label }}</div>
                    <div class="config-section-desc">{{ sectionDescription(activeDatabaseSection.key) }}</div>
                  </div>
                  <el-tag :type="isSectionEnabled(activeDatabaseSection) ? 'success' : 'info'" size="small">
                    {{ isSectionEnabled(activeDatabaseSection) ? '已启用' : '可选资源' }}
                  </el-tag>
                </div>

                <el-form :model="form" label-width="120px">
                  <el-form-item
                    v-for="field in activeDatabaseSection.fields"
                    :key="field.path"
                    :label="field.label"
                    :required="isFieldRequired(field.path, { sectionKey: activeDatabaseSection.key })"
                    :error="fieldError(field.path, field.label, { sectionKey: activeDatabaseSection.key })"
                  >
                    <el-switch
                      v-if="field.type === 'switch'"
                      :model-value="Boolean(getConfigValue(field.path))"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                    <el-select
                      v-else-if="field.type === 'select'"
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeDatabaseSection, field)"
                      style="width: 100%"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    >
                      <el-option v-for="option in field.options || []" :key="option.value || option" :label="option.label || option" :value="option.value || option" />
                    </el-select>
                    <el-input-number
                      v-else-if="field.type === 'number'"
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeDatabaseSection, field)"
                      :min="field.min ?? 0"
                      :max="field.max ?? 100000"
                      controls-position="right"
                      style="width: 100%"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                    <el-input
                      v-else
                      :model-value="getConfigValue(field.path)"
                      :disabled="shouldDisableField(activeDatabaseSection, field)"
                      :placeholder="field.placeholder || ''"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                  </el-form-item>
                </el-form>
              </div>

            </el-tab-pane>

            <el-tab-pane name="resources">
              <template #label>
                <div class="design-tab-label">
                  <span>{{ designTabMetaMap.resources.label }}</span>
                  <small>{{ designTabMetaMap.resources.helper }}</small>
                  <el-tag size="small" :type="designTabMetaMap.resources.tagType">{{ designTabMetaMap.resources.statusText }}</el-tag>
                </div>
              </template>

              <div class="resource-switcher">
                <div class="section-head inline-head">
                  <span>对象存储</span>
                  <el-tag size="small" type="success">按需启用</el-tag>
                </div>
                <div class="resource-switcher-grid">
                  <button
                    v-for="section in resourceOptionalSections"
                    :key="section.key"
                    type="button"
                    class="resource-switch-card"
                    :class="{ active: activeSectionKey === section.key, disabled: !isSectionEnabled(section) }"
                    @click="activeSectionKey = section.key"
                  >
                    <div class="resource-switch-head">
                      <div>
                        <div class="resource-switch-title">{{ section.label }}</div>
                        <div class="resource-switch-desc">{{ sectionDescription(section.key) }}</div>
                      </div>
                      <el-switch
                        :model-value="Boolean(getConfigValue(`resources.${section.key}.enabled`))"
                        @click.stop
                        @update:model-value="value => setConfigValue(`resources.${section.key}.enabled`, value)"
                      />
                    </div>
                    <div class="resource-switch-name">{{ sectionResourceName(section) }}</div>
                  </button>
                </div>
              </div>

              <div v-if="activeResourceSection" class="config-section" :class="{ 'section-disabled': !isSectionEnabled(activeResourceSection) }">
                <div class="config-section-head">
                  <div>
                    <div class="config-section-title">{{ activeResourceSection.label }}</div>
                    <div class="config-section-desc">{{ sectionDescription(activeResourceSection.key) }}</div>
                  </div>
                  <div class="section-head-actions">
                    <el-tag :type="isSectionEnabled(activeResourceSection) ? 'success' : 'info'" size="small">
                      {{ isSectionEnabled(activeResourceSection) ? '已启用' : '可选资源' }}
                    </el-tag>
                    <el-button v-if="isSectionEnabled(activeResourceSection)" type="primary" plain @click="addBucket">新增 Bucket</el-button>
                  </div>
                </div>

                <el-form :model="form" label-width="120px">
                  <el-form-item
                    v-for="field in resourceSwitchFields"
                    :key="field.path"
                    :label="field.label"
                  >
                    <el-switch
                      :model-value="Boolean(getConfigValue(field.path))"
                      @update:model-value="value => setConfigValue(field.path, value)"
                    />
                  </el-form-item>
                </el-form>

                <div v-if="isSectionEnabled(activeResourceSection)" class="multi-card-list">
                  <div v-for="(bucket, index) in objectStorageBuckets" :key="bucketCardKey(bucket, index)" class="multi-config-card">
                    <div class="multi-config-head">
                      <div>
                        <div class="multi-config-title">Bucket {{ index + 1 }}</div>
                        <div class="multi-config-desc">{{ bucket.bucket_name || `未命名 Bucket ${index + 1}` }}</div>
                      </div>
                      <el-button text type="danger" :disabled="objectStorageBuckets.length === 1" @click="removeBucket(index)">删除</el-button>
                    </div>

                    <el-form :model="bucket" label-width="120px">
                      <el-form-item
                        v-for="field in objectStorageConfigFields"
                        :key="`${index}-${field.path}`"
                        :label="field.label"
                        required
                        :error="bucketFieldError(bucket, field)"
                      >
                        <el-select
                          v-if="field.type === 'select'"
                          :model-value="getBucketFieldValue(bucket, field)"
                          style="width: 100%"
                          @update:model-value="value => updateBucketField(index, field, value)"
                        >
                          <el-option v-for="option in field.options || []" :key="option.value || option" :label="option.label || option" :value="option.value || option" />
                        </el-select>
                        <el-input
                          v-else
                          :model-value="getBucketFieldValue(bucket, field)"
                          :placeholder="field.placeholder || ''"
                          @update:model-value="value => updateBucketField(index, field, value)"
                        />
                      </el-form-item>
                    </el-form>
                  </div>
                </div>
                <el-empty v-else description="启用后可配置一个或多个 Bucket。" />
              </div>
            </el-tab-pane>
          </el-tabs>

          <div class="design-step-footer">
            <div class="design-step-summary">
              <strong>{{ currentDesignTabMeta.label }}</strong>
              <span>{{ currentDesignTabMeta.helper }}</span>
            </div>
            <div v-if="canManageIac" class="design-step-actions">
              <el-button :disabled="!canGoPrevDesignTab" @click="goPrevDesignTab">上一步</el-button>
              <el-button type="primary" :loading="isLastDesignTab && rendering" @click="goNextDesignTab">{{ isLastDesignTab ? '生成配置并预览' : '下一步' }}</el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>

<el-tab-pane name="preview">
        <template #label>
          <div class="tab-label">
            <span>配置预览</span>
            <em>{{ previewFileNames.length }}</em>
          </div>
        </template>

        <div class="table-card preview-card">
          <div class="section-head">
            <div>
              <span>生成预览</span>
              <div class="workspace-hint">{{ canManageIac ? '在这里查看和编辑 Terraform 内容，并保存当前方案。' : '在这里查看 Terraform 生成内容。' }}</div>
            </div>
            <div class="section-head-actions">
              <el-button v-if="canManageIac" type="success" :loading="saving" @click="handleSave">
                <el-icon><FolderOpened /></el-icon> 保存方案
              </el-button>
              <el-button v-if="previewFileNames.length" link type="primary" @click="copyCurrentFile">
                <el-icon><DocumentCopy /></el-icon> 复制当前文件
              </el-button>
            </div>
          </div>

          <div v-if="previewSummary" class="summary-grid">
            <div class="summary-item"><span class="summary-label">Provider</span><strong>{{ previewSummary.provider_label }}</strong></div>
            <div class="summary-item"><span class="summary-label">Region / Zone</span><strong>{{ previewSummary.region }} / {{ previewSummary.zone }}</strong></div>
            <div class="summary-item"><span class="summary-label">环境</span><strong>{{ previewSummary.metadata?.environment || '-' }}</strong></div>
            <div class="summary-item"><span class="summary-label">资源数</span><strong>{{ previewSummary.resource_count || 0 }}</strong></div>
            <div class="summary-item"><span class="summary-label">关联数</span><strong>{{ previewSummary.relation_count || 0 }}</strong></div>
          </div>

          <div v-if="previewSummary?.resources?.length" class="resource-list">
            <div v-for="resource in previewSummary.resources" :key="resource.key" class="resource-chip">
              <span class="resource-kind">{{ resource.label }}</span>
              <strong>{{ resource.name }}</strong>
            </div>
          </div>

          <div v-if="previewRelationships.length" class="relationship-preview">
            <div class="relationship-preview-head">资源关系</div>
            <div class="relationship-list">
              <div v-for="(relation, index) in previewRelationships" :key="`${relation.source}-${relation.target}-${relation.relation_type}-${index}`" class="relationship-chip">
                <strong>{{ relation.source_name }}</strong>
                <span>{{ relationTypeLabel(relation.relation_type) }}</span>
                <strong>{{ relation.target_name }}</strong>
              </div>
            </div>
          </div>

          <div v-if="!previewFileNames.length" class="empty-guide">
            <div class="empty-guide-icon">
              <el-icon><MagicStick /></el-icon>
            </div>
            <div class="empty-guide-title">还没有生成配置文件</div>
            <div class="empty-guide-desc">请先进入“方案设计”标签页，完成基础信息和参数填写后，点击“生成配置并预览”。</div>
            <div class="empty-guide-steps">推荐顺序：方案列表载入或新建方案 → 方案设计填写参数 → 生成配置并预览 → 保存方案。</div>
          </div>

          <div v-if="previewFileNames.length" class="preview-edit-tip">
            {{ canManageIac ? '以下为模板生成文件，如您有其余定制化需求，可直接在下方编辑 Terraform 文件内容，添加或修改资源。' : '以下为模板生成文件，当前仅支持查看。' }}
          </div>

          <el-tabs v-if="previewFileNames.length" v-model="activeFileName" class="file-tabs">
            <el-tab-pane v-for="file in previewFileNames" :key="file" :label="file" :name="file">
              <el-input
                type="textarea"
                resize="vertical"
                :autosize="{ minRows: 18, maxRows: 28 }"
                :model-value="editablePreviewFiles[file]"
                :disabled="!canManageIac"
                class="file-editor"
                spellcheck="false"
                @update:model-value="value => updatePreviewFile(file, value)"
              />
            </el-tab-pane>
          </el-tabs>
        </div>
      </el-tab-pane>

      <el-tab-pane name="execution">
        <template #label>
          <div class="tab-label">
            <span>执行与同步CMDB</span>
            <em>{{ executions.length }}</em>
          </div>
        </template>

        <div class="table-card execution-card">
          <div class="section-head">
            <div>
              <span>执行与同步CMDB</span>
              <div class="workspace-hint">保存方案后可在这里执行 Terraform，并将资源同步回 CMDB。</div>
            </div>
            <el-tag v-if="activeStackId || hasActiveWorkspace" size="small" type="success">方案：{{ currentWorkingSchemeName }}</el-tag>
          </div>

          <div v-if="!activeStackId" class="empty-guide">
            <div class="empty-guide-icon execution-guide-icon">
              <el-icon><Promotion /></el-icon>
            </div>
            <div class="empty-guide-title">还没有可执行的方案</div>
            <div class="empty-guide-desc">请先到“方案列表”打开一个已有方案，或新建方案并在“配置预览”里保存后，再回来执行 Terraform 或同步 CMDB。</div>
            <div class="empty-guide-steps">执行前建议：先在“配置预览”确认生成内容，再按顺序执行 `init / plan / apply`。</div>
          </div>

          <template v-else>
            <div class="execution-toolbar">
              <div class="execution-meta">
                <el-tag size="small" type="info">{{ form.cloud_provider }}</el-tag>
                <el-tag size="small" :type="statusTagType(currentStackStatus)">最近执行：{{ currentStackStatus || '未执行' }}</el-tag>
                <el-tag size="small" type="warning">最近同步：{{ formatTime(currentStackSyncAt) }}</el-tag>
              </div>
              <div class="execution-actions">
                <el-button v-if="canExecuteIac" size="small" :loading="executingAction === 'init'" @click="runExecution('init')">init</el-button>
                <el-button v-if="canExecuteIac" size="small" type="primary" :loading="executingAction === 'plan'" @click="openSecretDialog('execute', 'plan')">plan</el-button>
                <el-button v-if="canExecuteIac" size="small" type="success" :loading="executingAction === 'apply'" @click="openSecretDialog('execute', 'apply')">apply</el-button>
                <el-button v-if="canExecuteIac" size="small" type="danger" :loading="executingAction === 'destroy'" @click="openSecretDialog('execute', 'destroy')">destroy</el-button>
                <el-button v-if="canSyncCmdb" size="small" type="warning" :loading="syncingCmdb" @click="handleSyncCmdb">同步 CMDB</el-button>
              </div>
            </div>

            <div v-if="bindings.length" class="binding-grid">
              <div v-for="binding in bindings" :key="binding.id" class="binding-card">
                <div class="binding-title">{{ binding.resource_name }}</div>
                <div class="binding-meta">{{ binding.resource_key }} / {{ binding.resource_kind }}</div>
                <div class="binding-meta">CMDB：{{ binding.cmdb_item_name || '-' }}（{{ binding.cmdb_item_status || '-' }}）</div>
              </div>
            </div>

            <el-table v-if="executions.length" :data="executions" stripe style="width: 100%">
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div class="log-block">
                    <div class="log-title">命令</div>
                    <pre class="log-preview">{{ row.command || '-' }}</pre>
                    <div class="log-title">标准输出</div>
                    <pre class="log-preview">{{ row.stdout || '-' }}</pre>
                    <div class="log-title">标准错误</div>
                    <pre class="log-preview error-log">{{ row.stderr || '-' }}</pre>
                    <div class="log-title">Outputs</div>
                    <pre class="log-preview">{{ stringifyJson(row.outputs) }}</pre>
                    <div class="log-title">CMDB 摘要</div>
                    <pre class="log-preview">{{ stringifyJson(row.cmdb_summary) }}</pre>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="action_label" label="动作" width="100" />
              <el-table-column label="状态" width="120">
                <template #default="{ row }"><el-tag :type="statusTagType(row.status)">{{ row.status_label }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="return_code" label="返回码" width="90" />
              <el-table-column prop="created_by" label="执行人" width="110" />
              <el-table-column label="开始时间" width="180"><template #default="{ row }">{{ formatTime(row.started_at || row.created_at) }}</template></el-table-column>
              <el-table-column label="结束时间" width="180"><template #default="{ row }">{{ formatTime(row.finished_at) }}</template></el-table-column>
            </el-table>
            <el-empty v-else description="暂无执行记录" />
          </template>
        </div>
      </el-tab-pane>

    </el-tabs>

    <el-dialog v-model="secretDialogVisible" :title="secretDialogTitle" width="90%" style="max-width: 560px" append-to-body destroy-on-close>
      <el-alert :title="secretDialogHint" type="warning" show-icon :closable="false" />
      <el-form :model="secretForm" label-width="130px" style="margin-top: 16px">
        <el-form-item v-for="field in secretFields" :key="field.key" :label="field.label"><el-input v-model="secretForm[field.key]" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="secretDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSubmitting" @click="handleSecretDialogSubmit"><el-icon><Lock /></el-icon> 确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  bundleTerraformProject,
  createTerraformStack,
  deleteTerraformStack,
  downloadTerraformStack,
  executeTerraformStack,
  getIacCatalog,
  getTerraformExecutions,
  getTerraformStack,
  getTerraformStacks,
  renderTerraformProject,
  syncTerraformStackCmdb,
  updateTerraformStack,
} from '@/api/modules/iac'
import { useAuthStore } from '@/stores/auth'

const OPTIONAL_SECTION_KEYS = ['rds', 'redis', 'load_balancer', 'nat_gateway', 'object_storage']
const SECTION_DESCRIPTIONS = {
  metadata: '项目归属、环境与负责人等治理信息。',
  network: 'VPC、子网与入方向开放端口。',
  compute: '支持按台维护服务器规格、镜像、系统盘与公网带宽。',
  rds: '按需生成数据库实例。',
  redis: '按需生成缓存实例。',
  load_balancer: '按需生成负载均衡。',
  nat_gateway: '按需生成公网访问出入口。',
  object_storage: '支持按需创建一个或多个对象存储桶。',
}
const FALLBACK_RELATION_TYPES = [
  { value: 'depends_on', label: '依赖' },
  { value: 'connects_to', label: '连接' },
  { value: 'runs_on', label: '部署在' },
]
const DATABASE_SECTION_KEYS = ['rds', 'redis']
const NETWORK_OPTIONAL_SECTION_KEYS = ['load_balancer', 'nat_gateway']
const RESOURCE_SECTION_KEYS = ['object_storage']
const DESIGN_TAB_ORDER = ['basic', 'network', 'compute', 'database', 'resources']
const REQUIRED_TOP_LEVEL_FIELDS = ['name', 'cloud_provider', 'region', 'zone']
const REQUIRED_SECTION_PATHS = {
  network: ['network.vpc_cidr', 'network.subnet_cidr', 'network.open_ingress_ports'],
  compute: [
    'compute.instance_name',
    'compute.instance_type',
    'compute.image_id',
    'compute.system_disk_type',
    'compute.system_disk_size',
    'compute.public_bandwidth',
  ],
}
const TOPOLOGY_BOUNDS = { width: 880, height: 420 }

const authStore = useAuthStore()
const canManageIac = computed(() => authStore.hasPermission('ops.iac.manage'))
const canExecuteIac = computed(() => authStore.hasPermission('ops.iac.execute'))
const canSyncCmdb = computed(() => authStore.hasPermission('ops.iac.execute') && authStore.hasPermission('cmdb.ci.manage'))

const catalog = ref({})
const listLoading = ref(false)
const rendering = ref(false)
const saving = ref(false)
const syncingCmdb = ref(false)
const executingAction = ref('')
const stacks = ref([])
const executions = ref([])
const bindings = ref([])
const activeStackId = ref(null)
const hasActiveWorkspace = ref(false)
const previewSummary = ref(null)
const previewFiles = ref({})
const editablePreviewFiles = ref({})
const activeWorkspaceTab = ref('stacks')
const activeDesignTab = ref('basic')
const activeFileName = ref('')
const activeSectionKey = ref('metadata')
const secretDialogVisible = ref(false)
const secretDialogMode = ref('export')
const pendingExecutionAction = ref('')
const dialogSubmitting = ref(false)
const secretForm = ref({})
const selectedRelationType = ref('depends_on')
const selectedSourceKey = ref('')
const topologyLayout = ref({})
const dragState = ref(null)
const form = ref(buildEmptyForm())

const providerOptions = computed(() => Object.entries(catalog.value).map(([value, meta]) => ({ value, label: meta.label })))
const currentProviderMeta = computed(() => catalog.value[form.value.cloud_provider] || null)
const currentRegions = computed(() => currentProviderMeta.value?.regions || [])
const currentZones = computed(() => {
  const options = currentProviderMeta.value?.zone_options?.[form.value.region] || []
  if (options.length) return options
  return form.value.zone ? [{ value: form.value.zone, label: form.value.zone }] : []
})
const currentSections = computed(() => currentProviderMeta.value?.sections || [])
const metadataSection = computed(() => currentSections.value.find(item => item.key === 'metadata') || null)
const networkSection = computed(() => currentSections.value.find(item => item.key === 'network') || null)
const computeSection = computed(() => currentSections.value.find(item => item.key === 'compute') || null)
const optionalSections = computed(() => currentSections.value.filter(item => isOptionalSection(item)))
const databaseSections = computed(() => currentSections.value.filter(item => DATABASE_SECTION_KEYS.includes(item.key)))
const networkOptionalSections = computed(() => currentSections.value.filter(item => NETWORK_OPTIONAL_SECTION_KEYS.includes(item.key)))
const resourceOptionalSections = computed(() => currentSections.value.filter(item => RESOURCE_SECTION_KEYS.includes(item.key)))
const computeInstanceFields = computed(() => (computeSection.value?.fields || []).filter(field => field.path.startsWith('compute.')))
const resourceSwitchFields = computed(() => (activeResourceSection.value?.fields || []).filter(field => field.type === 'switch'))
const objectStorageConfigFields = computed(() => (activeResourceSection.value?.fields || []).filter(field => field.type !== 'switch'))
const computeInstances = computed(() => ensureComputeInstances(form.value.config))
const objectStorageBuckets = computed(() => ensureObjectStorageBuckets(form.value.config))
const activeDatabaseSection = computed(() => databaseSections.value.find(item => item.key === activeSectionKey.value) || databaseSections.value[0] || null)
const activeNetworkOptionalSection = computed(() => networkOptionalSections.value.find(item => item.key === activeSectionKey.value) || networkOptionalSections.value[0] || null)
const activeResourceSection = computed(() => resourceOptionalSections.value.find(item => item.key === activeSectionKey.value) || resourceOptionalSections.value[0] || null)
const designTabMetaMap = computed(() => {
  const basic = summarizeBasicTab()
  const network = summarizeNetworkTab()
  const compute = summarizeServersTab()
  const database = summarizeOptionalGroup(databaseSections.value, '未启用数据库资源')
  const resources = summarizeStorageTab()

  return {
    basic: formatDesignTabMeta('basic', '基础信息', basic),
    network: formatDesignTabMeta('network', '网络', network),
    compute: formatDesignTabMeta('compute', '服务器', compute),
    database: formatDesignTabMeta('database', '数据库', database),
    resources: formatDesignTabMeta('resources', '扩展资源', resources),
  }
})
const currentDesignTabMeta = computed(() => designTabMetaMap.value[activeDesignTab.value] || designTabMetaMap.value.basic)
const canGoPrevDesignTab = computed(() => DESIGN_TAB_ORDER.indexOf(activeDesignTab.value) > 0)
const isLastDesignTab = computed(() => DESIGN_TAB_ORDER.indexOf(activeDesignTab.value) === DESIGN_TAB_ORDER.length - 1)
const secretFields = computed(() => currentProviderMeta.value?.secret_fields || [])
const relationTypeOptions = computed(() => currentProviderMeta.value?.relation_types || FALLBACK_RELATION_TYPES)
const previewFileNames = computed(() => Object.keys(editablePreviewFiles.value || {}))
const previewRelationships = computed(() => previewSummary.value?.relationships || [])
const topologyRelations = computed(() => getConfigValue('topology.relations') || [])
const currentStack = computed(() => stacks.value.find(item => item.id === activeStackId.value) || null)
const currentWorkingSchemeName = computed(() => currentStack.value?.name || String(form.value.name || '').trim() || '未命名方案')
const currentStackStatus = computed(() => currentStack.value?.last_execution_status || '')
const currentStackSyncAt = computed(() => currentStack.value?.last_cmdb_sync_at || '')
const secretDialogTitle = computed(() => secretDialogMode.value === 'export' ? '导出可执行 ZIP' : `执行 Terraform ${pendingExecutionAction.value}`)
const secretDialogHint = computed(() => secretDialogMode.value === 'export'
  ? '输入的凭证和实例密码仅用于本次导出，不会保存到 SxDevOps 数据库。'
  : '执行 plan/apply/destroy 时会临时写入 terraform.tfvars 到工作目录，执行记录会保留日志，但不会落库存储敏感值。')
const availableResourceOptions = computed(() => {
  const options = [
    { value: 'vpc', label: 'VPC', name: `${stackBaseName()}-vpc` },
    { value: 'subnet', label: 'Subnet', name: `${stackBaseName()}-subnet` },
    { value: 'security_group', label: 'Security Group', name: `${stackBaseName()}-sg` },
    { value: 'compute', label: 'ECS', name: sectionResourceNameByKey('compute') },
  ]
  if (form.value.cloud_provider === 'huaweicloud' && Number(getConfigValue('compute.public_bandwidth') || 0) > 0) options.push({ value: 'eip', label: 'EIP', name: `${stackBaseName()}-eip` })
  OPTIONAL_SECTION_KEYS.forEach((key) => {
    const section = currentSections.value.find(item => item.key === key)
    if (section && isSectionEnabled(section)) options.push({ value: key, label: section.label, name: sectionResourceName(section) })
  })
  return options
})
const topologyNodes = computed(() => availableResourceOptions.value.map((item, index) => ({ ...item, ...(topologyLayout.value[item.value] || defaultNodePosition(item.value, index)) })))
const canvasRelations = computed(() => topologyRelations.value.map((relation, index) => {
  const source = topologyNodes.value.find(item => item.value === relation.source)
  const target = topologyNodes.value.find(item => item.value === relation.target)
  if (!source || !target) return null
  return { ...relation, id: topologyRelationKey(relation, index), x1: source.x + 74, y1: source.y + 56, x2: target.x + 74, y2: target.y + 56 }
}).filter(Boolean))

function buildEmptyForm() { return { name: 'prod-web', description: 'Production web baseline', cloud_provider: 'aliyun', region: '', zone: '', config: {} } }
function cloneDeep(value) { return JSON.parse(JSON.stringify(value ?? {})) }
function deepMerge(base, override) {
  if (Array.isArray(base) || Array.isArray(override)) return cloneDeep(override === undefined ? base : override)
  if (base && typeof base === 'object' && override && typeof override === 'object') {
    const merged = { ...cloneDeep(base) }
    Object.keys(override).forEach((key) => { merged[key] = key in merged ? deepMerge(merged[key], override[key]) : cloneDeep(override[key]) })
    return merged
  }
  return cloneDeep(override === undefined ? base : override)
}
function normalizeNumberValue(value, fallback = 0) {
  if (value === '' || value === null || value === undefined) return fallback
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}
function baseServerConfig(compute = {}) {
  return {
    instance_name: compute.instance_name || '',
    instance_type: compute.instance_type || '',
    image_id: compute.image_id || '',
    system_disk_type: compute.system_disk_type || '',
    system_disk_size: normalizeNumberValue(compute.system_disk_size, 40),
    public_bandwidth: normalizeNumberValue(compute.public_bandwidth, 0),
  }
}
function normalizeServer(server = {}, fallback = {}) {
  const merged = { ...fallback, ...(server || {}) }
  return {
    instance_name: merged.instance_name || merged.name || fallback.instance_name || '',
    instance_type: merged.instance_type || merged.flavor_id || fallback.instance_type || '',
    image_id: merged.image_id || fallback.image_id || '',
    system_disk_type: merged.system_disk_type || fallback.system_disk_type || '',
    system_disk_size: normalizeNumberValue(merged.system_disk_size, fallback.system_disk_size ?? 40),
    public_bandwidth: normalizeNumberValue(merged.public_bandwidth, fallback.public_bandwidth ?? 0),
  }
}
function baseBucketConfig(storage = {}) {
  return {
    bucket_name: storage.bucket_name || '',
    acl: storage.acl || 'private',
    storage_class: storage.storage_class || '',
  }
}
function normalizeBucket(bucket = {}, fallback = {}) {
  const merged = { ...fallback, ...(bucket || {}) }
  return {
    bucket_name: merged.bucket_name || fallback.bucket_name || '',
    acl: merged.acl || fallback.acl || 'private',
    storage_class: merged.storage_class || fallback.storage_class || '',
  }
}
function readComputeInstances(config = {}) {
  const compute = config?.compute && typeof config.compute === 'object' ? config.compute : {}
  const fallback = baseServerConfig(compute)
  const rawInstances = Array.isArray(compute.instances) ? compute.instances : []
  const instances = rawInstances.filter(item => item && typeof item === 'object')
  return (instances.length ? instances : [fallback]).map(item => normalizeServer(item, fallback))
}
function readObjectStorageBuckets(config = {}) {
  const storage = config?.resources?.object_storage && typeof config.resources.object_storage === 'object'
    ? config.resources.object_storage
    : {}
  const fallback = baseBucketConfig(storage)
  const rawBuckets = Array.isArray(storage.buckets) ? storage.buckets : []
  const buckets = rawBuckets.filter(item => item && typeof item === 'object')
  return (buckets.length ? buckets : [fallback]).map(item => normalizeBucket(item, fallback))
}
function syncPrimaryServer(config = {}) {
  const instances = readComputeInstances(config)
  const first = instances[0] || baseServerConfig(config?.compute || {})
  config.compute = { ...(config.compute || {}), ...first, instances }
  return instances
}
function syncPrimaryBucket(config = {}) {
  if (!config.resources) config.resources = {}
  const storage = config.resources.object_storage && typeof config.resources.object_storage === 'object'
    ? config.resources.object_storage
    : {}
  const buckets = readObjectStorageBuckets({ resources: { object_storage: storage } })
  const first = buckets[0] || baseBucketConfig(storage)
  config.resources.object_storage = { ...storage, ...first, enabled: Boolean(storage.enabled), buckets }
  return buckets
}
function normalizeProviderConfigCollections(config = {}) {
  const nextConfig = cloneDeep(config || {})
  if (!nextConfig.compute || typeof nextConfig.compute !== 'object') nextConfig.compute = {}
  if (!nextConfig.resources || typeof nextConfig.resources !== 'object') nextConfig.resources = {}
  syncPrimaryServer(nextConfig)
  syncPrimaryBucket(nextConfig)
  return nextConfig
}
function ensureComputeInstances(config = {}) { return readComputeInstances(config) }
function ensureObjectStorageBuckets(config = {}) { return readObjectStorageBuckets(config) }
function buildProviderConfig(provider, sourceConfig = {}) {
  return normalizeProviderConfigCollections(deepMerge(cloneDeep(catalog.value[provider]?.defaults || {}), sourceConfig || {}))
}
function getFieldValue(path) {
  if (REQUIRED_TOP_LEVEL_FIELDS.includes(path) || ['description'].includes(path)) return form.value[path]
  return getConfigValue(path)
}
function isFilledValue(value) {
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value === 'boolean') return true
  return String(value ?? '').trim() !== ''
}
function isFieldRequired(path, options = {}) {
  const { sectionKey = '' } = options
  if (REQUIRED_TOP_LEVEL_FIELDS.includes(path)) return true
  if (sectionKey && OPTIONAL_SECTION_KEYS.includes(sectionKey)) {
    return isSectionEnabled({ key: sectionKey }) && !String(path).endsWith('.enabled')
  }
  return (REQUIRED_SECTION_PATHS[sectionKey] || []).includes(path)
}
function fieldError(path, label, options = {}) {
  if (!isFieldRequired(path, options)) return ''
  if (isFilledValue(getFieldValue(path))) return ''
  if (path === 'network.open_ingress_ports') return '请至少填写一个开放端口'
  return `${label}不能为空`
}
function summarizeSectionFields(section, options = {}) {
  const { includeSwitch = false, requiredOnly = true } = options
  const fields = (section?.fields || []).filter((field) => {
    if (!includeSwitch && field.type === 'switch') return false
    if (requiredOnly) return isFieldRequired(field.path, { sectionKey: section?.key })
    return true
  })
  const completed = fields.filter(field => isFilledValue(getFieldValue(field.path))).length
  return {
    completed,
    total: fields.length,
    state: fields.length && completed === fields.length ? 'complete' : (completed > 0 ? 'partial' : 'pending'),
  }
}
function summarizeBasicTab() {
  const baseFields = [form.value.name, form.value.cloud_provider, form.value.region, form.value.zone]
  const baseCompleted = baseFields.filter(isFilledValue).length
  const metadata = summarizeSectionFields(metadataSection.value)
  const total = baseFields.length + metadata.total
  const completed = baseCompleted + metadata.completed
  return {
    completed,
    total,
    state: total && completed === total ? 'complete' : (completed > 0 ? 'partial' : 'pending'),
  }
}
function summarizeOptionalGroup(sections, emptyHelper = '未启用扩展资源') {
  const enabledSections = (sections || []).filter(section => isSectionEnabled(section))
  if (!enabledSections.length) {
    return { completed: 0, total: 0, state: 'optional', helper: emptyHelper }
  }
  let completedSections = 0
  enabledSections.forEach((section) => {
    const summary = summarizeSectionFields(section)
    if (!summary.total || summary.completed === summary.total) completedSections += 1
  })
  return {
    completed: completedSections,
    total: enabledSections.length,
    state: completedSections === enabledSections.length ? 'complete' : 'partial',
    helper: `已启用 ${enabledSections.length} 项`,
  }
}
function summarizeNetworkTab() {
  const base = summarizeSectionFields(networkSection.value)
  const optional = summarizeOptionalGroup(networkOptionalSections.value, '未启用附加网络资源')
  const total = base.total + optional.total
  const completed = base.completed + optional.completed
  let state = base.state
  if (base.state === 'complete' && ['complete', 'optional'].includes(optional.state)) state = optional.state === 'complete' ? 'complete' : 'complete'
  else if (base.completed > 0 || optional.state === 'partial' || optional.state === 'complete') state = 'partial'
  const helper = optional.state === 'optional'
    ? `${base.completed}/${base.total} 项网络配置已完成`
    : `${base.completed}/${base.total} 项网络配置，附加资源已启用 ${optional.total} 项`
  return { completed, total, state, helper }
}
function summarizeServersTab() {
  const instances = computeInstances.value
  const fields = computeInstanceFields.value
  const completed = instances.filter(server => fields.every(field => isFilledValue(getServerFieldValue(server, field)))).length
  return {
    completed,
    total: instances.length,
    state: completed === instances.length ? 'complete' : (completed > 0 ? 'partial' : 'pending'),
    helper: `已配置 ${instances.length} 台服务器`,
  }
}
function summarizeStorageTab() {
  const section = resourceOptionalSections.value[0]
  if (!section || !isSectionEnabled(section)) {
    return { completed: 0, total: 0, state: 'optional', helper: '未启用对象存储' }
  }
  const buckets = objectStorageBuckets.value
  const fields = objectStorageConfigFields.value
  const completed = buckets.filter(bucket => fields.every(field => isFilledValue(getBucketFieldValue(bucket, field)))).length
  return {
    completed,
    total: buckets.length,
    state: completed === buckets.length ? 'complete' : (completed > 0 ? 'partial' : 'pending'),
    helper: `已配置 ${buckets.length} 个 Bucket`,
  }
}
function formatDesignTabMeta(name, label, summary) {
  const helper = summary.helper || (summary.total ? `${summary.completed}/${summary.total} 项已完成` : '可按需配置')
  if (summary.state === 'complete') return { name, label, helper, statusText: '已完成', tagType: 'success' }
  if (summary.state === 'optional') return { name, label, helper, statusText: '可选', tagType: 'info' }
  return { name, label, helper, statusText: '待完善', tagType: 'warning' }
}
function buildDefaultStackName(provider, config = {}) {
  const providerDefault = String(catalog.value[provider]?.default_stack_name || '').trim()
  if (providerDefault) return providerDefault
  const instanceName = String(config?.compute?.instance_name || '').trim()
  if (!instanceName) return 'prod-web'
  return instanceName.replace(/-\d+$/, '') || 'prod-web'
}
function suggestZone(provider, region, fallback = '') {
  const zoneOptions = catalog.value[provider]?.zone_options?.[region] || []
  if (zoneOptions.length) return zoneOptions[0].value
  return fallback || catalog.value[provider]?.default_zone || ''
}
function goPrevDesignTab() {
  const index = DESIGN_TAB_ORDER.indexOf(activeDesignTab.value)
  if (index > 0) activeDesignTab.value = DESIGN_TAB_ORDER[index - 1]
}
async function goNextDesignTab() {
  const index = DESIGN_TAB_ORDER.indexOf(activeDesignTab.value)
  if (index < 0) return
  if (index === DESIGN_TAB_ORDER.length - 1) {
    await handleRender()
    return
  }
  activeDesignTab.value = DESIGN_TAB_ORDER[index + 1]
}
function getPreferredOptionalSectionKey(tab = activeDesignTab.value) {
  if (tab === 'database') return databaseSections.value[0]?.key || ''
  if (tab === 'network') return networkOptionalSections.value[0]?.key || ''
  if (tab === 'resources') return resourceOptionalSections.value[0]?.key || ''
  return optionalSections.value[0]?.key || 'metadata'
}
function applyProviderDefaults(provider, options = {}) {
  const meta = catalog.value[provider]
  if (!meta) return
  const nextConfig = buildProviderConfig(provider, options.config || {})
  const nextRegion = options.keepRegion && form.value.region ? form.value.region : (meta.regions?.[0]?.value || '')
  const nextZone = options.keepRegion && form.value.zone ? form.value.zone : suggestZone(provider, nextRegion, form.value.zone)
  form.value = {
    name: (options.keepIdentity ? form.value.name : '') || 'New',
    description: (options.keepIdentity ? form.value.description : '') || 'Production web baseline',
    cloud_provider: provider,
    region: nextRegion,
    zone: nextZone,
    config: nextConfig,
  }
  activeDesignTab.value = 'basic'
  activeSectionKey.value = getPreferredOptionalSectionKey('database') || 'metadata'
  selectedSourceKey.value = ''
  resetTopologyLayout()
  pruneTopologyRelations()
}
async function fetchCatalog() {
  const response = await getIacCatalog()
  catalog.value = response.providers || {}
  const providers = Object.keys(catalog.value)
  if (!providers.length) return
  const provider = catalog.value[form.value.cloud_provider] ? form.value.cloud_provider : providers[0]
  applyProviderDefaults(provider, { keepIdentity: Boolean(form.value.name || form.value.description), config: form.value.config })
}
async function fetchStacks() {
  listLoading.value = true
  try { const response = await getTerraformStacks(); stacks.value = response.results || response || [] } finally { listLoading.value = false }
}
async function fetchExecutions(stackId = activeStackId.value) {
  if (!stackId) { executions.value = []; return }
  executions.value = await getTerraformExecutions(stackId)
}
function handleProviderChange(provider) {
  applyProviderDefaults(provider, { keepIdentity: true })
  activeStackId.value = null
  previewSummary.value = null
  previewFiles.value = {}
  editablePreviewFiles.value = {}
  bindings.value = []
  executions.value = []
}
function handleRegionChange(region) {
  const suggested = suggestZone(form.value.cloud_provider, region, form.value.zone)
  if (suggested && !currentZones.value.some(item => item.value === form.value.zone)) {
    form.value = { ...form.value, zone: suggested }
  }
}
function getConfigValue(path) { return path.split('.').reduce((current, key) => (current == null ? undefined : current[key]), form.value.config) }
function setConfigValue(path, value) {
  const keys = path.split('.')
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  let cursor = nextConfig
  keys.forEach((key, index) => {
    if (index === keys.length - 1) { cursor[key] = value; return }
    if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {}
    cursor = cursor[key]
  })
  if (path.startsWith('compute.')) syncPrimaryServer(nextConfig)
  if (path.startsWith('resources.object_storage')) syncPrimaryBucket(nextConfig)
  form.value.config = nextConfig
  if (path.startsWith('resources.') || path === 'compute.public_bandwidth') { pruneTopologyRelations(); resetTopologyLayout() }
}
function setPortsValue(path, raw) { setConfigValue(path, String(raw || '').split(/[;,\s]+/).map(item => item.trim()).filter(Boolean).map(item => Number(item)).filter(item => Number.isFinite(item))) }
function serverFieldKey(field) { return String(field.path || '').replace(/^compute\./, '') }
function getServerFieldValue(server, field) { return server?.[serverFieldKey(field)] }
function serverFieldError(server, field) { return isFilledValue(getServerFieldValue(server, field)) ? '' : `${field.label}不能为空` }
function serverCardKey(server, index) { return `${server.instance_name || 'server'}-${index}` }
function updateServerField(index, field, value) {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const instances = syncPrimaryServer(nextConfig)
  if (!instances[index]) return
  instances[index][serverFieldKey(field)] = value
  nextConfig.compute.instances = instances.map(item => normalizeServer(item, baseServerConfig(nextConfig.compute)))
  syncPrimaryServer(nextConfig)
  form.value.config = nextConfig
  pruneTopologyRelations()
  resetTopologyLayout()
}
function addServer() {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const instances = syncPrimaryServer(nextConfig)
  const fallback = baseServerConfig(nextConfig.compute)
  instances.push(normalizeServer({ ...fallback, instance_name: `${stackBaseName()}-${String(instances.length + 1).padStart(2, '0')}` }, fallback))
  nextConfig.compute.instances = instances
  syncPrimaryServer(nextConfig)
  form.value.config = nextConfig
  resetTopologyLayout()
}
function removeServer(index) {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const instances = syncPrimaryServer(nextConfig)
  if (instances.length <= 1) return
  instances.splice(index, 1)
  nextConfig.compute.instances = instances
  syncPrimaryServer(nextConfig)
  form.value.config = nextConfig
  pruneTopologyRelations()
  resetTopologyLayout()
}
function bucketFieldKey(field) { return String(field.path || '').replace(/^resources\.object_storage\./, '') }
function getBucketFieldValue(bucket, field) { return bucket?.[bucketFieldKey(field)] }
function bucketFieldError(bucket, field) { return isFilledValue(getBucketFieldValue(bucket, field)) ? '' : `${field.label}不能为空` }
function bucketCardKey(bucket, index) { return `${bucket.bucket_name || 'bucket'}-${index}` }
function updateBucketField(index, field, value) {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const buckets = syncPrimaryBucket(nextConfig)
  if (!buckets[index]) return
  buckets[index][bucketFieldKey(field)] = value
  nextConfig.resources.object_storage.buckets = buckets.map(item => normalizeBucket(item, baseBucketConfig(nextConfig.resources.object_storage)))
  syncPrimaryBucket(nextConfig)
  form.value.config = nextConfig
  pruneTopologyRelations()
  resetTopologyLayout()
}
function addBucket() {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const buckets = syncPrimaryBucket(nextConfig)
  const fallback = baseBucketConfig(nextConfig.resources.object_storage)
  buckets.push(normalizeBucket({ ...fallback, bucket_name: `${stackBaseName()}-bucket-${buckets.length + 1}` }, fallback))
  nextConfig.resources.object_storage.enabled = true
  nextConfig.resources.object_storage.buckets = buckets
  syncPrimaryBucket(nextConfig)
  form.value.config = nextConfig
  pruneTopologyRelations()
  resetTopologyLayout()
}
function removeBucket(index) {
  const nextConfig = normalizeProviderConfigCollections(cloneDeep(form.value.config))
  const buckets = syncPrimaryBucket(nextConfig)
  if (buckets.length <= 1) return
  buckets.splice(index, 1)
  nextConfig.resources.object_storage.buckets = buckets
  syncPrimaryBucket(nextConfig)
  form.value.config = nextConfig
  pruneTopologyRelations()
  resetTopologyLayout()
}
function ensureSubmissionDefaults() {
  const nextName = String(form.value.name || '').trim() || buildDefaultStackName(form.value.cloud_provider, form.value.config)
  const nextRegion = String(form.value.region || '').trim() || (currentRegions.value[0]?.value || '')
  const nextZone = String(form.value.zone || '').trim() || suggestZone(form.value.cloud_provider, nextRegion)
  if (nextName !== form.value.name || nextRegion !== form.value.region || nextZone !== form.value.zone) {
    form.value = { ...form.value, name: nextName, region: nextRegion, zone: nextZone }
  }
}
function normalizePayload(extra = {}) {
  pruneTopologyRelations()
  ensureSubmissionDefaults()
  return { name: form.value.name, description: form.value.description, cloud_provider: form.value.cloud_provider, region: form.value.region, zone: form.value.zone, config: normalizeProviderConfigCollections(cloneDeep(form.value.config)), ...extra }
}
function applyPreview(rendered) {
  previewSummary.value = rendered.summary || null
  previewFiles.value = rendered.generated_files || rendered.files || {}
  editablePreviewFiles.value = cloneDeep(previewFiles.value)
  const names = Object.keys(editablePreviewFiles.value)
  activeFileName.value = names.includes(activeFileName.value) ? activeFileName.value : (names[0] || '')
}
function updatePreviewFile(file, value) { editablePreviewFiles.value = { ...editablePreviewFiles.value, [file]: value } }
function applyStackResponse(response) {
  activeStackId.value = response.id
  hasActiveWorkspace.value = true
  form.value = { name: response.name, description: response.description, cloud_provider: response.cloud_provider, region: response.region, zone: response.zone, config: buildProviderConfig(response.cloud_provider, response.config || {}) }
  bindings.value = response.resource_bindings || []
  activeDesignTab.value = 'basic'
  activeSectionKey.value = getPreferredOptionalSectionKey('database') || 'metadata'
  selectedSourceKey.value = ''
  resetTopologyLayout()
  applyPreview(response)
}
async function handleRender() {
  rendering.value = true
  try {
    const rendered = await renderTerraformProject(normalizePayload())
    applyPreview(rendered)
    activeWorkspaceTab.value = 'preview'
    ElMessage.success('Terraform 配置已生成')
  } finally { rendering.value = false }
}
async function handleSave() {
  saving.value = true
  const isUpdate = Boolean(activeStackId.value)
  try {
    const payload = normalizePayload()
    const response = isUpdate ? await updateTerraformStack(activeStackId.value, payload) : await createTerraformStack(payload)
    applyStackResponse(response)
    activeWorkspaceTab.value = 'preview'
    await fetchStacks(); await fetchExecutions(response.id)
    ElMessage.success(isUpdate ? 'Terraform 方案已保存' : 'Terraform 方案已创建')
  } finally { saving.value = false }
}
async function loadStack(id) {
  const response = await getTerraformStack(id)
  applyStackResponse(response)
  activeWorkspaceTab.value = 'preview'
  await fetchExecutions(id)
  ElMessage.success(`已载入方案 ${response.name}`)
}
function resetForm() {
  activeStackId.value = null
  hasActiveWorkspace.value = true
  previewSummary.value = null
  previewFiles.value = {}
  editablePreviewFiles.value = {}
  bindings.value = []
  executions.value = []
  activeWorkspaceTab.value = 'design'
  applyProviderDefaults(form.value.cloud_provider || Object.keys(catalog.value)[0] || 'aliyun')
}
async function handleDelete(row) { await deleteTerraformStack(row.id); if (activeStackId.value === row.id) resetForm(); await fetchStacks(); ElMessage.success('方案已删除') }
async function handleDownloadTemplate(row) { const blob = await downloadTerraformStack(row.id); triggerBlobDownload(blob, `${row.name}-terraform.zip`) }
function resetSecretForm() { const values = {}; secretFields.value.forEach((field) => { values[field.key] = '' }); secretForm.value = values }
function openSecretDialog(mode, action = '') {
  if (mode === 'execute' && !activeStackId.value) { ElMessage.warning('请先保存或载入一个 Terraform 方案'); return }
  if (mode === 'execute') activeWorkspaceTab.value = 'execution'
  secretDialogMode.value = mode
  pendingExecutionAction.value = action
  resetSecretForm()
  secretDialogVisible.value = true
}
async function handleSecretDialogSubmit() {
  dialogSubmitting.value = true
  try {
    if (secretDialogMode.value === 'export') {
      const blob = await bundleTerraformProject(normalizePayload({ secrets: { ...secretForm.value } }))
      triggerBlobDownload(blob, `${form.value.name || 'terraform'}-terraform.zip`)
      ElMessage.success('ZIP 已下载')
    } else {
      await runExecution(pendingExecutionAction.value, { ...secretForm.value })
    }
    secretDialogVisible.value = false
  } finally { dialogSubmitting.value = false }
}
async function runExecution(action, secrets = {}) {
  if (!activeStackId.value) { ElMessage.warning('请先保存或载入一个 Terraform 方案'); return }
  executingAction.value = action
  try {
    const response = await executeTerraformStack(activeStackId.value, { action, secrets })
    if (response.stack) applyStackResponse(response.stack)
    activeWorkspaceTab.value = 'execution'
    await fetchStacks(); await fetchExecutions(activeStackId.value)
    const execution = response.execution || {}
    if (execution.status === 'failed') ElMessage.warning(response.message || 'Terraform 执行失败')
    else ElMessage.success(response.message || `Terraform ${action} 执行成功`)
  } finally { executingAction.value = '' }
}
async function handleSyncCmdb() {
  if (!activeStackId.value) { ElMessage.warning('请先保存或载入一个 Terraform 方案'); return }
  syncingCmdb.value = true
  try {
    const response = await syncTerraformStackCmdb(activeStackId.value)
    if (response.stack) applyStackResponse(response.stack)
    activeWorkspaceTab.value = 'execution'
    await fetchStacks()
    ElMessage.success(response.message || 'CMDB 同步完成')
  } finally { syncingCmdb.value = false }
}
function triggerBlobDownload(blob, filename) { const url = window.URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); document.body.removeChild(anchor); window.URL.revokeObjectURL(url) }
async function copyCurrentFile() { if (!activeFileName.value) return; await navigator.clipboard.writeText(editablePreviewFiles.value[activeFileName.value] || ''); ElMessage.success(`已复制 ${activeFileName.value}`) }
function formatPorts(value) { return Array.isArray(value) ? value.join(',') : '' }
function formatTime(value) { if (!value) return '-'; return String(value).replace('T', ' ').slice(0, 19) }
function stringifyJson(value) { if (!value || (typeof value === 'object' && !Object.keys(value).length)) return '-'; return JSON.stringify(value, null, 2) }
function isOptionalSection(section) { return OPTIONAL_SECTION_KEYS.includes(section.key) }
function isSectionEnabled(section) { return !isOptionalSection(section) || Boolean(getConfigValue(`resources.${section.key}.enabled`)) }
function shouldDisableField(section, field) { return isOptionalSection(section) && field.type !== 'switch' && !isSectionEnabled(section) }
function statusTagType(status) { if (status === 'success') return 'success'; if (status === 'failed') return 'danger'; if (status === 'running') return 'warning'; return 'info' }
function sectionDescription(key) { return SECTION_DESCRIPTIONS[key] || '按当前云厂商的字段填写参数。' }
function stackBaseName() { return String(form.value.name || 'terraform').trim().replace(/\s+/g, '-').replace(/^-+|-+$/g, '') || 'terraform' }
function sectionResourceName(section) { return sectionResourceNameByKey(section.key) }
function sectionResourceNameByKey(key) {
  if (key === 'metadata') return form.value.description || '治理信息'
  if (key === 'network') return `${stackBaseName()}-vpc / ${stackBaseName()}-subnet`
  if (key === 'compute') return computeInstances.value.length > 1 ? `${computeInstances.value.length} 台服务器` : (getConfigValue('compute.instance_name') || `${stackBaseName()}-compute`)
  if (key === 'rds') return getConfigValue('resources.rds.name') || '未命名 RDS'
  if (key === 'redis') return getConfigValue('resources.redis.name') || '未命名 Redis'
  if (key === 'load_balancer') return getConfigValue('resources.load_balancer.name') || '未命名负载均衡'
  if (key === 'nat_gateway') return getConfigValue('resources.nat_gateway.name') || '未命名 NAT'
  if (key === 'object_storage') return objectStorageBuckets.value.length > 1 ? `${objectStorageBuckets.value.length} 个 Bucket` : (getConfigValue('resources.object_storage.bucket_name') || '未命名 Bucket')
  return '-'
}
function resourceLabel(key) { return availableResourceOptions.value.find(item => item.value === key)?.label || key }
function relationTypeLabel(value) { return relationTypeOptions.value.find(item => item.value === value)?.label || value }
function ensureTopologyState() { const current = getConfigValue('topology.relations'); if (!Array.isArray(current)) setConfigValue('topology.relations', []) }
function topologyRelationKey(relation, index) { return `${relation.source || 'source'}-${relation.relation_type || 'type'}-${relation.target || 'target'}-${index}` }
function defaultNodePosition(key, index) {
  const presets = { vpc: { x: 50, y: 40 }, subnet: { x: 270, y: 40 }, security_group: { x: 510, y: 40 }, compute: { x: 270, y: 200 }, eip: { x: 510, y: 200 }, load_balancer: { x: 50, y: 200 }, rds: { x: 50, y: 320 }, redis: { x: 270, y: 320 }, nat_gateway: { x: 510, y: 320 }, object_storage: { x: 690, y: 200 } }
  return presets[key] || { x: 50 + (index % 4) * 180, y: 40 + Math.floor(index / 4) * 130 }
}
function resetTopologyLayout() { const next = {}; availableResourceOptions.value.forEach((item, index) => { next[item.value] = defaultNodePosition(item.value, index) }); topologyLayout.value = next }
function nodeStyle(node) { return { left: `${node.x}px`, top: `${node.y}px` } }
function setTopologyRelations(relations) { setConfigValue('topology.relations', relations) }
function updateTopologyRelation(index, key, value) { ensureTopologyState(); const next = cloneDeep(topologyRelations.value); if (!next[index]) return; next[index][key] = value; setTopologyRelations(next) }
function removeTopologyRelation(index) { ensureTopologyState(); const next = cloneDeep(topologyRelations.value); next.splice(index, 1); setTopologyRelations(next) }
function upsertTopologyRelation(source, target, relationType, description = '') {
  if (!source || !target || source === target) return
  ensureTopologyState()
  const next = cloneDeep(topologyRelations.value)
  const existingIndex = next.findIndex(item => item.source === source && item.target === target && item.relation_type === relationType)
  if (existingIndex >= 0) { if (description) next[existingIndex].description = description }
  else next.push({ source, target, relation_type: relationType, description })
  setTopologyRelations(next)
}
function pruneTopologyRelations() { const allowed = new Set(availableResourceOptions.value.map(item => item.value)); const filtered = topologyRelations.value.filter(item => allowed.has(item?.source) && allowed.has(item?.target)); if (filtered.length !== topologyRelations.value.length) setTopologyRelations(filtered) }
function buildRecommendedTopologyRelations() {
  const available = new Set(availableResourceOptions.value.map(item => item.value))
  const relations = [
    { source: 'subnet', relation_type: 'depends_on', target: 'vpc', description: 'Subnet depends on VPC' },
    { source: 'security_group', relation_type: 'depends_on', target: 'vpc', description: 'Security group depends on VPC' },
    { source: 'compute', relation_type: 'depends_on', target: 'subnet', description: 'Compute depends on subnet' },
    { source: 'compute', relation_type: 'depends_on', target: 'security_group', description: 'Compute depends on security group' },
    { source: 'load_balancer', relation_type: 'connects_to', target: 'compute', description: 'Load balancer routes to compute' },
    { source: 'compute', relation_type: 'depends_on', target: 'rds', description: 'Application host depends on RDS' },
    { source: 'compute', relation_type: 'depends_on', target: 'redis', description: 'Application host depends on Redis' },
    { source: 'compute', relation_type: 'depends_on', target: 'object_storage', description: 'Application host depends on object storage' },
    { source: 'nat_gateway', relation_type: 'depends_on', target: 'subnet', description: 'NAT gateway depends on subnet' },
    { source: 'rds', relation_type: 'depends_on', target: 'subnet', description: 'RDS depends on subnet' },
    { source: 'redis', relation_type: 'depends_on', target: 'subnet', description: 'Redis depends on subnet' },
    { source: 'compute', relation_type: 'depends_on', target: 'eip', description: 'Compute depends on EIP' },
  ]
  return relations.filter(item => available.has(item.source) && available.has(item.target))
}
function applyRecommendedTopology() { setTopologyRelations(buildRecommendedTopologyRelations()); ElMessage.success('已填充推荐资源关系') }
function handleNodeClick(key) {
  if (!selectedSourceKey.value) { selectedSourceKey.value = key; return }
  if (selectedSourceKey.value === key) { selectedSourceKey.value = ''; return }
  upsertTopologyRelation(selectedSourceKey.value, key, selectedRelationType.value)
  selectedSourceKey.value = ''
  ElMessage.success('已创建资源关系')
}
function startNodeDrag(event, key) {
  const node = topologyLayout.value[key] || defaultNodePosition(key, 0)
  dragState.value = { key, startX: event.clientX, startY: event.clientY, originX: node.x, originY: node.y }
  window.addEventListener('mousemove', handleNodeDrag)
  window.addEventListener('mouseup', stopNodeDrag)
}
function handleNodeDrag(event) {
  if (!dragState.value) return
  const { key, startX, startY, originX, originY } = dragState.value
  const nextX = Math.max(20, Math.min(TOPOLOGY_BOUNDS.width - 168, originX + event.clientX - startX))
  const nextY = Math.max(20, Math.min(TOPOLOGY_BOUNDS.height - 112, originY + event.clientY - startY))
  topologyLayout.value = { ...topologyLayout.value, [key]: { x: nextX, y: nextY } }
}
function stopNodeDrag() { dragState.value = null; window.removeEventListener('mousemove', handleNodeDrag); window.removeEventListener('mouseup', stopNodeDrag) }
watch(activeDesignTab, (value) => {
  const expected = getPreferredOptionalSectionKey(value)
  if (['database', 'network', 'resources'].includes(value) && expected && activeSectionKey.value !== expected) {
    const available = value === 'database'
      ? databaseSections.value
      : value === 'network'
        ? networkOptionalSections.value
        : resourceOptionalSections.value
    if (!available.some(item => item.key === activeSectionKey.value)) activeSectionKey.value = expected
  }
})
onMounted(async () => { await fetchCatalog(); await fetchStacks() })
onBeforeUnmount(() => { stopNodeDrag() })
</script>

<style scoped>
.terraform-page { display: flex; flex-direction: column; gap: 4px; }
.panel { background: linear-gradient(135deg, rgba(239,246,255,.96) 0%, rgba(236,254,255,.94) 52%, rgba(248,250,252,.98) 100%); border: 1px solid rgba(96,165,250,.18); border-radius: 24px; box-shadow: 0 16px 36px rgba(14,165,233,.08); padding: 14px 22px; }
.hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.terraform-header { align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-subtitle, .provider-desc, .config-section-desc, .resource-switch-desc, .workspace-hint { color: var(--text-secondary); line-height: 1.6; }
.topology-toolbar, .execution-meta, .execution-actions, .topology-tip, .section-head-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.workspace-banner { display: flex; align-items: center; gap: 10px; margin-top: -6px; padding: 14px 16px; border-radius: 16px; border: 1px dashed rgba(148, 163, 184, 0.28); background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.92)); color: var(--text-secondary); }
.workspace-banner.active { border-style: solid; border-color: rgba(34, 197, 94, 0.24); background: linear-gradient(180deg, rgba(240, 253, 244, 0.96), rgba(236, 253, 245, 0.92)); color: #166534; }
.workspace-banner-icon { font-size: 18px; color: #16a34a; }
.release-hero-title-row { display: flex; align-items: center; gap: 12px; }
.release-hero-title-inline { flex-wrap: wrap; }
.title-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 14px; background: linear-gradient(135deg, #0ea5e9, #2563eb); color: #fff; box-shadow: 0 10px 20px rgba(37,99,235,.2); font-size: 20px; }
.release-hero-title-row h2 { margin: 0; color: #0f172a; }
.inline-subtitle { max-width: none; margin: 0; font-size: 13px; }
.hero-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.hero-actions :deep(.el-button) { min-height: 38px; padding: 0 16px; border-radius: 12px; }
.new-plan-button { border: none; background: linear-gradient(135deg, #22c55e, #16a34a); box-shadow: 0 12px 24px rgba(22, 163, 74, 0.22); }
.new-plan-button:hover, .new-plan-button:focus { background: linear-gradient(135deg, #4ade80, #22c55e); }
.module-tabs { border-radius: 20px; padding: 18px; background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92)); box-shadow: 0 18px 36px rgba(15, 23, 42, 0.06); }
.module-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.module-tabs :deep(.el-tabs__nav-wrap::after) { background-color: rgba(148, 163, 184, 0.2); }
.module-tabs :deep(.el-tabs__content) { overflow: visible; }
.design-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.design-tabs :deep(.el-tabs__item) { font-weight: 600; }
.design-tabs :deep(.el-tabs__nav-wrap::after) { background-color: rgba(148, 163, 184, 0.16); }
.design-tabs :deep(.el-tabs__content) { overflow: visible; }
.tab-label { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; }
.tab-label em { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 999px; background: rgba(14, 165, 233, 0.12); color: #0369a1; font-style: normal; font-size: 12px; }
.design-tab-label { display: inline-flex; align-items: center; gap: 8px; }
.design-tab-label small { color: var(--text-secondary); font-size: 12px; font-weight: 500; }
.form-card, .preview-card, .execution-card, .stack-table-card { display: flex; flex-direction: column; gap: 16px; }
.section-head, .config-section-head, .resource-switch-head, .execution-toolbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.provider-tip, .resource-switcher, .config-section, .multi-config-card { padding: 16px; border-radius: 16px; border: 1px solid rgba(148, 163, 184, 0.18); background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.86)); }
.provider-title, .config-section-title, .resource-switch-title, .relationship-preview-head, .binding-title { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.workspace-header { margin-bottom: 2px; }
.inline-head { margin-bottom: 10px; }
.resource-switcher-grid, .summary-grid, .resource-list, .relationship-list, .binding-grid, .resource-pill-list, .multi-card-list { display: grid; gap: 12px; }
.resource-switcher-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.multi-card-list { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.multi-config-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.multi-config-title { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.multi-config-desc, .preview-edit-tip { color: var(--text-secondary); line-height: 1.6; }
.design-step-footer, .design-step-actions, .design-step-summary { display: flex; align-items: center; gap: 12px; }
.design-step-footer { justify-content: space-between; padding-top: 4px; border-top: 1px solid rgba(148, 163, 184, 0.18); }
.design-step-summary { color: var(--text-secondary); }
.design-step-summary strong { color: var(--text-primary); }
.resource-switch-card { width: 100%; padding: 14px; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 14px; background: rgba(255, 255, 255, 0.78); text-align: left; cursor: pointer; transition: 0.2s ease; }
.resource-switch-card.active, .resource-switch-card:hover { border-color: rgba(14, 165, 233, 0.45); box-shadow: 0 10px 24px rgba(14, 165, 233, 0.12); transform: translateY(-1px); }
.resource-switch-card.disabled, .section-disabled { opacity: 0.72; }
.resource-switch-name { margin-top: 12px; font-size: 13px; font-weight: 600; color: var(--text-primary); }
.topology-panel { gap: 16px; }
.topology-tip, .binding-meta, .log-title, .topology-node-kind, .summary-label, .resource-kind { font-size: 12px; color: var(--text-secondary); }
.topology-canvas { position: relative; height: 420px; border-radius: 18px; overflow: hidden; border: 1px solid rgba(15, 23, 42, 0.08); background: radial-gradient(circle at top left, rgba(14, 165, 233, 0.14), transparent 32%), radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.12), transparent 28%), linear-gradient(180deg, #f8fafc, #eef2ff); }
.topology-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.topology-edge { stroke: rgba(15, 118, 110, 0.76); stroke-width: 2.5; }
.topology-edge.active { stroke: #0f766e; stroke-width: 3; }
.topology-edge-label { font-size: 12px; font-weight: 700; fill: #0f172a; text-anchor: middle; }
.edge-delete { width: 24px; height: 24px; border: none; border-radius: 999px; background: rgba(239, 68, 68, 0.92); color: #fff; cursor: pointer; pointer-events: auto; }
.topology-node { position: absolute; width: 148px; min-height: 86px; padding: 12px; border-radius: 16px; border: 1px solid rgba(14, 165, 233, 0.28); background: rgba(255, 255, 255, 0.9); box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08); cursor: move; user-select: none; }
.topology-node.selected { border-color: #0f766e; box-shadow: 0 16px 32px rgba(15, 118, 110, 0.16); }
.topology-node-kind, .summary-label, .resource-kind { display: block; margin-bottom: 6px; }
.topology-node-name { font-weight: 700; color: var(--text-primary); line-height: 1.5; word-break: break-word; }
.resource-pill, .resource-chip, .relationship-chip, .binding-card, .relation-item, .summary-item { padding: 12px 14px; border-radius: 14px; border: 1px solid rgba(148, 163, 184, 0.18); background: rgba(255, 255, 255, 0.85); }
.summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.resource-list, .relationship-list, .binding-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.relationship-preview, .relation-list, .log-block { display: flex; flex-direction: column; gap: 10px; }
.relation-item { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.relation-main { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.relation-actions { display: flex; gap: 8px; align-items: center; min-width: 280px; }
.file-tabs { min-height: 480px; }
.empty-guide { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; min-height: 240px; padding: 28px 24px; border: 1px dashed rgba(14, 165, 233, 0.28); border-radius: 18px; background: linear-gradient(180deg, rgba(240, 249, 255, 0.9), rgba(248, 250, 252, 0.96)); text-align: center; }
.empty-guide-icon { display: inline-flex; align-items: center; justify-content: center; width: 54px; height: 54px; border-radius: 16px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #fff; font-size: 24px; box-shadow: 0 14px 28px rgba(14, 165, 233, 0.18); }
.execution-guide-icon { background: linear-gradient(135deg, #34d399, #059669); box-shadow: 0 14px 28px rgba(5, 150, 105, 0.18); }
.empty-guide-title { font-size: 18px; font-weight: 700; color: var(--text-primary); }
.empty-guide-desc { max-width: 620px; color: var(--text-primary); line-height: 1.8; }
.empty-guide-steps { max-width: 680px; color: var(--text-secondary); line-height: 1.8; font-size: 13px; }
.file-preview, .log-preview { margin: 0; overflow: auto; padding: 16px; border-radius: 14px; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.file-preview { min-height: 420px; max-height: 640px; }
.file-editor :deep(.el-textarea__inner) { min-height: 420px !important; border-radius: 14px; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.65; font-family: Consolas, "Courier New", monospace; border-color: rgba(148, 163, 184, 0.2); }
.file-editor :deep(.el-textarea__inner:focus) { box-shadow: 0 0 0 1px rgba(14, 165, 233, 0.28) inset; }
.error-log { color: #fecaca; }
@media (max-width: 960px) {
  .hero, .terraform-header { flex-direction: column; align-items: stretch; }
  .workspace-banner { align-items: flex-start; }
  .design-tab-label, .design-step-footer, .design-step-actions, .design-step-summary { flex-direction: column; align-items: stretch; }
  .resource-switcher-grid, .summary-grid, .resource-pill-list, .resource-list, .relationship-list, .multi-card-list { grid-template-columns: 1fr; }
  .relation-item, .relation-actions { flex-direction: column; align-items: stretch; min-width: 0; }
}
.hero.panel { border-radius: 20px; }
</style>

