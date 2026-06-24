from sxdevops.features import filter_feature_tools, tool_feature_enabled


PLATFORM_TOOL_EXECUTORS = {
    'query_knowledge_graph',
    'query_hosts',
    'query_observability',
    'query_workorders',
    'query_task_center',
    'query_task_resources',
    'query_event_wall',
    'query_container_assets',
    'query_k8s_cluster_summary',
    'query_k8s_resources',
    'query_alerts',
    'query_alert_root_cause',
    'query_alert_metrics',
    'query_dashboard_metadata',
    'query_grafana_promql',
    'query_dashboard_panel_data',
    'query_observability_links',
    'query_events',
    'query_logs',
    'query_traces',
    'query_recent_changes',
    'query_host_tasks',
    'generate_host_task',
    'draft_aiops_skill',
}


TOOL_PERMISSION_MAP = {
    'query_knowledge_graph': ('any', ['aiops.knowledge.view']),
    'query_hosts': ('any', ['ops.host.view']),
    'query_observability': ('any', ['ops.alert.view', 'ops.log.entry.view', 'ops.log.query', 'ops.trace.view', 'ops.deployment.view']),
    'query_workorders': ('any', ['ops.ticket.view', 'ops.deployment.view']),
    'query_task_center': ('any', ['ops.host.execute']),
    'query_task_resources': ('any', ['ops.task.resource.view']),
    'query_event_wall': ('any', ['eventwall.view']),
    'query_container_assets': ('any', ['ops.k8s.view', 'ops.docker.view']),
    'query_k8s_cluster_summary': ('any', ['ops.k8s.view']),
    'query_k8s_resources': ('any', ['ops.k8s.view']),
    'query_alerts': ('any', ['ops.alert.view']),
    'query_alert_root_cause': ('any', ['ops.alert.view']),
    'query_alert_metrics': ('any', ['ops.metric.query']),
    'query_dashboard_metadata': ('any', ['ops.grafana.view']),
    'query_grafana_promql': ('any', ['ops.metric.query', 'ops.grafana.view']),
    'query_dashboard_panel_data': ('any', ['ops.grafana.view']),
    'query_observability_links': ('any', ['ops.observability.link.view']),
    'query_events': ('any', ['eventwall.view']),
    'query_logs': ('any', ['ops.log.entry.view', 'ops.log.query']),
    'query_traces': ('any', ['ops.trace.view']),
    'query_recent_changes': ('any', ['ops.deployment.view']),
    'query_host_tasks': ('any', ['ops.host.execute']),
    'generate_host_task': ('any', ['aiops.task.generate']),
    'draft_aiops_skill': ('any', ['aiops.config.manage']),
}


def platform_tool_allowed(user, tool_name, permission_checker):
    if not tool_feature_enabled(tool_name):
        return False
    mode, permissions = TOOL_PERMISSION_MAP.get(tool_name, ('any', []))
    if not permissions:
        return False
    if mode == 'all':
        return permission_checker(user, list(permissions))
    return any(permission_checker(user, [permission]) for permission in permissions)


def whitelisted_platform_tool_names(active_mcp_servers, platform_server_type, user, permission_checker):
    tool_names = []
    for server in active_mcp_servers:
        if getattr(server, 'server_type', '') != platform_server_type:
            continue
        for tool_name in filter_feature_tools(getattr(server, 'tool_whitelist', None) or []):
            if tool_name not in tool_names and platform_tool_allowed(user, tool_name, permission_checker):
                tool_names.append(tool_name)
    return tool_names


def validate_platform_tool_registry(active_mcp_servers, platform_server_type, user, permission_checker, catalog_tool_names):
    whitelisted = set()
    disabled = set()
    for server in active_mcp_servers:
        if getattr(server, 'server_type', '') != platform_server_type:
            continue
        raw_names = list(getattr(server, 'tool_whitelist', None) or [])
        filtered_names = filter_feature_tools(raw_names)
        disabled.update(set(raw_names) - set(filtered_names))
        whitelisted.update(filtered_names)

    catalog_tool_names = set(catalog_tool_names or [])
    executable = set(PLATFORM_TOOL_EXECUTORS)
    allowed = {
        name
        for name in whitelisted
        if platform_tool_allowed(user, name, permission_checker)
    }
    return {
        'status': 'ok',
        'whitelisted_count': len(whitelisted),
        'allowed_count': len(allowed),
        'missing_catalog': sorted(allowed - catalog_tool_names),
        'missing_executor': sorted(allowed - executable),
        'catalog_without_executor': sorted(catalog_tool_names - executable),
        'executor_not_whitelisted': sorted((catalog_tool_names & executable) - whitelisted),
        'feature_disabled': sorted(disabled),
    }


def filter_registered_platform_tools(tool_names):
    return [
        tool_name
        for tool_name in filter_feature_tools(tool_names or [])
        if tool_name in PLATFORM_TOOL_EXECUTORS
    ]
