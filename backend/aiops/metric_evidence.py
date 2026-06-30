import re
from collections import Counter
from datetime import timedelta

from django.utils import timezone


ALERT_METRIC_QUERY_BUDGET = 8
ALERT_METRIC_SERIES_LIMIT = 5
ALERT_METRIC_MAX_DURATION_MINUTES = 120
ALERT_METRIC_DEFAULT_DURATION_MINUTES = 60
ALERT_METRIC_DEFAULT_STEP_SECONDS = 60


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def safe_float(value, default=None):
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def alert_metric_promql(alert):
    metric = str(alert.metric_name or '').strip()
    if not metric or not re.match(r'^[a-zA-Z_:][a-zA-Z0-9_:]*$', metric):
        return ''
    labels = dict(alert.labels if isinstance(alert.labels, dict) else {})
    for key, value in {
        'environment': alert.environment,
        'cluster': alert.cluster,
        'namespace': alert.namespace,
        'service': alert.service,
    }.items():
        if value and not labels.get(key):
            labels[key] = value
    resource = str(alert.resource or '').strip()
    resource_type = str(alert.resource_type or '').strip().lower()
    if resource:
        if resource_type in {'pod', 'pods'}:
            labels.setdefault('pod', resource)
        elif resource_type in {'deployment', 'deployments'}:
            labels.setdefault('deployment', resource)
        elif resource_type in {'node', 'nodes'}:
            labels.setdefault('node', resource)
            labels.setdefault('instance', resource)
        elif resource_type in {'service', 'services'}:
            labels.setdefault('service', resource)
    selectors = []
    for key in ['environment', 'cluster', 'namespace', 'pod', 'deployment', 'service', 'job', 'instance', 'node', 'container']:
        value = labels.get(key)
        if value not in [None, '']:
            selectors.append(f'{key}="{promql_escape_label_value(value)}"')
    if not selectors:
        return ''
    return f'{metric}' + '{' + ','.join(selectors[:6]) + '}'


def promql_escape_label_value(value):
    return str(value or '').replace('\\', '\\\\').replace('"', '\\"')


def promql_selector(label_values, allowed_labels=None, max_labels=6):
    allowed = allowed_labels or ['environment', 'cluster', 'namespace', 'pod', 'deployment', 'service', 'job', 'instance', 'node', 'container']
    selectors = []
    for key in allowed:
        value = label_values.get(key) if isinstance(label_values, dict) else ''
        if value not in (None, ''):
            selectors.append(f'{key}="{promql_escape_label_value(value)}"')
        if len(selectors) >= max_labels:
            break
    return '{' + ','.join(selectors) + '}' if selectors else ''


def promql_regex_selector(label_values, allowed_labels=None, max_labels=4):
    allowed = allowed_labels or ['environment', 'cluster', 'namespace', 'service', 'deployment', 'pod', 'job', 'instance', 'node']
    selectors = []
    for key in allowed:
        value = label_values.get(key) if isinstance(label_values, dict) else ''
        text = str(value or '').strip()
        if text:
            selectors.append(f'{key}=~".*{re.escape(text)}.*"')
        if len(selectors) >= max_labels:
            break
    return '{' + ','.join(selectors) + '}' if selectors else ''


def promql_with_extra_matchers(selector, extra_matchers):
    extras = [str(item or '').strip() for item in (extra_matchers or []) if str(item or '').strip()]
    text = str(selector or '').strip()
    if text.startswith('{') and text.endswith('}'):
        body = text[1:-1].strip()
        parts = [body] if body else []
        parts.extend(extras)
        return '{' + ','.join(parts) + '}' if parts else ''
    if extras:
        return '{' + ','.join(extras) + '}'
    return text


def alert_metric_label_context(alert):
    labels = dict(alert.labels if isinstance(alert.labels, dict) else {})
    for key, value in {
        'environment': alert.environment,
        'cluster': alert.cluster,
        'namespace': alert.namespace,
        'service': alert.service,
    }.items():
        if value and not labels.get(key):
            labels[key] = value
    resource = str(alert.resource or '').strip()
    resource_type = str(alert.resource_type or '').strip().lower()
    if resource:
        if resource_type in {'pod', 'pods'}:
            labels.setdefault('pod', resource)
        elif resource_type in {'deployment', 'deployments'}:
            labels.setdefault('deployment', resource)
        elif resource_type in {'node', 'nodes'}:
            labels.setdefault('node', resource)
            labels.setdefault('instance', resource)
        elif resource_type in {'service', 'services'}:
            labels.setdefault('service', resource)
        else:
            labels.setdefault('resource', resource)
    return labels


def metric_plan_item(name, promql, category, intent, weight='medium'):
    expression = str(promql or '').strip()
    if not expression:
        return None
    return {
        'name': name,
        'promql': expression,
        'category': category,
        'intent': intent,
        'weight': weight,
    }


def dedupe_metric_plan(plan, budget=ALERT_METRIC_QUERY_BUDGET):
    deduped = []
    seen = set()
    for item in plan:
        if not item or not item.get('promql'):
            continue
        key = item['promql']
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= budget:
            break
    return deduped


