from django.test import SimpleTestCase

from aiops.services import _action_tool_filter_should_apply, _filter_runtime_tools_for_action


def tool_spec(name):
    return {'type': 'function', 'function': {'name': name, 'description': name, 'parameters': {'type': 'object'}}}


class ActionToolFilterTests(SimpleTestCase):
    def test_action_allowed_tools_filter_platform_registry(self):
        tools = [tool_spec('query_logs'), tool_spec('query_k8s_resources'), tool_spec('query_alerts')]
        registry = {
            'query_logs': {'kind': 'platform_mcp', 'tool_name': 'query_logs'},
            'query_k8s_resources': {'kind': 'platform_mcp', 'tool_name': 'query_k8s_resources'},
            'query_alerts': {'kind': 'platform_mcp', 'tool_name': 'query_alerts'},
        }
        action = {'code': 'log.query_generate', 'allowed_tools': ['query_logs']}

        filtered_tools, filtered_registry, trace = _filter_runtime_tools_for_action(tools, registry, action)

        self.assertEqual([item['function']['name'] for item in filtered_tools], ['query_logs'])
        self.assertEqual(set(filtered_registry.keys()), {'query_logs'})
        self.assertTrue(trace['enforced'])
        self.assertEqual(trace['action_code'], 'log.query_generate')
        self.assertEqual(trace['exposed_tools'], ['query_logs'])
        self.assertEqual(set(trace['blocked_tools']), {'query_k8s_resources', 'query_alerts'})

    def test_action_allowed_tools_match_external_raw_tool_name(self):
        tools = [tool_spec('mcp__hbase_monitor__cluster_status'), tool_spec('query_logs')]
        registry = {
            'mcp__hbase_monitor__cluster_status': {'kind': 'external', 'raw_tool_name': 'cluster_status'},
            'query_logs': {'kind': 'platform_mcp', 'tool_name': 'query_logs'},
        }
        action = {'code': 'hbase.inspect', 'allowed_tools': ['cluster_status']}

        filtered_tools, filtered_registry, trace = _filter_runtime_tools_for_action(tools, registry, action)

        self.assertEqual([item['function']['name'] for item in filtered_tools], ['mcp__hbase_monitor__cluster_status'])
        self.assertEqual(set(filtered_registry.keys()), {'mcp__hbase_monitor__cluster_status'})
        self.assertEqual(trace['exposed_tools'], ['mcp__hbase_monitor__cluster_status'])
        self.assertEqual(trace['blocked_tools'], ['query_logs'])

    def test_non_k8s_inventory_question_keeps_task_resource_route_available(self):
        action = {
            'code': 'k8s.diagnose',
            'allowed_tools': ['query_k8s_cluster_summary', 'query_k8s_resources'],
        }

        should_apply = _action_tool_filter_should_apply(action, '本地 HBase 集群有几个集群？有哪些节点？')

        self.assertFalse(should_apply)

    def test_task_generation_action_still_filters_non_k8s_inventory_question(self):
        action = {
            'code': 'host_task.generate',
            'allowed_tools': ['query_task_resources', 'generate_host_task'],
        }

        should_apply = _action_tool_filter_should_apply(action, '本地 HBase 集群生成一个巡检任务')

        self.assertTrue(should_apply)
