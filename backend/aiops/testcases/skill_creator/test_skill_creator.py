import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from aiops.models import (
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsSkill,
)
from aiops.services import (
    _action_registry_item_by_code,
    _apply_dispatch_result_to_message,
    _build_skill_draft_from_arguments,
    _dispatch_with_tool_runtime,
    _run_tool_call,
    confirm_action,
    get_agent_config,
)
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class SkillCreatorTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='skill_creator_admin', password='Passw0rd!123')
        self.user.rbac_roles.add(Role.objects.get(code='platform-admin'))
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        get_agent_config()
        self.session = AIOpsChatSession.objects.create(user=self.user, title='skill creator')
        self.user_message = AIOpsChatMessage.objects.create(
            session=self.session,
            role=AIOpsChatMessage.ROLE_USER,
            content='创建一个 HBase 巡检 Skill',
        )
        self.assistant_message = AIOpsChatMessage.objects.create(
            session=self.session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            content='处理中',
        )

    def skill_arguments(self):
        return {
            'name': 'hbase-cluster-inspector',
            'description': '用于 HBase 集群节点、Master、RegionServer 和监控指标巡检。',
            'category': 'HBase 运维',
            'content': '先查询资源底座确认节点，再检查 Master、RegionServer、Region 分布和关键指标；只输出证据和建议。',
            'applicable_actions': ['skill.create'],
            'examples': ['检查 HBase 集群节点数', '沉淀 HBase 巡检 SOP'],
            'builtin_tools': ['query_task_resources', 'query_logs', 'not_existing_tool'],
            'output_contract': {'sections': ['结论', '证据', '建议'], 'trigger_keywords': ['HBase', 'RegionServer']},
        }

    def test_builtin_assets_include_skill_creator_and_collaboration_mcp(self):
        skill = AIOpsSkill.objects.get(slug='skill-creator')
        action = _action_registry_item_by_code('skill.create', user=self.user)
        mcp = AIOpsMCPServer.objects.get(name='协同沉淀 MCP')

        self.assertEqual(skill.name, 'skill-creator')
        self.assertIn('draft_aiops_skill', skill.builtin_tools)
        self.assertIsNotNone(action)
        self.assertEqual(action['allowed_tools'], ['draft_aiops_skill'])
        self.assertIn('skill-creator', action['skills'])
        self.assertIn('draft_aiops_skill', mcp.tool_whitelist)

    def test_draft_tool_returns_pending_skill_draft_without_creating_skill(self):
        before_count = AIOpsSkill.objects.filter(is_builtin=False).count()

        result = _run_tool_call(
            self.session,
            self.user_message,
            self.user,
            'draft_aiops_skill',
            self.skill_arguments(),
            registry_entry={'kind': 'platform_mcp', 'tool_name': 'draft_aiops_skill'},
        )

        draft = result['pending_action_draft']
        self.assertEqual(result['message_type'], AIOpsChatMessage.TYPE_ACTION)
        self.assertEqual(draft['action_type'], AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL)
        self.assertEqual(draft['name'], 'hbase-cluster-inspector')
        self.assertEqual(draft['builtin_tools'], ['query_task_resources', 'query_logs'])
        self.assertEqual(AIOpsSkill.objects.filter(is_builtin=False).count(), before_count)

    def test_apply_dispatch_result_creates_pending_skill_action(self):
        draft = _build_skill_draft_from_arguments(self.user, '创建 HBase Skill', self.skill_arguments())

        _message, pending_action = _apply_dispatch_result_to_message(
            self.session,
            self.assistant_message,
            {
                'content': '已生成 Skill 草案，等待确认。',
                'pending_action_draft': draft,
                'tool_calls': ['draft_aiops_skill'],
            },
            self.user,
            question='创建 HBase Skill',
        )

        self.assertIsNotNone(pending_action)
        self.assertEqual(pending_action.action_type, AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL)
        self.assertEqual(pending_action.status, AIOpsPendingAction.STATUS_PENDING)
        self.assertFalse(pending_action.result_payload)
        self.assistant_message.refresh_from_db()
        self.assertEqual(self.assistant_message.metadata['action_trace']['draft']['action_type'], AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL)

    def test_confirm_pending_skill_action_creates_team_skill(self):
        draft = _build_skill_draft_from_arguments(self.user, '创建 HBase Skill', self.skill_arguments())
        pending_action = AIOpsPendingAction.objects.create(
            session=self.session,
            message=self.assistant_message,
            action_type=AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL,
            title=draft['name'],
            risk_level=draft['risk_level'],
            action_payload=draft,
        )

        confirmed_payload = confirm_action(pending_action, self.user)

        pending_action.refresh_from_db()
        self.assertEqual(pending_action.status, AIOpsPendingAction.STATUS_EXECUTED)
        self.assertTrue(pending_action.result_payload['materialized_as_skill'])
        skill = AIOpsSkill.objects.get(pk=pending_action.result_payload['skill_id'])
        self.assertFalse(skill.is_builtin)
        self.assertEqual(skill.name, 'hbase-cluster-inspector')
        self.assertEqual(skill.slug, confirmed_payload['slug'])
        self.assertEqual(skill.builtin_tools, ['query_task_resources', 'query_logs'])

    def test_confirm_pending_skill_action_api_uses_config_permission(self):
        draft = _build_skill_draft_from_arguments(self.user, '创建 HBase Skill', self.skill_arguments())
        pending_action = AIOpsPendingAction.objects.create(
            session=self.session,
            message=self.assistant_message,
            action_type=AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL,
            title=draft['name'],
            risk_level=draft['risk_level'],
            action_payload=draft,
        )

        response = self.client.post(f'/api/aiops/actions/{pending_action.id}/confirm/', {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['materialized_as_skill'])
        self.assertEqual(response.data['skill_name'], 'hbase-cluster-inspector')

    @patch('aiops.services._request_model_completion')
    def test_skill_create_action_skips_environment_preflight(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='test provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='http://model.example/v1',
            default_model='test-model',
            is_enabled=True,
        )
        provider.set_api_key('token')
        provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider', 'updated_at'])
        arguments = self.skill_arguments()
        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'content': '',
                        'tool_calls': [{
                            'id': 'call-1',
                            'type': 'function',
                            'function': {'name': 'draft_aiops_skill', 'arguments': json.dumps(arguments, ensure_ascii=False)},
                        }],
                    },
                }],
            },
            {'choices': [{'message': {'content': '结论：已生成 Skill 草案，等待确认。'}}]},
            {'choices': [{'message': {'content': '结论：已生成 Skill 草案，等待确认。\n关键点：将保存为团队 Skill。'}}]},
        ]

        result = _dispatch_with_tool_runtime(
            self.session,
            self.user_message,
            self.user,
            '创建一个 HBase 巡检 Skill',
        )

        self.assertNotEqual(result.get('metadata', {}).get('error_code'), 'environment_required')
        self.assertIsNotNone(result.get('pending_action_draft'), result)
        self.assertEqual(result['pending_action_draft']['action_type'], AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL)
        self.assertIn('draft_aiops_skill', result['tool_calls'])
