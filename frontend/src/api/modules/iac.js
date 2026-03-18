import request from '../request'

const TERRAFORM_EXECUTION_TIMEOUT = 900000

export const getIacCatalog = () => request.get('/iac/catalog/')
export const renderTerraformProject = (data) => request.post('/iac/render/', data)
export const bundleTerraformProject = (data) => request.post('/iac/bundle/', data, { responseType: 'blob' })

export const getTerraformStacks = (params) => request.get('/iac/stacks/', { params })
export const getTerraformStack = (id) => request.get(`/iac/stacks/${id}/`)
export const createTerraformStack = (data) => request.post('/iac/stacks/', data)
export const updateTerraformStack = (id, data) => request.put(`/iac/stacks/${id}/`, data)
export const deleteTerraformStack = (id) => request.delete(`/iac/stacks/${id}/`)
export const downloadTerraformStack = (id) => request.get(`/iac/stacks/${id}/download/`, { responseType: 'blob' })
export const getTerraformExecutions = (id) => request.get(`/iac/stacks/${id}/executions/`)
export const executeTerraformStack = (id, data) => request.post(`/iac/stacks/${id}/execute/`, data, { timeout: TERRAFORM_EXECUTION_TIMEOUT })
export const syncTerraformStackCmdb = (id) => request.post(`/iac/stacks/${id}/sync_cmdb/`)
