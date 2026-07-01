from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from aiops.models import AIOpsChatMessage, AIOpsChatSession
from aiops.services import (
    _action_registry_item_by_code,
    _build_runtime_prompt,
    _dispatch_with_tool_runtime,
    _select_runtime_skills,
    build_agent_runtime_context,
    get_agent_config,
)
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


User = get_user_model()


class SkillStub:
    def __init__(
        self,
        slug,
        *,
        name='',
        description='',
        category='',
        content='',
        applicable_actions=None,
        builtin_tools=None,
        recommended_tools=None,
        examples=None,
        output_contract=None,
    ):
        self.id = None
        self.slug = slug
        self.name = name or slug
        self.description = description
        self.category = category
        self.content = content or f'{self.name} runtime guide'
        self.applicable_actions = applicable_actions or []
        self.builtin_tools = builtin_tools or []
        self.recommended_tools = recommended_tools or []
        self.examples = examples or []
        self.output_contract = output_contract or {}
        self.risk_level = 'read_only'


def trace_item(selection, slug):
    return next(item for item in selection['trace']['items'] if item['slug'] == slug)


class SkillRuntimeSelectionTests(SimpleTestCase):
    def formatter_skill(self):
        return SkillStub(
            'answer-formatter',
            name='回答整形',
            description='统一回答结构',
            category='formatter',
        )

    def test_action_bound_skill_is_selected_before_unmatched_skill(self):
        formatter = self.formatter_skill()
        log_skill = SkillStub(
            'log-guide',
            name='日志分析',
            description='日志查询与异常分析 SOP',
            applicable_actions=['log.query_generate'],
            builtin_tools=['query_logs'],
        )
        inventory_skill = SkillStub(
            'inventory-guide',
            name='资源盘点',
            description='资源清单盘点',
            builtin_tools=['query_task_resources'],
        )

        selection = _select_runtime_skills(
            [inventory_skill, log_skill, formatter],
            question='帮我分析 api-server 的错误日志',
            selected_action={'code': 'log.query_generate', 'skills': ['log-guide']},
            tool_calls=['query_logs'],
        )

        self.assertEqual(selection['trace']['selected_slugs'][:2], ['answer-formatter', 'log-guide'])
        self.assertTrue(trace_item(selection, 'log-guide')['prompt_included'])
        self.assertIn('action_router', trace_item(selection, 'log-guide')['hit_reason'])
        self.assertFalse(trace_item(selection, 'inventory-guide')['prompt_included'])

    def test_keyword_examples_trigger_skill_without_action(self):
        formatter = self.formatter_skill()
        hbase_skill = SkillStub(
            'hbase-runbook',
            name='HBase 巡检',
            description='HBase 集群节点、RegionServer、Master 状态分析',
            examples=['分析 HBase 集群日志超时和 RegionServer 异常'],
            output_contract={'trigger_keywords': ['HBase', 'RegionServer', '集群节点']},
        )
        k8s_skill = SkillStub(
            'k8s-runbook',
            name='K8s 诊断',
            description='Kubernetes Pod Deployment Service 排查',
            examples=['检查 Pod 重启'],
        )

        selection = _select_runtime_skills(
            [formatter, k8s_skill, hbase_skill],
            question='本地 HBase 集群有几个节点，RegionServer 有没有超时？',
        )

        self.assertTrue(trace_item(selection, 'hbase-runbook')['prompt_included'])
        self.assertIn('keyword', trace_item(selection, 'hbase-runbook')['hit_reason'])
        self.assertFalse(trace_item(selection, 'k8s-runbook')['prompt_included'])

    def test_tool_calls_trigger_formatter_stage_skill(self):
        formatter = self.formatter_skill()
        log_skill = SkillStub(
            'log-guide',
            name='日志分析',
            description='日志查询结果分析',
            builtin_tools=['query_logs'],
        )
        cluster_skill = SkillStub(
            'cluster-status',
            name='集群状态',
            description='外部 MCP 集群状态工具结果分析',
            recommended_tools=['cluster_status'],
        )

        selection = _select_runtime_skills(
            [formatter, log_skill, cluster_skill],
            question='继续分析工具结果',
            tool_calls=['query_logs', 'mcp__hbase_monitor__cluster_status'],
            max_count=5,
        )

        self.assertTrue(trace_item(selection, 'log-guide')['prompt_included'])
        self.assertIn('query_logs', trace_item(selection, 'log-guide')['matched_tools'])
        self.assertTrue(trace_item(selection, 'cluster-status')['prompt_included'])
        self.assertIn('cluster_status', trace_item(selection, 'cluster-status')['matched_tools'])

    def test_prompt_limit_keeps_formatter_as_first_skill(self):
        formatter = self.formatter_skill()
        matching_skills = [
            SkillStub(
                f'hbase-runbook-{index}',
                name=f'HBase 巡检 {index}',
                description='HBase 集群节点 RegionServer Master 状态分析',
                examples=['HBase 集群节点异常'],
            )
            for index in range(4)
        ]

        selection = _select_runtime_skills(
            [*matching_skills, formatter],
            question='HBase 集群节点状态异常',
            max_count=1,
            max_chars=300,
        )

        self.assertEqual(selection['trace']['selected_slugs'], ['answer-formatter'])
        self.assertEqual(selection['trace']['prompt_skill_count'], 1)
        self.assertTrue(trace_item(selection, 'answer-formatter')['prompt_included'])
        self.assertFalse(trace_item(selection, 'hbase-runbook-0')['prompt_included'])


