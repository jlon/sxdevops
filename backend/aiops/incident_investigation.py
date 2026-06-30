import logging
import time
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from eventwall.models import EventRecord
from eventwall.services import record_event
from ops.log_views import _merge_config as merge_log_config
from ops.log_views import _run_query as run_log_provider_query
from ops.models import Alert, K8sCluster, LogDataSource, MetricDataSource, TaskResource, TracingDataSource
from ops.observability_views import execute_promql_query
from ops.tracing_providers import search_tracing

from . import metric_evidence
from .models import (
    AIOpsChatSession,
    AIOpsExternalTask,
    AIOpsIncident,
    AIOpsIncidentAction,
    AIOpsIncidentEvidence,
    AIOpsIncidentHypothesis,
    AIOpsToolInvocation,
)


logger = logging.getLogger(__name__)
INVESTIGATION_ACTION_CODE = 'incident.investigate'
INVESTIGATION_SOURCE_AGENT = 'sxdevops-incident-intake'
INVESTIGATION_AUDIT_USERNAME = 'aiops-system'
K8S_RESOURCE_TYPES = {
    'pod',
    'pods',
    'deployment',
    'deployments',
    'statefulset',
    'statefulsets',
    'daemonset',
    'daemonsets',
    'replicaset',
    'replicasets',
    'container',
    'containers',
}
K8S_SCOPE_KEYWORDS = ('k8s', 'kubernetes', 'pod', 'deployment', 'statefulset', 'daemonset', 'replicaset')
RCA_MAX_EVIDENCE_ITEMS = 12
RCA_MAX_SAMPLE_ITEMS = 5
RCA_TEXT_LIMIT = 180
RCA_EVIDENCE_SOURCE_ORDER = (
    'builtin.alert_snapshot',
    'builtin.metric_snapshot',
    'builtin.log_snapshot',
    'builtin.trace_snapshot',
    'builtin.k8s_snapshot',
    'builtin.event_timeline',
    'builtin.task_resource_scope',
)


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_text(value, limit=RCA_TEXT_LIMIT):
    text = ' '.join(str(value or '').split())
    return text[:limit]


def _iso_or_none(value):
    return value.isoformat() if value else None


def incident_scope(incident):
    return {
        'environment': incident.environment,
        'cluster': incident.cluster,
        'namespace': incident.namespace,
        'service': incident.service,
        'resource_type': incident.resource_type,
        'resource': incident.resource,
    }


def investigation_window(incident, minutes=60):
    started_at = incident.started_at or incident.detected_at or timezone.now()
    last_seen_at = incident.last_seen_at or started_at
    return started_at - timedelta(minutes=minutes), last_seen_at + timedelta(minutes=minutes)


def _investigation_audit_user():
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=INVESTIGATION_AUDIT_USERNAME,
        defaults={'is_active': False},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def _investigation_audit_session(incident):
    user = _investigation_audit_user()
    title = f'Incident #{incident.id} 自动调查'
    context = {
        'source': 'incident_background_investigation',
        'incident_id': incident.id,
        'environment': incident.environment,
        'cluster': incident.cluster,
        'namespace': incident.namespace,
        'service': incident.service,
        'resource_type': incident.resource_type,
        'resource': incident.resource,
    }
    session = (
        AIOpsChatSession.objects
        .filter(user=user, title=title, mirror_source__isnull=True)
        .order_by('id')
        .first()
    )
    if session:
        session.context = context
        session.last_message_at = timezone.now()
        session.save(update_fields=['context', 'last_message_at', 'updated_at'])
        return session
    return AIOpsChatSession.objects.create(user=user, title=title, context=context)


def _finish_tool_invocation(invocation, started_at, response_summary, success=True):
    invocation.status = AIOpsToolInvocation.STATUS_SUCCESS if success else AIOpsToolInvocation.STATUS_FAILED
    invocation.latency_ms = max(int((time.time() - started_at) * 1000), 1)
    invocation.response_summary = response_summary
    invocation.save(update_fields=['status', 'latency_ms', 'response_summary'])


def _collect_evidence_with_audit(incident, task, session, tool_name, collector):
    started_at = time.time()
    invocation = AIOpsToolInvocation.objects.create(
        session=session,
        tool_name=tool_name,
        request_payload={
            'incident_id': incident.id,
            'task_id': task.id if task else None,
            'scope': incident_scope(incident),
        },
    )
    try:
        evidence = collector(incident, task=task, tool_invocation=invocation)
    except Exception as exc:
        _finish_tool_invocation(invocation, started_at, {'error': str(exc)[:300]}, success=False)
        raise
    _finish_tool_invocation(
        invocation,
        started_at,
        {
            'evidence_id': evidence.id,
            'kind': evidence.kind,
            'source': evidence.source,
            'summary': evidence.summary,
        },
        success=True,
    )
    return evidence, invocation


def _alert_payload(alert):
    labels = _safe_dict(alert.labels)
    annotations = _safe_dict(alert.annotations)
    return {
        'id': alert.id,
        'title': alert.title,
        'level': alert.level,
        'status': alert.status,
        'source_type': alert.source_type,
        'fingerprint': alert.fingerprint,
        'group_key': alert.group_key,
        'service': alert.service,
        'environment': alert.environment,
        'cluster': alert.cluster,
        'namespace': alert.namespace,
        'resource_type': alert.resource_type,
        'resource': alert.resource,
        'metric_name': alert.metric_name,
        'message': alert.message,
        'labels': labels,
        'annotations': annotations,
        'starts_at': alert.starts_at.isoformat() if alert.starts_at else None,
        'ends_at': alert.ends_at.isoformat() if alert.ends_at else None,
        'last_received_at': alert.last_received_at.isoformat() if alert.last_received_at else None,
        'occurrence_count': alert.occurrence_count,
    }


def _alert_evidence_summary(incident, alert_links):
    active_count = sum(1 for link in alert_links if link.alert.status == Alert.STATUS_ACTIVE)
    primary_link = next((link for link in alert_links if link.role == 'primary'), alert_links[0] if alert_links else None)
    primary_title = primary_link.alert.title if primary_link else incident.title
    return f'关联 {len(alert_links)} 条告警，活跃 {active_count} 条；主信号：{primary_title}'


def collect_alert_evidence(incident, task=None, tool_invocation=None):
    alert_links = list(
        incident.alert_links
        .select_related('alert')
        .order_by('created_at', 'id')
    )
    window_start, window_end = investigation_window(incident)
    payload = {
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'status': incident.status,
            'severity': incident.severity,
            'dedupe_key': incident.dedupe_key,
            'active_alert_count': incident.active_alert_count,
            'alert_count': incident.alert_count,
        },
        'alerts': [
            {
                'role': link.role,
                'role_display': link.get_role_display(),
                'linked_reason': link.linked_reason,
                'alert': _alert_payload(link.alert),
            }
            for link in alert_links
        ],
    }
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_ALERT,
        source='builtin.alert_snapshot',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': _alert_evidence_summary(incident, alert_links),
            'payload': payload,
            'weight': AIOpsIncidentEvidence.WEIGHT_PRIMARY,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _event_matches_incident(incident, event):
    if event.correlation_id == f'aiops_incident:{incident.id}':
        return True
    if incident.service and (event.application == incident.service or event.business_line == incident.service):
        return True
    if incident.resource and event.resource_name == incident.resource:
        return True
    if incident.environment and not incident.service and not incident.resource:
        return event.environment == incident.environment
    return False


def collect_event_evidence(incident, task=None, tool_invocation=None, limit=20):
    window_start, window_end = investigation_window(incident)
    candidates = (
        EventRecord.objects
        .filter(occurred_at__gte=window_start, occurred_at__lte=window_end)
        .exclude(module='aiops', category='incident')
        .order_by('-occurred_at', '-id')[:100]
    )
    events = [event for event in candidates if _event_matches_incident(incident, event)][:limit]
    payload = {
        'events': [
            {
                'id': event.id,
                'module': event.module,
                'category': event.category,
                'action': event.action,
                'result': event.result,
                'severity': event.severity,
                'title': event.title,
                'summary': event.summary,
                'resource_type': event.resource_type,
                'resource_id': event.resource_id,
                'resource_name': event.resource_name,
                'environment': event.environment,
                'application': event.application,
                'occurred_at': event.occurred_at.isoformat() if event.occurred_at else None,
            }
            for event in events
        ],
    }
    summary = f'时间窗内匹配到 {len(events)} 条相关事件'
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_EVENT,
        source='builtin.event_timeline',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': AIOpsIncidentEvidence.WEIGHT_CONTEXT,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _norm(value):
    return str(value or '').strip().lower()


