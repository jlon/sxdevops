import request from '../request'

export const getEventWallOverview = (params) => request.get('/events/overview/', { params })
export const getEventWallEvents = (params) => request.get('/events/', { params })
export const getEventWallEvent = (id) => request.get(`/events/${id}/`)
export const getEventWallAssociations = (params) => request.get('/events/associations/', { params })
export const getEventWallFilterOptions = (params) => request.get('/events/filter_options/', { params })
