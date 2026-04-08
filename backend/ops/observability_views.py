from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

import requests as http_requests
from django.conf import settings
from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.services import user_has_permissions
from .models import Alert, LogDataSource
from .serializers import AlertSerializer


REQUEST_TIMEOUT = 20
DEFAULT_TRACE_LIMIT = 20

DEMO_SERVICES = [
    {'id': 'svc-gateway', 'name': 'gateway-service', 'short_name': 'gateway', 'layers': ['GENERAL'], 'group': 'sxdevops'},
    {'id': 'svc-order', 'name': 'order-service', 'short_name': 'order', 'layers': ['GENERAL'], 'group': 'sxdevops'},
    {'id': 'svc-payment', 'name': 'payment-service', 'short_name': 'payment', 'layers': ['GENERAL'], 'group': 'sxdevops'},
    {'id': 'svc-member', 'name': 'member-service', 'short_name': 'member', 'layers': ['GENERAL'], 'group': 'sxdevops'},
]

DEMO_TRACES = [
    {
        'trace_id': 'trace-demo-20260329-001',
        'segment_id': 'segment-demo-001',
        'service_id': 'svc-gateway',
        'service_name': 'gateway-service',
        'instance_name': 'gateway-prod-01',
        'endpoint_names': ['GET /api/orders/{id}', 'POST /api/payments'],
        'duration_ms': 248,
        'start': '2026-03-29T09:18:26+08:00',
        'is_error': False,
        'state': 'SUCCESS',
        'summary': '订单详情请求穿透到订单与支付服务，整体延迟稳定。',
    },
    {
        'trace_id': 'trace-demo-20260329-002',
        'segment_id': 'segment-demo-002',
        'service_id': 'svc-payment',
        'service_name': 'payment-service',
        'instance_name': 'payment-prod-02',
        'endpoint_names': ['POST /api/payments/callback'],
        'duration_ms': 1432,
        'start': '2026-03-29T09:14:11+08:00',
        'is_error': True,
        'state': 'ERROR',
        'summary': '支付回调在调用会员服务时超时，链路出现错误 Span。',
    },
    {
        'trace_id': 'trace-demo-20260329-003',
        'segment_id': 'segment-demo-003',
        'service_id': 'svc-order',
        'service_name': 'order-service',
        'instance_name': 'order-gray-01',
        'endpoint_names': ['POST /api/orders/confirm'],
        'duration_ms': 612,
        'start': '2026-03-29T09:05:48+08:00',
        'is_error': False,
        'state': 'SUCCESS',
        'summary': '灰度订单确认链路完成，数据库写入阶段耗时略高。',
    },
    {
        'trace_id': 'trace-demo-20260329-004',
        'segment_id': 'segment-demo-004',
        'service_id': 'svc-member',
        'service_name': 'member-service',
        'instance_name': 'member-prod-01',
        'endpoint_names': ['GET /api/members/{id}/profile'],
        'duration_ms': 318,
        'start': '2026-03-29T08:57:03+08:00',
        'is_error': False,
        'state': 'SUCCESS',
        'summary': '会员资料查询链路稳定，缓存命中率较高。',
    },
]

