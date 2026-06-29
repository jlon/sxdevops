import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from eventwall.models import EventRecord
from eventwall.services import record_event
from ops.models import Alert

from .models import AIOpsExternalTask, AIOpsIncident, AIOpsIncidentEvidence


logger = logging.getLogger(__name__)
INVESTIGATION_ACTION_CODE = 'incident.investigate'
INVESTIGATION_SOURCE_AGENT = 'sxdevops-incident-intake'


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


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


def collect_alert_evidence(incident, task=None):
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


def collect_event_evidence(incident, task=None, limit=20):
    window_start, window_end = investigation_window(incident)
    candidates = (
        EventRecord.objects
        .filter(occurred_at__gte=window_start, occurred_at__lte=window_end)
        .exclude(module='aiops', category='incident', action='investigate_incident')
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
            {'tool': 'builtin.event_timeline', 'title': '采集相关事件时间线', 'risk_level': 'read_only', 'status': 'pending'},
        ],
        orchestration_state={
            'version': '1.0',
            'mode': 'readonly',
            'started_at': now.isoformat(),
            'incident_id': incident.id,
            'scope': incident_scope(incident),
        },
    )


@transaction.atomic
def _run_readonly_investigation_atomic(incident, reason='alert_changed'):
    incident = AIOpsIncident.objects.select_for_update().get(id=incident.id)
    task = create_investigation_task(incident, reason=reason)
    evidence_items = [
        collect_alert_evidence(incident, task=task),
        collect_event_evidence(incident, task=task),
    ]
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
    }
    task.agent_results = [
        {
            'agent': 'incident_readonly_investigator',
            'agent_name': 'Incident 只读调查',
            'status': 'completed',
            'observations': [item.summary for item in evidence_items],
            'confidence': 'medium',
        }
    ]
    task.react_trace = [
        {'phase': 'collect_alerts', 'status': 'completed', 'evidence_id': evidence_items[0].id},
        {'phase': 'collect_events', 'status': 'completed', 'evidence_id': evidence_items[1].id},
        {'phase': 'terminate', 'status': 'completed', 'stop_condition': '只读证据快照已刷新'},
    ]
    task.result_payload = {
        'mode': 'incident_readonly_investigation',
        'incident_id': incident.id,
        'evidence_ids': [item.id for item in evidence_items],
        'summary': '已刷新 Incident 只读调查证据。',
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
        summary=f'Incident #{incident.id} 已刷新 {len(evidence_items)} 条只读证据',
        resource_type='aiops_incident',
        resource_id=incident.id,
        resource_name=incident.title,
        environment=incident.environment,
        application=incident.service,
        severity=EventRecord.SEVERITY_INFO,
        correlation_id=f'aiops_incident:{incident.id}',
        metadata={'task_id': task.id, 'evidence_ids': [item.id for item in evidence_items], 'reason': reason},
    )
    return task


def _record_failed_investigation_task(incident, reason, error):
    incident = AIOpsIncident.objects.get(id=incident.id)
    task = create_investigation_task(incident, reason=reason)
    task.status = AIOpsExternalTask.STATUS_FAILED
    task.error_message = str(error)[:255]
    task.result_payload = {'mode': 'incident_readonly_investigation', 'incident_id': incident.id, 'error': str(error)}
    task.save(update_fields=['status', 'error_message', 'result_payload', 'updated_at'])
    return task


def run_readonly_investigation(incident, reason='alert_changed'):
    try:
        return _run_readonly_investigation_atomic(incident, reason=reason)
    except Exception as exc:
        _record_failed_investigation_task(incident, reason, exc)
        raise


def schedule_readonly_investigation(incident, reason='alert_changed'):
    incident_id = incident.id

    def _run():
        try:
            fresh_incident = AIOpsIncident.objects.get(id=incident_id)
            run_readonly_investigation(fresh_incident, reason=reason)
        except Exception:
            logger.exception('Failed to run readonly investigation for incident %s', incident_id)

    transaction.on_commit(_run)
