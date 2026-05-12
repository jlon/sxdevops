import re
from collections import Counter, defaultdict

from eventwall.models import EventRecord, EventSource
from ops.models import (
    Alert,
    GrafanaSetting,
    LogDataSource,
    LogEntry,
    ObservabilityDataSourceLink,
    SystemPostureSystem,
    TracingDataSource,
)

from .models import AIOpsKnowledgeEnvironment


UNKNOWN_SYSTEM = '未标记系统'
UNKNOWN_ENV = '未标记环境'
UNKNOWN_SERVICE = '未标记服务'
MOJIBAKE_HINTS = {
    '\u9422', '\u975b', '\u6662', '\u93c8', '\u9359', '\u6d5c', '\u7eef',
    '\u93ac', '\u5a34', '\u6fa7', '\u7039', '\u68ff', '\u6d60', '\u65c2',
}


CAPABILITY_DEFS = [
    ('logs', '日志', 'logs', '/logs'),
    ('tracing', '链路', 'tracing', '/observability/tracing'),
    ('dashboards', '看板', 'dashboard', '/observability/grafana'),
    ('alerts', '告警', 'alert', '/alerts'),
    ('posture', '系统态势', 'posture', '/observability/system-posture'),
    ('internal_events', '内部事件', 'internal_event', '/events/wall'),
    ('external_events', '外部事件', 'external_event', '/events/wall'),
]


def _mojibake_score(text):
    return sum(text.count(token) for token in MOJIBAKE_HINTS) + text.count(chr(0xfffd))


def _repair_text(value):
    text = str(value or '').strip()
    if not text:
        return ''
    candidates = [text]
    for encoding in ('latin1', 'gbk', 'gb18030'):
        try:
            repaired = text.encode(encoding).decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired and any('\u4e00' <= char <= '\u9fff' for char in repaired):
            candidates.append(repaired)
    return min(candidates, key=lambda item: (_mojibake_score(item), len(item)))


def _clean(value, fallback=''):
    text = _repair_text(value)
    return text or fallback


def _is_demoish_text(*values):
    text = ' '.join(str(value or '') for value in values).lower()
    return any(keyword in text for keyword in ['demo', '演示', '示例', '样例'])


def _is_invalid_environment(value):
    text = _clean(value)
    if not text:
        return True
    lowered = text.lower()
    return lowered.startswith('env-') or set(text) == {'?'} or text in {'未知', 'unknown', 'null', 'none', '-'}