DEMO_TRACE_SPANS = {
    'trace-demo-20260329-001': [
        {'span_id': 0, 'parent_span_id': -1, 'service_code': 'gateway-service', 'service_instance_name': 'gateway-prod-01', 'endpoint_name': 'GET /api/orders/{id}', 'start_time': '2026-03-29T09:18:26.000+08:00', 'end_time': '2026-03-29T09:18:26.248+08:00', 'duration_ms': 248, 'type': 'Entry', 'peer': '', 'component': 'SpringMVC', 'is_error': False, 'layer': 'HTTP', 'tags': [{'key': 'http.method', 'value': 'GET'}, {'key': 'http.status_code', 'value': '200'}], 'logs': []},
        {'span_id': 1, 'parent_span_id': 0, 'service_code': 'order-service', 'service_instance_name': 'order-prod-01', 'endpoint_name': 'queryOrderById', 'start_time': '2026-03-29T09:18:26.024+08:00', 'end_time': '2026-03-29T09:18:26.156+08:00', 'duration_ms': 132, 'type': 'Exit', 'peer': 'order-service:20880', 'component': 'Dubbo', 'is_error': False, 'layer': 'RPC_FRAMEWORK', 'tags': [{'key': 'db.statement.count', 'value': '2'}], 'logs': []},
        {'span_id': 2, 'parent_span_id': 0, 'service_code': 'payment-service', 'service_instance_name': 'payment-prod-01', 'endpoint_name': 'queryPaymentStatus', 'start_time': '2026-03-29T09:18:26.061+08:00', 'end_time': '2026-03-29T09:18:26.199+08:00', 'duration_ms': 138, 'type': 'Exit', 'peer': 'payment-service:20880', 'component': 'Dubbo', 'is_error': False, 'layer': 'RPC_FRAMEWORK', 'tags': [{'key': 'result', 'value': 'PAID'}], 'logs': []},
    ],
    'trace-demo-20260329-002': [
        {'span_id': 0, 'parent_span_id': -1, 'service_code': 'payment-service', 'service_instance_name': 'payment-prod-02', 'endpoint_name': 'POST /api/payments/callback', 'start_time': '2026-03-29T09:14:11.000+08:00', 'end_time': '2026-03-29T09:14:12.432+08:00', 'duration_ms': 1432, 'type': 'Entry', 'peer': '', 'component': 'SpringMVC', 'is_error': True, 'layer': 'HTTP', 'tags': [{'key': 'http.method', 'value': 'POST'}, {'key': 'http.status_code', 'value': '500'}], 'logs': [{'time': '2026-03-29T09:14:12.406+08:00', 'data': [{'key': 'error.kind', 'value': 'TimeoutException'}, {'key': 'message', 'value': 'member-service request timed out'}]}]},
        {'span_id': 1, 'parent_span_id': 0, 'service_code': 'member-service', 'service_instance_name': 'member-prod-01', 'endpoint_name': 'loadMemberForPayment', 'start_time': '2026-03-29T09:14:11.202+08:00', 'end_time': '2026-03-29T09:14:12.401+08:00', 'duration_ms': 1199, 'type': 'Exit', 'peer': 'member-service:20880', 'component': 'Dubbo', 'is_error': True, 'layer': 'RPC_FRAMEWORK', 'tags': [{'key': 'timeout.ms', 'value': '1000'}], 'logs': [{'time': '2026-03-29T09:14:12.401+08:00', 'data': [{'key': 'cause', 'value': 'Read timed out'}]}]},
    ],
    'trace-demo-20260329-003': [
        {'span_id': 0, 'parent_span_id': -1, 'service_code': 'order-service', 'service_instance_name': 'order-gray-01', 'endpoint_name': 'POST /api/orders/confirm', 'start_time': '2026-03-29T09:05:48.000+08:00', 'end_time': '2026-03-29T09:05:48.612+08:00', 'duration_ms': 612, 'type': 'Entry', 'peer': '', 'component': 'SpringMVC', 'is_error': False, 'layer': 'HTTP', 'tags': [{'key': 'release', 'value': 'gray'}], 'logs': []},
        {'span_id': 1, 'parent_span_id': 0, 'service_code': 'order-service', 'service_instance_name': 'order-gray-01', 'endpoint_name': 'OrderRepository.save', 'start_time': '2026-03-29T09:05:48.198+08:00', 'end_time': '2026-03-29T09:05:48.587+08:00', 'duration_ms': 389, 'type': 'Local', 'peer': '', 'component': 'MySQL', 'is_error': False, 'layer': 'DATABASE', 'tags': [{'key': 'db.type', 'value': 'mysql'}], 'logs': []},
    ],
    'trace-demo-20260329-004': [
        {'span_id': 0, 'parent_span_id': -1, 'service_code': 'member-service', 'service_instance_name': 'member-prod-01', 'endpoint_name': 'GET /api/members/{id}/profile', 'start_time': '2026-03-29T08:57:03.000+08:00', 'end_time': '2026-03-29T08:57:03.318+08:00', 'duration_ms': 318, 'type': 'Entry', 'peer': '', 'component': 'SpringMVC', 'is_error': False, 'layer': 'HTTP', 'tags': [{'key': 'cache.hit', 'value': 'true'}], 'logs': []},
        {'span_id': 1, 'parent_span_id': 0, 'service_code': 'member-service', 'service_instance_name': 'member-prod-01', 'endpoint_name': 'Redis GET member:profile', 'start_time': '2026-03-29T08:57:03.021+08:00', 'end_time': '2026-03-29T08:57:03.057+08:00', 'duration_ms': 36, 'type': 'Exit', 'peer': 'redis-member-01:6379', 'component': 'Jedis', 'is_error': False, 'layer': 'CACHE', 'tags': [{'key': 'cache.hit', 'value': 'true'}], 'logs': []},
    ],
}