def _contains_either(left, right):
    left_text = _norm(left)
    right_text = _norm(right)
    return bool(left_text and right_text and (left_text in right_text or right_text in left_text))


def _metadata_value(resource, key):
    metadata = resource.metadata if isinstance(resource.metadata, dict) else {}
    return metadata.get(key) or ''


def _task_resource_broad_filter(incident):
    query = Q()
    if incident.environment:
        query |= Q(environment__name__icontains=incident.environment) | Q(environment__code__icontains=incident.environment)
    if incident.cluster:
        query |= (
            Q(cluster__name__icontains=incident.cluster)
            | Q(name__icontains=incident.cluster)
            | Q(description__icontains=incident.cluster)
            | Q(metadata__cluster__icontains=incident.cluster)
            | Q(metadata__cluster_name__icontains=incident.cluster)
        )
    if incident.namespace:
        query |= Q(namespace__icontains=incident.namespace)
    if incident.service:
        query |= (
            Q(system__name__icontains=incident.service)
            | Q(name__icontains=incident.service)
            | Q(description__icontains=incident.service)
            | Q(metadata__service__icontains=incident.service)
            | Q(metadata__role__icontains=incident.service)
        )
    if incident.resource:
        query |= Q(name__icontains=incident.resource) | Q(description__icontains=incident.resource) | Q(metadata__resource__icontains=incident.resource)
    return query


def _has_task_resource_scope(incident):
    return any([
        incident.environment,
        incident.cluster,
        incident.namespace,
        incident.service,
        incident.resource,
    ])


def _task_resource_match_score(resource, incident):
    score = 0
    if incident.environment and (
        _contains_either(incident.environment, resource.environment.name if resource.environment_id else '')
        or _contains_either(incident.environment, resource.environment.code if resource.environment_id else '')
    ):
        score += 2
    if incident.cluster and (
        _contains_either(incident.cluster, resource.cluster.name if resource.cluster_id else '')
        or _contains_either(incident.cluster, resource.name)
        or _contains_either(incident.cluster, resource.description)
        or _contains_either(incident.cluster, _metadata_value(resource, 'cluster'))
        or _contains_either(incident.cluster, _metadata_value(resource, 'cluster_name'))
    ):
        score += 8
    if incident.namespace and _contains_either(incident.namespace, resource.namespace):
        score += 4
    if incident.service and (
        _contains_either(incident.service, resource.name)
        or _contains_either(incident.service, resource.system.name if resource.system_id else '')
        or _contains_either(incident.service, resource.description)
        or _contains_either(incident.service, _metadata_value(resource, 'service'))
        or _contains_either(incident.service, _metadata_value(resource, 'role'))
    ):
        score += 6
    if incident.resource and (
        _contains_either(incident.resource, resource.name)
        or _contains_either(incident.resource, resource.description)
        or _contains_either(incident.resource, _metadata_value(resource, 'resource'))
    ):
        score += 8
    if resource.status == TaskResource.STATUS_WARNING:
        score += 1
    return score


def _format_task_resource(resource, score):
    metadata = resource.metadata if isinstance(resource.metadata, dict) else {}
    return {
        'id': resource.id,
        'name': resource.name,
        'resource_type': resource.resource_type,
        'resource_type_display': resource.get_resource_type_display(),
        'status': resource.status,
        'status_display': resource.get_status_display(),
        'environment': resource.environment.name if resource.environment_id else '',
        'system': resource.system.name if resource.system_id else '',
        'cluster': resource.cluster.name if resource.cluster_id else '',
        'namespace': resource.namespace,
        'ip_address': str(resource.ip_address or ''),
        'owner': resource.owner,
        'role': str(metadata.get('role') or ''),
        'match_score': score,
    }


def _cluster_inventory_for_resources(incident, resources):
    host_resources = [resource for resource in resources if resource.resource_type == TaskResource.RESOURCE_HOST]
    if not host_resources:
        return None
    roles = Counter(
        str(_metadata_value(resource, 'role') or 'node')
        for resource in host_resources
    )
    environment_names = [
        resource.environment.name
        for resource in host_resources
        if resource.environment_id and resource.environment.name
    ]
    cluster_name = incident.cluster or (environment_names[0] if environment_names else incident.environment)
    return {
        'cluster_count': 1 if cluster_name else 0,
        'cluster_name': cluster_name,
        'node_count': len(host_resources),
        'node_names': [resource.name for resource in host_resources],
        'roles': dict(roles),
        'source': 'task_resource_base',
        'resource_type': TaskResource.RESOURCE_HOST,
        'is_k8s': False,
    }


def collect_task_resource_evidence(incident, task=None, tool_invocation=None, limit=50):
    window_start, window_end = investigation_window(incident)
    scored = []
    if _has_task_resource_scope(incident):
        queryset = TaskResource.objects.select_related('environment', 'system', 'cluster').filter(_task_resource_broad_filter(incident))
        scored = [
            (resource, _task_resource_match_score(resource, incident))
            for resource in queryset.order_by('environment__sort_order', 'system__sort_order', 'resource_type', 'name', 'id')[:200]
        ]
    matched = [
        (resource, score)
        for resource, score in scored
        if score > 0
    ]
    matched.sort(key=lambda item: (-item[1], item[0].resource_type, item[0].name, item[0].id))
    matched = matched[:limit]
    resources = [resource for resource, _score in matched]
    cluster_inventory = _cluster_inventory_for_resources(incident, resources)
    payload = {
        'summary': {
            'count': len(resources),
            'resource_ids': [resource.id for resource in resources],
            'resource_type_counts': dict(Counter(resource.resource_type for resource in resources)),
            'status_counts': dict(Counter(resource.status for resource in resources)),
        },
        'resources': [
            _format_task_resource(resource, score)
            for resource, score in matched
        ],
        'cluster_inventory': cluster_inventory,
    }
    if cluster_inventory:
        summary = f"资源底座匹配 {len(resources)} 个执行资源；非 K8s 集群 {cluster_inventory['cluster_name']} 含 {cluster_inventory['node_count']} 个节点"
    elif resources:
        summary = f'资源底座匹配 {len(resources)} 个执行资源，可用于确认影响范围和执行目标'
    else:
        summary = '资源底座未匹配到当前 Incident 范围，后续处置前需补充或确认资源映射'
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_TOPOLOGY,
        source='builtin.task_resource_scope',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': AIOpsIncidentEvidence.WEIGHT_SUPPORTING if resources else AIOpsIncidentEvidence.WEIGHT_CONTEXT,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _primary_alert_for_metric_evidence(incident):
    primary_link = (
        incident.alert_links
        .select_related('alert')
        .filter(role='primary')
        .order_by('created_at', 'id')
        .first()
    )
    if primary_link:
        return primary_link.alert
    fallback_link = (
        incident.alert_links
        .select_related('alert')
        .order_by('created_at', 'id')
        .first()
    )
    return fallback_link.alert if fallback_link else None


def _select_incident_metric_datasource_id(incident):
    queryset = MetricDataSource.objects.filter(is_enabled=True)
    if incident.environment:
        datasource = queryset.filter(environment=incident.environment).order_by('-is_default', 'name').first()
        if datasource:
            return datasource.id
    datasource = queryset.filter(is_default=True).order_by('environment', 'name').first()
    if datasource:
        return datasource.id
    datasource = queryset.order_by('environment', '-is_default', 'name').first()
    return datasource.id if datasource else ''


def _metric_failure(plan_item, error):
    return {
        'name': plan_item.get('name'),
        'category': plan_item.get('category'),
        'intent': plan_item.get('intent'),
        'weight': plan_item.get('weight'),
        'promql': plan_item.get('promql'),
        'status': 'failed',
        'trend': 'unknown',
        'series_count': 0,
        'series': [],
        'error': str(error)[:240],
    }


