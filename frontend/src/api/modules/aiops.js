import request from '../request'

export const getAIOpsBootstrap = () => request.get('/aiops/bootstrap/')

export const getAIOpsSessions = (params) => request.get('/aiops/sessions/', { params })
export const createAIOpsSession = (data) => request.post('/aiops/sessions/', data)
export const getAIOpsMessages = (id) => request.get(`/aiops/sessions/${id}/messages/`)
export const sendAIOpsMessage = (id, data) => request.post(`/aiops/sessions/${id}/send_message/`, data)

export const confirmAIOpsAction = (id) => request.post(`/aiops/actions/${id}/confirm/`)
export const cancelAIOpsAction = (id) => request.post(`/aiops/actions/${id}/cancel/`)

export const getAIOpsConfig = () => request.get('/aiops/admin/config/')
export const updateAIOpsConfig = (data) => request.put('/aiops/admin/config/', data)
export const getAIOpsAuditOverview = () => request.get('/aiops/admin/audit/overview/')
export const getAIOpsAuditSessions = (params) => request.get('/aiops/admin/audit/sessions/', { params })
export const getAIOpsAuditToolInvocations = (params) => request.get('/aiops/admin/audit/tool-invocations/', { params })
export const getAIOpsAuditActions = (params) => request.get('/aiops/admin/audit/actions/', { params })

export const getAIOpsProviders = () => request.get('/aiops/admin/providers/')
export const createAIOpsProvider = (data) => request.post('/aiops/admin/providers/', data)
export const updateAIOpsProvider = (id, data) => request.patch(`/aiops/admin/providers/${id}/`, data)
export const deleteAIOpsProvider = (id) => request.delete(`/aiops/admin/providers/${id}/`)
export const testAIOpsProvider = (id) => request.post(`/aiops/admin/providers/${id}/test_connection/`)

export const getAIOpsMcpServers = () => request.get('/aiops/admin/mcp-servers/')
export const createAIOpsMcpServer = (data) => request.post('/aiops/admin/mcp-servers/', data)
export const updateAIOpsMcpServer = (id, data) => request.patch(`/aiops/admin/mcp-servers/${id}/`, data)
export const deleteAIOpsMcpServer = (id) => request.delete(`/aiops/admin/mcp-servers/${id}/`)

export const getAIOpsSkills = () => request.get('/aiops/admin/skills/')
export const createAIOpsSkill = (data) => request.post('/aiops/admin/skills/', data)
export const updateAIOpsSkill = (id, data) => request.patch(`/aiops/admin/skills/${id}/`, data)
export const deleteAIOpsSkill = (id) => request.delete(`/aiops/admin/skills/${id}/`)