DEMO_GRAFANA_DASHBOARDS = [
    {'key': 'apm-overview', 'title': 'APM 全链路总览', 'slug': 'apm-overview', 'path': '/d/apm-overview', 'panel_count': 18, 'tags': ['SkyWalking', '应用', 'SLA'], 'description': '面向应用负责人查看服务吞吐、慢调用与错误率。'},
    {'key': 'infra-overview', 'title': '基础设施总览', 'slug': 'infra-overview', 'path': '/d/infra-overview', 'panel_count': 14, 'tags': ['Node', 'CPU', 'Memory'], 'description': '聚合节点 CPU、内存、磁盘与 Pod 负载走势。'},
    {'key': 'log-drilldown', 'title': '日志钻取看板', 'slug': 'log-drilldown', 'path': '/d/log-drilldown', 'panel_count': 12, 'tags': ['Loki', 'Error', 'Audit'], 'description': '配合日志中心快速回放错误时段与关键日志。'},
    {'key': 'ingress-slo', 'title': '入口流量与 SLO', 'slug': 'ingress-slo', 'path': '/d/ingress-slo', 'panel_count': 10, 'tags': ['Nginx', 'Latency', 'Availability'], 'description': '聚焦入口 QPS、响应时间分位和可用性目标。'},
]


class ObservabilityError(Exception):
    def __init__(self, message, status_code=status.HTTP_400_BAD_REQUEST, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}


def _deny_if_missing_any(request, codes):
    allowed = any(user_has_permissions(request.user, [code]) for code in codes)
    if allowed:
        return None
    return Response({'detail': f"缺少权限: {', '.join(codes)}"}, status=status.HTTP_403_FORBIDDEN)


def _has_permission(request, code):
    return user_has_permissions(request.user, [code])


def _observability_access(request):
    return {
        'log_query': _has_permission(request, 'ops.log.query'),
        'log_datasource': _has_permission(request, 'ops.log.datasource.view'),
        'alerts': _has_permission(request, 'ops.alert.view'),
        'trace': _has_permission(request, 'ops.trace.view'),
        'grafana': _has_permission(request, 'ops.grafana.view'),
    }


def _observability_defaults():
    return getattr(settings, 'OBSERVABILITY_CONFIG', {}) or {}


def _skywalking_config():
    config = dict(_observability_defaults().get('skywalking', {}))
    config.setdefault('provider', 'skywalking')
    config.setdefault('enabled', True)
    config.setdefault('ui_url', '')
    config.setdefault('oap_url', '')
    config.setdefault('graphql_path', '/graphql')
    config.setdefault('default_layer', '')
    config.setdefault('demo_mode', True)
    return config


def _grafana_config():
    config = dict(_observability_defaults().get('grafana', {}))
    config.setdefault('enabled', True)
    config.setdefault('url', '')
    config.setdefault('default_path', '')
    config.setdefault('demo_mode', True)
    return config


def _join_external_url(base, path=''):
    if not base:
        return ''
    normalized = base if base.endswith('/') else f'{base}/'
    return urljoin(normalized, path.lstrip('/'))


def _skywalking_graphql_url(config):
    oap_url = (config.get('oap_url') or '').rstrip('/')
    if not oap_url:
        return ''
    graphql_path = config.get('graphql_path') or '/graphql'
    if oap_url.endswith(graphql_path):
        return oap_url
    return f"{oap_url}{graphql_path if graphql_path.startswith('/') else '/' + graphql_path}"


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return {'raw': response.text}


