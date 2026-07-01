from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import AIOpsAgentConfig, AIOpsAgentProfile, AIOpsMCPServer, AIOpsModelProvider, AIOpsSkill
from aiops.services import ensure_default_agent_profile, resolve_agent_profile_for_user, runtime_config_for_agent
from rbac.models import PermissionDefinition
from rbac.models import Role
from rbac.models import UserGroup
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

    def test_default_agent_initializes_with_runtime_defaults(self):
        config = AIOpsAgentConfig.objects.create(
            name='default-init-test',
            system_prompt='default prompt',
            welcome_message='default welcome',
            suggested_questions=['default question'],
            enabled_mcp_server_ids=[11],
            enabled_skill_ids=[22],
        )

        agent = ensure_default_agent_profile(config)

        self.assertEqual(agent.slug, 'general')
        self.assertEqual(agent.name, '通用运维 Agent')
        self.assertTrue(agent.is_builtin)
        self.assertTrue(agent.is_default)
        self.assertTrue(agent.is_enabled)
        self.assertEqual(agent.system_prompt, 'default prompt')
        self.assertEqual(agent.welcome_message, 'default welcome')
        self.assertEqual(agent.suggested_questions, ['default question'])
        self.assertEqual(agent.enabled_mcp_server_ids, [11])
        self.assertEqual(agent.enabled_skill_ids, [22])
        self.assertEqual(agent.execution_policy, AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM)

    def test_default_agent_initialization_keeps_existing_custom_default(self):
        custom_default = AIOpsAgentProfile.objects.create(
            name='Custom Default Agent',
            slug='custom-default-agent',
            is_default=True,
            is_enabled=True,
        )
        config = AIOpsAgentConfig.objects.create(name='existing-default-test')

        general_agent = ensure_default_agent_profile(config)

        self.assertEqual(general_agent.slug, 'general')
        self.assertFalse(general_agent.is_default)
        custom_default.refresh_from_db()
        self.assertTrue(custom_default.is_default)
        self.assertEqual(AIOpsAgentProfile.objects.get(is_default=True).slug, custom_default.slug)

    def test_default_agent_initialization_replaces_disabled_default(self):
        disabled_default = AIOpsAgentProfile.objects.create(
            name='Disabled Default Agent',
            slug='disabled-default-agent',
            is_default=True,
            is_enabled=False,
        )
        config = AIOpsAgentConfig.objects.create(name='disabled-default-test')

        general_agent = ensure_default_agent_profile(config)

        self.assertEqual(general_agent.slug, 'general')
        self.assertTrue(general_agent.is_default)
        disabled_default.refresh_from_db()
        self.assertFalse(disabled_default.is_default)
        self.assertEqual(AIOpsAgentProfile.objects.get(is_default=True).slug, 'general')

    def test_builtin_default_agent_follows_global_provider_override(self):
        initial_provider = AIOpsModelProvider.objects.create(
            name='Initial Provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://initial.example.com/v1',
            default_model='initial-model',
            is_enabled=True,
        )
        initial_provider.set_api_key('initial-key')
        initial_provider.save(update_fields=['api_key_encrypted'])
        override_provider = AIOpsModelProvider.objects.create(
            name='Override Provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://override.example.com/v1',
            default_model='override-model',
            is_enabled=True,
        )
        override_provider.set_api_key('override-key')
        override_provider.save(update_fields=['api_key_encrypted'])
        config = AIOpsAgentConfig.objects.create(name='provider-override-test', default_provider=initial_provider)
        default_agent = ensure_default_agent_profile(config)
        default_agent.default_provider = initial_provider
        default_agent.save(update_fields=['default_provider'])
        config.default_provider = override_provider
        config.save(update_fields=['default_provider'])

        runtime = runtime_config_for_agent(config, default_agent)

        self.assertEqual(runtime.default_provider_id, override_provider.id)

    def test_create_agent_seeds_runtime_fields_from_default_agent(self):
        default_agent = ensure_default_agent_profile(AIOpsAgentConfig.objects.create(
            name='seed-default-test',
            system_prompt='seed prompt',
            welcome_message='seed welcome',
            suggested_questions=['seed question'],
            enabled_mcp_server_ids=[31],
            enabled_skill_ids=[41],
        ))
        default_agent.execution_policy = AIOpsAgentProfile.EXECUTION_FULL_AUTO
        default_agent.save(update_fields=['execution_policy'])

        response = self.client.post('/api/aiops/admin/agents/', {
            'name': 'Seeded Agent',
            'slug': 'seeded-agent',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['system_prompt'], 'seed prompt')
        self.assertEqual(response.data['welcome_message'], 'seed welcome')
        self.assertEqual(response.data['suggested_questions'], ['seed question'])
        self.assertEqual(response.data['enabled_mcp_server_ids'], [31])
        self.assertEqual(response.data['enabled_skill_ids'], [41])
        self.assertEqual(response.data['execution_policy'], AIOpsAgentProfile.EXECUTION_MANUAL_CONFIRM)

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

    def test_bootstrap_includes_runtime_summary_for_each_available_agent(self):
        config = AIOpsAgentConfig.objects.create(name='bootstrap-runtime-test')
        default_agent = ensure_default_agent_profile(config)
        default_mcp = AIOpsMCPServer.objects.create(name='Default Bootstrap MCP')
        custom_mcp = AIOpsMCPServer.objects.create(name='Custom Bootstrap MCP')
        custom_skill = AIOpsSkill.objects.create(name='Custom Bootstrap Skill', slug='custom-bootstrap-skill')
        default_agent.enabled_mcp_server_ids = [default_mcp.id]
        default_agent.save(update_fields=['enabled_mcp_server_ids'])
        custom_agent = AIOpsAgentProfile.objects.create(
            name='Runtime Preview Agent',
            slug='runtime-preview-agent',
            enabled_mcp_server_ids=[custom_mcp.id],
            enabled_skill_ids=[custom_skill.id],
            execution_policy=AIOpsAgentProfile.EXECUTION_READ_ONLY,
            is_enabled=True,
        )

        response = self.client.get('/api/aiops/bootstrap/')

        self.assertEqual(response.status_code, 200, response.data)
        agent_payload = next(item for item in response.data['available_agents'] if item['slug'] == custom_agent.slug)
        self.assertEqual(agent_payload['runtime']['active_mcp_server_ids'], [custom_mcp.id])
        self.assertEqual(agent_payload['runtime']['active_skill_ids'], [custom_skill.id])
        self.assertFalse(agent_payload['runtime']['allow_action_execution'])

    def test_agent_runtime_endpoint_uses_same_permission_and_runtime_rules(self):
        ensure_default_agent_profile(AIOpsAgentConfig.objects.create(name='runtime-endpoint-test'))
        mcp = AIOpsMCPServer.objects.create(name='Endpoint Runtime MCP')
        skill = AIOpsSkill.objects.create(name='Endpoint Runtime Skill', slug='endpoint-runtime-skill')
        agent = AIOpsAgentProfile.objects.create(
            name='Endpoint Runtime Agent',
            slug='endpoint-runtime-agent',
            enabled_mcp_server_ids=[mcp.id],
            enabled_skill_ids=[skill.id],
            is_enabled=True,
        )

        response = self.client.get(f'/api/aiops/admin/agents/{agent.id}/runtime/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['agent']['slug'], 'endpoint-runtime-agent')
        self.assertEqual(response.data['runtime']['active_mcp_server_ids'], [mcp.id])
        self.assertEqual(response.data['runtime']['active_skill_ids'], [skill.id])
        self.assertEqual(response.data['active_mcp_servers'][0]['name'], 'Endpoint Runtime MCP')
        self.assertEqual(response.data['active_skills'][0]['slug'], 'endpoint-runtime-skill')

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

    def test_runtime_config_for_empty_custom_agent_inherits_default_agent(self):
        config = AIOpsAgentConfig.objects.create(
            name='runtime-inherit-test',
            system_prompt='global prompt',
            welcome_message='global welcome',
            suggested_questions=['global'],
            allow_action_execution=True,
        )
        provider = AIOpsModelProvider.objects.create(
            name='Default Runtime Provider',
            base_url='https://model.example.test/v1',
            default_model='ops-model',
        )
        mcp = AIOpsMCPServer.objects.create(name='Default Runtime MCP')
        skill = AIOpsSkill.objects.create(name='Default Runtime Skill', slug='default-runtime-skill')
        default_agent = ensure_default_agent_profile(config)
        default_agent.default_provider = provider
        default_agent.system_prompt = 'default prompt'
        default_agent.welcome_message = 'default welcome'
        default_agent.suggested_questions = ['default question']
        default_agent.enabled_mcp_server_ids = [mcp.id]
        default_agent.enabled_skill_ids = [skill.id]
        default_agent.save(update_fields=[
            'default_provider',
            'system_prompt',
            'welcome_message',
            'suggested_questions',
            'enabled_mcp_server_ids',
            'enabled_skill_ids',
        ])
        custom_agent = AIOpsAgentProfile.objects.create(
            name='Empty Custom Agent',
            slug='empty-custom-agent',
            is_enabled=True,
        )

        runtime = runtime_config_for_agent(config, custom_agent)

        self.assertEqual(runtime.default_provider_id, provider.id)
        self.assertEqual(runtime.system_prompt, 'default prompt')
        self.assertEqual(runtime.welcome_message, 'default welcome')
        self.assertEqual(runtime.suggested_questions, ['default question'])
        self.assertEqual(runtime.enabled_mcp_server_ids, [mcp.id])
        self.assertEqual(runtime.enabled_skill_ids, [skill.id])

    def test_runtime_skill_filter_includes_group_roles(self):
        chat_perm = PermissionDefinition.objects.get(code='aiops.chat.view')
        agent_run_perm = PermissionDefinition.objects.get(code='aiops.agent.run')
        role = Role.objects.create(code='hbase-runtime-role', name='HBase Runtime Role')
        role.permissions.set([chat_perm, agent_run_perm])
        group = UserGroup.objects.create(code='hbase-runtime-group', name='HBase Runtime Group')
        group.roles.add(role)
        user = User.objects.create_user(username='group_runtime_user', password='Passw0rd!123')
        user.rbac_groups.add(group)
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        mcp = AIOpsMCPServer.objects.create(name='Group Runtime MCP')
        skill = AIOpsSkill.objects.create(
            name='Group Runtime Skill',
            slug='group-runtime-skill',
            allowed_role_codes=['hbase-runtime-role'],
        )
        agent = AIOpsAgentProfile.objects.create(
            name='Group Runtime Agent',
            slug='group-runtime-agent',
            enabled_mcp_server_ids=[mcp.id],
            enabled_skill_ids=[skill.id],
            is_enabled=True,
        )

        response = client.get(f'/api/aiops/admin/agents/{agent.id}/runtime/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['runtime']['active_skill_ids'], [skill.id])
        self.assertEqual(response.data['active_skills'][0]['slug'], 'group-runtime-skill')

    def test_resource_registration_can_bind_provider_mcp_and_skill_to_agents(self):
        ensure_default_agent_profile(AIOpsAgentConfig.objects.create(name='resource-bind-test'))
        agent = AIOpsAgentProfile.objects.create(
            name='Bound Agent',
            slug='bound-agent',
            is_enabled=True,
        )

        provider_response = self.client.post('/api/aiops/admin/providers/', {
            'name': 'Bound Provider',
            'base_url': 'https://bound-provider.example.test/v1',
            'default_model': 'bound-model',
            'bind_agent_ids': [agent.id],
        }, format='json')
        self.assertEqual(provider_response.status_code, 201, provider_response.data)
        agent.refresh_from_db()
        self.assertEqual(agent.default_provider_id, provider_response.data['id'])

        mcp_response = self.client.post('/api/aiops/admin/mcp-servers/', {
            'name': 'Bound MCP',
            'server_type': 'http',
            'endpoint_or_command': 'https://mcp.example.test',
            'bind_agent_ids': [agent.id],
        }, format='json')
        self.assertEqual(mcp_response.status_code, 201, mcp_response.data)
        agent.refresh_from_db()
        self.assertIn(mcp_response.data['id'], agent.enabled_mcp_server_ids)

        other_agent = AIOpsAgentProfile.objects.create(
            name='Other Bound Agent',
            slug='other-bound-agent',
            enabled_mcp_server_ids=[mcp_response.data['id']],
            is_enabled=True,
        )
        update_mcp_response = self.client.patch(f"/api/aiops/admin/mcp-servers/{mcp_response.data['id']}/", {
            'bind_agent_ids': [agent.id],
        }, format='json')
        self.assertEqual(update_mcp_response.status_code, 200, update_mcp_response.data)
        other_agent.refresh_from_db()
        self.assertNotIn(mcp_response.data['id'], other_agent.enabled_mcp_server_ids)

        skill_response = self.client.post('/api/aiops/admin/skills/', {
            'name': 'Bound Skill',
            'slug': 'bound-skill',
            'description': '绑定到 Agent 的测试 Skill',
            'bind_agent_ids': [agent.id],
        }, format='json')
        self.assertEqual(skill_response.status_code, 201, skill_response.data)
        agent.refresh_from_db()
        self.assertIn(skill_response.data['id'], agent.enabled_skill_ids)

        update_skill_response = self.client.patch(f"/api/aiops/admin/skills/{skill_response.data['id']}/", {
            'bind_agent_ids': [],
        }, format='json')
        self.assertEqual(update_skill_response.status_code, 200, update_skill_response.data)
        agent.refresh_from_db()
        self.assertNotIn(skill_response.data['id'], agent.enabled_skill_ids)

    def test_skill_clone_can_bind_cloned_skill_to_agent(self):
        ensure_default_agent_profile(AIOpsAgentConfig.objects.create(name='skill-clone-bind-test'))
        agent = AIOpsAgentProfile.objects.create(
            name='Skill Clone Agent',
            slug='skill-clone-agent',
            is_enabled=True,
        )
        source = AIOpsSkill.objects.create(
            name='Source Clone Skill',
            slug='source-clone-skill',
        )

        response = self.client.post(f'/api/aiops/admin/skills/{source.id}/clone/', {
            'bind_agent_ids': [agent.id],
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        agent.refresh_from_db()
        self.assertIn(response.data['id'], agent.enabled_skill_ids)

    def test_resource_agent_binding_requires_agent_manage_permission(self):
        config_manage_perm = PermissionDefinition.objects.get(code='aiops.config.manage')
        role = Role.objects.create(code='aiops-config-manager', name='AIOps Config Manager')
        role.permissions.set([config_manage_perm])
        user = User.objects.create_user(username='config_manager', password='Passw0rd!123')
        user.rbac_roles.add(role)
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        agent = ensure_default_agent_profile(AIOpsAgentConfig.objects.create(name='resource-bind-permission-test'))

        response = client.post('/api/aiops/admin/mcp-servers/', {
            'name': 'Unauthorized Bound MCP',
            'server_type': 'http',
            'endpoint_or_command': 'https://mcp.example.test',
            'bind_agent_ids': [agent.id],
        }, format='json')

        self.assertEqual(response.status_code, 403)

    def test_resource_agent_binding_rejects_unknown_agent_ids(self):
        response = self.client.post('/api/aiops/admin/mcp-servers/', {
            'name': 'Unknown Agent Bound MCP',
            'server_type': 'http',
            'endpoint_or_command': 'https://mcp.example.test',
            'bind_agent_ids': [99999],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('bind_agent_ids', response.data)

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