class BuiltinSkillRuntimeE2ETests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='skill_e2e', password='Passw0rd!123')
        self.user.rbac_roles.add(Role.objects.get(code='platform-admin'))

    def test_builtin_log_action_injects_only_relevant_skill_prompt(self):
        config = get_agent_config()
        runtime_context = build_agent_runtime_context(self.user, config=config)
        action = _action_registry_item_by_code('log.query_generate', user=self.user)

        selection = _select_runtime_skills(
            runtime_context.active_skills,
            question='帮我查询 HBase RegionServer 最近 30 分钟 ERROR 日志',
            selected_action=action,
            tool_calls=action['allowed_tools'],
        )
        selected_slugs = selection['trace']['selected_slugs']

        self.assertIn('answer-formatter', selected_slugs)
        self.assertIn('sx-log-query-guide', selected_slugs)
        self.assertIn('sx-log-field-dictionary', selected_slugs)
        self.assertNotIn('sx-k8s-troubleshooting', selected_slugs)
        self.assertLess(len(selected_slugs), len(runtime_context.active_skills))
        self.assertEqual(selection['trace']['prompt_skill_limit'], 6)

        prompt = _build_runtime_prompt(
            runtime_context.runtime_config,
            runtime_context.active_mcp_servers,
            selection['skills'],
            self.user,
            agent=runtime_context.agent,
            skill_prompt_trace=selection['trace'],
        )

        self.assertIn('按需注入 Skill：', prompt)
        self.assertIn('日志查询规范', prompt)
        self.assertIn('日志字段字典', prompt)
        self.assertNotIn('K8s 排障 SOP', prompt)
        self.assertNotIn('任务模板选择', prompt)

    def test_builtin_formatter_stage_reselects_skill_by_actual_tool_calls(self):
        config = get_agent_config()
        runtime_context = build_agent_runtime_context(self.user, config=config)

        selection = _select_runtime_skills(
            runtime_context.active_skills,
            question='继续分析刚才返回的日志样本',
            tool_calls=['query_logs'],
            max_count=5,
        )
        selected_slugs = selection['trace']['selected_slugs']

        self.assertIn('answer-formatter', selected_slugs)
        self.assertIn('sx-log-pattern-analysis', selected_slugs)
        self.assertNotIn('sx-k8s-alert-troubleshooting', selected_slugs)
        self.assertNotIn('sx-k8s-troubleshooting', selected_slugs)
        self.assertNotIn('sx-task-template-selection', selected_slugs)
        self.assertIn('query_logs', trace_item(selection, 'sx-log-pattern-analysis')['matched_tools'])

    def test_builtin_generic_hbase_question_does_not_inject_k8s_from_noise_keywords(self):
        config = get_agent_config()
        runtime_context = build_agent_runtime_context(self.user, config=config)

        selection = _select_runtime_skills(
            runtime_context.active_skills,
            question='本地 HBase 集群有几个节点，RegionServer 是否正常？',
        )
        selected_slugs = selection['trace']['selected_slugs']

        self.assertEqual(selected_slugs, ['answer-formatter'])
        self.assertFalse(trace_item(selection, 'sx-k8s-troubleshooting')['prompt_included'])
        self.assertFalse(trace_item(selection, 'sx-k8s-alert-troubleshooting')['prompt_included'])

    def test_builtin_generic_question_does_not_inject_domain_skill_from_chinese_fragments(self):
        config = get_agent_config()
        runtime_context = build_agent_runtime_context(self.user, config=config)

        selection = _select_runtime_skills(
            runtime_context.active_skills,
            question='这个问题怎么排查？',
        )

        self.assertEqual(selection['trace']['selected_slugs'], ['answer-formatter'])

    def test_builtin_explicit_k8s_question_still_injects_k8s_skills(self):
        config = get_agent_config()
        runtime_context = build_agent_runtime_context(self.user, config=config)

        selection = _select_runtime_skills(
            runtime_context.active_skills,
            question='K8s 集群 Pod Pending 怎么排查？',
        )
        selected_slugs = selection['trace']['selected_slugs']

        self.assertIn('sx-k8s-troubleshooting', selected_slugs)
        self.assertIn('sx-k8s-alert-troubleshooting', selected_slugs)

    def test_dispatch_runtime_uses_on_demand_builtin_skill_prompt_and_traces(self):
        get_agent_config()
        session = AIOpsChatSession.objects.create(
            user=self.user,
            title='skill runtime e2e',
            context={},
        )
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content='帮我查询 HBase RegionServer 最近 30 分钟 ERROR 日志',
        )
        log_action = _action_registry_item_by_code('log.query_generate', user=self.user)
        captured_payloads = []
        planning_calls = 0

        def fake_completion(provider, payload, **kwargs):
            nonlocal planning_calls
            captured_payloads.append(payload)
            if kwargs.get('purpose') == 'chat_planning':
                planning_calls += 1
                if planning_calls > 1:
                    return {
                        'choices': [{
                            'message': {
                                'content': '基于 query_logs 工具结果生成日志分析草稿。',
                            },
                        }],
                    }
                return {
                    'choices': [{
                        'message': {
                            'content': '',
                            'tool_calls': [{
                                'id': 'call-logs',
                                'type': 'function',
                                'function': {
                                    'name': 'query_logs',
                                    'arguments': '{"query":"RegionServer ERROR","duration_minutes":30,"limit":3}',
                                },
                            }],
                        },
                    }],
                }
            return {
                'choices': [{
                    'message': {
                        'content': '结论：命中 1 条日志。\n依据：query_logs 返回 RegionServer ERROR。\n建议操作：继续查看 RegionServer 状态。',
                    },
                }],
            }

        with (
            patch('aiops.services._provider_is_ready', return_value=True),
            patch('aiops.services._resolve_chat_environment', return_value={'status': 'resolved', 'environment': {'name': '本地 HBase 集群', 'aliases': []}}),
            patch('aiops.services._build_analysis_scope', return_value={'summary': {'node_count': 1}, 'services': ['hbase-regionserver']}),
            patch('aiops.services._select_action_for_question', return_value=log_action),
            patch('aiops.services.select_action_by_handler', return_value=log_action),
            patch('aiops.services._build_runtime_tool_registry', return_value=(
                [{'type': 'function', 'function': {'name': 'query_logs', 'description': 'query logs', 'parameters': {'type': 'object', 'properties': {}}}}],
                {'query_logs': {'kind': 'platform_mcp', 'tool_name': 'query_logs'}},
                [],
                [{'server_type': 'platform_builtin', 'status': 'connected', 'name': '平台内置 MCP', 'tool_count': 1}],
            )),
            patch('aiops.services._run_tool_call', return_value={
                'tool_output': {
                    'summary': {'count': 1, 'service': 'hbase-regionserver', 'duration_minutes': 30},
                    'logs': [{'message': 'RegionServer ERROR timeout'}],
                },
                'sections': [{'title': '日志结果', 'items': ['RegionServer ERROR timeout']}],
                'citations': [{'title': '日志中心', 'path': '/observability/logs'}],
                'message_type': AIOpsChatMessage.TYPE_ANALYSIS,
            }),
            patch('aiops.services._request_model_completion', side_effect=fake_completion),
        ):
            result = _dispatch_with_tool_runtime(
                session,
                user_message,
                self.user,
                user_message.content,
            )

        planning_prompt = captured_payloads[0]['messages'][0]['content']
        self.assertIn('按需注入 Skill：', planning_prompt)
        self.assertIn('日志查询规范', planning_prompt)
        self.assertIn('日志字段字典', planning_prompt)
        self.assertNotIn('K8s 排障 SOP', planning_prompt)
        self.assertNotIn('任务模板选择', planning_prompt)
        self.assertEqual(result['tool_calls'], ['query_logs'])
        planning_slugs = result['metadata']['planning_skill_trace']['selected_slugs']
        self.assertEqual(planning_slugs[0], 'answer-formatter')
        self.assertIn('sx-log-field-dictionary', planning_slugs)
        self.assertIn('sx-log-query-guide', planning_slugs)
        self.assertNotIn('sx-k8s-troubleshooting', planning_slugs)
        self.assertNotIn('sx-task-template-selection', planning_slugs)
        self.assertIn('formatter_skill_trace', result['metadata'])
        self.assertIn('skill_trace', result['metadata'])

    def test_dispatch_runtime_stops_repeated_same_tool_arguments(self):
        get_agent_config()
        session = AIOpsChatSession.objects.create(
            user=self.user,
            title='tool budget e2e',
            context={},
        )
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content='帮我查 HBase 最近日志',
        )
        log_action = _action_registry_item_by_code('log.query_generate', user=self.user)
        planning_calls = 0

        def fake_completion(provider, payload, **kwargs):
            nonlocal planning_calls
            if kwargs.get('purpose') == 'chat_planning':
                planning_calls += 1
                if planning_calls == 1:
                    return {
                        'choices': [{
                            'message': {
                                'content': '',
                                'tool_calls': [{
                                    'id': 'call-logs-1',
                                    'type': 'function',
                                    'function': {
                                        'name': 'query_logs',
                                        'arguments': '{"query":"hbase error","duration_minutes":30,"limit":3}',
                                    },
                                }],
                            },
                        }],
                    }
                if planning_calls == 2:
                    return {
                        'choices': [{
                            'message': {
                                'content': '',
                                'tool_calls': [{
                                    'id': 'call-logs-duplicate',
                                    'type': 'function',
                                    'function': {
                                        'name': 'query_logs',
                                        'arguments': '{"query":"hbase error","duration_minutes":30,"limit":3}',
                                    },
                                }],
                            },
                        }],
                    }
                return {
                    'choices': [{
                        'message': {
                            'content': '结论：已基于第一次 query_logs 结果收敛，不继续重复查询。',
                        },
                    }],
                }
            return {
                'choices': [{
                    'message': {
                        'content': '结论：命中 1 条日志。\n依据：query_logs 返回 HBase error。\n建议操作：检查 RegionServer。',
                    },
                }],
            }

        with (
            patch('aiops.services._provider_is_ready', return_value=True),
            patch('aiops.services._resolve_chat_environment', return_value={'status': 'resolved', 'environment': {'name': '本地 HBase 集群', 'aliases': []}}),
            patch('aiops.services._build_analysis_scope', return_value={'summary': {'node_count': 1}, 'services': ['hbase-regionserver']}),
            patch('aiops.services._select_action_for_question', return_value=log_action),
            patch('aiops.services.select_action_by_handler', return_value=log_action),
            patch('aiops.services._build_runtime_tool_registry', return_value=(
                [{'type': 'function', 'function': {'name': 'query_logs', 'description': 'query logs', 'parameters': {'type': 'object', 'properties': {}}}}],
                {'query_logs': {'kind': 'platform_mcp', 'tool_name': 'query_logs'}},
                [],
                [{'server_type': 'platform_builtin', 'status': 'connected', 'name': '平台内置 MCP', 'tool_count': 1}],
            )),
            patch('aiops.services._run_tool_call', return_value={
                'tool_output': {
                    'summary': {'count': 1, 'service': 'hbase-regionserver', 'duration_minutes': 30},
                    'logs': [{'message': 'HBase error'}],
                },
                'sections': [{'title': '日志结果', 'items': ['HBase error']}],
                'citations': [{'title': '日志中心', 'path': '/observability/logs'}],
                'message_type': AIOpsChatMessage.TYPE_ANALYSIS,
            }) as mocked_run_tool_call,
            patch('aiops.services._request_model_completion', side_effect=fake_completion),
        ):
            result = _dispatch_with_tool_runtime(
                session,
                user_message,
                self.user,
                user_message.content,
            )

        self.assertEqual(mocked_run_tool_call.call_count, 1)
        self.assertEqual(result['tool_calls'], ['query_logs'])
        self.assertEqual(result['metadata']['tool_budget']['total_calls'], 1)
        self.assertEqual(len(result['metadata']['tool_budget']['stops']), 1)
        self.assertIn('相同参数', result['metadata']['tool_budget']['stops'][0]['reason'])