def _skywalking_query(query, variables=None, config=None):
    config = config or _skywalking_config()
    endpoint = _skywalking_graphql_url(config)
    if not endpoint:
        raise ObservabilityError('SkyWalking OAP GraphQL 地址未配置', status.HTTP_400_BAD_REQUEST)
    try:
        response = http_requests.post(
            endpoint,
            json={'query': query, 'variables': variables or {}},
            timeout=REQUEST_TIMEOUT,
        )
    except http_requests.Timeout as exc:
        raise ObservabilityError('SkyWalking 请求超时', status.HTTP_504_GATEWAY_TIMEOUT, {'detail': str(exc)}) from exc
    except http_requests.ConnectionError as exc:
        raise ObservabilityError('无法连接到 SkyWalking OAP', status.HTTP_502_BAD_GATEWAY, {'detail': str(exc)}) from exc
    payload = _safe_json(response)
    if response.status_code >= 400:
        raise ObservabilityError(payload.get('message') or payload.get('error') or 'SkyWalking 请求失败', response.status_code, payload)
    if payload.get('errors'):
        error_message = payload['errors'][0].get('message') or 'SkyWalking GraphQL 返回错误'
        raise ObservabilityError(error_message, status.HTTP_502_BAD_GATEWAY, payload)
    return payload.get('data') or {}


def _duration_strings(minutes=30):
    end = datetime.now()
    start = end - timedelta(minutes=max(5, int(minutes or 30)))
    return {
        'start': start.strftime('%Y-%m-%d %H%M'),
        'end': end.strftime('%Y-%m-%d %H%M'),
        'step': 'MINUTE',
    }


def _normalize_services(items):
    services = []
    for item in items or []:
        layers = item.get('layers') or []
        if isinstance(layers, str):
            layers = [layers]
        services.append({
            'id': item.get('id') or item.get('name') or '',
            'name': item.get('name') or item.get('shortName') or '',
            'short_name': item.get('shortName') or item.get('name') or '',
            'layers': layers,
            'group': item.get('group') or '',
        })
    return [item for item in services if item['id']]


def _load_skywalking_services(config, layer=''):
    variables = {'layer': layer or None}
    queries = [
        (
            """
            query ListServices($layer: ServiceLayer) {
              listServices(layer: $layer) {
                id
                name
                shortName
                group
                layers
              }
            }
            """,
            'listServices',
        ),
        (
            """
            query ServicesByDuration($duration: Duration!) {
              getAllServices(duration: $duration) {
                id
                name
                shortName
                group
              }
            }
            """,
            'getAllServices',
        ),
    ]
    last_error = None
    for query, field in queries:
        try:
            if field == 'getAllServices':
                data = _skywalking_query(query, {'duration': _duration_strings(60)}, config)
            else:
                data = _skywalking_query(query, variables, config)
            services = _normalize_services(data.get(field))
            if services:
                return services
        except ObservabilityError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _load_skywalking_topology(config):
    query = """
    query GlobalTopology($duration: Duration!) {
      getGlobalTopology(duration: $duration) {
        nodes {
          id
          name
          type
          layers
        }
        calls {
          id
          source
          target
        }
      }
    }
    """
    data = _skywalking_query(query, {'duration': _duration_strings(30)}, config).get('getGlobalTopology') or {}
    nodes = data.get('nodes') or []
    calls = data.get('calls') or []
    return {
        'node_count': len(nodes),
        'call_count': len(calls),
        'nodes': nodes,
        'calls': calls,
    }


