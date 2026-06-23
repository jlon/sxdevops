from django.test import SimpleTestCase

from aiops.routing_policy import (
    build_routing_constraints,
    selected_action_should_preempt_llm,
    should_defer_direct_route_to_llm,
)


class RoutingPolicyE2ETests(SimpleTestCase):
    def test_read_only_inventory_question_delegates_to_llm_with_tool_constraints_when_provider_ready(self):
        question = '使用本地 HBase 集群环境继续分析：再看看有几个集群？'
        selected_action = {'code': 'k8s.diagnose', 'display_name': 'K8s 诊断'}

        self.assertFalse(
            selected_action_should_preempt_llm(
                question,
                selected_action,
                provider_ready=True,
            )
        )
        self.assertTrue(
            should_defer_direct_route_to_llm(
                question,
                provider_ready=True,
                route_name='direct_k8s_resource_lookup',
            )
        )

        constraints = build_routing_constraints(question)
        self.assertTrue(any('query_task_resources' in item for item in constraints))
        self.assertTrue(any('不要调用 K8s 工具' in item for item in constraints))

    def test_mutation_action_still_preempts_llm_for_safety(self):
        question = '给这些主机生成巡检任务并执行'
        selected_action = {'code': 'host_task.generate', 'display_name': '生成任务'}

        self.assertTrue(
            selected_action_should_preempt_llm(
                question,
                selected_action,
                provider_ready=True,
            )
        )
        self.assertFalse(
            should_defer_direct_route_to_llm(
                question,
                provider_ready=True,
                route_name='direct_task_resource_lookup',
            )
        )