def collect_metric_evidence(incident, task=None, tool_invocation=None, budget=2, step=60):
    alert = _primary_alert_for_metric_evidence(incident)
    window_start, window_end = investigation_window(incident)
    if not alert:
        payload = {
            'summary': {
                'alert_id': None,
                'planned_count': 0,
                'executed_count': 0,
                'abnormal_count': 0,
                'missing_count': 0,
                'failed_count': 0,
                'metric_datasource_id': '',
            },
            'plan': [],
            'evidence': [],
        }
        summary = '未找到关联告警，已跳过指标取证'
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    else:
        plan = metric_evidence.build_alert_metric_query_plan(alert, budget=budget)
        datasource_id = _select_incident_metric_datasource_id(incident)
        collected = []
        failures = []
        for item in plan:
            if not datasource_id:
                failure = _metric_failure(item, '未配置启用的指标数据源')
                collected.append(failure)
                failures.append(failure)
                continue
            try:
                payload = execute_promql_query(
                    item['promql'],
                    range_query=True,
                    start_time=window_start,
                    end_time=window_end,
                    step=step,
                    metric_datasource_id=datasource_id or '',
                    environment=incident.environment or alert.environment or '',
                    prefer_metric_datasource=True,
                )
                collected.append(metric_evidence.summarize_metric_query_result(item, payload))
            except Exception as exc:
                failure = _metric_failure(item, exc)
                collected.append(failure)
                failures.append(failure)
        abnormal_count = len([item for item in collected if item.get('status') == 'abnormal'])
        missing_count = len([item for item in collected if item.get('status') == 'missing'])
        failed_count = len(failures)
        payload = {
            'summary': {
                'alert_id': alert.id,
                'fingerprint': alert.fingerprint,
                'planned_count': len(plan),
                'executed_count': len(collected),
                'abnormal_count': abnormal_count,
                'missing_count': missing_count,
                'failed_count': failed_count,
                'metric_datasource_id': datasource_id or '',
                'step': step,
                'window': {'start': window_start.isoformat(), 'end': window_end.isoformat()},
            },
            'plan': plan,
            'evidence': collected,
        }
        summary = f'指标取证计划 {len(plan)} 项，执行 {len(collected)} 项，异常 {abnormal_count} 项，无数据 {missing_count} 项，失败 {failed_count} 项'
        weight = AIOpsIncidentEvidence.WEIGHT_SUPPORTING if collected else AIOpsIncidentEvidence.WEIGHT_CONTEXT
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_METRIC,
        source='builtin.metric_snapshot',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': weight,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _log_query_terms(incident):
    terms = []
    for value in [incident.service, incident.resource, incident.namespace, incident.cluster]:
        text = str(value or '').strip()
        if text and text not in terms:
            terms.append(text)
    return terms


def _log_label_value(value):
    return str(value or '').replace('\\', '\\\\').replace('"', '\\"')


def _log_query_for_provider(provider, incident):
    terms = _log_query_terms(incident)
    service = incident.service or incident.resource
    namespace = incident.namespace
    if provider == 'loki':
        labels = {}
        if namespace:
            labels['namespace'] = namespace
        selector = '{' + ','.join(f'{key}="{_log_label_value(value)}"' for key, value in labels.items()) + '}' if labels else '{job!=""}'
        return f'{selector} |~ "(?i)error|exception|timeout|failed|fatal|warn"'
    if provider == 'elk':
        clauses = []
        if service:
            clauses.append(f'(service:"{service}" OR service.name:"{service}" OR container:"{service}")')
        clauses.append('(level:"ERROR" OR level:"WARN" OR message:*error* OR message:*exception* OR message:*timeout* OR message:*failed*)')
        return ' AND '.join(clauses)
    if provider == 'sls':
        return ' AND '.join(terms + ['error OR exception OR timeout OR failed OR warn']) if terms else 'error OR exception OR timeout OR failed OR warn'
    return ' '.join(terms)


def _log_sample(item):
    attributes = item.get('attributes') if isinstance(item.get('attributes'), dict) else {}
    return {
        'timestamp': item.get('timestamp') or '',
        'level': item.get('level') or '',
        'source': item.get('source') or '',
        'message': str(item.get('message') or '')[:500],
        'datasource_id': item.get('datasource_id'),
        'datasource_name': item.get('datasource_name') or '',
        'trace_id': attributes.get('trace_id') or attributes.get('traceId') or '',
    }


def build_log_snapshot_payload(incident, limit=8, window_minutes=60):
    window_start, window_end = investigation_window(incident, minutes=window_minutes)
    start_ms = int(window_start.timestamp() * 1000)
    end_ms = int(window_end.timestamp() * 1000)
    datasources = list(LogDataSource.objects.filter(is_enabled=True).order_by('-is_default', 'provider', 'name')[:2])
    logs = []
    datasource_results = []
    errors = []
    for datasource in datasources:
        config = merge_log_config(datasource.provider, datasource.config)
        query = _log_query_for_provider(datasource.provider, incident)
        payload = {
            'provider': datasource.provider,
            'datasource_id': datasource.id,
            'start_ms': start_ms,
            'end_ms': end_ms,
            'limit': limit,
            'query': query,
        }
        if datasource.provider == 'elk':
            payload['source'] = config.get('index_pattern') or '*'
            payload['index_pattern'] = config.get('index_pattern') or '*'
            payload['time_field'] = config.get('time_field') or '@timestamp'
            payload['message_fields'] = config.get('message_fields') or 'message,log,msg'
        elif datasource.provider == 'sls':
            payload['source'] = config.get('logstore') or ''
            payload['logstore'] = config.get('logstore') or ''
        try:
            result = run_log_provider_query(datasource.provider, config, payload)
            datasource_results.append({
                'id': datasource.id,
                'name': datasource.name,
                'provider': datasource.provider,
                'query': query,
                'total': result.get('total', len(result.get('logs') or [])),
            })
            for item in result.get('logs') or []:
                enriched = dict(item)
                enriched['datasource_id'] = datasource.id
                enriched['datasource_name'] = datasource.name
                logs.append(enriched)
        except Exception as exc:
            errors.append({'datasource_id': datasource.id, 'name': datasource.name, 'provider': datasource.provider, 'error': str(exc)[:240]})
    logs.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
    logs = logs[:limit]
    level_counts = Counter(str(item.get('level') or 'unknown').lower() for item in logs)
    payload = {
        'summary': {
            'datasource_count': len(datasources),
            'queried_datasource_count': len(datasource_results),
            'log_count': len(logs),
            'error_count': sum(level_counts.get(level, 0) for level in ['error', 'fatal', 'critical']),
            'warning_count': sum(level_counts.get(level, 0) for level in ['warning', 'warn']),
            'failed_count': len(errors),
        },
        'datasources': datasource_results,
        'errors': errors,
        'logs': [_log_sample(item) for item in logs],
    }
    return payload, window_start, window_end


def collect_log_evidence(incident, task=None, tool_invocation=None, limit=8):
    payload, window_start, window_end = build_log_snapshot_payload(incident, limit=limit)
    summary_payload = payload['summary']
    if summary_payload['datasource_count'] == 0:
        summary = '未配置启用的日志数据源，已跳过日志取证'
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    elif summary_payload['log_count']:
        summary = f"日志取证命中 {summary_payload['log_count']} 条日志，ERROR {summary_payload['error_count']} 条，WARNING {summary_payload['warning_count']} 条"
        weight = AIOpsIncidentEvidence.WEIGHT_SUPPORTING
    else:
        summary = f"日志取证未命中日志，查询数据源 {summary_payload['queried_datasource_count']} 个，失败 {summary_payload['failed_count']} 个"
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_LOG,
        source='builtin.log_snapshot',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': weight,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _select_tracing_datasource():
    queryset = TracingDataSource.objects.filter(is_enabled=True)
    return (
        queryset.filter(is_default=True).order_by('id').first()
        or queryset.order_by('id').first()
    )


def _trace_sample(trace):
    return {
        'trace_id': trace.get('trace_id') or '',
        'service_name': trace.get('service_name') or '',
        'instance_name': trace.get('instance_name') or '',
        'endpoint_names': trace.get('endpoint_names') or [],
        'duration_ms': trace.get('duration_ms') or 0,
        'start': trace.get('start') or '',
        'state': trace.get('state') or ('ERROR' if trace.get('is_error') else 'SUCCESS'),
        'is_error': bool(trace.get('is_error')),
        'summary': trace.get('summary') or '',
    }