def build_alert_metric_query_plan(alert, budget=ALERT_METRIC_QUERY_BUDGET):
    labels = alert_metric_label_context(alert)
    plan = []
    raw_promql = alert_metric_promql(alert)
    if raw_promql:
        plan.append(metric_plan_item('告警触发指标', raw_promql, 'trigger', '确认告警自身指标在时间窗口内是否仍异常', 'strong'))

    exact_selector = promql_selector(labels, ['cluster', 'namespace', 'service', 'deployment', 'pod', 'job', 'instance', 'node', 'container'])
    service_selector = promql_regex_selector(labels, ['cluster', 'namespace', 'service', 'deployment', 'pod', 'job'])
    node_selector = promql_regex_selector(labels, ['cluster', 'node', 'instance'])
    alert_text = f'{alert.title} {alert.message} {alert.metric_name} {alert.service} {alert.resource_type} {alert.resource}'.lower()
    has_service_context = bool(labels.get('service') or labels.get('deployment') or labels.get('pod') or alert.service)
    has_k8s_context = bool(alert.cluster or alert.namespace or labels.get('pod') or labels.get('deployment') or any(
        keyword in alert_text for keyword in ['k8s', 'kubernetes', 'pod', 'deployment', 'container', 'oom', 'restart', 'crashloop']
    ))
    has_node_context = bool(labels.get('node') or str(alert.resource_type or '').lower() in {'node', 'nodes', 'host', 'instance'})

    if has_service_context and service_selector:
        request_total_expr = f'sum(rate(http_requests_total{service_selector}[5m]))'
        status_5xx_selector = promql_with_extra_matchers(service_selector, ['status=~"5.."'])
        code_5xx_selector = promql_with_extra_matchers(service_selector, ['code=~"5.."'])
        if any(keyword in alert_text for keyword in ['success rate', '成功率', '可用性', 'availability', 'slo', 'sla']):
            plan.append(metric_plan_item(
                '下单成功率',
                f'(1 - ((sum(rate(http_requests_total{status_5xx_selector}[5m])) + sum(rate(http_requests_total{code_5xx_selector}[5m]))) / clamp_min({request_total_expr}, 0.001)))',
                'service_red',
                '确认业务成功率是否低于 SLO 目标',
                'strong',
            ))
        plan.extend([
            metric_plan_item(
                '服务 5xx 错误率',
                f'((sum(rate(http_requests_total{status_5xx_selector}[5m])) + sum(rate(http_requests_total{code_5xx_selector}[5m]))) / clamp_min({request_total_expr}, 0.001))',
                'service_red',
                '确认服务请求错误是否接近告警窗口抬升',
                'strong',
            ),
            metric_plan_item(
                '服务 P95 延迟',
                f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service_selector}[5m])) by (le))',
                'service_red',
                '确认服务延迟是否与告警同步抬升',
                'strong',
            ),
            metric_plan_item(
                '服务请求量',
                f'sum(rate(http_requests_total{service_selector}[5m]))',
                'service_red',
                '确认流量是否突增、突降或无流量',
                'medium',
            ),
        ])

    if has_k8s_context:
        k8s_selector = exact_selector or service_selector
        plan.extend([
            metric_plan_item(
                '容器重启增量',
                f'sum(increase(kube_pod_container_status_restarts_total{k8s_selector}[10m])) by (namespace, pod)' if k8s_selector else '',
                'k8s_runtime',
                '确认 Pod 或容器是否在告警前后重启',
                'strong',
            ),
            metric_plan_item(
                '容器 CPU 使用',
                f'sum(rate(container_cpu_usage_seconds_total{k8s_selector}[5m])) by (namespace, pod)' if k8s_selector else '',
                'k8s_runtime',
                '确认 CPU 使用是否异常抬升',
                'medium',
            ),
            metric_plan_item(
                '容器内存使用',
                f'sum(container_memory_working_set_bytes{k8s_selector}) by (namespace, pod)' if k8s_selector else '',
                'k8s_runtime',
                '确认内存使用是否接近异常',
                'medium',
            ),
        ])
        deployment = labels.get('deployment') or (alert.resource if str(alert.resource_type or '').lower() in {'deployment', 'deployments'} else '')
        if deployment and alert.namespace:
            dep_selector = promql_selector({'namespace': alert.namespace, 'deployment': deployment}, ['namespace', 'deployment'])
            plan.append(metric_plan_item(
                'Deployment 可用副本',
                f'kube_deployment_status_replicas_available{dep_selector}',
                'k8s_runtime',
                '确认 Deployment 可用副本是否不足',
                'strong',
            ))

    if has_node_context and node_selector:
        idle_selector = promql_with_extra_matchers(node_selector, ['mode="idle"'])
        plan.extend([
            metric_plan_item(
                '节点 CPU 使用率',
                f'1 - avg(rate(node_cpu_seconds_total{idle_selector}[5m]))',
                'node_runtime',
                '确认节点 CPU 是否异常',
                'medium',
            ),
            metric_plan_item(
                '节点内存可用率',
                f'node_memory_MemAvailable_bytes{node_selector} / node_memory_MemTotal_bytes{node_selector}',
                'node_runtime',
                '确认节点内存是否紧张',
                'medium',
            ),
        ])

    return dedupe_metric_plan(plan, budget=budget)


