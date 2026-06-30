from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.incident_investigation import register_llm_rca_planner, run_readonly_investigation
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
    AIOpsToolInvocation,
)
from aiops.services import sync_incident_action_verification_for_task, sync_session_to_demo_if_needed
from eventwall.models import EventRecord
from ops.models import Alert, AlertIntegration, Host, HostTask, HostTaskExecution, K8sCluster, LogDataSource, MetricDataSource, TaskResource, TaskResourceGroup, TracingDataSource
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class IncidentAlertIntakeTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        register_llm_rca_planner(None)
        self.integration = AlertIntegration.objects.create(
            name='Prometheus',
            provider=Alert.SOURCE_PROMETHEUS,
            default_labels={'environment': 'prod'},
        )
        self.client = APIClient()

    def tearDown(self):
        register_llm_rca_planner(None)

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
        self.assertEqual(incident.status, AIOpsIncident.STATUS_INVESTIGATING)
        self.assertEqual(incident.metadata['last_investigation']['status'], AIOpsExternalTask.STATUS_COMPLETED)
        self.assertEqual(incident.severity, AIOpsIncident.SEVERITY_CRITICAL)
        self.assertEqual(incident.environment, 'prod')
        self.assertEqual(incident.cluster, 'dev-k8s-cluster')
        self.assertEqual(incident.namespace, 'production')
        self.assertEqual(incident.service, 'order-center')
        self.assertEqual(incident.alert_count, 1)
        self.assertEqual(incident.active_alert_count, 1)
        link = AIOpsIncidentAlert.objects.get(incident=incident, alert=alert)
        self.assertEqual(link.role, AIOpsIncidentAlert.ROLE_PRIMARY)
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 7)
        alert_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.alert_snapshot')
        log_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.log_snapshot')
        trace_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.trace_snapshot')
        k8s_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.k8s_snapshot')
        event_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.event_timeline')
        resource_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.task_resource_scope')
        self.assertIsNotNone(alert_evidence.tool_invocation)
        self.assertIsNotNone(log_evidence.tool_invocation)
        self.assertIsNotNone(trace_evidence.tool_invocation)
        self.assertIsNotNone(k8s_evidence.tool_invocation)
        self.assertIsNotNone(event_evidence.tool_invocation)
        self.assertIsNotNone(resource_evidence.tool_invocation)
        self.assertEqual(alert_evidence.tool_invocation.tool_name, 'builtin.alert_snapshot')
        self.assertEqual(log_evidence.tool_invocation.tool_name, 'builtin.log_snapshot')
        self.assertEqual(trace_evidence.tool_invocation.tool_name, 'builtin.trace_snapshot')
        self.assertEqual(k8s_evidence.tool_invocation.tool_name, 'builtin.k8s_snapshot')
        self.assertEqual(event_evidence.tool_invocation.tool_name, 'builtin.event_timeline')
        self.assertEqual(resource_evidence.tool_invocation.tool_name, 'builtin.task_resource_scope')
        self.assertEqual(
            set(AIOpsToolInvocation.objects.filter(session__context__source='incident_background_investigation').values_list('tool_name', flat=True)),
            {'builtin.alert_snapshot', 'builtin.metric_snapshot', 'builtin.log_snapshot', 'builtin.trace_snapshot', 'builtin.k8s_snapshot', 'builtin.event_timeline', 'builtin.task_resource_scope'},
        )
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertEqual(task.status, AIOpsExternalTask.STATUS_COMPLETED)
        self.assertEqual(task.input_payload['incident_id'], incident.id)
        self.assertEqual(len(task.result_payload['tool_invocation_ids']), 7)
        self.assertEqual(len(task.orchestration_state['tool_invocation_ids']), 7)
        self.assertTrue(all(item.get('tool_invocation_id') for item in task.react_trace[:7]))
        rca_input = task.orchestration_state['rca_input']
        self.assertEqual(rca_input['version'], '1.0')
        self.assertEqual(rca_input['incident']['id'], incident.id)
        self.assertEqual(rca_input['incident']['service'], 'order-center')
        self.assertTrue(rca_input['policy']['forbid_unobserved_facts'])
        self.assertEqual(rca_input['hypothesis']['root_cause_type'], AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM)
        self.assertEqual(
            [item['source'] for item in rca_input['evidence']],
            [
                'builtin.alert_snapshot',
                'builtin.metric_snapshot',
                'builtin.log_snapshot',
                'builtin.trace_snapshot',
                'builtin.k8s_snapshot',
                'builtin.event_timeline',
                'builtin.task_resource_scope',
            ],
        )
        self.assertTrue(all('key_facts' in item for item in rca_input['evidence']))
        self.assertTrue(all('payload' not in item for item in rca_input['evidence']))
        self.assertEqual(task.result_payload['rca_input_version'], '1.0')
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
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 7)
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
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=incident).count(), 7)
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

    def test_alert_detail_can_start_incident_investigation(self):
        user = User.objects.create_user(username='alert-investigator', password='Passw0rd!123')
        user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        alert = Alert.objects.create(
            title='HBase RegionServer Down',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='RegionServer unavailable',
            environment='prod',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
            resource='regionserver-1',
            fingerprint='hbase-rs-down-1',
            group_key='hbase-regionserver',
            labels={'alertname': 'HBaseRegionServerDown'},
        )

        response = self.client.post(f'/api/alerts/{alert.id}/incident/investigate/')

        self.assertEqual(response.status_code, 201, response.data)
        incident = AIOpsIncident.objects.get()
        self.assertEqual(response.data['incident']['id'], incident.id)
        self.assertEqual(incident.service, 'hbase')
        self.assertEqual(AIOpsIncidentAlert.objects.filter(incident=incident, alert=alert).count(), 1)
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertEqual(task.status, AIOpsExternalTask.STATUS_COMPLETED)
        self.assertEqual(task.input_payload['reason'], 'manual_alert_investigation')
        self.assertTrue(AIOpsIncidentEvidence.objects.filter(incident=incident, kind=AIOpsIncidentEvidence.KIND_ALERT).exists())

    def test_hbase_incident_investigation_collects_task_resource_scope(self):
        env = TaskResourceGroup.objects.create(name='本地 HBase 集群', code='hbase-local', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        TaskResource.objects.create(
            name='hbase-master',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='127.0.0.11',
            metadata={'role': 'master', 'cluster': 'hbase-local'},
        )
        TaskResource.objects.create(
            name='hbase-regionserver-1',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_WARNING,
            ip_address='127.0.0.12',
            metadata={'role': 'regionserver', 'cluster': 'hbase-local', 'service': 'hbase'},
        )
        TaskResource.objects.create(
            name='hbase-regionserver-2',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='127.0.0.13',
            metadata={'role': 'regionserver', 'cluster': 'hbase-local', 'service': 'hbase'},
        )
        TaskResource.objects.create(
            name='rs-backup-3',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='127.0.0.14',
            metadata={'role': 'regionserver', 'cluster': 'hbase-local', 'service': 'hbase'},
        )
        alert = Alert.objects.create(
            title='HBase RegionServer Down',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='RegionServer unavailable',
            environment='本地 HBase 集群',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
            resource='hbase-regionserver-1',
            fingerprint='hbase-rs-down-resource-scope',
            group_key='hbase-regionserver-resource-scope',
            labels={'alertname': 'HBaseRegionServerDown'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_hbase_scope')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.task_resource_scope')
        self.assertEqual(evidence.kind, AIOpsIncidentEvidence.KIND_TOPOLOGY)
        self.assertEqual(evidence.payload['summary']['count'], 4)
        inventory = evidence.payload['cluster_inventory']
        self.assertEqual(inventory['cluster_count'], 1)
        self.assertEqual(inventory['node_count'], 4)
        self.assertEqual(set(inventory['node_names']), {'hbase-master', 'hbase-regionserver-1', 'hbase-regionserver-2', 'rs-backup-3'})
        k8s_evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.k8s_snapshot')
        self.assertFalse(k8s_evidence.payload['summary']['cluster_found'])
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertIn(evidence.id, hypothesis.supporting_evidence_ids)
        actions = list(AIOpsIncidentAction.objects.filter(incident=incident).order_by('action_type'))
        self.assertEqual({item.action_type for item in actions}, {AIOpsIncidentAction.ACTION_INVESTIGATE, AIOpsIncidentAction.ACTION_VERIFY})
        verify_action = AIOpsIncidentAction.objects.get(incident=incident, action_type=AIOpsIncidentAction.ACTION_VERIFY)
        self.assertEqual(verify_action.risk_level, AIOpsIncidentAction.RISK_LOW)
        self.assertEqual(verify_action.action_payload['task_type'], HostTask.TASK_REFRESH_METRICS)
        self.assertEqual(verify_action.action_payload['target_type'], HostTask.TARGET_HOST)
        self.assertEqual(set(verify_action.action_payload['resource_ids']), set(TaskResource.objects.values_list('id', flat=True)))
        self.assertEqual(verify_action.action_payload['host_count'], 4)
        self.assertIn('执行仍需用户确认', verify_action.action_payload['reason'])
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        topology_item = next(item for item in task.orchestration_state['rca_input']['evidence'] if item['source'] == 'builtin.task_resource_scope')
        rca_inventory = topology_item['key_facts']['cluster_inventory']
        self.assertEqual(rca_inventory['cluster_count'], 1)
        self.assertEqual(rca_inventory['node_count'], 4)
        self.assertEqual(set(rca_inventory['node_name_samples']), {'hbase-master', 'hbase-regionserver-1', 'hbase-regionserver-2', 'rs-backup-3'})
        self.assertEqual(rca_inventory['roles']['regionserver'], 3)

    def test_incident_investigation_collects_k8s_evidence(self):
        cluster = K8sCluster.objects.create(
            name='dev-k8s-cluster',
            kubeconfig='demo',
            status='connected',
        )
        alert = Alert.objects.create(
            title='Web Frontend Pod Pending',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='web frontend pod pending in staging namespace',
            environment='prod',
            cluster=cluster.name,
            namespace='staging',
            service='web-frontend',
            resource_type='deployment',
            resource='web-frontend',
            fingerprint='k8s-web-frontend-pending',
            group_key='k8s-web-frontend-pending',
            labels={'alertname': 'KubeDeploymentReplicasMismatch', 'namespace': 'staging'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_k8s_scope')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.k8s_snapshot')
        summary = evidence.payload['summary']
        self.assertEqual(evidence.kind, AIOpsIncidentEvidence.KIND_K8S)
        self.assertEqual(evidence.tool_invocation.tool_name, 'builtin.k8s_snapshot')
        self.assertTrue(summary['cluster_found'])
        self.assertEqual(summary['cluster_name'], cluster.name)
        self.assertEqual(summary['namespaces'], ['staging'])
        self.assertGreaterEqual(summary['pods_total'], 1)
        self.assertGreaterEqual(summary['pods_abnormal'], 1)
        self.assertGreaterEqual(summary['workloads_degraded'], 1)
        self.assertTrue(any(item['status'] == 'Pending' for item in evidence.payload['pods']))
        self.assertTrue(any(item['name'] == 'web-frontend' for item in evidence.payload['workloads']))
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertIn('builtin.k8s_snapshot', [step['tool'] for step in task.plan_steps])
        self.assertTrue(any(item.get('phase') == 'collect_k8s' for item in task.react_trace))
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertIn(evidence.id, hypothesis.supporting_evidence_ids)

    def test_remediation_planner_keeps_verify_proposal_when_followup_exists(self):
        env = TaskResourceGroup.objects.create(name='prod', code='prod', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        TaskResource.objects.create(
            name='order-host-01',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            metadata={'service': 'order-center'},
        )
        alert = Alert.objects.create(
            title='Order Error High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='order errors are high',
            environment='prod',
            cluster='prod',
            namespace='production',
            service='order-center',
            resource_type='service',
            resource='order-center',
            fingerprint='order-followup-existing',
            group_key='order-followup-existing',
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='first_pass')
        followup = AIOpsIncidentAction.objects.get(incident=incident, action_type=AIOpsIncidentAction.ACTION_INVESTIGATE)
        followup.status = AIOpsIncidentAction.STATUS_COMPLETED
        followup.verification_status = 'readonly_completed'
        followup.save(update_fields=['status', 'verification_status'])

        run_readonly_investigation(incident, reason='second_pass')

        self.assertEqual(AIOpsIncidentAction.objects.filter(incident=incident, action_type=AIOpsIncidentAction.ACTION_INVESTIGATE).count(), 1)
        self.assertEqual(AIOpsIncidentAction.objects.filter(incident=incident, action_type=AIOpsIncidentAction.ACTION_VERIFY).count(), 1)

    def test_llm_rca_planner_can_promote_structured_primary_hypothesis(self):
        captured = {}

        def fake_planner(incident, rca_input, task=None):
            captured['rca_input'] = rca_input
            alert_item = next(item for item in rca_input['evidence'] if item['source'] == 'builtin.alert_snapshot')
            return {
                'title': 'order-center 可能存在依赖错误',
                'root_cause_type': AIOpsIncidentHypothesis.TYPE_DEPENDENCY_FAILURE,
                'confidence': 0.71,
                'supporting_evidence_ids': [alert_item['id']],
                'counter_evidence_ids': [],
                'missing_evidence': ['缺少下游依赖 Trace 详情'],
                'recommended_next_checks': ['补查下游依赖错误链路'],
                'summary': '基于当前告警和证据包，优先怀疑下游依赖失败。',
            }

        register_llm_rca_planner(fake_planner)
        alert = Alert.objects.create(
            title='Order Dependency Error',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='order dependency failed',
            environment='prod',
            service='order-center',
            resource='order-center',
            fingerprint='order-llm-rca',
            group_key='order-llm-rca',
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_llm_rca')

        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertEqual(hypothesis.generated_by, 'llm_rca_planner')
        self.assertEqual(hypothesis.root_cause_type, AIOpsIncidentHypothesis.TYPE_DEPENDENCY_FAILURE)
        self.assertEqual(float(hypothesis.confidence), 0.71)
        self.assertTrue(hypothesis.supporting_evidence_ids)
        self.assertEqual(captured['rca_input']['incident']['id'], incident.id)
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertEqual(task.orchestration_state['rca_input']['hypothesis']['id'], hypothesis.id)

    def test_llm_rca_planner_rejects_unobserved_evidence_ids(self):
        def fake_planner(incident, rca_input, task=None):
            return {
                'title': 'order-center 可能存在依赖错误',
                'root_cause_type': AIOpsIncidentHypothesis.TYPE_DEPENDENCY_FAILURE,
                'confidence': 0.91,
                'supporting_evidence_ids': [999999],
                'counter_evidence_ids': [],
                'missing_evidence': [],
                'recommended_next_checks': [],
                'summary': '这个结论引用了不存在的证据。',
            }

        register_llm_rca_planner(fake_planner)
        alert = Alert.objects.create(
            title='Order Error High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='order errors are high',
            environment='prod',
            service='order-center',
            resource='order-center',
            fingerprint='order-llm-invalid-rca',
            group_key='order-llm-invalid-rca',
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_invalid_llm_rca')

        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertEqual(hypothesis.generated_by, 'rule_based')
        self.assertEqual(hypothesis.root_cause_type, AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM)

    def test_llm_rca_planner_failure_falls_back_to_rule_hypothesis(self):
        def failing_planner(incident, rca_input, task=None):
            raise RuntimeError('model timeout')

        register_llm_rca_planner(failing_planner)
        alert = Alert.objects.create(
            title='Order Error High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='order errors are high',
            environment='prod',
            service='order-center',
            resource='order-center',
            fingerprint='order-llm-timeout-rca',
            group_key='order-llm-timeout-rca',
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        with self.assertLogs('aiops.incident_investigation', level='ERROR') as logs:
            run_readonly_investigation(incident, reason='test_failed_llm_rca')

        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertIn('LLM RCA planner failed', '\n'.join(logs.output))
        self.assertEqual(hypothesis.generated_by, 'rule_based')
        self.assertEqual(hypothesis.root_cause_type, AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM)
        self.assertEqual(task.status, AIOpsExternalTask.STATUS_COMPLETED)

    @patch('aiops.incident_investigation.execute_promql_query')
    def test_incident_investigation_collects_metric_evidence(self, mocked_promql):
        metric_source = MetricDataSource.objects.create(
            name='hbase-prometheus',
            environment='本地 HBase 集群',
            is_default=True,
            config={'query_url': 'http://prometheus.local:9090'},
        )
        alert = Alert.objects.create(
            title='HBase RegionServer RPC Latency High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='RegionServer latency is high',
            environment='本地 HBase 集群',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
            resource_type='service',
            resource='hbase-regionserver',
            metric_name='http_requests_total',
            fingerprint='hbase-rs-latency-metric-scope',
            group_key='hbase-regionserver-metric-scope',
            labels={'service': 'hbase', 'namespace': 'middleware'},
        )
        mocked_promql.return_value = {
            'query': 'mock',
            'range': True,
            'source': 'metric_datasource',
            'metric_datasource': {'id': metric_source.id, 'name': metric_source.name},
            'series_count': 1,
            'result': [{
                'metric': {'service': 'hbase', 'namespace': 'middleware'},
                'values': [
                    [1710000000, '1'],
                    [1710000060, '1'],
                    [1710000120, '5'],
                ],
            }],
            'sample': [],
        }

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_metric_scope')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.metric_snapshot')
        self.assertEqual(evidence.kind, AIOpsIncidentEvidence.KIND_METRIC)
        self.assertEqual(evidence.tool_invocation.tool_name, 'builtin.metric_snapshot')
        self.assertEqual(evidence.payload['summary']['alert_id'], alert.id)
        self.assertGreaterEqual(evidence.payload['summary']['planned_count'], 1)
        self.assertGreaterEqual(evidence.payload['summary']['abnormal_count'], 1)
        self.assertEqual(evidence.payload['summary']['metric_datasource_id'], metric_source.id)
        mocked_promql.assert_called()
        self.assertTrue(mocked_promql.call_args.kwargs['prefer_metric_datasource'])
        self.assertEqual(mocked_promql.call_args.kwargs['metric_datasource_id'], metric_source.id)
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertIn(evidence.id, hypothesis.supporting_evidence_ids)

    @patch('aiops.incident_investigation.execute_promql_query')
    def test_incident_investigation_skips_metric_query_without_datasource(self, mocked_promql):
        alert = Alert.objects.create(
            title='HBase RegionServer RPC Latency High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='RegionServer latency is high',
            environment='本地 HBase 集群',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
            resource_type='service',
            resource='hbase-regionserver',
            metric_name='http_requests_total',
            fingerprint='hbase-rs-latency-no-ds',
            group_key='hbase-regionserver-no-ds',
            labels={'service': 'hbase', 'namespace': 'middleware'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_metric_no_datasource')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.metric_snapshot')
        self.assertGreaterEqual(evidence.payload['summary']['planned_count'], 1)
        self.assertEqual(evidence.payload['summary']['failed_count'], evidence.payload['summary']['planned_count'])
        self.assertIn('未配置启用的指标数据源', evidence.payload['evidence'][0]['error'])
        mocked_promql.assert_not_called()

    def test_incident_investigation_collects_log_evidence(self):
        LogDataSource.objects.create(
            name='demo-loki-hbase',
            provider='loki',
            is_default=True,
            config={'demo_mode': True},
        )
        alert = Alert.objects.create(
            title='Gateway Error High',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='gateway errors are high',
            environment='prod',
            cluster='cn-sh-prod',
            namespace='prod',
            service='gateway-service',
            resource_type='service',
            resource='gateway-service',
            fingerprint='gateway-error-log-scope',
            group_key='gateway-error-log-scope',
            labels={'service': 'gateway-service', 'namespace': 'prod'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_log_scope')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.log_snapshot')
        self.assertEqual(evidence.kind, AIOpsIncidentEvidence.KIND_LOG)
        self.assertEqual(evidence.tool_invocation.tool_name, 'builtin.log_snapshot')
        self.assertGreaterEqual(evidence.payload['summary']['datasource_count'], 1)
        self.assertGreaterEqual(evidence.payload['summary']['log_count'], 1)
        self.assertTrue(any('failed' in item['message'].lower() for item in evidence.payload['logs']))
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertIn(evidence.id, hypothesis.supporting_evidence_ids)

    def test_incident_investigation_collects_trace_evidence(self):
        TracingDataSource.objects.create(
            name='demo-tempo',
            provider='tempo',
            is_default=True,
            config={'demo_mode': True},
        )
        alert = Alert.objects.create(
            title='Order Create Error',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='order create failed',
            environment='prod',
            cluster='dev-k8s-cluster',
            namespace='production',
            service='order-service',
            resource_type='service',
            resource='order-service',
            fingerprint='order-create-trace-scope',
            group_key='order-create-trace-scope',
            labels={'service': 'order-service', 'namespace': 'production'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_trace_scope')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.trace_snapshot')
        summary = evidence.payload['summary']
        self.assertEqual(evidence.kind, AIOpsIncidentEvidence.KIND_TRACE)
        self.assertEqual(evidence.tool_invocation.tool_name, 'builtin.trace_snapshot')
        self.assertTrue(summary['datasource_found'])
        self.assertTrue(summary['service_matched'])
        self.assertEqual(summary['service_name'], 'order-service')
        self.assertGreaterEqual(summary['match_count'], 1)
        self.assertGreaterEqual(summary['error_match_count'], 1)
        self.assertTrue(any(item['is_error'] for item in evidence.payload['traces']))
        task = AIOpsExternalTask.objects.get(action_code='incident.investigate')
        self.assertIn('builtin.trace_snapshot', [step['tool'] for step in task.plan_steps])
        self.assertTrue(any(item.get('phase') == 'collect_traces' for item in task.react_trace))
        hypothesis = AIOpsIncidentHypothesis.objects.get(incident=incident, status=AIOpsIncidentHypothesis.STATUS_PRIMARY)
        self.assertIn(evidence.id, hypothesis.supporting_evidence_ids)

    def test_incident_investigation_skips_trace_without_service(self):
        TracingDataSource.objects.create(
            name='demo-tempo-no-service',
            provider='tempo',
            is_default=True,
            config={'demo_mode': True},
        )
        alert = Alert.objects.create(
            title='Cluster Node Pressure',
            level='warning',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='cluster node pressure',
            environment='prod',
            cluster='dev-k8s-cluster',
            namespace='production',
            fingerprint='cluster-node-pressure-no-service',
            group_key='cluster-node-pressure-no-service',
            labels={'namespace': 'production'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_trace_no_service')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.trace_snapshot')
        summary = evidence.payload['summary']
        self.assertTrue(summary['datasource_found'])
        self.assertFalse(summary['service_matched'])
        self.assertEqual(summary['match_count'], 0)
        self.assertEqual(evidence.payload['traces'], [])

    def test_incident_investigation_does_not_fallback_trace_for_unknown_service(self):
        TracingDataSource.objects.create(
            name='demo-tempo-unknown-service',
            provider='tempo',
            is_default=True,
            config={'demo_mode': True},
        )
        alert = Alert.objects.create(
            title='Unknown Service Error',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='unknown service failed',
            environment='prod',
            cluster='dev-k8s-cluster',
            namespace='production',
            service='unknown-service',
            resource_type='service',
            resource='unknown-service',
            fingerprint='unknown-service-trace-scope',
            group_key='unknown-service-trace-scope',
            labels={'service': 'unknown-service', 'namespace': 'production'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        run_readonly_investigation(incident, reason='test_trace_unknown_service')

        evidence = AIOpsIncidentEvidence.objects.get(incident=incident, source='builtin.trace_snapshot')
        summary = evidence.payload['summary']
        self.assertTrue(summary['datasource_found'])
        self.assertFalse(summary['service_matched'])
        self.assertEqual(summary['service_name'], 'unknown-service')
        self.assertEqual(summary['match_count'], 0)
        self.assertEqual(evidence.payload['traces'], [])

    def test_readonly_investigation_does_not_reopen_resolved_incident(self):
        alert = Alert.objects.create(
            title='Order Error Recovered',
            level='critical',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            status=Alert.STATUS_RESOLVED,
            message='order error recovered',
            environment='prod',
            cluster='dev-k8s-cluster',
            namespace='production',
            service='order-service',
            fingerprint='order-recovered-investigation',
            group_key='order-recovered-investigation',
            labels={'service': 'order-service', 'namespace': 'production'},
        )

        from aiops.incidents import upsert_incident_for_alert

        incident, _ = upsert_incident_for_alert(alert, schedule_investigation=False)
        self.assertEqual(incident.status, AIOpsIncident.STATUS_RESOLVED)
        run_readonly_investigation(incident, reason='test_resolved_investigation')

        incident.refresh_from_db()
        self.assertEqual(incident.status, AIOpsIncident.STATUS_RESOLVED)
        self.assertEqual(incident.metadata['last_investigation']['status'], AIOpsExternalTask.STATUS_COMPLETED)

    def test_alert_detail_can_link_existing_incident(self):
        user = User.objects.create_user(username='alert-linker', password='Passw0rd!123')
        user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        alert = Alert.objects.create(
            title='HBase GC High',
            level='warning',
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='GC pause high',
            environment='prod',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
            fingerprint='hbase-gc-high-1',
        )
        incident = AIOpsIncident.objects.create(
            title='hbase / RegionServer unstable',
            status=AIOpsIncident.STATUS_OPEN,
            severity=AIOpsIncident.SEVERITY_WARNING,
            source_type=AIOpsIncident.SOURCE_ALERT,
            dedupe_key='manual:hbase-regionserver',
            environment='prod',
            cluster='hbase-local',
            namespace='middleware',
            service='hbase',
        )

        response = self.client.post(
            f'/api/alerts/{alert.id}/incident/link/',
            {'incident_id': incident.id, 'role': AIOpsIncidentAlert.ROLE_SYMPTOM, 'reason': '同一 HBase 故障窗口'},
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        link = AIOpsIncidentAlert.objects.get(incident=incident, alert=alert)
        self.assertEqual(link.role, AIOpsIncidentAlert.ROLE_SYMPTOM)
        self.assertEqual(link.linked_reason, '同一 HBase 故障窗口')
        incident.refresh_from_db()
        self.assertEqual(incident.alert_count, 1)
        self.assertEqual(response.data['incident']['id'], incident.id)


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
        self.incident.alert_count = 2
        self.incident.active_alert_count = 2
        self.incident.save(update_fields=['alert_count', 'active_alert_count'])
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
        self.assertIn('alert_suppression', suggestion_types)
        suggestion_by_type = {item['type']: item for item in response.data['retrospective_suggestions']}
        self.assertEqual(suggestion_by_type['alert_suppression']['target_route']['query']['policy'], 'inhibition')
        self.assertEqual(suggestion_by_type['alert_suppression']['draft_payload']['matchers'][0]['key'], 'environment')
        self.assertEqual(suggestion_by_type['knowledge_environment']['target_route']['path'], '/aiops/knowledge')
        self.assertEqual(suggestion_by_type['knowledge_environment']['draft_payload']['incident_id'], self.incident.id)
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
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=self.incident).count(), 7)
        self.assertTrue(AIOpsIncidentEvidence.objects.filter(incident=self.incident, source='builtin.task_resource_scope').exists())
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
            preconditions=['确认 order-center 已有可用副本'],
            rollback_plan=['如重启后异常扩大，停止后续目标并恢复原状态'],
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

    def test_materialize_auto_verification_action_creates_low_risk_pending_action(self):
        env = TaskResourceGroup.objects.create(name='prod', code='prod', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        resource = TaskResource.objects.create(
            name='order-host-01',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.0.1.21',
            metadata={'service': 'order-center'},
        )
        hypothesis = AIOpsIncidentHypothesis.objects.create(
            incident=self.incident,
            title='order-center 出现告警症状',
            root_cause_type=AIOpsIncidentHypothesis.TYPE_ALERT_SYMPTOM,
            confidence=0.45,
            status=AIOpsIncidentHypothesis.STATUS_PRIMARY,
        )
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            hypothesis=hypothesis,
            title='验证 order-center 资源状态',
            action_type=AIOpsIncidentAction.ACTION_VERIFY,
            risk_level=AIOpsIncidentAction.RISK_LOW,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            action_payload={
                'name': '验证 order-center 资源状态',
                'target_type': HostTask.TARGET_HOST,
                'task_type': HostTask.TASK_REFRESH_METRICS,
                'payload': {'check_scope': 'host_metrics'},
                'resource_ids': [resource.id],
                'target_refs': [{'source': 'task_resource', 'id': resource.id}],
                'host_count': 1,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_CONTINUE,
                'risk_level': AIOpsIncidentAction.RISK_LOW,
            },
            preconditions=['资源底座已匹配到目标主机。'],
            rollback_plan=['低风险验证任务不修改目标资源，无需回滚。'],
            verification_plan=['确认任务中心执行成功。'],
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(response.status_code, 200, response.data)
        action.refresh_from_db()
        pending_action = AIOpsPendingAction.objects.get(id=action.pending_action_id)
        self.assertEqual(pending_action.risk_level, AIOpsPendingAction.RISK_LOW)
        self.assertEqual(pending_action.action_payload['task_type'], HostTask.TASK_REFRESH_METRICS)
        self.assertEqual(pending_action.action_payload['target_refs'], [{'source': 'task_resource', 'id': resource.id}])
        self.assertEqual(action.verification_status, 'approval_pending')

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
            preconditions=['确认 order-center 已有可用副本'],
            rollback_plan=['如重启后异常扩大，停止后续目标并恢复原状态'],
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
            preconditions=['确认 order-center 已有可用副本'],
            rollback_plan=['如重启后异常扩大，停止后续目标并恢复原状态'],
            verification_plan=['确认服务恢复'],
        )

        first = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')
        second = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(AIOpsPendingAction.objects.count(), 1)

    def test_materialize_incident_action_rejects_high_risk_without_safety_plan(self):
        host = Host.objects.create(hostname='order-host-04', ip_address='10.0.1.24', environment='prod', status='online')
        action = AIOpsIncidentAction.objects.create(
            incident=self.incident,
            title='强制重启 order-center',
            action_type=AIOpsIncidentAction.ACTION_FIX,
            risk_level=AIOpsIncidentAction.RISK_HIGH,
            status=AIOpsIncidentAction.STATUS_PROPOSED,
            action_payload={
                'name': '强制重启 order-center',
                'target_type': HostTask.TARGET_HOST,
                'task_type': HostTask.TASK_RUN_COMMAND,
                'payload': {'command': 'systemctl restart order-center'},
                'target_refs': [{'source': 'host', 'id': host.id}],
                'host_count': 1,
            },
        )

        response = self.client.post(f'/api/aiops/incidents/{self.incident.id}/actions/{action.id}/materialize/')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('前置条件', response.data['detail'])
        self.assertIn('回滚方案', response.data['detail'])
        self.assertIn('验证计划', response.data['detail'])
        self.assertFalse(AIOpsPendingAction.objects.exists())

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
        LogDataSource.objects.create(
            name='demo-loki-verification',
            provider='loki',
            is_default=True,
            config={'demo_mode': True},
        )
        K8sCluster.objects.create(
            name='dev-k8s-cluster',
            kubeconfig='demo',
            status='connected',
        )
        self.incident.cluster = 'dev-k8s-cluster'
        self.incident.namespace = 'production'
        self.incident.resource_type = 'deployment'
        self.incident.resource = 'api-server'
        self.incident.active_alert_count = 0
        self.incident.save(update_fields=['cluster', 'namespace', 'resource_type', 'resource', 'active_alert_count'])
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
        evidence = AIOpsIncidentEvidence.objects.get(
            incident=self.incident,
            kind=AIOpsIncidentEvidence.KIND_TASK,
            source=f'builtin.verification.{action.id}',
        )
        self.assertEqual(evidence.weight, AIOpsIncidentEvidence.WEIGHT_PRIMARY)
        self.assertEqual(evidence.payload['verification_status'], 'verified_resolved')
        self.assertEqual(evidence.payload['task_id'], task.id)
        self.assertEqual(evidence.payload['executions'][0]['output_preview'], 'ok')
        observation = evidence.payload['observation']
        self.assertEqual(observation['alerts']['active_alert_count'], 0)
        self.assertGreaterEqual(observation['logs']['datasource_count'], 1)
        self.assertGreaterEqual(observation['logs']['log_count'], 0)
        self.assertTrue(observation['k8s']['cluster_found'])
        self.assertEqual(observation['k8s']['cluster_name'], 'dev-k8s-cluster')
        self.assertFalse(AIOpsIncidentEvidence.objects.filter(incident=self.incident, source='builtin.log_snapshot').exists())
        self.assertFalse(AIOpsIncidentEvidence.objects.filter(incident=self.incident, source='builtin.k8s_snapshot').exists())
        knowledge = AIOpsReviewKnowledge.objects.get(slug=f'incident-{self.incident.id}-review')
        self.assertEqual(knowledge.source_refs[0]['type'], 'incident')
        self.assertIn('verified_resolved', knowledge.tags)
        self.assertTrue(any(item.get('type') == 'incident_action' and item.get('id') == action.id for item in knowledge.evidence))
        verification_events = EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_verified', result=EventRecord.RESULT_SUCCESS)
        self.assertEqual(verification_events.count(), 1)
        second = sync_incident_action_verification_for_task(task)
        self.assertEqual(second, 0)
        self.assertEqual(AIOpsReviewKnowledge.objects.filter(slug=f'incident-{self.incident.id}-review').count(), 1)
        self.assertEqual(AIOpsIncidentEvidence.objects.filter(incident=self.incident, source=f'builtin.verification.{action.id}').count(), 1)
        self.assertEqual(verification_events.count(), 1)
        self.assertTrue(EventRecord.objects.filter(
            module='aiops',
            category='incident',
            action='incident_action_verified',
            result=EventRecord.RESULT_SUCCESS,
            metadata__review_knowledge_id=knowledge.id,
            metadata__verification_evidence_id=evidence.id,
        ).exists())

    def test_verification_sync_refreshes_stale_incident_alert_counts(self):
        alert = Alert.objects.create(
            title='order-center HighErrorRate',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='prometheus',
            source_type=Alert.SOURCE_PROMETHEUS,
            message='5xx ratio above threshold',
            environment=self.incident.environment,
            service=self.incident.service,
        )
        AIOpsIncidentAlert.objects.create(
            incident=self.incident,
            alert=alert,
            role=AIOpsIncidentAlert.ROLE_PRIMARY,
        )
        alert.status = Alert.STATUS_RESOLVED
        alert.save(update_fields=['status'])
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

        updated = sync_incident_action_verification_for_task(task)

        self.assertEqual(updated, 1)
        action.refresh_from_db()
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.alert_count, 1)
        self.assertEqual(self.incident.active_alert_count, 0)
        self.assertEqual(action.verification_status, 'verified_resolved')
        self.assertEqual(self.incident.status, AIOpsIncident.STATUS_RESOLVED)

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
        evidence = AIOpsIncidentEvidence.objects.get(
            incident=self.incident,
            kind=AIOpsIncidentEvidence.KIND_TASK,
            source=f'builtin.verification.{action.id}',
        )
        self.assertEqual(evidence.weight, AIOpsIncidentEvidence.WEIGHT_SUPPORTING)
        self.assertEqual(evidence.payload['verification_status'], 'no_improvement')
        self.assertEqual(evidence.payload['executions'][0]['error_preview'], 'failed')
        self.assertTrue(EventRecord.objects.filter(module='aiops', category='incident', action='incident_action_verified', result=EventRecord.RESULT_FAILED).exists())