def collect_trace_evidence(incident, task=None, tool_invocation=None, limit=5):
    window_start, window_end = investigation_window(incident)
    datasource = _select_tracing_datasource()
    service_name = str(incident.service or '').strip()
    if not datasource:
        payload = {
            'summary': {
                'datasource_found': False,
                'service_matched': False,
                'match_count': 0,
                'error_match_count': 0,
                'error': '',
            },
            'tracing': None,
            'query': {'service': service_name, 'trace_state': 'ERROR', 'limit': limit},
            'traces': [],
        }
        summary = '未配置启用的 Trace 数据源，已跳过链路取证'
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    elif not service_name:
        payload = {
            'summary': {
                'datasource_found': True,
                'datasource_id': datasource.id,
                'datasource_name': datasource.name,
                'provider': datasource.provider,
                'service_matched': False,
                'match_count': 0,
                'error_match_count': 0,
                'error': '',
            },
            'tracing': None,
            'query': {'service': '', 'trace_state': 'ERROR', 'limit': limit},
            'traces': [],
        }
        summary = 'Incident 未包含明确服务名，已跳过链路取证'
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    else:
        provider = datasource.provider
        datasource_id = str(datasource.id)
        error = ''
        try:
            result = search_tracing({
                'provider': provider,
                'datasource_id': datasource_id,
                'service_name': service_name,
                'trace_state': 'ERROR',
                'duration_minutes': 120,
                'limit': limit,
            })
            service = result.get('matched_service')
            traces = result.get('traces') or []
            tracing_meta = result.get('tracing') or {}
            result_summary = result.get('summary') or {}
        except Exception as exc:
            service = None
            traces = []
            tracing_meta = {
                'provider': provider,
                'datasource_id': datasource_id,
                'datasource_name': datasource.name,
            }
            result_summary = {}
            error = str(exc)[:240]
        match_count = _safe_int(result_summary.get('match_count'), len(traces))
        error_match_count = _safe_int(result_summary.get('error_match_count'), len([item for item in traces if item.get('is_error')]))
        payload = {
            'summary': {
                'datasource_found': True,
                'datasource_id': datasource.id,
                'datasource_name': datasource.name,
                'provider': provider,
                'service_matched': bool(service),
                'service_id': service.get('id') if service else '',
                'service_name': service.get('name') if service else service_name,
                'match_count': match_count,
                'error_match_count': error_match_count,
                'error': error,
            },
            'tracing': tracing_meta,
            'query': {
                'service': service_name,
                'service_id': service.get('id') if service else '',
                'trace_state': 'ERROR',
                'limit': limit,
                'duration_minutes': 120,
            },
            'traces': [_trace_sample(item) for item in traces[:limit]],
        }
        if error:
            summary = f'Trace 取证失败：{error}'
            weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
        elif not service:
            summary = f'Trace 取证未匹配到服务 {service_name}'
            weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
        elif traces:
            summary = f"Trace 取证命中 {match_count} 条异常链路，错误 {error_match_count} 条"
            weight = AIOpsIncidentEvidence.WEIGHT_SUPPORTING
        else:
            summary = f'Trace 取证未命中 {service_name} 的异常链路'
            weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_TRACE,
        source='builtin.trace_snapshot',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': weight,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _incident_has_k8s_scope(incident):
    resource_type = str(incident.resource_type or '').strip().lower()
    if resource_type in K8S_RESOURCE_TYPES:
        return True
    text = ' '.join([
        str(incident.cluster or ''),
        str(incident.resource_type or ''),
        str(incident.resource or ''),
        str(incident.service or ''),
    ]).lower()
    if any(keyword in text for keyword in K8S_SCOPE_KEYWORDS):
        return True
    return bool(incident.cluster and K8sCluster.objects.filter(name__iexact=incident.cluster).exists())


def _select_incident_k8s_cluster(incident):
    queryset = K8sCluster.objects.all()
    if incident.cluster:
        cluster = queryset.filter(name__iexact=incident.cluster).first()
        if cluster:
            return cluster
        cluster_name = str(incident.cluster or '').lower()
        if any(keyword in cluster_name for keyword in ('k8s', 'kubernetes')):
            cluster = queryset.filter(name__icontains=incident.cluster).order_by('-updated_at', '-id').first()
            if cluster:
                return cluster
    return None


def _pod_sample(pod):
    return {
        'name': pod.get('name') or '',
        'namespace': pod.get('namespace') or '',
        'status': pod.get('status') or '',
        'node': pod.get('node') or '',
        'restarts': pod.get('restarts') or 0,
        'containers': pod.get('containers') or [],
    }


def _dedupe_named_items(items):
    seen = set()
    result = []
    for item in items:
        key = (item.get('namespace') or '', item.get('name') or '')
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _workload_degraded(item):
    replicas = item.get('replicas')
    ready = item.get('ready_replicas', item.get('ready'))
    desired = item.get('desired')
    if replicas is not None:
        try:
            return int(ready or 0) < int(replicas or 0)
        except (TypeError, ValueError):
            return False
    if desired is not None:
        try:
            return int(ready or 0) < int(desired or 0)
        except (TypeError, ValueError):
            return False
    return False


def _workload_sample(item, workload_type):
    return {
        'name': item.get('name') or '',
        'namespace': item.get('namespace') or '',
        'workload_type': workload_type,
        'replicas': item.get('replicas'),
        'ready_replicas': item.get('ready_replicas', item.get('ready')),
        'available_replicas': item.get('available_replicas'),
    }


def build_k8s_snapshot_payload(incident, limit=8, window_minutes=60):
    window_start, window_end = investigation_window(incident, minutes=window_minutes)
    cluster = _select_incident_k8s_cluster(incident) if _incident_has_k8s_scope(incident) else None
    if not cluster:
        payload = {
            'summary': {
                'cluster_found': False,
                'pods_total': 0,
                'pods_abnormal': 0,
                'pods_restarting': 0,
                'workloads_degraded': 0,
                'error': '',
            },
            'cluster': None,
            'pods': [],
            'workloads': [],
        }
    else:
        from ops.k8s_views import get_k8s_pods_snapshot, get_k8s_resource_snapshot, get_k8s_summary_snapshot

        namespaces = [incident.namespace] if incident.namespace else None
        error = ''
        try:
            cluster_summary = get_k8s_summary_snapshot(cluster)
            pods = get_k8s_pods_snapshot(cluster, namespaces)
            workloads = []
            for workload_type in ['deployments', 'statefulsets', 'daemonsets']:
                workloads.extend(
                    _workload_sample(item, workload_type)
                    for item in get_k8s_resource_snapshot(cluster, workload_type, namespaces)
                    if _workload_degraded(item)
                )
        except Exception as exc:
            cluster_summary = {'cluster_name': cluster.name, 'status': cluster.status}
            pods = []
            workloads = []
            error = str(exc)[:240]
        abnormal_pods = [pod for pod in pods if str(pod.get('status') or '') not in {'Running', 'Succeeded'}]
        restarting_pods = [pod for pod in pods if int(pod.get('restarts', 0) or 0) > 0]
        pod_samples = _dedupe_named_items(abnormal_pods + restarting_pods + pods)
        payload = {
            'summary': {
                'cluster_found': True,
                'cluster_id': cluster.id,
                'cluster_name': cluster.name,
                'namespaces': namespaces or [],
                'pods_total': len(pods),
                'pods_abnormal': len(abnormal_pods),
                'pods_restarting': len(restarting_pods),
                'workloads_degraded': len(workloads),
                'error': error,
            },
            'cluster': cluster_summary,
            'pods': [_pod_sample(pod) for pod in pod_samples[:limit]],
            'workloads': workloads[:limit],
        }
    return payload, window_start, window_end