def _search_skywalking_traces(config, payload, services):
    limit = max(1, min(int(payload.get('limit') or DEFAULT_TRACE_LIMIT), 50))
    default_service_id = payload.get('service_id') or (services[0]['id'] if services else '')
    if not default_service_id and not (payload.get('trace_id') or '').strip():
        return []
    condition = {
        'serviceId': default_service_id,
        'traceId': payload.get('trace_id') or '',
        'queryDuration': _duration_strings(payload.get('duration_minutes') or 30),
        'minTraceDuration': payload.get('min_duration_ms') or 0,
        'maxTraceDuration': payload.get('max_duration_ms') or 0,
        'traceState': payload.get('trace_state') or 'ALL',
        'queryOrder': 'BY_START_TIME',
        'paging': {'pageNum': 1, 'pageSize': limit},
    }
    query = """
    query SearchTraces($condition: TraceQueryCondition) {
      queryBasicTraces(condition: $condition) {
        traces {
          segmentId
          endpointNames
          duration
          start
          isError
          traceIds
        }
      }
    }
    """
    traces_payload = _skywalking_query(query, {'condition': condition}, config).get('queryBasicTraces') or {}
    service_name = next((item['name'] for item in services if item['id'] == condition['serviceId']), '')
    traces = []
    for item in traces_payload.get('traces') or []:
        trace_ids = item.get('traceIds') or []
        traces.append({
            'trace_id': trace_ids[0] if trace_ids else item.get('segmentId') or '',
            'segment_id': item.get('segmentId') or '',
            'service_id': condition['serviceId'],
            'service_name': service_name,
            'instance_name': '',
            'endpoint_names': item.get('endpointNames') or [],
            'duration_ms': item.get('duration') or 0,
            'start': item.get('start') or '',
            'is_error': bool(item.get('isError')),
            'state': 'ERROR' if item.get('isError') else 'SUCCESS',
            'summary': '来自 SkyWalking OAP 的实时链路结果。',
        })
    return traces


def _trace_detail_from_spans(trace_id, spans):
    normalized_spans = []
    services = set()
    endpoints = set()
    error_count = 0
    total_duration = 0
    for item in spans or []:
        if item.get('isError'):
            error_count += 1
        duration_ms = item.get('duration_ms')
        if duration_ms is None:
            start_value = item.get('startTime') or item.get('start_time') or 0
            end_value = item.get('endTime') or item.get('end_time') or 0
            duration_ms = max(0, int(end_value or 0) - int(start_value or 0))
        total_duration = max(total_duration, duration_ms)
        service_code = item.get('serviceCode') or item.get('service_code') or ''
        endpoint_name = item.get('endpointName') or item.get('endpoint_name') or ''
        if service_code:
            services.add(service_code)
        if endpoint_name:
            endpoints.add(endpoint_name)
        normalized_spans.append({
            'span_id': item.get('spanId') if item.get('spanId') is not None else item.get('span_id'),
            'parent_span_id': item.get('parentSpanId') if item.get('parentSpanId') is not None else item.get('parent_span_id'),
            'service_code': service_code,
            'service_instance_name': item.get('serviceInstanceName') or item.get('service_instance_name') or '',
            'endpoint_name': endpoint_name,
            'start_time': item.get('startTime') or item.get('start_time') or '',
            'end_time': item.get('endTime') or item.get('end_time') or '',
            'duration_ms': duration_ms,
            'type': item.get('type') or '',
            'peer': item.get('peer') or '',
            'component': item.get('component') or '',
            'is_error': bool(item.get('isError') if item.get('isError') is not None else item.get('is_error')),
            'layer': item.get('layer') or '',
            'tags': item.get('tags') or [],
            'logs': item.get('logs') or [],
        })
    return {
        'trace_id': trace_id,
        'span_count': len(normalized_spans),
        'duration_ms': total_duration,
        'error_count': error_count,
        'services': sorted(services),
        'endpoints': sorted(endpoints),
        'spans': normalized_spans,
    }


def _load_skywalking_trace_detail(config, trace_id):
    query = """
    query TraceDetail($traceId: ID!) {
      queryTrace(traceId: $traceId) {
        spans {
          traceId
          segmentId
          spanId
          parentSpanId
          serviceCode
          serviceInstanceName
          startTime
          endTime
          endpointName
          type
          peer
          component
          isError
          layer
          tags {
            key
            value
          }
          logs {
            time
            data {
              key
              value
            }
          }
        }
      }
    }
    """
    data = _skywalking_query(query, {'traceId': trace_id}, config).get('queryTrace') or {}
    return _trace_detail_from_spans(trace_id, data.get('spans') or [])


def _demo_services():
    return [dict(item) for item in DEMO_SERVICES]


