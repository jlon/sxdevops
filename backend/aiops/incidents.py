from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from eventwall.models import EventRecord
from eventwall.services import record_event
from ops.models import Alert

from .models import AIOpsExternalTask, AIOpsIncident, AIOpsIncidentAlert


ACTIVE_INCIDENT_STATUSES = [
    AIOpsIncident.STATUS_OPEN,
    AIOpsIncident.STATUS_INVESTIGATING,
    AIOpsIncident.STATUS_MITIGATING,
    AIOpsIncident.STATUS_VERIFYING,
]
SEVERITY_RANK = {
    AIOpsIncident.SEVERITY_INFO: 1,
    AIOpsIncident.SEVERITY_WARNING: 2,
    AIOpsIncident.SEVERITY_CRITICAL: 3,
}
INVESTIGATION_REFRESH_MINUTES = 10
INVESTIGATION_IN_FLIGHT_STATUSES = {
    AIOpsExternalTask.STATUS_QUEUED,
    AIOpsExternalTask.STATUS_RUNNING,
}


def build_incident_dedupe_key(alert):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    alert_name = labels.get('alertname') or alert.metric_name or alert.title
    if alert.group_key:
        return f'group:{alert.source_type}:{alert.group_key}'
    if alert.fingerprint:
        return f'fingerprint:{alert.source_type}:{alert.fingerprint}'
    parts = [
        alert.source_type,
        alert.environment,
        alert.cluster,
        alert.namespace,
        alert.service,
        alert.resource_type,
        alert.resource,
        alert_name,
    ]
    return 'scope:' + ':'.join(str(item or '-').strip() for item in parts)


def _incident_title(alert):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    alert_name = labels.get('alertname') or alert.metric_name or alert.title
    scope = alert.service or alert.resource or alert.namespace or alert.cluster or alert.environment
    if scope and alert_name and str(alert_name) not in str(scope):
        return f'{scope} / {alert_name}'
    return alert.title or str(alert_name or '告警事件')


def _alert_scope_value(alert, field):
    value = getattr(alert, field, '') or ''
    if value:
        return value
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    return str(labels.get(field) or '').strip()


def _incident_summary(alert):
    scope = ' / '.join(item for item in [
        _alert_scope_value(alert, 'environment'),
        _alert_scope_value(alert, 'cluster'),
        _alert_scope_value(alert, 'namespace'),
        _alert_scope_value(alert, 'service'),
        _alert_scope_value(alert, 'resource'),
    ] if item)
    message = (alert.message or '').strip()
    if scope and message:
        return f'{scope}: {message[:200]}'
    if scope:
        return scope
    return message[:200]


def _max_severity(current, candidate):
    current_rank = SEVERITY_RANK.get(current or AIOpsIncident.SEVERITY_INFO, 1)
    candidate_rank = SEVERITY_RANK.get(candidate or AIOpsIncident.SEVERITY_INFO, 1)
    return candidate if candidate_rank > current_rank else current


def _refresh_incident_counts(incident):
    aggregate = incident.alert_links.aggregate(
        alert_count=Count('alert', distinct=True),
        active_alert_count=Count(
            'alert',
            filter=Q(alert__status=Alert.STATUS_ACTIVE),
            distinct=True,
        ),
    )
    incident.alert_count = aggregate.get('alert_count') or 0
    incident.active_alert_count = aggregate.get('active_alert_count') or 0
    if incident.active_alert_count == 0 and incident.status in ACTIVE_INCIDENT_STATUSES:
        incident.status = AIOpsIncident.STATUS_RESOLVED
        incident.resolved_at = timezone.now()
    elif incident.active_alert_count > 0 and incident.status == AIOpsIncident.STATUS_RESOLVED:
        incident.status = AIOpsIncident.STATUS_OPEN
        incident.resolved_at = None
    incident.save(update_fields=['alert_count', 'active_alert_count', 'status', 'resolved_at', 'updated_at'])


def _record_incident_event(incident, alert, action, created=False):
    severity = EventRecord.SEVERITY_DANGER if incident.severity == AIOpsIncident.SEVERITY_CRITICAL else EventRecord.SEVERITY_WARNING
    record_event(
        module='aiops',
        category='incident',
        action=action,
        title='Incident 自动归并' if not created else 'Incident 自动创建',
        summary=f'告警 {alert.title} 已关联到 Incident #{incident.id}',
        resource_type='aiops_incident',
        resource_id=incident.id,
        resource_name=incident.title,
        business_line=incident.service,
        environment=incident.environment,
        application=incident.service,
        severity=severity,
        correlation_id=f'aiops_incident:{incident.id}',
        related_resources=[
            {'module': 'ops', 'type': 'alert', 'id': str(alert.id), 'name': alert.title},
        ],
        metadata={
            'alert_id': alert.id,
            'dedupe_key': incident.dedupe_key,
            'status': incident.status,
            'severity': incident.severity,
        },
    )


