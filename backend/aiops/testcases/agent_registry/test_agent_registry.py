from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsAgentProfile
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class AgentRegistryApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='agent_admin', password='Passw0rd!123')
        self.user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def response_results(self, response):
        if isinstance(response.data, dict) and 'results' in response.data:
            return response.data['results']
        return response.data

    def test_bootstrap_creates_default_agent_and_custom_agent_can_be_default(self):
        bootstrap_response = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(bootstrap_response.status_code, 200)
        self.assertEqual(bootstrap_response.data['default_agent']['slug'], 'general')
        self.assertTrue(bootstrap_response.data['available_agents'])

        response = self.client.post('/api/aiops/admin/agents/', {
            'name': 'HBase 运维 Agent',
            'slug': 'hbase-ops',
            'description': '面向 HBase 集群巡检和排障',
            'execution_policy': AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM,
            'tool_policy': {'max_risk_level': 'high', 'allow_execute': True},
            'allowed_role_codes': ['ops-admin'],
            'suggested_questions': ['本地 HBase 集群有几个 RegionServer？'],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['slug'], 'hbase-ops')
        self.assertFalse(response.data['is_default'])

        list_response = self.client.get('/api/aiops/admin/agents/')
        self.assertEqual(list_response.status_code, 200)
        agents = self.response_results(list_response)
        self.assertEqual({item['slug'] for item in agents}, {'general', 'hbase-ops'})

        set_default_response = self.client.post(f"/api/aiops/admin/agents/{response.data['id']}/set-default/")
        self.assertEqual(set_default_response.status_code, 200)
        self.assertTrue(set_default_response.data['is_default'])

        refreshed_bootstrap = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(refreshed_bootstrap.status_code, 200)
        self.assertEqual(refreshed_bootstrap.data['default_agent']['slug'], 'hbase-ops')