def _demo_topology():
    nodes = [{'id': item['id'], 'name': item['name'], 'type': 'SERVICE', 'layers': item['layers']} for item in DEMO_SERVICES]
    calls = [
        {'id': 'call-gateway-order', 'source': 'svc-gateway', 'target': 'svc-order'},
        {'id': 'call-gateway-payment', 'source': 'svc-gateway', 'target': 'svc-payment'},
        {'id': 'call-payment-member', 'source': 'svc-payment', 'target': 'svc-member'},
    ]
    return {
        'node_count': len(nodes),
        'call_count': len(calls),
        'nodes': nodes,
        'calls': calls,
    }


def _demo_search_traces(payload):
    service_id = payload.get('service_id') or ''
    trace_id = (payload.get('trace_id') or '').strip().lower()
    keyword = (payload.get('keyword') or '').strip().lower()
    trace_state = payload.get('trace_state') or 'ALL'
    limit = max(1, min(int(payload.get('limit') or DEFAULT_TRACE_LIMIT), 50))

    traces = []
    for item in DEMO_TRACES:
        if service_id and item['service_id'] != service_id:
            continue
        if trace_state == 'ERROR' and not item['is_error']:
            continue
        if trace_state == 'SUCCESS' and item['is_error']:
            continue
        haystack = ' '.join([item['trace_id'], item['service_name'], item['summary'], *item['endpoint_names']]).lower()
        if trace_id and trace_id not in item['trace_id'].lower():
            continue
        if keyword and keyword not in haystack:
            continue
        traces.append(dict(item))
    return traces[:limit]


def _demo_trace_detail(trace_id):
    if trace_id not in DEMO_TRACE_SPANS:
        raise ObservabilityError('未找到对应的演示 Trace', status.HTTP_404_NOT_FOUND)
    detail = _trace_detail_from_spans(trace_id, DEMO_TRACE_SPANS[trace_id])
    matched = next((item for item in DEMO_TRACES if item['trace_id'] == trace_id), None)
    if matched:
        detail['service_name'] = matched['service_name']
        detail['start'] = matched['start']
        detail['state'] = matched['state']
    return detail


def _tracing_meta(config, source='demo', warning=''):
    graphql_url = _skywalking_graphql_url(config)
    ui_url = config.get('ui_url') or ''
    configured = bool(config.get('enabled') and (config.get('oap_url') or ui_url))
    status_text = '演示模式' if source == 'demo' else '已接入 SkyWalking'
    if warning:
        status_text = f'{status_text}，{warning}'
    return {
        'provider': 'skywalking',
        'enabled': bool(config.get('enabled')),
        'configured': configured,
        'source': source,
        'status_text': status_text,
        'ui_url': ui_url,
        'oap_url': config.get('oap_url') or '',
        'graphql_url': graphql_url,
        'embed_url': ui_url,
        'warning': warning,
    }


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
        'status_text': '已接入 Grafana' if configured else '未配置外部地址，当前显示推荐看板',
        'url': base_url,
        'embed_url': _join_external_url(base_url, default_path) if configured and default_path else base_url,
        'dashboard_count': len(dashboards),
        'panel_count': sum(item['panel_count'] for item in dashboards),
        'datasource_count': 4,
        'dashboards': dashboards,
    }