def collect_k8s_evidence(incident, task=None, tool_invocation=None, limit=8):
    payload, window_start, window_end = build_k8s_snapshot_payload(incident, limit=limit)
    summary_payload = payload['summary']
    if not summary_payload['cluster_found']:
        summary = 'Incident 未匹配到 K8s 集群范围，已跳过 K8s 运行态取证'
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    elif summary_payload['error']:
        summary = f"K8s 运行态取证失败：{summary_payload['error']}"
        weight = AIOpsIncidentEvidence.WEIGHT_CONTEXT
    else:
        summary = (
            f"K8s 运行态：Pod {summary_payload['pods_total']} 个，异常 {summary_payload['pods_abnormal']} 个，"
            f"重启 {summary_payload['pods_restarting']} 个，降级工作负载 {summary_payload['workloads_degraded']} 个"
        )
        weight = (
            AIOpsIncidentEvidence.WEIGHT_SUPPORTING
            if (
                summary_payload['pods_abnormal']
                or summary_payload['pods_restarting']
                or summary_payload['workloads_degraded']
            )
            else AIOpsIncidentEvidence.WEIGHT_CONTEXT
        )
    evidence, _ = AIOpsIncidentEvidence.objects.update_or_create(
        incident=incident,
        kind=AIOpsIncidentEvidence.KIND_K8S,
        source='builtin.k8s_snapshot',
        defaults={
            'source_task': task,
            'tool_invocation': tool_invocation,
            'scope': incident_scope(incident),
            'window_start': window_start,
            'window_end': window_end,
            'summary': summary,
            'payload': payload,
            'weight': weight,
            'collected_at': timezone.now(),
        },
    )
    return evidence


def _evidence_by_source(incident):
    return {
        evidence.source: evidence
        for evidence in incident.evidence_items.all()
    }


def _rca_alert_facts(payload):
    alerts = payload.get('alerts') if isinstance(payload.get('alerts'), list) else []
    active = []
    active_count = 0
    primary = None
    for item in alerts:
        if not isinstance(item, dict):
            continue
        alert = item.get('alert') if isinstance(item.get('alert'), dict) else {}
        fact = {
            'id': alert.get('id'),
            'role': item.get('role') or '',
            'title': _short_text(alert.get('title')),
            'level': alert.get('level') or '',
            'status': alert.get('status') or '',
            'metric_name': alert.get('metric_name') or '',
            'starts_at': alert.get('starts_at'),
            'resource': alert.get('resource') or '',
        }
        if item.get('role') == 'primary' and primary is None:
            primary = fact
        if fact['status'] == Alert.STATUS_ACTIVE:
            active_count += 1
            if len(active) < RCA_MAX_SAMPLE_ITEMS:
                active.append(fact)
    return {
        'alert_count': len(alerts),
        'active_alert_count': active_count,
        'primary_alert': primary,
        'active_alerts': active,
    }


def _rca_metric_facts(payload):
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    evidence = payload.get('evidence') if isinstance(payload.get('evidence'), list) else []
    samples = []
    for item in evidence[:RCA_MAX_SAMPLE_ITEMS]:
        if not isinstance(item, dict):
            continue
        samples.append({
            'name': _short_text(item.get('name'), 80),
            'category': item.get('category') or '',
            'intent': _short_text(item.get('intent')),
            'status': item.get('status') or '',
            'trend': item.get('trend') or '',
            'series_count': _safe_int(item.get('series_count')),
            'error': _short_text(item.get('error')),
        })
    return {
        'planned_count': _safe_int(summary.get('planned_count')),
        'executed_count': _safe_int(summary.get('executed_count')),
        'abnormal_count': _safe_int(summary.get('abnormal_count')),
        'missing_count': _safe_int(summary.get('missing_count')),
        'failed_count': _safe_int(summary.get('failed_count')),
        'metric_datasource_id': summary.get('metric_datasource_id') or '',
        'samples': samples,
    }


