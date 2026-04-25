from urllib.parse import quote

from django.conf import settings
from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import user_has_permissions
from .models import Alert, LogDataSource, TracingDataSource
from .serializers import AlertSerializer, TracingDataSourceSerializer
from .tracing_providers import (
    DEMO_TRACES,
    ObservabilityError,
    load_trace_detail,
    load_tracing_catalog,
    search_tracing,
    test_tracing_connection,
    tracing_provider_info,
)


DEMO_GRAFANA_DASHBOARDS = [
    {'key': 'apm-overview', 'title': 'APM 全链路总览', 'slug': 'apm-overview', 'path': '/d/apm-overview', 'panel_count': 18, 'tags': ['SkyWalking', '应用', 'SLA'], 'description': '面向应用负责人查看服务吞吐、慢调用与错误率。'},
    {'key': 'infra-overview', 'title': '基础设施总览', 'slug': 'infra-overview', 'path': '/d/infra-overview', 'panel_count': 14, 'tags': ['Node', 'CPU', 'Memory'], 'description': '聚合节点 CPU、内存、磁盘与 Pod 负载走势。'},
    {'key': 'log-drilldown', 'title': '日志钻取看板', 'slug': 'log-drilldown', 'path': '/d/log-drilldown', 'panel_count': 12, 'tags': ['Loki', 'Error', 'Audit'], 'description': '配合日志中心快速回放错误时段与关键日志。'},
    {'key': 'ingress-slo', 'title': '入口流量与 SLO', 'slug': 'ingress-slo', 'path': '/d/ingress-slo', 'panel_count': 10, 'tags': ['Nginx', 'Latency', 'Availability'], 'description': '聚焦入口 QPS、响应时间分位和可用性目标。'},
]


def _deny_if_missing_any(request, codes):
    allowed = any(user_has_permissions(request.user, [code]) for code in codes)
    if allowed:
        return None
    return Response({'detail': f"缺少权限: {', '.join(codes)}"}, status=403)


def _has_permission(request, code):
    return user_has_permissions(request.user, [code])


def _observability_access(request):
    return {
        'log_query': _has_permission(request, 'ops.log.query'),
        'log_datasource': _has_permission(request, 'ops.log.datasource.view'),
        'alerts': _has_permission(request, 'ops.alert.view'),
        'trace': _has_permission(request, 'ops.trace.view'),
        'trace_datasource': _has_permission(request, 'ops.trace.datasource.view'),
        'grafana': _has_permission(request, 'ops.grafana.view'),
    }


def _observability_defaults():
    return getattr(settings, 'OBSERVABILITY_CONFIG', {}) or {}


def _join_external_url(base, path=''):
    base = (base or '').rstrip('/')
    if not base:
        return ''
    normalized_path = (path or '').strip()
    if not normalized_path:
        return base
    if not normalized_path.startswith('/'):
        normalized_path = f'/{normalized_path}'
    return f'{base}{normalized_path}'


def _grafana_config():
    config = dict(_observability_defaults().get('grafana', {}))
    config.setdefault('enabled', True)
    config.setdefault('url', '')
    config.setdefault('default_path', '')
    config.setdefault('demo_mode', True)
    return config


def _grafana_meta():
    config = _grafana_config()
    configured_dashboards = config.get('dashboards') or DEMO_GRAFANA_DASHBOARDS
    dashboards = []
    base_url = config.get('url') or ''
    default_path = (config.get('default_path') or '').strip()
    for item in configured_dashboards:
        item_path = (item.get('path') or '').strip()
        slug = item.get('slug') or item.get('key') or ''
        path = item_path or default_path or (f"/d/{quote(slug)}" if slug else '')
        dashboards.append({
            **item,
            'path': path,
            'url': _join_external_url(base_url, path) if base_url and path else base_url,
        })
    configured = bool(config.get('enabled') and base_url)
    return {
        'enabled': bool(config.get('enabled')),
        'configured': configured,
        'source': 'grafana' if configured else 'demo',
        'status_text': '已接入 Grafana' if configured else '未配置外部地址，当前展示推荐看板',
        'url': base_url,
        'embed_url': _join_external_url(base_url, default_path) if configured and default_path else base_url,
        'dashboard_count': len(dashboards),
        'panel_count': sum(item['panel_count'] for item in dashboards),
        'datasource_count': 4,
        'dashboards': dashboards,
    }


def _log_module_summary():
    providers = []
    grouped = LogDataSource.objects.values('provider').annotate(total=Count('id')).order_by('provider')
    enabled_by_provider = {
        item['provider']: item['count']
        for item in LogDataSource.objects.filter(is_enabled=True).values('provider').annotate(count=Count('id'))
    }
    for item in grouped:
        provider = item['provider']
        providers.append({
            'provider': provider,
            'total': item['total'],
            'enabled': enabled_by_provider.get(provider, 0),
        })

    return {
        'query_path': '/logs/query',
        'datasource_path': '/logs/datasources',
        'datasource_count': LogDataSource.objects.count(),
        'enabled_count': LogDataSource.objects.filter(is_enabled=True).count(),
        'default_count': LogDataSource.objects.filter(is_default=True).count(),
        'providers': providers,
    }


