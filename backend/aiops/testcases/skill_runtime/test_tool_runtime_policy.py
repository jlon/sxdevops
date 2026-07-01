from django.test import SimpleTestCase

from aiops.tool_runtime_policy import ToolRuntimeBudget, build_tool_budget_prompt, tool_output_is_empty


class ToolRuntimePolicyTests(SimpleTestCase):
    def test_prompt_exposes_runtime_budget_rules(self):
        prompt = build_tool_budget_prompt(max_tool_calls=10)

        self.assertIn('最多调用 10 次工具', prompt)
        self.assertIn('连续 2 次返回空结果或错误', prompt)
        self.assertIn('同一工具不要调用超过 3 次', prompt)

    def test_empty_result_detection_uses_common_platform_shapes(self):
        self.assertTrue(tool_output_is_empty({'summary': {'count': 0}, 'logs': []}))
        self.assertTrue(tool_output_is_empty({'summary': {'series_count': 0}, 'series': []}))
        self.assertTrue(tool_output_is_empty({'error': 'timeout'}))
        self.assertFalse(tool_output_is_empty({'summary': {'count': 1}, 'logs': [{'message': 'error'}]}))
        self.assertFalse(tool_output_is_empty({'summary': {'series_count': 1}, 'series': [{'metric': 'up'}]}))
        self.assertFalse(tool_output_is_empty({'resources': [{'name': 'hbase-master'}]}))
        self.assertFalse(tool_output_is_empty({'structured': {'status': 'ok'}}))

    def test_budget_blocks_repeated_same_arguments_and_tool_overuse(self):
        budget = ToolRuntimeBudget(max_tool_calls=3, max_calls_per_tool=2)

        allowed, reason = budget.allow('query_logs', {'query': 'hbase'})
        self.assertTrue(allowed, reason)
        budget.record('query_logs', {'query': 'hbase'}, {'summary': {'count': 1}, 'logs': [{'message': 'x'}]})

        allowed, reason = budget.allow('query_logs', {'query': 'hbase'})
        self.assertFalse(allowed)
        self.assertIn('相同参数', reason)

        allowed, reason = budget.allow('query_logs', {'query': 'regionserver'})
        self.assertTrue(allowed, reason)
        budget.record('query_logs', {'query': 'regionserver'}, {'summary': {'count': 1}, 'logs': [{'message': 'x'}]})

        allowed, reason = budget.allow('query_logs', {'query': 'master'})
        self.assertFalse(allowed)
        self.assertIn('已调用 2 次', reason)

    def test_budget_stops_after_repeated_empty_results(self):
        budget = ToolRuntimeBudget(max_empty_results_per_tool=2)

        budget.record('query_traces', {'query': 'hbase'}, {'summary': {'trace_count': 0}, 'traces': []})
        allowed, reason = budget.allow('query_traces', {'query': 'hbase-rs'})
        self.assertTrue(allowed, reason)

        budget.record('query_traces', {'query': 'hbase-rs'}, {'summary': {'trace_count': 0}, 'traces': []})
        allowed, reason = budget.allow('query_traces', {'query': 'hbase-master'})
        self.assertFalse(allowed)
        self.assertIn('连续 2 次', reason)
