from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsAgentProfile, AIOpsChatMessage, AIOpsChatSession, AIOpsPendingAction
from aiops.services import _apply_dispatch_result_to_message, create_pending_task_action_from_draft, get_agent_config
from eventwall.models import EventRecord
from ops.models import HostTask, TaskResource, TaskResourceGroup
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class AgentExecutionE2ETests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        get_agent_config()
        self.user = User.objects.create_user(username='agent_executor', password='Passw0rd!123')
        self.user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.environment = TaskResourceGroup.objects.create(
            name='agent-exec-env',
            code='agent-exec-env',
            group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        self.resource = TaskResource.objects.create(
            name='agent-exec-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=self.environment,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.88.0.10',
            ssh_user='root',
        )

    def create_pending_action(self, agent_slug='general'):
        session = AIOpsChatSession.objects.create(
            user=self.user,
            title='agent execution e2e',
            context={
                'agent_slug': agent_slug,
                'agent_name': '通用运维 Agent',
                'runtime': {'execution_policy': AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM},
            },
        )
        message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            content='已生成巡检任务，等待确认。',
        )
        return create_pending_task_action_from_draft(session, message, self.create_task_draft())

    def create_task_draft(self):
        return {
            'name': 'Agent 资源巡检',
            'description': '由 AIOps Agent 生成的任务',
            'target_type': HostTask.TARGET_HOST,
            'task_type': HostTask.TASK_RUN_COMMAND,
            'resource_ids': [self.resource.id],
            'target_refs': [{'source': 'task_resource', 'id': self.resource.id}],
            'host_count': 1,
            'execution_mode': HostTask.EXECUTION_MODE_SSH,
            'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            'timeout_seconds': 30,
            'risk_level': AIOpsPendingAction.RISK_HIGH,
            'request_summary': '检查 agent-exec-env 的资源状态',
            'payload': {'command': 'hostname && uptime', 'script_kind': 'shell'},
        }

    def create_invalid_target_action(self):
        action = self.create_pending_action()
        payload = dict(action.action_payload or {})
        payload['resource_ids'] = [999999]
        payload['target_refs'] = [{'source': 'task_resource', 'id': 999999}]
        action.action_payload = payload
        action.save(update_fields=['action_payload'])
        return action

    @patch('aiops.services.start_host_task')
    def test_confirm_pending_action_creates_and_starts_task_center_task(self, mocked_start_host_task):
        action = self.create_pending_action()

        response = self.client.post(f'/api/aiops/actions/{action.id}/confirm/', {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        action.refresh_from_db()
        self.assertEqual(action.status, AIOpsPendingAction.STATUS_EXECUTED)
        self.assertTrue(action.result_payload['materialized_in_task_center'])
        self.assertTrue(action.result_payload['execution_started'])
        self.assertEqual(action.result_payload['authorization']['mode'], 'manual_confirm')
        self.assertEqual(action.result_payload['authorization']['confirmed_by'], self.user.username)
        self.assertEqual(action.result_payload['authorization']['agent_slug'], 'general')
        self.assertIn('aiops.task.execute', action.result_payload['authorization']['permissions_checked'])
        self.assertIn('ops.host.execute', action.result_payload['authorization']['permissions_checked'])

        task = HostTask.objects.get(pk=action.result_payload['task_id'])
        self.assertEqual(response.data['task_id'], task.id)
        self.assertEqual(response.data['task']['id'], task.id)
        self.assertEqual(task.trigger_source, HostTask.TRIGGER_SOURCE_AIOPS)
        self.assertEqual(task.created_by, self.user.username)
        self.assertEqual(task.source_context['source'], 'aiops')
        self.assertEqual(task.source_context['session_id'], action.session_id)
        self.assertEqual(task.source_context['pending_action_id'], action.id)
        self.assertEqual(task.source_context['agent_slug'], 'general')
        self.assertEqual(task.source_context['execution_policy'], AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM)
        self.assertEqual(task.source_context['authorization_mode'], 'manual_confirm')
        self.assertEqual(task.source_context['authorized_by'], self.user.username)
        self.assertEqual(task.source_context['risk_level'], AIOpsPendingAction.RISK_HIGH)
        self.assertEqual(task.payload['command'], 'hostname && uptime')
        mocked_start_host_task.assert_called_once()
        self.assertEqual(mocked_start_host_task.call_args.args[0].id, task.id)
        self.assertEqual(mocked_start_host_task.call_args.args[1][0].resource_id, self.resource.id)

        events = EventRecord.objects.filter(resource_type='host_task', resource_id=task.id)
        self.assertTrue(events.filter(action='create_host_task_record').exists())
        self.assertTrue(events.filter(action='start_host_task_from_aiops').exists())

    @patch('aiops.services.start_host_task')
    def test_execution_audit_links_pending_action_and_task_center_context(self, mocked_start_host_task):
        action = self.create_pending_action()
        confirm_response = self.client.post(f'/api/aiops/actions/{action.id}/confirm/', {}, format='json')
        self.assertEqual(confirm_response.status_code, 200, confirm_response.data)
        task_id = confirm_response.data['task_id']

        audit_response = self.client.get('/api/aiops/admin/audit/actions/')

        self.assertEqual(audit_response.status_code, 200, audit_response.data)
        audit_rows = audit_response.data['results']
        audit_row = next(item for item in audit_rows if item['id'] == action.id)
        self.assertEqual(audit_row['task_id'], task_id)
        self.assertEqual(audit_row['task_name'], 'Agent 资源巡检')
        self.assertEqual(audit_row['agent_slug'], 'general')
        self.assertEqual(audit_row['agent_name'], '通用运维 Agent')
        self.assertEqual(audit_row['authorization_mode'], 'manual_confirm')
        self.assertTrue(audit_row['materialized_in_task_center'])
        self.assertTrue(audit_row['execution_started'])

        task_response = self.client.get(f'/api/host-tasks/{task_id}/')

        self.assertEqual(task_response.status_code, 200, task_response.data)
        source_context = task_response.data['source_context']
        self.assertEqual(source_context['source'], 'aiops')
        self.assertEqual(source_context['pending_action_id'], action.id)
        self.assertEqual(source_context['agent_slug'], 'general')
        self.assertEqual(source_context['agent_name'], '通用运维 Agent')
        self.assertEqual(source_context['authorization_mode'], 'manual_confirm')
        self.assertEqual(source_context['authorized_by'], self.user.username)

    @patch('aiops.services.start_host_task')
    def test_confirm_pending_action_does_not_create_task_for_invalid_targets(self, mocked_start_host_task):
        action = self.create_invalid_target_action()

        response = self.client.post(f'/api/aiops/actions/{action.id}/confirm/', {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(HostTask.objects.filter(trigger_source=HostTask.TRIGGER_SOURCE_AIOPS).exists())
        mocked_start_host_task.assert_not_called()
        action.refresh_from_db()
        self.assertEqual(action.status, AIOpsPendingAction.STATUS_FAILED)
        self.assertIn('没有找到有效的目标主机', action.result_payload['error'])

    @patch('aiops.services.start_host_task')
    def test_full_auto_agent_materializes_and_starts_task_without_manual_confirm(self, mocked_start_host_task):
        agent = AIOpsAgentProfile.objects.create(
            name='Full Auto Agent',
            slug='full-auto-agent',
            execution_policy=AIOpsAgentProfile.EXECUTION_FULL_AUTO,
            tool_policy={
                'allow_read_only': True,
                'allow_generate_task': True,
                'allow_execute': True,
                'max_risk_level': AIOpsPendingAction.RISK_HIGH,
            },
            is_enabled=True,
        )
        session = AIOpsChatSession.objects.create(
            user=self.user,
            title='full auto e2e',
            context={'agent_slug': agent.slug, 'agent_name': agent.name},
        )
        assistant_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            content='处理中',
        )

        _assistant_message, pending_action = _apply_dispatch_result_to_message(
            session,
            assistant_message,
            {
                'content': '已生成巡检任务。',
                'pending_action_draft': self.create_task_draft(),
                'tool_calls': ['generate_host_task'],
            },
            self.user,
            question='检查 agent-exec-env 的资源状态',
        )

        self.assertIsNotNone(pending_action)
        pending_action.refresh_from_db()
        self.assertEqual(pending_action.status, AIOpsPendingAction.STATUS_EXECUTED)
        self.assertTrue(pending_action.result_payload['materialized_in_task_center'])
        self.assertTrue(pending_action.result_payload['execution_started'])
        self.assertEqual(pending_action.result_payload['authorization']['mode'], 'full_auto')
        self.assertEqual(pending_action.result_payload['authorization']['agent_slug'], agent.slug)
        task = HostTask.objects.get(pk=pending_action.result_payload['task_id'])
        self.assertEqual(task.source_context['agent_slug'], agent.slug)
        self.assertEqual(task.source_context['authorization_mode'], 'full_auto')
        mocked_start_host_task.assert_called_once()
        authorization_events = EventRecord.objects.filter(
            resource_type='aiops_action',
            resource_id=pending_action.id,
            action='auto_authorize_host_task_from_aiops',
        )
        self.assertTrue(authorization_events.exists())
        authorization_event = authorization_events.get()
        self.assertEqual(authorization_event.metadata['task_id'], task.id)
        self.assertEqual(authorization_event.metadata['agent_slug'], agent.slug)
        self.assertEqual(authorization_event.metadata['authorization_mode'], 'full_auto')

        assistant_message.refresh_from_db()
        self.assertEqual(assistant_message.metadata['created_task_id'], task.id)
        self.assertTrue(assistant_message.metadata['task_materialized_in_center'])
        self.assertEqual(assistant_message.metadata['action_trace']['decision']['status'], 'materialized')
        self.assertEqual(assistant_message.metadata['action_trace']['decision']['reason'], 'full_auto')

    @patch('aiops.services.start_host_task')
    def test_full_auto_agent_falls_back_to_manual_confirm_when_risk_exceeds_policy(self, mocked_start_host_task):
        agent = AIOpsAgentProfile.objects.create(
            name='Constrained Full Auto Agent',
            slug='constrained-full-auto-agent',
            execution_policy=AIOpsAgentProfile.EXECUTION_FULL_AUTO,
            tool_policy={
                'allow_read_only': True,
                'allow_generate_task': True,
                'allow_execute': True,
                'max_risk_level': AIOpsPendingAction.RISK_MEDIUM,
            },
            is_enabled=True,
        )
        session = AIOpsChatSession.objects.create(
            user=self.user,
            title='full auto fallback',
            context={'agent_slug': agent.slug, 'agent_name': agent.name},
        )
        assistant_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            content='处理中',
        )

        _assistant_message, pending_action = _apply_dispatch_result_to_message(
            session,
            assistant_message,
            {
                'content': '已生成高风险巡检任务。',
                'pending_action_draft': self.create_task_draft(),
                'tool_calls': ['generate_host_task'],
            },
            self.user,
            question='检查 agent-exec-env 的资源状态',
        )

        self.assertIsNotNone(pending_action)
        pending_action.refresh_from_db()
        self.assertEqual(pending_action.status, AIOpsPendingAction.STATUS_PENDING)
        self.assertFalse(HostTask.objects.filter(trigger_source=HostTask.TRIGGER_SOURCE_AIOPS).exists())
        mocked_start_host_task.assert_not_called()
        assistant_message.refresh_from_db()
        self.assertEqual(assistant_message.metadata['action_trace']['decision']['status'], 'pending_confirmation')