def _rca_log_facts(payload):
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    logs = payload.get('logs') if isinstance(payload.get('logs'), list) else []
    return {
        'datasource_count': _safe_int(summary.get('datasource_count')),
        'queried_datasource_count': _safe_int(summary.get('queried_datasource_count')),
        'log_count': _safe_int(summary.get('log_count')),
        'error_count': _safe_int(summary.get('error_count')),
        'warning_count': _safe_int(summary.get('warning_count')),
        'failed_count': _safe_int(summary.get('failed_count')),
        'samples': [
            {
                'timestamp': item.get('timestamp') or '',
                'level': item.get('level') or '',
                'source': item.get('source') or '',
                'message': _short_text(item.get('message')),
                'trace_id': item.get('trace_id') or '',
            }
            for item in logs[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
    }


def _rca_trace_facts(payload):
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    traces = payload.get('traces') if isinstance(payload.get('traces'), list) else []
    return {
        'datasource_found': bool(summary.get('datasource_found')),
        'service_matched': bool(summary.get('service_matched')),
        'service_name': summary.get('service_name') or '',
        'match_count': _safe_int(summary.get('match_count')),
        'error_match_count': _safe_int(summary.get('error_match_count')),
        'error': _short_text(summary.get('error')),
        'samples': [
            {
                'trace_id': item.get('trace_id') or '',
                'service_name': item.get('service_name') or '',
                'duration_ms': _safe_int(item.get('duration_ms')),
                'state': item.get('state') or '',
                'is_error': bool(item.get('is_error')),
                'summary': _short_text(item.get('summary')),
            }
            for item in traces[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
    }


def _rca_k8s_facts(payload):
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    pods = payload.get('pods') if isinstance(payload.get('pods'), list) else []
    workloads = payload.get('workloads') if isinstance(payload.get('workloads'), list) else []
    return {
        'cluster_found': bool(summary.get('cluster_found')),
        'cluster_name': summary.get('cluster_name') or '',
        'namespaces': summary.get('namespaces') if isinstance(summary.get('namespaces'), list) else [],
        'pods_total': _safe_int(summary.get('pods_total')),
        'pods_abnormal': _safe_int(summary.get('pods_abnormal')),
        'pods_restarting': _safe_int(summary.get('pods_restarting')),
        'workloads_degraded': _safe_int(summary.get('workloads_degraded')),
        'error': _short_text(summary.get('error')),
        'pod_samples': [
            {
                'name': item.get('name') or '',
                'namespace': item.get('namespace') or '',
                'status': item.get('status') or '',
                'node': item.get('node') or '',
                'restarts': _safe_int(item.get('restarts')),
            }
            for item in pods[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
        'workload_samples': [
            {
                'name': item.get('name') or '',
                'namespace': item.get('namespace') or '',
                'workload_type': item.get('workload_type') or '',
                'replicas': item.get('replicas'),
                'ready_replicas': item.get('ready_replicas'),
            }
            for item in workloads[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
    }


def _rca_event_facts(payload):
    events = payload.get('events') if isinstance(payload.get('events'), list) else []
    return {
        'event_count': len(events),
        'samples': [
            {
                'id': item.get('id'),
                'module': item.get('module') or '',
                'category': item.get('category') or '',
                'action': item.get('action') or '',
                'result': item.get('result') or '',
                'title': _short_text(item.get('title')),
                'occurred_at': item.get('occurred_at'),
            }
            for item in events[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
    }


def _rca_cluster_inventory(inventory):
    if not isinstance(inventory, dict):
        return None
    node_names = inventory.get('node_names') if isinstance(inventory.get('node_names'), list) else []
    return {
        'cluster_count': _safe_int(inventory.get('cluster_count')),
        'cluster_name': inventory.get('cluster_name') or '',
        'node_count': _safe_int(inventory.get('node_count')),
        'node_name_samples': node_names[:RCA_MAX_SAMPLE_ITEMS],
        'roles': inventory.get('roles') if isinstance(inventory.get('roles'), dict) else {},
        'source': inventory.get('source') or '',
        'resource_type': inventory.get('resource_type') or '',
        'is_k8s': bool(inventory.get('is_k8s')),
    }


def _rca_topology_facts(payload):
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    inventory = payload.get('cluster_inventory') if isinstance(payload.get('cluster_inventory'), dict) else None
    resources = payload.get('resources') if isinstance(payload.get('resources'), list) else []
    return {
        'resource_count': _safe_int(summary.get('count')),
        'resource_type_counts': summary.get('resource_type_counts') if isinstance(summary.get('resource_type_counts'), dict) else {},
        'status_counts': summary.get('status_counts') if isinstance(summary.get('status_counts'), dict) else {},
        'cluster_inventory': _rca_cluster_inventory(inventory),
        'samples': [
            {
                'id': item.get('id'),
                'name': item.get('name') or '',
                'resource_type': item.get('resource_type') or '',
                'status': item.get('status') or '',
                'environment': item.get('environment') or '',
                'cluster': item.get('cluster') or '',
                'namespace': item.get('namespace') or '',
                'role': item.get('role') or '',
                'match_score': _safe_int(item.get('match_score')),
            }
            for item in resources[:RCA_MAX_SAMPLE_ITEMS]
            if isinstance(item, dict)
        ],
    }


def _rca_key_facts(evidence):
    payload = evidence.payload if isinstance(evidence.payload, dict) else {}
    if evidence.kind == AIOpsIncidentEvidence.KIND_ALERT:
        return _rca_alert_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_METRIC:
        return _rca_metric_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_LOG:
        return _rca_log_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_TRACE:
        return _rca_trace_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_K8S:
        return _rca_k8s_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_EVENT:
        return _rca_event_facts(payload)
    if evidence.kind == AIOpsIncidentEvidence.KIND_TOPOLOGY:
        return _rca_topology_facts(payload)
    return {}


def _rca_evidence_item(evidence):
    return {
        'id': evidence.id,
        'kind': evidence.kind,
        'kind_display': evidence.get_kind_display(),
        'source': evidence.source,
        'summary': _short_text(evidence.summary, 260),
        'weight': evidence.weight,
        'window_start': _iso_or_none(evidence.window_start),
        'window_end': _iso_or_none(evidence.window_end),
        'collected_at': _iso_or_none(evidence.collected_at),
        'tool_invocation_id': evidence.tool_invocation_id,
        'key_facts': _rca_key_facts(evidence),
    }


def build_rca_evidence_package(incident, evidence_items=None, hypothesis=None):
    if evidence_items is None:
        incident = AIOpsIncident.objects.prefetch_related('evidence_items').get(id=incident.id)
        evidence_items = list(incident.evidence_items.all())
    source_rank = {source: index for index, source in enumerate(RCA_EVIDENCE_SOURCE_ORDER)}
    ordered = sorted(
        evidence_items,
        key=lambda item: (source_rank.get(item.source, len(source_rank)), item.id),
    )[:RCA_MAX_EVIDENCE_ITEMS]
    package = {
        'version': '1.0',
        'generated_at': timezone.now().isoformat(),
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'status': incident.status,
            'severity': incident.severity,
            'source_type': incident.source_type,
            'environment': incident.environment,
            'cluster': incident.cluster,
            'namespace': incident.namespace,
            'service': incident.service,
            'resource_type': incident.resource_type,
            'resource': incident.resource,
            'alert_count': incident.alert_count,
            'active_alert_count': incident.active_alert_count,
            'started_at': _iso_or_none(incident.started_at),
            'last_seen_at': _iso_or_none(incident.last_seen_at),
        },
        'evidence': [_rca_evidence_item(item) for item in ordered],
        'policy': {
            'scope': 'current_incident_only',
            'max_evidence_items': RCA_MAX_EVIDENCE_ITEMS,
            'max_sample_items_per_evidence': RCA_MAX_SAMPLE_ITEMS,
            'require_supporting_evidence_ids': True,
            'forbid_unobserved_facts': True,
            'use_missing_evidence_when_uncertain': True,
        },
    }
    if hypothesis:
        package['hypothesis'] = {
            'id': hypothesis.id,
            'title': hypothesis.title,
            'root_cause_type': hypothesis.root_cause_type,
            'confidence': float(hypothesis.confidence),
            'supporting_evidence_ids': hypothesis.supporting_evidence_ids,
            'counter_evidence_ids': hypothesis.counter_evidence_ids,
            'missing_evidence': hypothesis.missing_evidence,
        }
    return package


def build_verification_observation(incident, log_limit=5, window_minutes=30):
    window_start, window_end = investigation_window(incident, minutes=window_minutes)
    observation = {
        'generated_at': timezone.now().isoformat(),
        'window': {
            'start': _iso_or_none(window_start),
            'end': _iso_or_none(window_end),
        },
        'scope': incident_scope(incident),
        'alerts': {
            'alert_count': incident.alert_count,
            'active_alert_count': incident.active_alert_count,
        },
    }
    log_payload, _log_start, _log_end = build_log_snapshot_payload(incident, limit=log_limit, window_minutes=window_minutes)
    observation['logs'] = _rca_log_facts(log_payload)
    k8s_payload, _k8s_start, _k8s_end = build_k8s_snapshot_payload(incident, window_minutes=window_minutes)
    observation['k8s'] = _rca_k8s_facts(k8s_payload)
    return observation


def _evidence_ids(*items):
    return [item.id for item in items if item]


def _event_count(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    events = payload.get('events') if isinstance(payload.get('events'), list) else []
    return len(events)


def _alert_count(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    alerts = payload.get('alerts') if isinstance(payload.get('alerts'), list) else []
    return len(alerts)


def _task_resource_count(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    try:
        return int(summary.get('count') or 0)
    except (TypeError, ValueError):
        return 0


def _metric_summary(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    def _int_value(key):
        try:
            return int(summary.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return {
        'planned_count': _int_value('planned_count'),
        'executed_count': _int_value('executed_count'),
        'abnormal_count': _int_value('abnormal_count'),
        'missing_count': _int_value('missing_count'),
        'failed_count': _int_value('failed_count'),
    }


def _log_summary(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    def _int_value(key):
        try:
            return int(summary.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return {
        'datasource_count': _int_value('datasource_count'),
        'log_count': _int_value('log_count'),
        'error_count': _int_value('error_count'),
        'warning_count': _int_value('warning_count'),
        'failed_count': _int_value('failed_count'),
    }


def _trace_summary(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    return {
        'datasource_found': bool(summary.get('datasource_found')),
        'service_matched': bool(summary.get('service_matched')),
        'match_count': _safe_int(summary.get('match_count')),
        'error_match_count': _safe_int(summary.get('error_match_count')),
        'error': str(summary.get('error') or ''),
    }


def _k8s_summary(evidence):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
    def _int_value(key):
        try:
            return int(summary.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return {
        'cluster_found': bool(summary.get('cluster_found')),
        'pods_total': _int_value('pods_total'),
        'pods_abnormal': _int_value('pods_abnormal'),
        'pods_restarting': _int_value('pods_restarting'),
        'workloads_degraded': _int_value('workloads_degraded'),
        'error': str(summary.get('error') or ''),
    }


def _primary_alert_title(evidence, incident):
    payload = evidence.payload if evidence and isinstance(evidence.payload, dict) else {}
    alerts = payload.get('alerts') if isinstance(payload.get('alerts'), list) else []
    for item in alerts:
        if not isinstance(item, dict) or item.get('role') != 'primary':
            continue
        alert = item.get('alert') if isinstance(item.get('alert'), dict) else {}
        return str(alert.get('title') or '').strip()
    return incident.title


def _recommended_next_checks(incident, event_count, resource_count=None):
    checks = [
        '补查同时间窗指标走势，确认告警是否伴随资源或业务指标异常。',
        '补查错误日志或慢调用样本，确认直接错误模式。',
    ]
    if incident.cluster or incident.namespace:
        checks.append('补查 K8s Pod、Workload 和 Event 状态。')
    if event_count == 0:
        checks.append('补查发布、工单和任务中心记录，确认是否存在未接入的变更。')
    if resource_count == 0:
        checks.append('补充资源底座映射，确认告警对象对应的主机、K8s 或中间件节点。')
    return checks


def generate_root_cause_hypothesis(incident, task=None):
    incident = AIOpsIncident.objects.prefetch_related('evidence_items').get(id=incident.id)
    evidence = _evidence_by_source(incident)
    alert_evidence = evidence.get('builtin.alert_snapshot')
    event_evidence = evidence.get('builtin.event_timeline')
    resource_evidence = evidence.get('builtin.task_resource_scope')
    metric_evidence_item = evidence.get('builtin.metric_snapshot')
    log_evidence = evidence.get('builtin.log_snapshot')
    trace_evidence = evidence.get('builtin.trace_snapshot')
    k8s_evidence = evidence.get('builtin.k8s_snapshot')
    event_count = _event_count(event_evidence)
    alert_count = _alert_count(alert_evidence)
    resource_count = _task_resource_count(resource_evidence)
    metric_summary = _metric_summary(metric_evidence_item)
    log_summary = _log_summary(log_evidence)
    trace_summary = _trace_summary(trace_evidence)
    k8s_summary = _k8s_summary(k8s_evidence)
    if event_count:
        root_cause_type = AIOpsIncidentHypothesis.TYPE_CHANGE_REGRESSION
        title = f'{incident.service or incident.title} 可能受近期事件或变更影响'
        summary = f'Incident 时间窗内存在 {event_count} 条相关事件，需要结合告警、日志和变更内容验证是否为直接诱因。'
        confidence = 0.62 if alert_count else 0.48
        supporting_ids = _evidence_ids(alert_evidence, event_evidence, metric_evidence_item, log_evidence, trace_evidence, k8s_evidence, resource_evidence)
        missing = ['缺少事件详情与异常指标之间的直接因果证据。']
    elif alert_count:
        root_cause_type = AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM
        primary_alert = _primary_alert_title(alert_evidence, incident)
        title = f'{incident.service or incident.resource or incident.title} 出现 {primary_alert} 告警症状'
        summary = f'当前主要证据来自 {alert_count} 条关联告警，尚不足以判定底层根因。'
        has_runtime_signal = any([log_summary['error_count'], trace_summary['error_match_count'], k8s_summary['pods_abnormal'], k8s_summary['workloads_degraded']])
        confidence = 0.6 if has_runtime_signal else (0.55 if metric_summary['abnormal_count'] else 0.45)
        supporting_ids = _evidence_ids(alert_evidence, metric_evidence_item, log_evidence, trace_evidence, k8s_evidence, resource_evidence)
        missing = ['缺少变更证据，暂不能确认根因类型。']
    else:
        root_cause_type = AIOpsIncidentHypothesis.TYPE_UNKNOWN
        title = f'{incident.title} 根因待确认'
        summary = '当前 Incident 尚缺少可用证据，只能保持未知根因。'
        confidence = 0.2
        supporting_ids = _evidence_ids(metric_evidence_item, log_evidence, trace_evidence, k8s_evidence, resource_evidence)
        missing = ['缺少告警、指标、日志、Trace、K8s 和变更证据。']
    if metric_summary['planned_count'] == 0:
        missing.append('未生成可执行指标查询计划，需补充告警指标名或服务/资源标签。')
    elif metric_summary['executed_count'] == 0:
        missing.append('指标查询未执行成功，需确认 Prometheus 或指标数据源配置。')
    elif metric_summary['missing_count'] or metric_summary['failed_count']:
        missing.append('部分指标无数据或查询失败，需确认指标标签、PromQL 和数据源状态。')
    if log_summary['datasource_count'] == 0:
        missing.append('未配置启用的日志数据源，无法确认错误日志模式。')
    elif log_summary['log_count'] == 0:
        missing.append('日志查询未命中样本，需放宽服务、namespace 或时间窗口。')
    elif log_summary['failed_count']:
        missing.append('部分日志数据源查询失败，需确认日志接入配置。')
    if not trace_summary['datasource_found']:
        missing.append('未配置启用的 Trace 数据源，无法确认调用链错误或慢调用。')
    elif trace_summary['error']:
        missing.append('Trace 查询失败，需确认链路数据源配置。')
    elif incident.service and not trace_summary['service_matched']:
        missing.append('Trace 数据源未匹配到 Incident 服务，需确认服务命名映射。')
    elif incident.service and trace_summary['match_count'] == 0:
        missing.append('Trace 查询未命中异常链路，需结合日志或放宽时间窗口。')
    if _incident_has_k8s_scope(incident):
        if not k8s_summary['cluster_found']:
            missing.append('Incident 包含 K8s 范围，但未匹配到 K8s 集群配置。')
        elif k8s_summary['error']:
            missing.append('K8s 运行态查询失败，需检查 kubeconfig 或集群连接。')
        elif k8s_summary['pods_total'] == 0:
            missing.append('K8s 查询未返回 Pod，需确认 namespace 或资源名称。')
    if resource_count == 0:
        missing.append('缺少当前 Incident 范围的资源底座映射，影响后续执行目标确认。')
    recommended = _recommended_next_checks(incident, event_count, resource_count)
    AIOpsIncidentHypothesis.objects.filter(
        incident=incident,
        status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        generated_by='rule_based',
    ).exclude(root_cause_type=root_cause_type).update(status=AIOpsIncidentHypothesis.STATUS_REJECTED)
    hypothesis, _ = AIOpsIncidentHypothesis.objects.update_or_create(
        incident=incident,
        status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        generated_by='rule_based',
        defaults={
            'title': title[:256],
            'root_cause_type': root_cause_type,
            'confidence': confidence,
            'supporting_evidence_ids': supporting_ids,
            'counter_evidence_ids': [],
            'missing_evidence': missing,
            'recommended_next_checks': recommended,
            'summary': summary,
            'source_task': task,
            'generated_at': timezone.now(),
        },
    )
    return hypothesis


def generate_remediation_proposals(incident, hypothesis):
    next_checks = hypothesis.recommended_next_checks if isinstance(hypothesis.recommended_next_checks, list) else []
    if not next_checks:
        next_checks = _recommended_next_checks(incident, 0)
    payload = {
        'mode': 'readonly_followup',
        'incident_id': incident.id,
        'hypothesis_id': hypothesis.id,
        'recommended_checks': next_checks,
        'target_scope': incident_scope(incident),
    }
    defaults = {
        'title': f'补充 {incident.service or incident.title} 只读证据',
        'risk_level': AIOpsIncidentAction.RISK_READ_ONLY,
        'action_payload': payload,
        'preconditions': ['仅允许调用只读查询工具，不执行变更、重启、扩缩容或命令。'],
        'rollback_plan': ['只读动作无需回滚；若查询失败，只记录失败原因并保留现有 Incident 状态。'],
        'verification_plan': next_checks,
        'created_by': INVESTIGATION_SOURCE_AGENT,
    }
    existing = AIOpsIncidentAction.objects.filter(
        incident=incident,
        hypothesis=hypothesis,
        action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
    ).first()
    reusable_statuses = {
        AIOpsIncidentAction.STATUS_PROPOSED,
        AIOpsIncidentAction.STATUS_FAILED,
        AIOpsIncidentAction.STATUS_CANCELED,
    }
    if existing and existing.status not in reusable_statuses:
        return [existing]
    if not existing or existing.status in {AIOpsIncidentAction.STATUS_FAILED, AIOpsIncidentAction.STATUS_CANCELED}:
        defaults.update({
            'status': AIOpsIncidentAction.STATUS_PROPOSED,
            'verification_status': '',
            'result_summary': '',
        })
    proposal, _ = AIOpsIncidentAction.objects.update_or_create(
        incident=incident,
        hypothesis=hypothesis,
        action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
        defaults=defaults,
    )
    return [proposal]


def create_investigation_task(incident, reason='alert_changed'):
    payload = {
        'incident_id': incident.id,
        'reason': reason,
        'environment': incident.environment,
        'cluster': incident.cluster,
        'namespace': incident.namespace,
        'service': incident.service,
        'severity': incident.severity,
        'dedupe_key': incident.dedupe_key,
    }
    now = timezone.now()
    return AIOpsExternalTask.objects.create(
        source_agent=INVESTIGATION_SOURCE_AGENT,
        title=f'Incident #{incident.id} 只读调查',
        action_code=INVESTIGATION_ACTION_CODE,
        agent_mode='readonly',
        status=AIOpsExternalTask.STATUS_RUNNING,
        input_payload=payload,
        plan_steps=[
            {'tool': 'builtin.alert_snapshot', 'title': '采集关联告警快照', 'risk_level': 'read_only', 'status': 'running'},
            {'tool': 'builtin.metric_snapshot', 'title': '采集指标趋势快照', 'risk_level': 'read_only', 'status': 'pending'},
            {'tool': 'builtin.log_snapshot', 'title': '采集错误日志快照', 'risk_level': 'read_only', 'status': 'pending'},
            {'tool': 'builtin.trace_snapshot', 'title': '采集调用链错误快照', 'risk_level': 'read_only', 'status': 'pending'},
            {'tool': 'builtin.k8s_snapshot', 'title': '采集 K8s 运行态快照', 'risk_level': 'read_only', 'status': 'pending'},
            {'tool': 'builtin.event_timeline', 'title': '采集相关事件时间线', 'risk_level': 'read_only', 'status': 'pending'},
            {'tool': 'builtin.task_resource_scope', 'title': '采集资源底座范围', 'risk_level': 'read_only', 'status': 'pending'},
        ],
        orchestration_state={
            'version': '1.0',
            'mode': 'readonly',
            'started_at': now.isoformat(),
            'incident_id': incident.id,
            'scope': incident_scope(incident),
        },
    )


def _mark_investigation_task_failed(task, error):
    task.status = AIOpsExternalTask.STATUS_FAILED
    task.error_message = str(error)[:255]
    task.result_payload = {
        'mode': 'incident_readonly_investigation',
        'incident_id': task.input_payload.get('incident_id') if isinstance(task.input_payload, dict) else None,
        'error': str(error),
    }
    task.save(update_fields=['status', 'error_message', 'result_payload', 'updated_at'])
    return task


def _mark_incident_investigating(incident, task, reason):
    metadata = incident.metadata if isinstance(incident.metadata, dict) else {}
    now = timezone.now()
    metadata['last_investigation'] = {
        'task_id': task.id,
        'reason': reason,
        'status': AIOpsExternalTask.STATUS_RUNNING,
        'started_at': now.isoformat(),
    }
    update_fields = ['metadata', 'updated_at']
    if incident.status == AIOpsIncident.STATUS_OPEN:
        incident.status = AIOpsIncident.STATUS_INVESTIGATING
        update_fields.append('status')
    incident.metadata = metadata
    incident.save(update_fields=update_fields)


def _mark_incident_investigation_finished(incident, task, status, error=''):
    fresh = AIOpsIncident.objects.get(id=incident.id)
    metadata = fresh.metadata if isinstance(fresh.metadata, dict) else {}
    last = metadata.get('last_investigation') if isinstance(metadata.get('last_investigation'), dict) else {}
    if last.get('task_id') != task.id:
        last = {'task_id': task.id}
    last.update({
        'status': status,
        'completed_at': timezone.now().isoformat(),
    })
    if error:
        last['error'] = str(error)[:240]
    metadata['last_investigation'] = last
    fresh.metadata = metadata
    fresh.save(update_fields=['metadata', 'updated_at'])


def _run_readonly_investigation_internal(incident, reason='alert_changed'):
    incident = AIOpsIncident.objects.get(id=incident.id)
    task = create_investigation_task(incident, reason=reason)
    _mark_incident_investigating(incident, task, reason)
    audit_session = _investigation_audit_session(incident)
    try:
        alert_evidence, alert_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.alert_snapshot',
            collect_alert_evidence,
        )
        metric_evidence_item, metric_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.metric_snapshot',
            collect_metric_evidence,
        )
        log_evidence, log_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.log_snapshot',
            collect_log_evidence,
        )
        trace_evidence, trace_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.trace_snapshot',
            collect_trace_evidence,
        )
        k8s_evidence, k8s_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.k8s_snapshot',
            collect_k8s_evidence,
        )
        event_evidence, event_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.event_timeline',
            collect_event_evidence,
        )
        resource_evidence, resource_invocation = _collect_evidence_with_audit(
            incident,
            task,
            audit_session,
            'builtin.task_resource_scope',
            collect_task_resource_evidence,
        )
    except Exception as exc:
        _mark_investigation_task_failed(task, exc)
        _mark_incident_investigation_finished(incident, task, AIOpsExternalTask.STATUS_FAILED, error=exc)
        raise
    evidence_items = [alert_evidence, metric_evidence_item, log_evidence, trace_evidence, k8s_evidence, event_evidence, resource_evidence]
    tool_invocation_ids = [
        alert_invocation.id,
        metric_invocation.id,
        log_invocation.id,
        trace_invocation.id,
        k8s_invocation.id,
        event_invocation.id,
        resource_invocation.id,
    ]
    hypothesis = generate_root_cause_hypothesis(incident, task=task)
    rca_evidence_package = build_rca_evidence_package(incident, evidence_items=evidence_items, hypothesis=hypothesis)
    proposals = generate_remediation_proposals(incident, hypothesis)
    now = timezone.now()
    task.status = AIOpsExternalTask.STATUS_COMPLETED
    task.completed_at = now
    task.plan_steps = [
        {**step, 'status': 'completed', 'completed_at': now.isoformat()}
        for step in task.plan_steps
    ]
    task.orchestration_state = {
        **(task.orchestration_state or {}),
        'completed_at': now.isoformat(),
        'evidence_count': len(evidence_items),
        'audit_session_id': audit_session.id,
        'tool_invocation_ids': tool_invocation_ids,
        'rca_input': rca_evidence_package,
    }
    task.agent_results = [
        {
            'agent': 'incident_readonly_investigator',
            'agent_name': 'Incident 只读调查',
            'status': 'completed',
            'observations': [item.summary for item in evidence_items] + [hypothesis.summary],
            'confidence': 'medium',
        }
    ]
    task.react_trace = [
        {'phase': 'collect_alerts', 'status': 'completed', 'evidence_id': evidence_items[0].id, 'tool_invocation_id': alert_invocation.id},
        {'phase': 'collect_metrics', 'status': 'completed', 'evidence_id': evidence_items[1].id, 'tool_invocation_id': metric_invocation.id},
        {'phase': 'collect_logs', 'status': 'completed', 'evidence_id': evidence_items[2].id, 'tool_invocation_id': log_invocation.id},
        {'phase': 'collect_traces', 'status': 'completed', 'evidence_id': evidence_items[3].id, 'tool_invocation_id': trace_invocation.id},
        {'phase': 'collect_k8s', 'status': 'completed', 'evidence_id': evidence_items[4].id, 'tool_invocation_id': k8s_invocation.id},
        {'phase': 'collect_events', 'status': 'completed', 'evidence_id': evidence_items[5].id, 'tool_invocation_id': event_invocation.id},
        {'phase': 'collect_task_resources', 'status': 'completed', 'evidence_id': evidence_items[6].id, 'tool_invocation_id': resource_invocation.id},
        {'phase': 'terminate', 'status': 'completed', 'stop_condition': '只读证据快照已刷新'},
    ]
    task.result_payload = {
        'mode': 'incident_readonly_investigation',
        'incident_id': incident.id,
        'evidence_ids': [item.id for item in evidence_items],
        'tool_invocation_ids': tool_invocation_ids,
        'hypothesis_id': hypothesis.id,
        'rca_input_version': rca_evidence_package['version'],
        'proposal_ids': [item.id for item in proposals],
        'summary': '已刷新 Incident 只读调查证据、主根因假设和只读处置建议。',
    }
    task.save(update_fields=[
        'status',
        'completed_at',
        'plan_steps',
        'orchestration_state',
        'agent_results',
        'react_trace',
        'result_payload',
        'updated_at',
    ])
    record_event(
        module='aiops',
        category='incident',
        action='investigate_incident',
        title='Incident 只读调查',
        summary=f'Incident #{incident.id} 已刷新 {len(evidence_items)} 条只读证据、1 条主根因假设和 {len(proposals)} 条建议',
        resource_type='aiops_incident',
        resource_id=incident.id,
        resource_name=incident.title,
        environment=incident.environment,
        application=incident.service,
        severity=EventRecord.SEVERITY_INFO,
        correlation_id=f'aiops_incident:{incident.id}',
        metadata={
            'task_id': task.id,
            'evidence_ids': [item.id for item in evidence_items],
            'tool_invocation_ids': tool_invocation_ids,
            'hypothesis_id': hypothesis.id,
            'proposal_ids': [item.id for item in proposals],
            'reason': reason,
        },
    )
    _mark_incident_investigation_finished(incident, task, AIOpsExternalTask.STATUS_COMPLETED)
    return task


def run_readonly_investigation(incident, reason='alert_changed'):
    return _run_readonly_investigation_internal(incident, reason=reason)


def schedule_readonly_investigation(incident, reason='alert_changed'):
    incident_id = incident.id

    def _run():
        try:
            fresh_incident = AIOpsIncident.objects.get(id=incident_id)
            run_readonly_investigation(fresh_incident, reason=reason)
        except Exception:
            logger.exception('Failed to run readonly investigation for incident %s', incident_id)

    transaction.on_commit(_run)