def _is_microservice_name(value):
    text = _clean(value)
    if not text or len(text) > 64:
        return False
    lowered = text.lower()
    if lowered.endswith('-release'):
        return False
    blocked_tokens = [
        'demo',
        'alert-demo',
        'traffic-generator',
        'prometheus',
        'alertmanager',
        'kube-state-metrics',
        'node-exporter',
        'grafana',
        'loki',
        'tempo',
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    if lowered.startswith(('kube-', 'kubernetes-', 'node-', 'job ')):
        return False
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', text))


def _node_key(kind, *parts):
    return ':'.join([kind, *[str(part).strip().replace(':', '_') for part in parts if str(part).strip()]])


def _matches_filters(value, allowed):
    return not allowed or value in allowed


def _append_unique(target, value, limit=4):
    if not value or value in target:
        return
    if len(target) < limit:
        target.append(value)


def _empty_graph(filters=None):
    return {
        'nodes': [],
        'edges': [],
        'summary': {
            'node_count': 0,
            'edge_count': 0,
            'service_count': 0,
            'datasource_count': 0,
            'event_source_count': 0,
            'capability_count': 0,
        },
        'filters': {
            'systems': [],
            'business_lines': [],
            'environments': [],
            'services': [],
            **(filters or {}),
        },
        'relation_legend': [
            {'key': 'observability_link', 'label': '可观测性跳转配置'},
            {'key': 'environment_system', 'label': '环境包含系统'},
            {'key': 'system_service', 'label': '系统承载服务'},
            {'key': 'service_capability', 'label': '服务产生数据'},
            {'key': 'system_dependency', 'label': '系统依赖'},
            {'key': 'capability_datasource', 'label': '能力接入数据源'},
            {'key': 'capability_event_source', 'label': '能力接入事件源'},
        ],
        'environment_required': True,
    }


def _clean_list(values):
    result = []
    for value in values or []:
        text = _clean(value)
        if text and text not in result:
            result.append(text)
    return result


def _int_list(values):
    result = []
    for value in values or []:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item and item not in result:
            result.append(item)
    return result


def _enabled_knowledge_environments():
    return list(AIOpsKnowledgeEnvironment.objects.filter(is_enabled=True).order_by('name', 'id'))


def resolve_knowledge_environment(name):
    text = _clean(name)
    if not text:
        return None
    config = AIOpsKnowledgeEnvironment.objects.filter(is_enabled=True, name=text).first()
    if not config:
        return None
    return {
        'name': config.name,
        'event_environments': _clean_list(config.event_environments),
        'grafana_folder_keys': _clean_list(config.grafana_folder_keys),
        'log_datasource_ids': _int_list(config.log_datasource_ids),
        'tracing_datasource_ids': _int_list(config.tracing_datasource_ids),
        'alert_environments': _clean_list(config.alert_environments),
    }


def resolve_knowledge_environments_from_text(text):
    query = str(text or '')
    matches = []
    for config in _enabled_knowledge_environments():
        if config.name and config.name in query:
            resolved = resolve_knowledge_environment(config.name)
            if resolved:
                matches.append(resolved)
    return matches


def _folder_matches(folder, selected_folders):
    return bool(_matched_configured_folder(folder, selected_folders))


def _matched_configured_folder(folder, selected_folders):
    folder = _clean(folder)
    if not folder:
        return ''
    if not selected_folders:
        return folder
    matches = [
        selected
        for selected in selected_folders
        if folder == selected or folder.startswith(f'{selected}/')
    ]
    if not matches:
        return ''
    return sorted(matches, key=len, reverse=True)[0]


def _event_source_code_for_event(event, event_source_catalog):
    metadata = event.metadata or {}
    source_code = _clean(metadata.get('event_source_code'))
    if source_code:
        return source_code
    resource_type = _clean(event.resource_type)
    for code, source in event_source_catalog.items():
        if source.source_kind != EventSource.KIND_BUILTIN:
            continue
        resource_types = (source.config or {}).get('resource_types') or []
        if resource_type and resource_type in resource_types:
            return code
    return ''


def build_knowledge_graph(params=None):
    params = params or {}
    if hasattr(params, 'getlist'):
        selected_system = {_clean(item) for item in (params.getlist('system') or params.getlist('business_line')) if _clean(item)}
    else:
        selected_system = set()
    selected_env = {_clean(item) for item in params.getlist('environment') if _clean(item)} if hasattr(params, 'getlist') else set()
    selected_service = {_clean(item) for item in params.getlist('service') if _clean(item)} if hasattr(params, 'getlist') else set()
    knowledge_env_configs = _enabled_knowledge_environments()
    selected_knowledge_configs = [config for config in knowledge_env_configs if config.name in selected_env]
    use_knowledge_env = bool(selected_knowledge_configs)
    event_env_to_graph = {}
    alert_env_to_graph = {}
    source_env_to_graph = {}
    selected_event_environments = set()
    selected_alert_environments = set()
    selected_grafana_folders = set()
    selected_log_datasource_ids = set()
    selected_tracing_datasource_ids = set()
    if use_knowledge_env:
        selected_env = {config.name for config in selected_knowledge_configs}
        for config in selected_knowledge_configs:
            for environment in _clean_list(config.event_environments):
                selected_event_environments.add(environment)
                event_env_to_graph[environment] = config.name
                source_env_to_graph.setdefault(environment, config.name)
            for environment in _clean_list(config.alert_environments):
                selected_alert_environments.add(environment)
                alert_env_to_graph[environment] = config.name
                source_env_to_graph.setdefault(environment, config.name)
            selected_grafana_folders.update(_clean_list(config.grafana_folder_keys))
            selected_log_datasource_ids.update(_int_list(config.log_datasource_ids))
            selected_tracing_datasource_ids.update(_int_list(config.tracing_datasource_ids))

    def graph_environment(source_environment, kind=''):
        environment = _clean(source_environment, UNKNOWN_ENV)
        if not use_knowledge_env:
            return environment
        if kind == 'event':
            return event_env_to_graph.get(environment, environment)
        if kind == 'alert':
            return alert_env_to_graph.get(environment, environment)
        return source_env_to_graph.get(environment, environment)

    nodes = {}
    edges = {}
    context_by_service = defaultdict(Counter)
    records_by_service = defaultdict(lambda: {
        'systems': Counter(),
        'environments': Counter(),
        'capabilities': Counter(),
        'examples': [],
    })

    def add_node(node_id, label, kind, category='', route='', status='', metric=0, description='', **extra):
        existing = nodes.get(node_id)
        if existing:
            existing['metric'] = max(existing.get('metric') or 0, metric or 0)
            if description and not existing.get('description'):
                existing['description'] = description
            for key in ('system_name', 'business_line', 'environment', 'service'):
                if extra.get(key) and not existing.get(key):
                    existing[key] = extra[key]
            return existing
        nodes[node_id] = {
            'id': node_id,
            'label': label,
            'kind': kind,
            'category': category or kind,
            'route': route,
            'status': status,
            'metric': metric or 0,
            'description': description,
            **extra,
        }
        return nodes[node_id]

    def add_edge(source, target, label, relation='related', weight=1):
        if not source or not target or source == target:
            return
        edge_id = f'{source}->{target}:{relation}:{label}'
        if edge_id in edges:
            edges[edge_id]['weight'] += weight
            return
        edges[edge_id] = {
            'id': edge_id,
            'source': source,
            'target': target,
            'label': label,
            'relation': relation,
            'weight': weight,
        }

    def add_capability_context(capability, system_name='', environment='', service='', count=1, example=''):
        system_name = _clean(system_name, UNKNOWN_SYSTEM)
        environment = _clean(environment, UNKNOWN_ENV)
        service = _clean(service, UNKNOWN_SERVICE)

        if not (
            _matches_filters(system_name, selected_system)
            and _matches_filters(environment, selected_env)
            and _matches_filters(service, selected_service)
        ):
            return

        env_id = _node_key('environment', environment)
        system_id = _node_key('system', environment, system_name)
        service_id = _node_key('service', environment, system_name, service)
        capability_id = _node_key('capability', capability)

        add_node(env_id, environment, 'environment', '环境', metric=count, environment=environment)
        add_node(
            system_id,
            system_name,
            'system',
            '系统',
            metric=count,
            system_name=system_name,
            business_line=system_name,
            environment=environment,
        )
        add_node(
            service_id,
            service,
            'service',
            '服务',
            metric=count,
            system_name=system_name,
            business_line=system_name,
            environment=environment,
            service=service,
        )
        add_edge(env_id, system_id, '包含系统', 'environment_system', count)
        add_edge(system_id, service_id, '承载服务', 'system_service', count)
        add_edge(service_id, capability_id, '产生数据', 'service_capability', count)

        record = records_by_service[service_id]
        record['systems'][system_name] += count
        record['environments'][environment] += count
        record['capabilities'][capability] += count
        _append_unique(record['examples'], example)

    def remember_service_context(service, system_name='', environment='', count=1):
        service = _clean(service)
        system_name = _clean(system_name)
        environment = _clean(environment)
        if not service or not (system_name or environment):
            return
        context_by_service[service][(system_name, environment)] += count

    def resolve_service_context(service):
        service = _clean(service)
        if not service or service not in context_by_service:
            return '', ''
        return context_by_service[service].most_common(1)[0][0]

    alert_queryset = Alert.objects.order_by('-created_at')
    event_queryset = (
        EventRecord.objects
        .filter(is_demo=False)
        .exclude(source_type=EventRecord.SOURCE_SEED)
        .order_by('-occurred_at')
    )
    posture_queryset = SystemPostureSystem.objects.filter(is_enabled=True).order_by('sort_order', 'name')
    if use_knowledge_env:
        alert_queryset = alert_queryset.filter(environment__in=selected_alert_environments) if selected_alert_environments else Alert.objects.none()
        event_queryset = event_queryset.filter(environment__in=selected_event_environments) if selected_event_environments else EventRecord.objects.none()
        source_environments = set(source_env_to_graph)
        posture_queryset = posture_queryset.filter(environment__in=source_environments) if source_environments else SystemPostureSystem.objects.none()
    alert_records = list(alert_queryset[:200])
    event_records = list(event_queryset[:240])
    posture_systems = list(posture_queryset)

    runtime_services = set()
    runtime_service_systems = {}
    for event in event_records:
        service_name = _clean(event.application)
        if _is_microservice_name(service_name):
            runtime_services.add(service_name)
            if _clean(event.business_line):
                runtime_service_systems.setdefault(service_name, _clean(event.business_line))
    for system in posture_systems:
        service_specs = system.service_specs if isinstance(system.service_specs, list) else []
        for service in service_specs:
            service_name = _clean(service.get('name') or service.get('id'))
            if _is_microservice_name(service_name):
                runtime_services.add(service_name)
                runtime_service_systems.setdefault(service_name, _clean(system.name))

    for alert in alert_records:
        if not use_knowledge_env or _clean(alert.service) in runtime_services:
            remember_service_context(alert.service or alert.resource or alert.title, alert.business_line, graph_environment(alert.environment, 'alert'))
    for event in event_records:
        service_name = _clean(event.application)
        if not use_knowledge_env or service_name in runtime_services:
            remember_service_context(service_name or event.resource_name or event.resource_type or event.module, event.business_line, graph_environment(event.environment, 'event'))
    for system in posture_systems:
        system_environment = graph_environment(system.environment, 'posture')
        remember_service_context(system.name, system.name, system_environment, 2)
        service_specs = system.service_specs if isinstance(system.service_specs, list) else []
        for service in service_specs:
            service_name = _clean(service.get('name') or service.get('id'))
            if not use_knowledge_env or service_name in runtime_services:
                remember_service_context(service_name, system.name, system_environment)

    configured_environment_options = [config.name for config in knowledge_env_configs]
    discovered_environment_options = sorted({
        environment
        for counter in context_by_service.values()
        for _, environment in counter
        if environment and not _is_invalid_environment(environment)
    })
    available_environment_options = configured_environment_options or discovered_environment_options

    if not selected_env:
        return _empty_graph({'environments': available_environment_options})

    for key, label, kind, route in CAPABILITY_DEFS:
        add_node(_node_key('capability', key), label, kind, '数据来源', route=route)

    log_datasource_queryset = LogDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
    if use_knowledge_env:
        log_datasource_queryset = log_datasource_queryset.filter(id__in=selected_log_datasource_ids) if selected_log_datasource_ids else LogDataSource.objects.none()
    for datasource in log_datasource_queryset:
        if _is_demoish_text(datasource.name, datasource.description, datasource.provider):
            continue
        node_id = _node_key('log_ds', datasource.id)
        add_node(
            node_id,
            datasource.name,
            'datasource',
            '日志数据源',
            route='/logs/datasources',
            status='enabled',
            description=datasource.description,
            provider=datasource.provider,
        )
        add_edge(_node_key('capability', 'logs'), node_id, '接入日志源', 'capability_datasource')

    tracing_datasource_queryset = TracingDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
    if use_knowledge_env:
        tracing_datasource_queryset = tracing_datasource_queryset.filter(id__in=selected_tracing_datasource_ids) if selected_tracing_datasource_ids else TracingDataSource.objects.none()
    for datasource in tracing_datasource_queryset:
        if _is_demoish_text(datasource.name, datasource.description, datasource.provider):
            continue
        node_id = _node_key('trace_ds', datasource.id)
        add_node(
            node_id,
            datasource.name,
            'datasource',
            '链路数据源',
            route='/observability/tracing/datasources',
            status='enabled',
            description=datasource.description,
            provider=datasource.provider,
        )
        add_edge(_node_key('capability', 'tracing'), node_id, '接入链路源', 'capability_datasource')

    dashboard_nodes = {}
    dashboard_folder_counts = Counter()

    def add_dashboard_folder_node(folder_name):
        folder_name = _matched_configured_folder(folder_name, selected_grafana_folders if use_knowledge_env else None)
        if not folder_name:
            return ''
        node_id = _node_key('dashboard_folder', folder_name)
        node = add_node(
            node_id,
            folder_name,
            'dashboard',
            'Grafana 看板目录',
            route='/observability/grafana',
            status='enabled',
            metric=dashboard_folder_counts[folder_name],
            description=f'看板目录：{folder_name}',
        )
        node['metric'] = dashboard_folder_counts[folder_name]
        node['description'] = f'看板目录：{folder_name}，包含 {dashboard_folder_counts[folder_name]} 个看板'
        add_edge(_node_key('capability', 'dashboards'), node_id, '展示看板', 'capability_dashboard')
        return node_id

    for setting in GrafanaSetting.objects.filter(enabled=True).order_by('name'):
        folders = setting.folders if isinstance(setting.folders, list) else []
        for folder in folders:
            add_dashboard_folder_node(folder.get('path') or folder.get('folder') or folder.get('name'))
        dashboards = setting.dashboards if isinstance(setting.dashboards, list) else []
        for dashboard in dashboards:
            if _is_demoish_text(dashboard.get('key'), dashboard.get('title'), dashboard.get('name'), dashboard.get('description')):
                continue
            dashboard_folder = _clean(dashboard.get('folder'))
            key = _clean(dashboard.get('key') or dashboard.get('uid') or dashboard.get('title') or dashboard.get('name'))
            if not key or not dashboard_folder:
                continue
            folder_name = _matched_configured_folder(dashboard_folder, selected_grafana_folders if use_knowledge_env else None)
            if use_knowledge_env and not folder_name:
                continue
            dashboard_folder_counts[folder_name] += 1
            node_id = add_dashboard_folder_node(folder_name)
            if node_id:
                dashboard_nodes[key] = node_id

    default_system_name = ''
    if use_knowledge_env:
        system_counter = Counter()
        for event in event_records:
            system_counter[_clean(event.business_line)] += 1
        for alert in alert_records:
            system_counter[_clean(alert.business_line)] += 1
        for system in posture_systems:
            system_counter[_clean(system.name)] += 1
        system_counter.pop('', None)
        system_counter.pop(UNKNOWN_SYSTEM, None)
        if system_counter:
            default_system_name = system_counter.most_common(1)[0][0]
        elif selected_knowledge_configs:
            default_system_name = _clean(selected_knowledge_configs[0].name, UNKNOWN_SYSTEM)

    if use_knowledge_env and selected_grafana_folders:
        for config in selected_knowledge_configs:
            for service_name in sorted(runtime_services):
                add_capability_context(
                    'dashboards',
                    runtime_service_systems.get(service_name) or default_system_name or config.name,
                    config.name,
                    service_name,
                    1,
                    '看板：已关联环境监控目录',
                )

    link_queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True).order_by('-is_default', 'name')
    if use_knowledge_env:
        if selected_log_datasource_ids:
            link_queryset = link_queryset.filter(log_datasource_id__in=selected_log_datasource_ids)
        else:
            link_queryset = link_queryset.none()
        if selected_tracing_datasource_ids:
            link_queryset = link_queryset.filter(tracing_datasource_id__in=selected_tracing_datasource_ids)
        else:
            link_queryset = link_queryset.none()
    for link in link_queryset:
        if _is_demoish_text(
            getattr(link.log_datasource, 'name', ''),
            getattr(link.log_datasource, 'description', ''),
            getattr(link.tracing_datasource, 'name', ''),
            getattr(link.tracing_datasource, 'description', ''),
        ):
            continue
        log_id = _node_key('log_ds', link.log_datasource_id)
        trace_id = _node_key('trace_ds', link.tracing_datasource_id)
        if link.log_to_trace_enabled or link.trace_to_log_enabled:
            add_edge(log_id, trace_id, 'Trace ID 关联', 'observability_link', 3 if link.is_default else 1)
        dashboard_id = dashboard_nodes.get(link.grafana_dashboard_key)
        if dashboard_id:
            if link.log_to_grafana_enabled or link.grafana_to_log_enabled:
                add_edge(log_id, dashboard_id, '日志看板跳转', 'observability_link')
            if link.trace_to_grafana_enabled or link.grafana_to_trace_enabled:
                add_edge(trace_id, dashboard_id, '链路看板跳转', 'observability_link')

    for entry in LogEntry.objects.order_by('-timestamp')[:200]:
        if use_knowledge_env and _clean(entry.service) not in runtime_services:
            continue
        system_name, environment = resolve_service_context(entry.service)
        add_capability_context(
            'logs',
            system_name,
            environment,
            entry.service,
            1,
            f'日志：{entry.service}',
        )

    for alert in alert_records:
        if _is_demoish_text(alert.title, alert.service, alert.resource, alert.message):
            continue
        if use_knowledge_env and _clean(alert.service) not in runtime_services:
            continue
        system_name = alert.business_line
        environment = graph_environment(alert.environment, 'alert')
        if not (system_name and environment):
            resolved_system, resolved_env = resolve_service_context(alert.service or alert.resource or alert.title)
            system_name = system_name or resolved_system
            environment = environment or resolved_env
        if use_knowledge_env and not system_name:
            system_name = default_system_name
        add_capability_context(
            'alerts',
            system_name,
            environment,
            alert.service or alert.resource or alert.title,
            2 if alert.level == 'critical' and alert.status == Alert.STATUS_ACTIVE else 1,
            f'告警：{alert.title}',
        )

    for system in posture_systems:
        system_name = system.name
        system_environment = graph_environment(system.environment, 'posture')
        if not use_knowledge_env:
            add_capability_context('posture', system_name, system_environment, system.name, 2, f'系统态势：{system.name}')
        service_specs = system.service_specs if isinstance(system.service_specs, list) else []
        for service in service_specs:
            service_name = service.get('name') or service.get('id')
            if use_knowledge_env and _clean(service_name) not in runtime_services:
                continue
            add_capability_context('posture', system_name, system_environment, service_name, 1, f'系统态势服务：{service_name}')
            system_service_id = _node_key('service', system_environment or UNKNOWN_ENV, system_name, system.name)
            service_id = _node_key('service', system_environment or UNKNOWN_ENV, system_name, service_name or UNKNOWN_SERVICE)
            add_edge(system_service_id, service_id, '系统服务拆解', 'system_service')
        dependencies = system.dependencies if isinstance(system.dependencies, list) else []
        for dependency in dependencies:
            if use_knowledge_env:
                continue
            dep_name = dependency.get('name') or dependency.get('id')
            add_capability_context('posture', system_name, system_environment, dep_name, 1, f'依赖：{dep_name}')
            system_service_id = _node_key('service', system_environment or UNKNOWN_ENV, system_name, system.name)
            dep_id = _node_key('service', system_environment or UNKNOWN_ENV, system_name, dep_name or UNKNOWN_SERVICE)
            add_edge(system_service_id, dep_id, dependency.get('role') or '依赖', 'system_dependency')

    for event in event_records:
        if _is_demoish_text(event.title, event.application, event.resource_name):
            continue
        event_service_name = _clean(event.application)
        if use_knowledge_env and event_service_name not in runtime_services:
            continue
        capability = 'external_events' if event.source_type == EventRecord.SOURCE_EXTERNAL else 'internal_events'
        event_system_name = event.business_line or (default_system_name if use_knowledge_env else '')
        add_capability_context(
            capability,
            event_system_name,
            graph_environment(event.environment, 'event'),
            event_service_name or event.resource_name or event.resource_type or event.module,
            2 if event.severity == EventRecord.SEVERITY_DANGER else 1,
            f'事件：{event.title}',
        )
        if use_knowledge_env:
            continue
        for related in event.related_resources or []:
            related_name = related.get('name') or related.get('id')
            if not related_name:
                continue
            add_capability_context(
                capability,
                event_system_name,
                graph_environment(event.environment, 'event'),
                related_name,
                1,
                f'关联资源：{related_name}',
            )

    event_source_queryset = EventSource.objects.filter(enabled=True).order_by('source_kind', 'source_type', 'name')
    event_source_catalog = {source.code: source for source in event_source_queryset}
    if use_knowledge_env:
        event_source_scope_records = [event for event in event_records if _clean(event.environment) in selected_event_environments]
    else:
        event_source_scope_records = [event for event in event_records if _matches_filters(_clean(event.environment), selected_env)]
    active_event_source_codes = {
        code
        for code in (_event_source_code_for_event(event, event_source_catalog) for event in event_source_scope_records)
        if code
    }
    for source in event_source_queryset:
        if source.code not in active_event_source_codes:
            continue
        capability = 'external_events' if source.source_kind == EventSource.KIND_EXTERNAL else 'internal_events'
        node_id = _node_key('event_source', source.id)
        add_node(
            node_id,
            source.name,
            'event_source',
            '事件源',
            route='/events/sources',
            status=source.status,
            description=source.description,
        )
        add_edge(_node_key('capability', capability), node_id, '接入事件源', 'capability_event_source')

    for service_id, record in records_by_service.items():
        service_node = nodes.get(service_id)
        if not service_node:
            continue
        service_node['metric'] = sum(record['capabilities'].values())
        service_node['description'] = ' / '.join(record['examples'][:3])
        service_node['capabilities'] = [
            {'name': key, 'count': count}
            for key, count in record['capabilities'].most_common()
        ]

    adjacency = defaultdict(set)
    for edge in edges.values():
        adjacency[edge['source']].add(edge['target'])
    reachable_ids = set()
    pending = [_node_key('environment', environment) for environment in selected_env]
    while pending:
        current = pending.pop()
        if current in reachable_ids:
            continue
        if current not in nodes:
            continue
        reachable_ids.add(current)
        pending.extend(adjacency.get(current, set()) - reachable_ids)

    nodes = {node_id: node for node_id, node in nodes.items() if node_id in reachable_ids}
    edges = {
        edge_id: edge
        for edge_id, edge in edges.items()
        if edge['source'] in reachable_ids and edge['target'] in reachable_ids
    }

    filtered_nodes = sorted(
        [node for node in nodes.values() if not str(node.get('id', '')).startswith('capability:')],
        key=lambda item: (item['kind'], item['label'], item['id']),
    )
    visible_ids = {node['id'] for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges.values()
        if edge['source'] in visible_ids and edge['target'] in visible_ids
    ]

    system_options = sorted({
        node.get('system_name') or node.get('business_line') or node['label']
        for node in filtered_nodes
        if node['kind'] in {'system', 'service'} and (node.get('system_name') or node.get('business_line') or node['kind'] == 'system')
    })
    environment_options = sorted({
        node.get('environment') or node['label']
        for node in filtered_nodes
        if node['kind'] in {'environment', 'system', 'service'} and (node.get('environment') or node['kind'] == 'environment')
    })
    service_options = sorted({
        node.get('service') or node['label']
        for node in filtered_nodes
        if node['kind'] == 'service'
    })

    kind_counts = Counter(node['kind'] for node in filtered_nodes)
    return {
        'nodes': filtered_nodes,
        'edges': filtered_edges,
        'summary': {
            'node_count': len(filtered_nodes),
            'edge_count': len(filtered_edges),
            'service_count': kind_counts.get('service', 0),
            'datasource_count': kind_counts.get('datasource', 0),
            'event_source_count': kind_counts.get('event_source', 0),
            'capability_count': len(CAPABILITY_DEFS),
        },
        'filters': {
            'systems': system_options,
            'business_lines': system_options,
            'environments': available_environment_options,
            'services': service_options,
        },
        'relation_legend': [
            {'key': 'observability_link', 'label': '可观测性跳转配置'},
            {'key': 'environment_system', 'label': '环境包含系统'},
            {'key': 'system_service', 'label': '系统承载服务'},
            {'key': 'service_capability', 'label': '服务产生数据'},
            {'key': 'system_dependency', 'label': '系统依赖'},
            {'key': 'capability_datasource', 'label': '能力接入数据源'},
            {'key': 'capability_event_source', 'label': '能力接入事件源'},
        ],
    }