def _alert_module_summary():
    latest = Alert.objects.select_related('host').all()[:5]
    return {
        'path': '/alerts',
        'total': Alert.objects.count(),
        'unacknowledged': Alert.objects.filter(is_acknowledged=False).count(),
        'critical': Alert.objects.filter(level='critical').count(),
        'warning': Alert.objects.filter(level='warning').count(),
        'info': Alert.objects.filter(level='info').count(),
        'recent': AlertSerializer(latest, many=True).data,
    }


class TracingDataSourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TracingDataSource.objects.all().order_by('provider', 'name')
    serializer_class = TracingDataSourceSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'tracing_datasource'
    event_resource_label = '链路数据源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.trace.datasource.view'],
        'retrieve': ['ops.trace.datasource.view'],
        'create': ['ops.trace.datasource.manage'],
        'update': ['ops.trace.datasource.manage'],
        'partial_update': ['ops.trace.datasource.manage'],
        'destroy': ['ops.trace.datasource.manage'],
        'test_connection': ['ops.trace.datasource.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        provider = self.request.query_params.get('provider')
        is_enabled = self.request.query_params.get('is_enabled')
        if provider:
            queryset = queryset.filter(provider=provider)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        datasource = self.get_object()
        try:
            preview = test_tracing_connection(datasource.provider, datasource.config or {})
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试成功',
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'preview_kind': preview.get('kind'), 'count': preview.get('count', 0)},
            )
            return Response({
                'success': True,
                'message': f'{datasource.name} 连接成功',
                'preview_count': preview.get('count', 0),
                'preview_kind': preview.get('kind'),
            })
        except ObservabilityError as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response({'success': False, 'message': str(exc), 'detail': exc.detail}, status=exc.status_code)
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response(
                {'success': False, 'message': '连接测试失败', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.trace.datasource.view')])
def tracing_providers(request):
    return Response({'providers': tracing_provider_info()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_overview(request):
    access = _observability_access(request)
    denied = _deny_if_missing_any(
        request,
        ['ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.grafana.view'],
    )
    if denied:
        return denied

    provider = request.query_params.get('provider', '')
    layer = request.query_params.get('layer', '')
    try:
        catalog = load_tracing_catalog(
            provider=provider,
            layer=layer,
            datasource_id=request.query_params.get('datasource_id', ''),
        ) if access['trace'] else None
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
    grafana = _grafana_meta() if access['grafana'] else None
    logs = _log_module_summary() if (access['log_query'] or access['log_datasource']) else None
    alerts = _alert_module_summary() if access['alerts'] else None

    navigation = []
    if access['log_query'] or access['log_datasource']:
        log_description = '统一进入日志查询与数据源管理。' if access['log_query'] and access['log_datasource'] else '进入日志中心并按当前权限查看可用标签。'
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': log_description, 'tone': 'info'})
    if access['alerts']:
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '集中处理当前未确认和高优先级告警。', 'tone': 'danger'})
    if access['trace']:
        navigation.append({'title': '链路追踪', 'path': '/observability/tracing', 'description': '统一查看 SkyWalking 与 OpenTelemetry Trace、Span 和调用拓扑。', 'tone': 'success'})
    if access['trace_datasource']:
        navigation.append({'title': '链路数据源', 'path': '/observability/tracing/datasources', 'description': '维护 SkyWalking、Tempo、Jaeger、Zipkin 查询入口与默认数据源。', 'tone': 'warning'})
    if access['grafana']:
        navigation.append({'title': 'Grafana 大屏', 'path': '/observability/grafana', 'description': '打开监控看板和推荐大屏。', 'tone': 'accent'})

    return Response({
        'modules': {
            'tracing': catalog['tracing'] if catalog else None,
            'grafana': grafana,
            'logs': logs,
            'alerts': alerts,
        },
        'summary': {
            'service_count': catalog['summary']['service_count'] if catalog else 0,
            'trace_count': catalog['summary']['trace_count'] if catalog else 0,
            'error_count': catalog['summary']['error_count'] if catalog else 0,
            'topology_nodes': catalog['summary']['topology_nodes'] if catalog else 0,
            'dashboard_count': grafana['dashboard_count'] if grafana else 0,
            'datasource_count': logs['datasource_count'] if logs else 0,
            'unacknowledged_alerts': alerts['unacknowledged'] if alerts else 0,
        },
        'navigation': navigation,
        'recent_traces': catalog['recent_traces'] if catalog else [],
        'providers': catalog['providers'] if catalog else [
            {
                'provider': item['id'],
                'provider_name': item['name'],
                'source': 'demo' if not item['configured'] else item['id'],
                'configured': item['configured'],
                'active': False,
            }
            for item in (tracing_provider_info() if access['trace_datasource'] else [])
        ],
        'recent_alerts': alerts['recent'] if alerts else [],
        'tips': [
            '链路追踪优先接入 SkyWalking、Tempo、Jaeger 或 Zipkin；未配置时自动展示演示数据。',
            'Tempo、Jaeger、Zipkin 统一按 OpenTelemetry 风格归一化为标准 Trace / Span 模型。',
            '日志中心、告警中心与链路追踪已收敛到可观测性菜单，便于统一排障。',
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_tracing_catalog(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_tracing_catalog(
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
            service_id=request.query_params.get('service_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def observability_tracing_search(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(search_tracing(request.data or {}))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_trace_detail(request, trace_id):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_trace_detail(
            trace_id,
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
