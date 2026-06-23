from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsAgentProfile, AIOpsChatMessage, AIOpsChatSession, AIOpsPendingAction
from aiops.services import create_pending_task_action_from_draft, get_agent_config
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
        draft = {
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
        return create_pending_task_action_from_draft(session, message, draft)

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
    def test_confirm_pending_action_does_not_create_task_for_invalid_targets(self, mocked_start_host_task):
        action = self.create_invalid_target_action()

        response = self.client.post(f'/api/aiops/actions/{action.id}/confirm/', {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(HostTask.objects.filter(trigger_source=HostTask.TRIGGER_SOURCE_AIOPS).exists())
        mocked_start_host_task.assert_not_called()
        action.refresh_from_db()
        self.assertEqual(action.status, AIOpsPendingAction.STATUS_FAILED)
        self.assertIn('没有找到有效的目标主机', action.result_payload['error'])
