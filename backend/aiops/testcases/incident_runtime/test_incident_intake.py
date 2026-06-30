from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.incident_investigation import run_readonly_investigation
from aiops.conversation_context import build_session_memory_snapshot
from aiops.models import (
    AIOpsChatSession,
    AIOpsExternalTask,
    AIOpsIncident,
    AIOpsIncidentAction,
    AIOpsIncidentAlert,
    AIOpsIncidentEvidence,
    AIOpsIncidentHypothesis,
    AIOpsPendingAction,
    AIOpsReviewKnowledge,
    AIOpsRunbook,
    AIOpsSkill,
)
from aiops.services import sync_incident_action_verification_for_task, sync_session_to_demo_if_needed
from eventwall.models import EventRecord
from ops.models import Alert, AlertIntegration, Host, HostTask, HostTaskExecution
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
        proposal = AIOpsIncidentAction.objects.get(incident=incident, action_type=AIOpsIncidentAction.ACTION_INVESTIGATE)
        self.assertEqual(proposal.status, AIOpsIncidentAction.STATUS_PROPOSED)
        self.assertEqual(proposal.risk_level, AIOpsIncidentAction.RISK_READ_ONLY)
        self.assertIn('只读', ''.join(proposal.preconditions))

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
        self.assertEqual(AIOpsIncidentAction.objects.filter(incident=incident, action_type=AIOpsIncidentAction.ACTION_INVESTIGATE).count(), 1)

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
        self.assertEqual(AIOpsIncidentAction.objects.filter(incident=incident).count(), 1)

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
        knowledge = AIOpsReviewKnowledge.objects.get(slug=f'incident-{self.incident.id}-review')
        self.assertEqual(knowledge.environment, self.incident.environment)
        self.assertEqual(knowledge.service, self.incident.service)
        self.assertEqual(knowledge.source_refs[0]['type'], 'incident')
        self.assertIn('manual_close', knowledge.tags)

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

    def test_incident_detail_includes_incident_actions(self):
        hypothesis = AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 出现 HighErrorRate 告警症状',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM,
            confidence=0.45,
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )
        AIOpsIncidentAction.objects.create(
            incident=self.incident,
            hypothesis=hypothesis,
            title='补充 order-center 只读证据',
            action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
            risk_level=AIOpsIncidentAction.RISK_READ_ONLY,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            verification_plan=['补查错误日志'],
        )

        response = self.client.get(f'/api/aiops/incidents/{self.incident.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['incident_actions']), 1)
        self.assertEqual(response.data['incident_actions'][0]['action_type_display'], '继续调查')
        self.assertEqual(response.data['incident_actions'][0]['risk_level_display'], '只读')

    def test_incident_detail_includes_retrospective_suggestions_and_review_knowledge(self):
        AIOpsReviewKnowledge.objects.create(
            slug=f'incident-{self.incident.id}-review',
            title=f'Incident #{self.incident.id} 复盘知识',
            summary='复盘摘要',
            environment=self.incident.environment,
            service=self.incident.service,
            tags=['incident', 'postmortem'],
            source_refs=[{'type': 'incident', 'id': self.incident.id}],
        )
        AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 发布后错误率升高',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_CHANGE_REGRESSION,
            confidence=0.7,
            supporting_evidence_ids=[1],
            summary='发布窗口与错误率升高时间一致。',
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )
        EventRecord.objects.create(
            module='aiops',
            category='incident',
            action='investigate_incident',
            title='Incident 自动调查',
            summary='已生成证据',
            correlation_id=f'aiops_incident:{self.incident.id}',
        )

        response = self.client.get(f'/api/aiops/incidents/{self.incident.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['review_knowledge']['slug'], f'incident-{self.incident.id}-review')
        suggestion_types = {item['type'] for item in response.data['retrospective_suggestions']}
        self.assertIn('skill', suggestion_types)
        self.assertIn('runbook', suggestion_types)
        timeline_types = [item['type'] for item in response.data['timeline']]
        self.assertIn('incident_created', timeline_types)
        self.assertIn('investigate_incident', timeline_types)

    def test_materialize_incident_skill_creates_idempotent_pending_action(self):
        AIOpsIncidentEvidence.objects.create(
            incident=self.incident,
            kind=AIOpsIncidentEvidence.KIND_ALERT,
            source='builtin.alert_snapshot',
            summary='错误率超过阈值',
            weight=AIOpsIncidentEvidence.WEIGHT_PRIMARY,
        )
        AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 发布后错误率升高',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_CHANGE_REGRESSION,
            confidence=0.7,
            supporting_evidence_ids=[1],
            summary='发布窗口与错误率升高时间一致。',
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )

        first = self.client.post(f'/api/aiops/incidents/{self.incident.id}/retrospective/skill/')
        second = self.client.post(f'/api/aiops/incidents/{self.incident.id}/retrospective/skill/')

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(first.data['created'])
        self.assertFalse(second.data['created'])
        self.assertEqual(AIOpsPendingAction.objects.filter(action_type=AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL).count(), 1)
        pending_action = AIOpsPendingAction.objects.get(action_type=AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL)
        self.assertEqual(first.data['pending_action']['id'], pending_action.id)
        self.assertEqual(second.data['pending_action']['id'], pending_action.id)
        self.assertEqual(pending_action.action_payload['incident_id'], self.incident.id)
        self.assertEqual(pending_action.action_payload['source'], 'incident_retrospective')
        self.assertIn('query_alerts', pending_action.action_payload['builtin_tools'])
        self.assertFalse(pending_action.action_payload['is_enabled'])
        self.assertFalse(AIOpsSkill.objects.filter(is_builtin=False).exists())
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='materialize_incident_skill').exists())

    def test_materialize_incident_runbook_creates_draft(self):
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='回滚 order-center',
            action_type=AIOpsIncidentAction.ACTION_ROLLBACK,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_COMPLETED,
            preconditions=['确认发布窗口一致'],
            rollback_plan=['恢复到上一版本'],
            verification_plan=['确认错误率恢复'],
            result_summary='回滚后告警恢复',
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/retrospective/runbook/')
        second = self.client.post(f'/api/aiops/incidents/{self.incident.id}/retrospective/runbook/')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(response.data['created'])
        self.assertFalse(second.data['created'])
        self.assertEqual(AIOpsRunbook.objects.count(), 1)
        runbook = AIOpsRunbook.objects.get(id=response.data['runbook']['id'])
        self.assertEqual(second.data['runbook']['id'], runbook.id)
        self.assertEqual(runbook.status, AIOpsRunbook.STATUS_DRAFT)
        self.assertEqual(runbook.environment, self.incident.environment)
        self.assertEqual(runbook.service, self.incident.service)
        self.assertEqual(runbook.source_refs[0]['type'], 'incident')
        self.assertIn('回滚 order-center', runbook.content)
        self.assertTrue(any(item.get('type') == 'incident_action' and item.get('id') == action.id for item in runbook.evidence))
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='materialize_incident_runbook').exists())

    def test_incident_chat_session_carries_incident_context(self):
        evidence = AIOpsIncidentEvidence.objects.create(
            incident=self.incident,
            kind=AIOpsIncidentEvidence.KIND_ALERT,
            source='builtin.alert_snapshot',
            summary='错误率超过阈值',
            weight=AIOpsIncidentEvidence.WEIGHT_PRIMARY,
        )
        hypothesis = AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 发布后错误率升高',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_CHANGE_REGRESSION,
            confidence=0.7,
            supporting_evidence_ids=[evidence.id],
            summary='发布窗口与错误率升高时间一致。',
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )
        AIOpsIncidentAction.objects.create(
            incident=self.incident,
            hypothesis=hypothesis,
            title='补查 order-center 错误日志',
            action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
            risk_level=AIOpsIncidentAction.RISK_READ_ONLY,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            verification_plan=['确认错误日志模式'],
        )

        first = self.client.post(f'/api/aiops/incidents/{self.incident.id}/chat-session/')
        second = self.client.post(f'/api/aiops/incidents/{self.incident.id}/chat-session/')

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(first.data['created'])
        self.assertFalse(second.data['created'])
        self.assertEqual(first.data['session']['id'], second.data['session']['id'])
        self.assertIn('主根因假设', first.data['suggested_question'])
        session = AIOpsChatSession.objects.get(id=first.data['session']['id'])
        context = session.context
        self.assertEqual(context['source'], 'incident_chat')
        self.assertEqual(context['incident_id'], self.incident.id)
        self.assertEqual(context['incident_context']['incident_id'], self.incident.id)
        self.assertEqual(context['incident_context']['primary_hypothesis']['id'], hypothesis.id)
        self.assertEqual(context['incident_context']['evidence_items'][0]['id'], evidence.id)
        self.assertEqual(context['page_context']['hints']['service'], self.incident.service)
        memory = build_session_memory_snapshot(session)
        self.assertEqual(memory['incident_context']['incident_id'], self.incident.id)
        self.assertEqual(memory['incident_context']['primary_hypothesis']['title'], hypothesis.title)
        self.assertIn('session_scope', memory['incident_context'])
        self.assertEqual(AIOpsChatSession.objects.filter(title=f'Incident #{self.incident.id} 排障追问').count(), 1)
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='open_incident_chat').exists())

    def test_demo_session_sync_keeps_chat_context(self):
        admin_user, _ = User.objects.get_or_create(username='admin', defaults={'is_staff': True, 'is_superuser': True})
        admin_user.set_password('Passw0rd!123')
        admin_user.save(update_fields=['password'])
        admin_user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        demo_user, _ = User.objects.get_or_create(username='demo')
        demo_user.set_password('Passw0rd!123')
        demo_user.save(update_fields=['password'])
        demo_user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        session = AIOpsChatSession.objects.create(
            user=admin_user,
            title='上下文同步测试',
            context={'incident_context': {'incident_id': self.incident.id}},
        )

        sync_session_to_demo_if_needed(session)

        mirror = AIOpsChatSession.objects.get(user=demo_user, mirror_source=session)
        self.assertEqual(mirror.context['incident_context']['incident_id'], self.incident.id)

    def test_run_readonly_incident_action_refreshes_evidence(self):
        run_readonly_investigation(self.incident, reason='test_seed')
        action = AIOpsIncidentAction.objects.get(
            incident=self.incident,
            action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
            risk_level=AIOpsIncidentAction.RISK_READ_ONLY,
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/run/')

        self.assertEqual(response.status_code, 200, response.data)
        action.refresh_from_db()
        self.assertEqual(action.status, AIOpsIncidentAction.STATUS_COMPLETED)
        self.assertEqual(action.verification_status, 'readonly_completed')
        task = AIOpsExternalTask.objects.filter(action_code='incident.investigate').order_by('-id').first()
        self.assertEqual(task.status, AIOpsExternalTask.STATUS_COMPLETED)
        self.assertEqual(task.input_payload['reason'], 'manual_followup')
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=self.incident).count(), 2)
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='run_incident_action').exists())
        response_action = next(item for item in response.data['incident_actions'] if item['id'] == action.id)
        self.assertEqual(response_action['status'], AIOpsIncidentAction.STATUS_COMPLETED)

    def test_run_incident_action_rejects_non_readonly_action(self):
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            verification_plan=['确认服务恢复'],
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/run/')

        self.assertEqual(response.status_code, 400, response.data)
        action.refresh_from_db()
        self.assertEqual(action.status, AIOpsIncidentAction.STATUS_PROPOSED)
        self.assertFalse(AIOpsExternalTask.objects.filter(action_code='incident.investigate').exists())

    def test_materialize_incident_action_creates_pending_action(self):
        host = Host.objects.create(hostname='order-host-01', ip_address='10.0.1.21', environment='prod', status='online')
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            action_payload={
                'name': '重启 order-center',
                'target_type': HostTask.TARGET_HOST,
                'task_type': HostTask.TASK_RUN_COMMAND,
                'payload': {'command': 'systemctl restart order-center'},
                'target_refs': [{'source': 'host', 'id': host.id}],
                'host_count': 1,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            },
            verification_plan=['确认服务恢复'],
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(response.status_code, 200, response.data)
        action.refresh_from_db()
        self.assertIsNotNone(action.pending_action_id)
        self.assertEqual(action.verification_status, 'approval_pending')
        pending_action = AIOpsPendingAction.objects.get(id=action.pending_action_id)
        self.assertEqual(pending_action.session.user, self.user)
        self.assertEqual(pending_action.action_type, AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK)
        self.assertEqual(pending_action.status, AIOpsPendingAction.STATUS_PENDING)
        self.assertEqual(pending_action.risk_level, AIOpsPendingAction.RISK_HIGH)
        self.assertEqual(pending_action.action_payload['incident_id'], self.incident.id)
        self.assertEqual(pending_action.action_payload['incident_action_id'], action.id)
        self.assertEqual(pending_action.action_payload['target_refs'], [{'source': 'host', 'id': host.id}])
        self.assertTrue(AIOpsChatSession.objects.filter(user=self.user, title=f'Incident #{self.incident.id} 审批').exists())
        response_action = next(item for item in response.data['incident_actions'] if item['id'] == action.id)
        self.assertEqual(response_action['pending_action'], pending_action.id)
        self.assertEqual(response_action['pending_action_status'], AIOpsPendingAction.STATUS_PENDING)
        self.assertEqual(response_action['pending_action_status_display'], '待确认')
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='materialize_incident_action').exists())

    @patch('aiops.services.start_host_task')
    def test_confirm_materialized_incident_action_syncs_task_link(self, mocked_start_host_task):
        host = Host.objects.create(hostname='order-host-03', ip_address='10.0.1.23', environment='prod', status='online')
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            action_payload={
                'name': '重启 order-center',
                'target_type': HostTask.TARGET_HOST,
                'task_type': HostTask.TASK_RUN_COMMAND,
                'payload': {'command': 'systemctl restart order-center'},
                'target_refs': [{'source': 'host', 'id': host.id}],
                'host_count': 1,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            },
            verification_plan=['确认服务恢复'],
        )
        materialize_response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')
        self.assertEqual(materialize_response.status_code, 200, materialize_response.data)
        action.refresh_from_db()

        confirm_response = self.client.post(f'/api/aiops/actions/{action.pending_action_id}/confirm/', {}, format='json')

        self.assertEqual(confirm_response.status_code, 200, confirm_response.data)
        action.refresh_from_db()
        pending_action = action.pending_action
        pending_action.refresh_from_db()
        task = HostTask.objects.get(id=pending_action.result_payload['task_id'])
        self.assertEqual(action.host_task_id, task.id)
        self.assertEqual(action.status, AIOpsIncidentAction.STATUS_RUNNING)
        self.assertEqual(action.verification_status, 'execution_started')
        self.assertIn(f'任务 #{task.id}', action.result_summary)
        self.assertEqual(task.source_context['incident_id'], self.incident.id)
        self.assertEqual(task.source_context['incident_action_id'], action.id)
        self.assertEqual(task.selection_filters['incident_id'], self.incident.id)
        self.assertEqual(task.selection_filters['incident_action_id'], action.id)
        self.assertTrue(pending_action.result_payload['execution_started'])
        mocked_start_host_task.assert_called_once()
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_task_started').exists())

    def test_materialize_incident_action_is_idempotent(self):
        host = Host.objects.create(hostname='order-host-02', ip_address='10.0.1.22', environment='prod', status='online')
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            action_payload={
                'name': '重启 order-center',
                'target_type': HostTask.TARGET_HOST,
                'task_type': HostTask.TASK_RUN_COMMAND,
                'payload': {'command': 'systemctl restart order-center'},
                'target_refs': [{'source': 'host', 'id': host.id}],
                'host_count': 1,
            },
        )

        first = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')
        second = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(AIOpsPendingAction.objects.count(), 1)

    def test_materialize_incident_action_rejects_readonly_action(self):
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='补充 order-center 只读证据',
            action_type=AIOpsIncidentAction.ACTION_INVESTIGATE,
            risk_level=AIOpsIncidentAction.RISK_READ_ONLY,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(AIOpsPendingAction.objects.exists())

    def test_verification_sync_marks_action_resolved_when_task_succeeds_without_active_alerts(self):
        self.incident.active_alert_count = 0
        self.incident.save(update_fields=['active_alert_count'])
        task = HostTask.objects.create(
            name='重启 order-center',
            task_type=HostTask.TASK_RUN_COMMAND,
            status=HostTask.STATUS_SUCCESS,
            trigger_source=HostTask.TRIGGER_SOURCE_AIOPS,
            lifecycle_status=HostTask.LIFECYCLE_SUCCESS,
            target_count=1,
            success_count=1,
            summary='共 1 台，成功 1，失败 0',
        )
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            host_task=task,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_RUNNING,
            verification_status='execution_started',
        )
        HostTaskExecution.objects.create(
            task=task,
            status=HostTaskExecution.STATUS_SUCCESS,
            command='systemctl restart order-center',
            output='ok',
        )

        updated = sync_incident_action_verification_for_task(task)

        self.assertEqual(updated, 1)
        action.refresh_from_db()
        self.incident.refresh_from_db()
        self.assertEqual(action.status, AIOpsIncidentAction.STATUS_COMPLETED)
        self.assertEqual(action.verification_status, 'verified_resolved')
        self.assertIn('已验证恢复', action.result_summary)
        self.assertEqual(self.incident.status, AIOpsIncident.STATUS_RESOLVED)
        self.assertIsNotNone(self.incident.resolved_at)
        knowledge = AIOpsReviewKnowledge.objects.get(slug=f'incident-{self.incident.id}-review')
        self.assertEqual(knowledge.source_refs[0]['type'], 'incident')
        self.assertIn('verified_resolved', knowledge.tags)
        self.assertTrue(any(item.get('type') == 'incident_action' and item.get('id') == action.id for item in knowledge.evidence))
        verification_events = EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_verified', result=EventRecord.RESULT_SUCCESS)
        self.assertEqual(verification_events.count(), 1)
        second = sync_incident_action_verification_for_task(task)
        self.assertEqual(second, 0)
        self.assertEqual(AIOpsReviewKnowledge.objects.filter(slug=f'incident-{self.incident.id}-review').count(), 1)
        self.assertEqual(verification_events.count(), 1)
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_verified', result=EventRecord.RESULT_SUCCESS, metadata__review_knowledge_id=knowledge.id).exists())

    def test_verification_sync_keeps_incident_open_when_task_fails(self):
        task = HostTask.objects.create(
            name='重启 order-center',
            task_type=HostTask.TASK_RUN_COMMAND,
            status=HostTask.STATUS_FAILED,
            trigger_source=HostTask.TRIGGER_SOURCE_AIOPS,
            lifecycle_status=HostTask.LIFECYCLE_FAILED,
            target_count=1,
            failed_count=1,
            summary='共 1 台，成功 0，失败 1',
        )
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            host_task=task,
            title='重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_RUNNING,
            verification_status='execution_started',
        )
        HostTaskExecution.objects.create(
            task=task,
            status=HostTaskExecution.STATUS_FAILED,
            command='systemctl restart order-center',
            error_message='failed',
        )

        updated = sync_incident_action_verification_for_task(task)

        self.assertEqual(updated, 1)
        action.refresh_from_db()
        self.incident.refresh_from_db()
        self.assertEqual(action.status, AIOpsIncidentAction.STATUS_FAILED)
        self.assertEqual(action.verification_status, 'no_improvement')
        self.assertIn('未形成有效恢复证据', action.result_summary)
        self.assertEqual(self.incident.status, AIOpsIncident.STATUS_OPEN)
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_verified', result=EventRecord.RESULT_FAILED).exists())
