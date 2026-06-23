from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsAgentConfig, AIOpsAgentProfile
from aiops.services import resolve_agent_profile_for_user, runtime_config_for_agent
from rbac.models import PermissionDefinition
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

    def test_chat_session_records_selected_agent_and_runtime_policy(self):
        AIOpsAgentProfile.objects.create(
            name='ReadOnly HBase Agent',
            slug='hbase-readonly',
            description='只读 HBase 巡检',
            execution_policy=AIOpsAgentProfile.EXECUTION_READ_ONLY,
            system_prompt='只允许做 HBase 只读分析。',
            welcome_message='HBase 只读助手',
            suggested_questions=['本地 HBase 集群有几个 RegionServer？'],
            is_enabled=True,
        )

        response = self.client.post('/api/aiops/sessions/', {
            'title': 'HBase 巡检',
            'agent_slug': 'hbase-readonly',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['agent']['slug'], 'hbase-readonly')
        self.assertEqual(response.data['context']['agent_slug'], 'hbase-readonly')
        self.assertFalse(response.data['context']['runtime']['allow_action_execution'])

        bootstrap_response = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(bootstrap_response.status_code, 200)
        self.assertTrue(any(agent['slug'] == 'hbase-readonly' for agent in bootstrap_response.data['available_agents']))

    def test_runtime_config_for_agent_overrides_global_config(self):
        config = AIOpsAgentConfig.objects.create(
            name='runtime-test',
            system_prompt='global prompt',
            welcome_message='global welcome',
            suggested_questions=['global'],
            allow_action_execution=True,
        )
        agent = AIOpsAgentProfile.objects.create(
            name='ReadOnly Agent',
            slug='readonly-runtime',
            system_prompt='agent prompt',
            welcome_message='agent welcome',
            suggested_questions=['agent question'],
            execution_policy=AIOpsAgentProfile.EXECUTION_READ_ONLY,
            enabled_mcp_server_ids=[1],
            enabled_skill_ids=[2],
            is_enabled=True,
        )

        runtime = runtime_config_for_agent(config, agent)

        self.assertEqual(runtime.system_prompt, 'agent prompt')
        self.assertEqual(runtime.welcome_message, 'agent welcome')
        self.assertEqual(runtime.suggested_questions, ['agent question'])
        self.assertEqual(runtime.enabled_mcp_server_ids, [1])
        self.assertEqual(runtime.enabled_skill_ids, [2])
        self.assertFalse(runtime.allow_action_execution)

    def test_non_default_agent_requires_agent_run_permission(self):
        chat_perm = PermissionDefinition.objects.get(code='aiops.chat.view')
        role = Role.objects.create(code='chat-only', name='Chat Only')
        role.permissions.set([chat_perm])
        user = User.objects.create_user(username='chat_only', password='Passw0rd!123')
        user.rbac_roles.add(role)
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        AIOpsAgentProfile.objects.create(
            name='Restricted Agent',
            slug='restricted-agent',
            execution_policy=AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM,
            is_enabled=True,
        )

        response = client.post('/api/aiops/sessions/', {
            'title': 'restricted',
            'agent_slug': 'restricted-agent',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('agent_slug', response.data)

        default_agent = resolve_agent_profile_for_user(user)
        self.assertEqual(default_agent.slug, 'general')

    def test_unknown_explicit_agent_slug_is_rejected(self):
        response = self.client.post('/api/aiops/sessions/', {
            'title': 'unknown agent',
            'agent_slug': 'missing-agent',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('agent_slug', response.data)