def metric_value_from_sample(sample):
    if isinstance(sample, (list, tuple)) and len(sample) >= 2:
        return safe_float(sample[1])
    return safe_float(sample)


def series_numeric_values(series):
    values = []
    for point in series.get('values') or []:
        number = metric_value_from_sample(point)
        if number is not None:
            values.append(number)
    if not values:
        number = metric_value_from_sample(series.get('value'))
        if number is not None:
            values.append(number)
    return values


def summarize_metric_series(series):
    metric = series.get('metric') or {}
    values = series_numeric_values(series)
    if not values:
        return {
            'metric': metric,
            'points': 0,
            'latest': None,
            'baseline': None,
            'maximum': None,
            'minimum': None,
            'trend': 'unknown',
            'abnormal': False,
        }
    latest = values[-1]
    head = values[:max(1, min(5, len(values)))]
    baseline = sum(head) / len(head)
    maximum = max(values)
    minimum = min(values)
    delta = latest - baseline
    abs_baseline = abs(baseline)
    if abs(delta) <= max(abs_baseline * 0.2, 0.0001):
        trend = 'flat'
    else:
        trend = 'up' if delta > 0 else 'down'
    abnormal = False
    if trend == 'up' and latest > max(baseline * 1.5, baseline + 0.01):
        abnormal = True
    if baseline > 0 and latest <= baseline * 0.3:
        abnormal = True
    return {
        'metric': metric,
        'points': len(values),
        'latest': round(latest, 6),
        'baseline': round(baseline, 6),
        'maximum': round(maximum, 6),
        'minimum': round(minimum, 6),
        'trend': trend,
        'abnormal': abnormal,
    }


def metric_label_text(metric):
    if not isinstance(metric, dict) or not metric:
        return 'scalar'
    preferred = ['namespace', 'pod', 'deployment', 'service', 'job', 'instance', 'node', 'container']
    parts = []
    for key in preferred:
        value = metric.get(key)
        if value not in (None, ''):
            parts.append(f'{key}={value}')
        if len(parts) >= 4:
            break
    if not parts:
        parts = [f'{key}={value}' for key, value in list(metric.items())[:4]]
    return ', '.join(parts) or 'scalar'


def summarize_metric_query_result(plan_item, payload, series_limit=ALERT_METRIC_SERIES_LIMIT):
    results = payload.get('result') or []
    series_summaries = [summarize_metric_series(item) for item in results[:series_limit]]
    abnormal_series = [item for item in series_summaries if item.get('abnormal')]
    has_data = bool(series_summaries)
    status_text = 'abnormal' if abnormal_series else ('normal' if has_data else 'missing')
    trend_counter = Counter(item.get('trend') for item in series_summaries if item.get('trend'))
    trend = trend_counter.most_common(1)[0][0] if trend_counter else 'unknown'
    return {
        'name': plan_item.get('name'),
        'category': plan_item.get('category'),
        'intent': plan_item.get('intent'),
        'weight': plan_item.get('weight'),
        'promql': plan_item.get('promql'),
        'status': status_text,
        'trend': trend,
        'series_count': payload.get('series_count', len(results)),
        'source': payload.get('source'),
        'metric_datasource': payload.get('metric_datasource'),
        'series': series_summaries,
    }


def format_metric_evidence_item(item):
    status_map = {'abnormal': '异常', 'normal': '有数据', 'missing': '无数据', 'failed': '未完成'}
    status_text = status_map.get(item.get('status'), item.get('status') or '未知')
    series = item.get('series') or []
    if item.get('status') == 'failed':
        return f"{item.get('name')}：查询未完成，{item.get('error') or '未返回详细原因'}"
    if not series:
        return f"{item.get('name')}：{status_text}，未返回时间序列；PromQL={item.get('promql')}"
    first = series[0]
    return (
        f"{item.get('name')}：{status_text}，趋势 {first.get('trend') or 'unknown'}，"
        f"最新 {first.get('latest')}，基线 {first.get('baseline')}，序列 {metric_label_text(first.get('metric'))}"
    )


def alert_metric_time_window(alert, duration_minutes):
    anchor = alert.starts_at or alert.last_received_at or alert.created_at or timezone.now()
    if timezone.is_naive(anchor):
        anchor = timezone.make_aware(anchor, timezone.get_current_timezone())
    duration = max(15, min(safe_int(duration_minutes, ALERT_METRIC_DEFAULT_DURATION_MINUTES), ALERT_METRIC_MAX_DURATION_MINUTES))
    before_minutes = min(duration // 2, 60)
    after_minutes = max(duration - before_minutes, 15)
    start_time = anchor - timedelta(minutes=before_minutes)
    end_time = max(timezone.now(), anchor + timedelta(minutes=after_minutes))
    if (end_time - start_time).total_seconds() > ALERT_METRIC_MAX_DURATION_MINUTES * 60:
        end_time = start_time + timedelta(minutes=ALERT_METRIC_MAX_DURATION_MINUTES)
    return start_time, end_time, duration
