from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsExternalTask, AIOpsIncident, AIOpsIncidentAlert, AIOpsIncidentEvidence, AIOpsIncidentHypothesis
from eventwall.models import EventRecord
from ops.models import Alert, AlertIntegration
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class IncidentAlertIntakeTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.integration = AlertIntegration.objects.create(
            name='Prometheus',
            provider=Alert.SOURCE_PROMETHEUS,
            default_labels={'environment': 'prod'},
        )
        self.client = APIClient()

    def post_alertmanager(self, alerts, group_key='service=order'):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
                {
                    'status': 'firing',
                    'groupKey': group_key,
                    'commonLabels': {'service': 'order-center', 'namespace': 'production'},
                    'alerts': alerts,
                },
                format='json',
            )

    def test_webhook_creates_incident_for_prometheus_alert(self):
        response = self.post_alertmanager([
            {
                'status': 'firing',
                'fingerprint': 'fp-incident-001',
                'labels': {
                    'alertname': 'HighErrorRate',
                    'severity': 'critical',
                    'cluster': 'dev-k8s-cluster',
                    'pod': 'order-api-0',
                },
                'annotations': {'summary': 'Order error rate high', 'description': '5xx ratio above threshold'},
                'startsAt': '2026-05-04T10:00:00+08:00',
            },
        ])

        self.assertEqual(response.status_code, 202, response.data)
        alert = Alert.objects.get()
        incident = AIOpsIncident.objects.get()
        self.assertEqual(incident.status, AIOpsIncident.STATUS_OPEN)
        self.assertEqual(incident.severity, AIOpsIncident.SEVERITY_CRITICAL)
        self.assertEqual(incident.environment, 'prod')
        self.assertEqual(incident.cluster, 'dev-k8s-cluster')
        self.assertEqual(incident.namespace, 'production')
        self.assertEqual(incident.service, 'order-center')
        self.assertEqual(incident.alert_count, 1)
        self.assertEqual(incident.active_alert_count, 1)
        link = AIOpsIncidentAlert.objects.get(incident=incident, alert=alert)
        self.assertEqual(link.role, AIOpsIncidentAlert.ROLE_PRIMARY)
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 2)
        self.assertTrue(AIOpsIncidentEvidence.objects.filter(incident=incident, source='builtin.alert_snapshot').exists())
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertEqual(task.status, AIOpsExternalTask.STATUS_COMPLETED)
        self.assertEqual(task.input_payload['incident_id'], incident.id)
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertEqual(hypothesis.root_cause_type, AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM)
        self.assertTrue(hypothesis.supporting_evidence_ids)
        self.assertIn('指标', ''.join(hypothesis.recommended_next_checks))

    def test_same_group_key_reuses_active_incident(self):
        first = self.post_alertmanager([
            {
                'status': 'firing',
                'fingerprint': 'fp-incident-101',
                'labels': {'alertname': 'HighErrorRate', 'severity': 'warning'},
                'annotations': {'summary': 'Order warning'},
            },
        ], group_key='service=order-center')
        second = self.post_alertmanager([
            {
                'status': 'firing',
                'fingerprint': 'fp-incident-102',
                'labels': {'alertname': 'HighLatency', 'severity': 'critical'},
                'annotations': {'summary': 'Order latency high'},
            },
        ], group_key='service=order-center')

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 202, second.data)
        incident = AIOpsIncident.objects.get()
        self.assertEqual(incident.alert_count, 2)
        self.assertEqual(incident.active_alert_count, 2)
        self.assertEqual(incident.severity, AIOpsIncident.SEVERITY_CRITICAL)
        self.assertEqual(AIOpsIncidentAlert.objects.filter(incident=incident).count(), 2)
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 2)
        self.assertEqual(AIOpsExternalTask.objects.filter(action_code='incident.investigate').count(), 2)
        alert_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.alert_snapshot')
        self.assertEqual(len(alert_evidence.payload['alerts']), 2)
        self.assertEqual(AIOpsIncidentHypothesis.objects.filter(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY).count(), 1)

    def test_repeated_same_alert_does_not_duplicate_incident_events(self):
        payload = [{
            'status': 'firing',
            'fingerprint': 'fp-incident-repeat',
            'labels': {'alertname': 'HighErrorRate', 'severity': 'warning'},
            'annotations': {'summary': 'Order warning'},
        }]

        first = self.post_alertmanager(payload, group_key='service=order-center')
        second = self.post_alertmanager(payload, group_key='service=order-center')

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 202, second.data)
        incident = AIOpsIncident.objects.get()
        self.assertEqual(AIOpsIncidentAlert.objects.filter(incident=incident).count(), 1)
        lifecycle_events = EventRecord.objects.filter(module='aiops', category='incident').exclude(action='investigate_incident')
        self.assertEqual(lifecycle_events.count(), 1)
        self.assertEqual(AIOpsExternalTask.objects.filter(action_code='incident.investigate').count(), 1)
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 2)
        self.assertEqual(AIOpsIncidentHypothesis.objects.filter(incident=incident).count(), 1)

    def test_resolved_signal_marks_incident_resolved_when_no_active_alerts(self):
        firing = self.post_alertmanager([
            {
                'status': 'firing',
                'fingerprint': 'fp-incident-resolve',
                'labels': {'alertname': 'HighErrorRate', 'severity': 'critical'},
                'annotations': {'summary': 'Order error rate high'},
            },
        ])
        with self.captureOnCommitCallbacks(execute=True):
            resolved = self.client.post(
                f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
                {
                    'status': 'resolved',
                    'groupKey': 'service=order',
                    'commonLabels': {'service': 'order-center'},
                    'alerts': [{
                        'status': 'resolved',
                        'fingerprint': 'fp-incident-resolve',
                        'labels': {'alertname': 'HighErrorRate', 'severity': 'critical'},
                        'annotations': {'summary': 'Order error rate recovered'},
                        'endsAt': '2026-05-04T10:30:00+08:00',
                    }],
                },
                format='json',
            )

        self.assertEqual(firing.status_code, 202, firing.data)
        self.assertEqual(resolved.status_code, 202, resolved.data)
        incident = AIOpsIncident.objects.get()
        self.assertEqual(incident.status, AIOpsIncident.STATUS_RESOLVED)
        self.assertEqual(incident.active_alert_count, 0)
        self.assertIsNotNone(incident.resolved_at)


class IncidentApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='incident-admin', password='Passw0rd!123')
        self.user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.incident = AIOpsIncident.objects.create(
            title='order-center / HighErrorRate',
            status=AIOpsIncident.STATUS_OPEN,
            severity=AIOpsIncident.SEVERITY_CRITICAL,
            dedupe_key='group:prometheus:service=order',
            environment='prod',
            service='order-center',
            alert_count=1,
            active_alert_count=1,
        )

    def test_incident_list_supports_filters(self):
        response = self.client.get('/api/aiops/incidents/', {'environment': 'prod', 'only_open': '1'})

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data['results'] if isinstance(response.data, dict) and 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'order-center / HighErrorRate')
        self.assertEqual(results[0]['active_alert_count'], 1)

    def test_close_incident_updates_status_and_owner(self):
        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/close/')

        self.assertEqual(response.status_code, 200, response.data)
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, AIOpsIncident.STATUS_CLOSED)
        self.assertEqual(self.incident.owner, 'incident-admin')
        self.assertIsNotNone(self.incident.closed_at)

    def test_incident_detail_includes_evidence(self):
        AIOpsIncidentEvidence.objects.create(
            incident=self.incident,
            kind=AIOpsIncidentEvidence.KIND_ALERT,
            source='builtin.alert_snapshot',
            summary='关联 1 条告警，活跃 1 条；主信号：HighErrorRate',
            payload={'alerts': [{'id': 1}]},
            weight=AIOpsIncidentEvidence.WEIGHT_PRIMARY,
        )

        response = self.client.get(f'/api/aiops/incidents/{self.incident.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['evidence_items']), 1)
        self.assertEqual(response.data['evidence_items'][0]['source'], 'builtin.alert_snapshot')
        self.assertEqual(response.data['evidence_items'][0]['kind_display'], '告警证据')

    def test_incident_detail_includes_hypotheses(self):
        AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 出现 HighErrorRate 告警症状',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM,
            confidence=0.45,
            supporting_evidence_ids=[1],
            missing_evidence=['缺少日志证据'],
            recommended_next_checks=['补查错误日志'],
            summary='当前主要证据来自告警。',
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )

        response = self.client.get(f'/api/aiops/incidents/{self.incident.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['hypotheses']), 1)
        self.assertEqual(response.data['hypotheses'][0]['status'], AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertEqual(response.data['hypotheses'][0]['root_cause_type_display'], '告警症状')
