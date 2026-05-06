from collections import Counter, defaultdict

from django.db.models import Count

from eventwall.models import EventRecord, EventSource
from ops.models import (
    Alert,
    Deployment,
    GrafanaSetting,
    LogDataSource,
    LogEntry,
    ObservabilityDataSourceLink,
    SystemPostureSystem,
    TracingDataSource,
    TransactionTicket,
)


UNKNOWN_BUSINESS = '未归属业务线'
UNKNOWN_ENV = '未标记环境'
UNKNOWN_SERVICE = '未标记服务'


CAPABILITY_DEFS = [
    ('workorders', '工单', 'workorder', '/workorders/transactions'),
    ('logs', '日志', 'logs', '/logs'),
    ('tracing', '链路', 'tracing', '/observability/tracing'),
    ('dashboards', '看板', 'dashboard', '/observability/grafana'),
    ('alerts', '告警', 'alert', '/alerts'),
    ('posture', '系统态势', 'posture', '/observability/system-posture'),
    ('internal_events', '内部事件', 'internal_event', '/events/wall'),
    ('external_events', '外部事件', 'external_event', '/events/wall'),
]


def _clean(value, fallback=''):
    text = str(value or '').strip()
    return text or fallback


def _node_key(kind, *parts):
    return ':'.join([kind, *[str(part).strip().replace(':', '_') for part in parts if str(part).strip()]])


def _matches_filters(value, allowed):
    return not allowed or value in allowed


def _append_unique(target, value, limit=4):
    if not value or value in target:
        return
    if len(target) < limit:
        target.append(value)