def _metadata_datetime(value):
    if not value:
        return None
    if hasattr(value, 'isoformat'):
        return value
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _last_investigation_metadata(incident):
    metadata = incident.metadata if isinstance(incident.metadata, dict) else {}
    last = metadata.get('last_investigation') if isinstance(metadata.get('last_investigation'), dict) else {}
    return last


def _recent_investigation_finished(last, now):
    completed_at = _metadata_datetime(last.get('completed_at'))
    if not completed_at:
        return False
    return completed_at >= now - timedelta(minutes=INVESTIGATION_REFRESH_MINUTES)


def _should_schedule_investigation(incident, reason):
    if not reason or incident.status in {AIOpsIncident.STATUS_RESOLVED, AIOpsIncident.STATUS_CLOSED}:
        return False
    last = _last_investigation_metadata(incident)
    if last.get('status') in INVESTIGATION_IN_FLIGHT_STATUSES:
        return False
    if reason in {'incident_created', 'incident_reopened', 'severity_upgraded'}:
        return True
    return not _recent_investigation_finished(last, timezone.now())


def _investigation_reason(created, link_created, role_changed, status_changed, severity_upgraded, incident_status):
    if created and incident_status != AIOpsIncident.STATUS_RESOLVED:
        return 'incident_created'
    if status_changed and incident_status in ACTIVE_INCIDENT_STATUSES:
        return 'incident_reopened'
    if severity_upgraded:
        return 'severity_upgraded'
    if role_changed:
        return 'alert_role_changed'
    if link_created:
        return 'alert_linked'
    return ''


@transaction.atomic
def upsert_incident_for_alert(alert, schedule_investigation=True):
    dedupe_key = build_incident_dedupe_key(alert)
    incident = (
        AIOpsIncident.objects
        .select_for_update()
        .filter(dedupe_key=dedupe_key, status__in=ACTIVE_INCIDENT_STATUSES + [AIOpsIncident.STATUS_RESOLVED])
        .order_by('-last_seen_at', '-id')
        .first()
    )
    created = incident is None
    started_at = alert.starts_at or alert.last_received_at or timezone.now()
    last_seen_at = alert.last_received_at or timezone.now()
    previous_severity = ''
    if created:
        incident = AIOpsIncident.objects.create(
            title=_incident_title(alert),
            status=AIOpsIncident.STATUS_RESOLVED if alert.status == Alert.STATUS_RESOLVED else AIOpsIncident.STATUS_OPEN,
            severity=alert.level or AIOpsIncident.SEVERITY_INFO,
            source_type=AIOpsIncident.SOURCE_ALERT,
            dedupe_key=dedupe_key,
            environment=_alert_scope_value(alert, 'environment'),
            cluster=_alert_scope_value(alert, 'cluster'),
            namespace=_alert_scope_value(alert, 'namespace'),
            service=_alert_scope_value(alert, 'service'),
            resource_type=_alert_scope_value(alert, 'resource_type'),
            resource=_alert_scope_value(alert, 'resource'),
            impact_summary=_incident_summary(alert),
            started_at=started_at,
            last_seen_at=last_seen_at,
            resolved_at=last_seen_at if alert.status == Alert.STATUS_RESOLVED else None,
            metadata={'primary_alert_id': alert.id, 'source_type': alert.source_type},
        )
    else:
        previous_severity = incident.severity
        incident.severity = _max_severity(incident.severity, alert.level)
        incident.last_seen_at = max(incident.last_seen_at or last_seen_at, last_seen_at)
        if not incident.started_at or started_at < incident.started_at:
            incident.started_at = started_at
        for field in ['environment', 'cluster', 'namespace', 'service', 'resource_type', 'resource']:
            if not getattr(incident, field):
                setattr(incident, field, _alert_scope_value(alert, field))
        if not incident.impact_summary:
            incident.impact_summary = _incident_summary(alert)
        metadata = incident.metadata if isinstance(incident.metadata, dict) else {}
        metadata.setdefault('primary_alert_id', alert.id)
        metadata['last_alert_id'] = alert.id
        incident.metadata = metadata
        incident.save(update_fields=[
            'severity',
            'last_seen_at',
            'started_at',
            'environment',
            'cluster',
            'namespace',
            'service',
            'resource_type',
            'resource',
            'impact_summary',
            'metadata',
            'updated_at',
        ])

    initial_role = AIOpsIncidentAlert.ROLE_PRIMARY if created else (
        AIOpsIncidentAlert.ROLE_RESOLVED_SIGNAL if alert.status == Alert.STATUS_RESOLVED else AIOpsIncidentAlert.ROLE_RELATED
    )
    link, link_created = AIOpsIncidentAlert.objects.get_or_create(
        incident=incident,
        alert=alert,
        defaults={'role': initial_role, 'linked_reason': '按告警指纹或分组键自动归并'},
    )
    role_changed = False
    desired_role = link.role
    if not link_created and alert.status == Alert.STATUS_RESOLVED:
        desired_role = AIOpsIncidentAlert.ROLE_RESOLVED_SIGNAL
    elif not link_created and link.role == AIOpsIncidentAlert.ROLE_RESOLVED_SIGNAL and alert.status == Alert.STATUS_ACTIVE:
        desired_role = AIOpsIncidentAlert.ROLE_RELATED
    if not link_created and link.role != desired_role:
        link.role = desired_role
        link.linked_reason = '按告警指纹或分组键自动归并'
        link.save(update_fields=['role', 'linked_reason', 'updated_at'])
        role_changed = True
    previous_status = incident.status
    _refresh_incident_counts(incident)
    incident.refresh_from_db()
    status_changed = incident.status != previous_status
    severity_upgraded = (
        not created
        and SEVERITY_RANK.get(incident.severity or AIOpsIncident.SEVERITY_INFO, 1)
        > SEVERITY_RANK.get(previous_severity or AIOpsIncident.SEVERITY_INFO, 1)
    )
    if status_changed:
        action = 'resolve_incident' if incident.status == AIOpsIncident.STATUS_RESOLVED else 'reopen_incident'
        _record_incident_event(incident, alert, action, created=False)
    elif created or link_created or role_changed:
        _record_incident_event(incident, alert, 'create_incident' if created else 'link_alert', created=created)
    reason = _investigation_reason(
        created,
        link_created,
        role_changed,
        status_changed,
        severity_upgraded,
        incident.status,
    )
    if reason and schedule_investigation and _should_schedule_investigation(incident, reason):
        from .incident_investigation import schedule_readonly_investigation

        schedule_readonly_investigation(incident, reason=reason)
    return incident, created