def _log_module_summary():
    providers = []
    grouped = (
        LogDataSource.objects.values('provider')
        .annotate(total=Count('id'))
        .order_by('provider')
    )
    enabled_by_provider = {
        item['provider']: item['count']
        for item in LogDataSource.objects.filter(is_enabled=True)
        .values('provider')
        .annotate(count=Count('id'))
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


def _load_tracing_catalog(layer=''):
    config = _skywalking_config()
    use_demo = not config.get('enabled') or not config.get('oap_url')
    warning = ''
    if use_demo:
        services = _demo_services()
        topology = _demo_topology()
        traces = _demo_search_traces({'limit': 6})
        return {
            'tracing': _tracing_meta(config, source='demo'),
            'services': services,
            'topology': topology,
            'summary': {
                'service_count': len(services),
                'trace_count': len(DEMO_TRACES),
                'error_count': len([item for item in DEMO_TRACES if item['is_error']]),
                'topology_nodes': topology['node_count'],
                'topology_calls': topology['call_count'],
            },
            'recent_traces': traces,
        }
    try:
        services = _load_skywalking_services(config, layer=layer)
        topology = _load_skywalking_topology(config)
        traces = _search_skywalking_traces(config, {'service_id': services[0]['id'] if services else '', 'limit': 6}, services)
        return {
            'tracing': _tracing_meta(config, source='skywalking'),
            'services': services,
            'topology': topology,
            'summary': {
                'service_count': len(services),
                'trace_count': len(traces),
                'error_count': len([item for item in traces if item['is_error']]),
                'topology_nodes': topology['node_count'],
                'topology_calls': topology['call_count'],
            },
            'recent_traces': traces,
        }
    except ObservabilityError as exc:
        if config.get('demo_mode'):
            services = _demo_services()
            topology = _demo_topology()
            warning = exc.detail.get('message') or str(exc)
            return {
                'tracing': _tracing_meta(config, source='demo', warning=f'已回退演示数据: {warning}'),
                'services': services,
                'topology': topology,
                'summary': {
                    'service_count': len(services),
                    'trace_count': len(DEMO_TRACES),
                    'error_count': len([item for item in DEMO_TRACES if item['is_error']]),
                    'topology_nodes': topology['node_count'],
                    'topology_calls': topology['call_count'],
                },
                'recent_traces': _demo_search_traces({'limit': 6}),
            }
        raise


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_overview(request):
    access = _observability_access(request)
    denied = _deny_if_missing_any(
        request,
        ['ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.trace.view', 'ops.grafana.view'],
    )
    if denied:
        return denied
    catalog = _load_tracing_catalog(layer=request.query_params.get('layer', '')) if access['trace'] else None
    grafana = _grafana_meta() if access['grafana'] else None
    logs = _log_module_summary() if (access['log_query'] or access['log_datasource']) else None
    alerts = _alert_module_summary() if access['alerts'] else None
    navigation = []
    if access['log_query'] or access['log_datasource']:
        log_description = '统一进入日志查询与数据源管理。' if access['log_query'] and access['log_datasource'] else '进入日志中心并按当前权限查看可用标签页。'
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': log_description, 'tone': 'info'})
    if access['alerts']:
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '集中处理当前未确认和高优先级告警。', 'tone': 'danger'})
    if access['trace']:
        navigation.append({'title': '链路追踪', 'path': '/observability/tracing', 'description': '查看 SkyWalking Trace、Span 和调用拓扑。', 'tone': 'success'})
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
        'recent_alerts': alerts['recent'] if alerts else [],
        'tips': [
            '链路追踪优先接入 SkyWalking OAP GraphQL；未配置时自动展示演示数据。',
            'Grafana 页面优先嵌入配置的大屏地址，无法嵌入时仍可通过外链跳转。',
            '日志中心与告警中心已归入可观测性平台菜单，便于统一巡检。',
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_tracing_catalog(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    return Response(_load_tracing_catalog(layer=request.query_params.get('layer', '')))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def observability_tracing_search(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    payload = request.data or {}
    catalog = _load_tracing_catalog(layer=payload.get('layer', ''))
    if catalog['tracing']['source'] == 'demo':
        traces = _demo_search_traces(payload)
    else:
        config = _skywalking_config()
        traces = _search_skywalking_traces(config, payload, catalog['services'])
    return Response({
        'tracing': catalog['tracing'],
        'services': catalog['services'],
        'summary': {
            **catalog['summary'],
            'match_count': len(traces),
            'error_match_count': len([item for item in traces if item['is_error']]),
        },
        'query': {
            'service_id': payload.get('service_id') or '',
            'trace_id': payload.get('trace_id') or '',
            'keyword': payload.get('keyword') or '',
            'trace_state': payload.get('trace_state') or 'ALL',
            'duration_minutes': payload.get('duration_minutes') or 30,
            'limit': payload.get('limit') or DEFAULT_TRACE_LIMIT,
        },
        'traces': traces,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_trace_detail(request, trace_id):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    catalog = _load_tracing_catalog(layer=request.query_params.get('layer', ''))
    try:
        if catalog['tracing']['source'] == 'demo':
            detail = _demo_trace_detail(trace_id)
        else:
            detail = _load_skywalking_trace_detail(_skywalking_config(), trace_id)
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
    return Response({
        'tracing': catalog['tracing'],
        'trace': detail,
    })
