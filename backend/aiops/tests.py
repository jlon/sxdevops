from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from ops.models import Host
from rbac.models import Role
from rbac.services import ensure_builtin_rbac

from .models import AIOpsChatSession
from .services import get_agent_config


User = get_user_model()


class AIOpsApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='aiops_user', password='Passw0rd!123')
        platform_admin = Role.objects.get(code='platform-admin')
        self.user.rbac_roles.add(platform_admin)
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        Host.objects.create(hostname='prod-web-01', ip_address='10.0.0.10', environment='prod', status='online')

    def test_bootstrap_returns_runtime(self):
        response = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)

    def test_send_message_creates_session_messages(self):
        session_response = self.client.post('/api/aiops/sessions/', {'title': '测试会话'}, format='json')
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生产环境有哪些主机？'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIOpsChatSession.objects.get(pk=session_id).messages.count(), 2)

    def test_task_request_creates_pending_action(self):
        session_response = self.client.post('/api/aiops/sessions/', {'title': '任务会话'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生成一份 Redis 巡检任务'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.data['pending_action'])

    def test_task_request_respects_action_execution_switch(self):
        config = get_agent_config()
        config.allow_action_execution = False
        config.save(update_fields=['allow_action_execution'])
        session_response = self.client.post('/api/aiops/sessions/', {'title': '任务会话'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生成一份 Redis 巡检任务'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['pending_action'])