@transaction.atomic
def link_alert_to_incident(alert, incident, role='', reason='', schedule_investigation=True, record_lifecycle_event=True):
    incident = AIOpsIncident.objects.select_for_update().get(id=incident.id)
    role = role or (
        AIOpsIncidentAlert.ROLE_RESOLVED_SIGNAL
        if alert.status == Alert.STATUS_RESOLVED
        else AIOpsIncidentAlert.ROLE_RELATED
    )
    valid_roles = {value for value, _ in AIOpsIncidentAlert.ROLE_CHOICES}
    if role not in valid_roles:
        role = AIOpsIncidentAlert.ROLE_RELATED
    link_reason = (reason or '手动关联告警到 Incident')[:255]
    link, created = AIOpsIncidentAlert.objects.get_or_create(
        incident=incident,
        alert=alert,
        defaults={'role': role, 'linked_reason': link_reason},
    )
    role_changed = False
    if not created and (link.role != role or link.linked_reason != link_reason):
        link.role = role
        link.linked_reason = link_reason
        link.save(update_fields=['role', 'linked_reason', 'updated_at'])
        role_changed = True

    previous_status = incident.status
    incident.severity = _max_severity(incident.severity, alert.level)
    incident.last_seen_at = max(incident.last_seen_at or timezone.now(), alert.last_received_at or timezone.now())
    alert_started_at = alert.starts_at or alert.last_received_at or timezone.now()
    if not incident.started_at or alert_started_at < incident.started_at:
        incident.started_at = alert_started_at
    update_fields = ['severity', 'last_seen_at', 'started_at', 'updated_at']
    for field in ['environment', 'cluster', 'namespace', 'service', 'resource_type', 'resource']:
        if not getattr(incident, field):
            setattr(incident, field, _alert_scope_value(alert, field))
            update_fields.append(field)
    metadata = incident.metadata if isinstance(incident.metadata, dict) else {}
    metadata['last_manual_alert_id'] = alert.id
    incident.metadata = metadata
    update_fields.append('metadata')
    incident.save(update_fields=list(dict.fromkeys(update_fields)))

    _refresh_incident_counts(incident)
    incident.refresh_from_db()
    status_changed = incident.status != previous_status
    if record_lifecycle_event and (created or role_changed or status_changed):
        action = 'link_alert' if not status_changed else (
            'resolve_incident' if incident.status == AIOpsIncident.STATUS_RESOLVED else 'reopen_incident'
        )
        _record_incident_event(incident, alert, action, created=False)
    should_refresh_investigation = (
        schedule_investigation
        and (created or role_changed or status_changed)
        and _should_schedule_investigation(incident, 'manual_alert_linked')
    )
    if should_refresh_investigation:
        from .incident_investigation import schedule_readonly_investigation

        schedule_readonly_investigation(incident, reason='manual_alert_linked')
    return incident, link, created