def build_knowledge_graph(params=None):
    params = params or {}
    selected_business = set(params.getlist('business_line')) if hasattr(params, 'getlist') else set()
    selected_env = set(params.getlist('environment')) if hasattr(params, 'getlist') else set()
    selected_service = set(params.getlist('service')) if hasattr(params, 'getlist') else set()

    nodes = {}
    edges = {}
    records_by_service = defaultdict(lambda: {
        'business_lines': Counter(),
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
            for key in ('business_line', 'environment', 'service'):
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

    def add_capability_context(capability, business_line='', environment='', service='', count=1, example=''):
        business_line = _clean(business_line, UNKNOWN_BUSINESS)
        environment = _clean(environment, UNKNOWN_ENV)
        service = _clean(service, UNKNOWN_SERVICE)

        if not (
            _matches_filters(business_line, selected_business)
            and _matches_filters(environment, selected_env)
            and _matches_filters(service, selected_service)
        ):
            return

        business_id = _node_key('business', business_line)
        env_id = _node_key('environment', business_line, environment)
        service_id = _node_key('service', business_line, environment, service)
        capability_id = _node_key('capability', capability)

        add_node(business_id, business_line, 'business', '业务线', metric=count)
        add_node(env_id, environment, 'environment', '环境', metric=count, business_line=business_line)
        add_node(
            service_id,
            service,
            'service',
            '服务',
            metric=count,
            business_line=business_line,
            environment=environment,
            service=service,
        )
        add_edge(business_id, env_id, '包含环境', 'business_environment', count)
        add_edge(env_id, service_id, '承载服务', 'environment_service', count)
        add_edge(service_id, capability_id, '产生数据', 'service_capability', count)

        record = records_by_service[service_id]
        record['business_lines'][business_line] += count
        record['environments'][environment] += count
        record['capabilities'][capability] += count
        _append_unique(record['examples'], example)

    for key, label, kind, route in CAPABILITY_DEFS:
        add_node(_node_key('capability', key), label, kind, '平台能力', route=route)

    for datasource in LogDataSource.objects.all().order_by('provider', 'name'):
        node_id = _node_key('log_ds', datasource.id)
        add_node(
            node_id,
            datasource.name,
            'datasource',
            '日志数据源',
            route='/logs/datasources',
            status='enabled' if datasource.is_enabled else 'disabled',
            description=datasource.description,
            provider=datasource.provider,
        )
        add_edge(_node_key('capability', 'logs'), node_id, '接入日志源', 'capability_datasource')

    for datasource in TracingDataSource.objects.all().order_by('provider', 'name'):
        node_id = _node_key('trace_ds', datasource.id)
        add_node(
            node_id,
            datasource.name,
            'datasource',
            '链路数据源',
            route='/observability/tracing/datasources',
            status='enabled' if datasource.is_enabled else 'disabled',
            description=datasource.description,
            provider=datasource.provider,
        )
        add_edge(_node_key('capability', 'tracing'), node_id, '接入链路源', 'capability_datasource')

    dashboard_nodes = {}
    for setting in GrafanaSetting.objects.all().order_by('name'):
        dashboards = setting.dashboards if isinstance(setting.dashboards, list) else []
        for dashboard in dashboards:
            key = _clean(dashboard.get('key') or dashboard.get('uid') or dashboard.get('title') or dashboard.get('name'))
            if not key:
                continue
            node_id = _node_key('dashboard', key)
            dashboard_nodes[key] = node_id
            add_node(
                node_id,
                dashboard.get('title') or dashboard.get('name') or key,
                'dashboard',
                'Grafana 看板',
                route='/observability/grafana',
                status='enabled' if setting.enabled else 'disabled',
                description=dashboard.get('description') or setting.default_path,
            )
            add_edge(_node_key('capability', 'dashboards'), node_id, '展示看板', 'capability_dashboard')

    for link in ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').order_by('-is_default', 'name'):
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

    for ticket in TransactionTicket.objects.order_by('-updated_at')[:120]:
        add_capability_context(
            'workorders',
            ticket.business_line,
            ticket.environment,
            ticket.title,
            1,
            f'工单：{ticket.title}',
        )

    for entry in LogEntry.objects.select_related('host').order_by('-timestamp')[:200]:
        add_capability_context(
            'logs',
            getattr(entry.host, 'business_line', '') if entry.host else '',
            getattr(entry.host, 'environment', '') if entry.host else '',
            entry.service,
            1,
            f'日志：{entry.service}',
        )

    for alert in Alert.objects.select_related('host').order_by('-created_at')[:200]:
        add_capability_context(
            'alerts',
            alert.business_line or (getattr(alert.host, 'business_line', '') if alert.host else ''),
            alert.environment or (getattr(alert.host, 'environment', '') if alert.host else ''),
            alert.service or alert.resource or alert.title,
            2 if alert.level == 'critical' and alert.status == Alert.STATUS_ACTIVE else 1,
            f'告警：{alert.title}',
        )

    for deployment in Deployment.objects.order_by('-executed_at', '-deployed_at', '-id')[:120]:
        add_capability_context(
            'dashboards',
            deployment.business_line,
            deployment.environment,
            deployment.app_name,
            1,
            f'发布：{deployment.app_name} {deployment.version}',
        )

    for system in SystemPostureSystem.objects.filter(is_enabled=True).order_by('sort_order', 'name'):
        business_line = system.domain or system.name
        add_capability_context('posture', business_line, system.environment, system.name, 2, f'系统态势：{system.name}')
        service_specs = system.service_specs if isinstance(system.service_specs, list) else []
        for service in service_specs:
            service_name = service.get('name') or service.get('id')
            add_capability_context('posture', business_line, system.environment, service_name, 1, f'系统态势服务：{service_name}')
            system_service_id = _node_key('service', business_line, system.environment or UNKNOWN_ENV, system.name)
            service_id = _node_key('service', business_line, system.environment or UNKNOWN_ENV, service_name or UNKNOWN_SERVICE)
            add_edge(system_service_id, service_id, '系统服务拆解', 'system_service')
        dependencies = system.dependencies if isinstance(system.dependencies, list) else []
        for dependency in dependencies:
            dep_name = dependency.get('name') or dependency.get('id')
            add_capability_context('posture', business_line, system.environment, dep_name, 1, f'依赖：{dep_name}')
            system_service_id = _node_key('service', business_line, system.environment or UNKNOWN_ENV, system.name)
            dep_id = _node_key('service', business_line, system.environment or UNKNOWN_ENV, dep_name or UNKNOWN_SERVICE)
            add_edge(system_service_id, dep_id, dependency.get('role') or '依赖', 'system_dependency')

    for event in EventRecord.objects.order_by('-occurred_at')[:240]:
        capability = 'external_events' if event.source_type == EventRecord.SOURCE_EXTERNAL else 'internal_events'
        add_capability_context(
            capability,
            event.business_line,
            event.environment,
            event.application or event.resource_name or event.resource_type or event.module,
            2 if event.severity == EventRecord.SEVERITY_DANGER else 1,
            f'事件：{event.title}',
        )
        for related in event.related_resources or []:
            related_name = related.get('name') or related.get('id')
            if not related_name:
                continue
            add_capability_context(
                capability,
                event.business_line,
                event.environment,
                related_name,
                1,
                f'关联资源：{related_name}',
            )

    for source in EventSource.objects.all().order_by('source_kind', 'source_type', 'name'):
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

    filtered_nodes = sorted(nodes.values(), key=lambda item: (item['kind'], item['label'], item['id']))
    visible_ids = {node['id'] for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges.values()
        if edge['source'] in visible_ids and edge['target'] in visible_ids
    ]

    business_options = sorted({
        node.get('business_line') or node['label']
        for node in filtered_nodes
        if node['kind'] in {'business', 'environment', 'service'} and (node.get('business_line') or node['kind'] == 'business')
    })
    environment_options = sorted({
        node.get('environment') or node['label']
        for node in filtered_nodes
        if node['kind'] in {'environment', 'service'} and (node.get('environment') or node['kind'] == 'environment')
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
            'capability_count': kind_counts.get('workorder', 0) + len(CAPABILITY_DEFS),
        },
        'filters': {
            'business_lines': business_options,
            'environments': environment_options,
            'services': service_options,
        },
        'relation_legend': [
            {'key': 'observability_link', 'label': '可观测性跳转配置'},
            {'key': 'service_capability', 'label': '服务产生数据'},
            {'key': 'system_dependency', 'label': '系统依赖'},
            {'key': 'capability_datasource', 'label': '能力接入数据源'},
            {'key': 'capability_event_source', 'label': '能力接入事件源'},
        ],
    }
