import re


LOOKUP_WORDS = {
    '几个', '几台', '多少', '数量', '有哪些', '哪些', '列表', '清单',
    '查看', '查看下', '看下', '看一下', '查询', '列出', '当前', '全部', '所有',
    '状态', '情况',
}

MUTATION_WORDS = {
    '生成', '创建', '新建', '安排', '发起', '执行', '运行', '重启', '扩容',
    '缩容', '删除', '修改', '更新', '变更', '调整', '更改', '设置', '改成',
    '改为', '安装', '部署', '初始化', 'patch', 'apply', 'scale', 'restart',
    'delete', 'change', 'update', 'set', 'install', 'deploy',
}

NON_K8S_INVENTORY_WORDS = {
    '资源底座', '任务中心资源', '机器', '主机', '服务器', '宿主机',
    '节点', 'node', 'nodes', '中间件', 'hbase', 'redis', 'mysql',
}

GENERIC_CLUSTER_WORDS = {'集群', 'cluster', 'clusters'}

K8S_SCOPE_WORDS = {
    'k8s', 'kubernetes', 'pod', 'pods', 'namespace', '命名空间',
    'deployment', 'deployments', 'statefulset', 'statefulsets',
    'daemonset', 'daemonsets', 'workload', 'workloads', 'svc',
    'service', 'services', 'kubectl', 'helm',
}


def _contains_any(text, words):
    lowered = str(text or '').lower()
    return any(word in lowered for word in words)


def has_mutation_intent(question):
    return _contains_any(question, MUTATION_WORDS)


def has_explicit_k8s_scope(question):
    return _contains_any(question, K8S_SCOPE_WORDS)


def is_resource_inventory_question(question):
    text = str(question or '')
    lowered = text.lower()
    has_lookup = _contains_any(lowered, LOOKUP_WORDS)
    has_inventory_scope = _contains_any(lowered, NON_K8S_INVENTORY_WORDS) or _contains_any(lowered, GENERIC_CLUSTER_WORDS)
    return has_lookup and has_inventory_scope and not has_mutation_intent(text)


def is_non_k8s_inventory_question(question):
    text = str(question or '')
    if not is_resource_inventory_question(text):
        return False
    if has_explicit_k8s_scope(text):
        return False
    return _contains_any(text, NON_K8S_INVENTORY_WORDS) or _contains_any(text, GENERIC_CLUSTER_WORDS)


def should_use_task_resource_fallback(question, *, provider_ready, knowledge_environment=None, analysis_scope=None):
    knowledge_environment = knowledge_environment or {}
    analysis_scope = analysis_scope or {}
    scoped_resource_envs = (
        knowledge_environment.get('task_resource_environment_ids')
        or analysis_scope.get('task_resource_environment_ids')
        or []
    )
    if not scoped_resource_envs:
        return False
    if provider_ready:
        return False
    return is_non_k8s_inventory_question(question)


def should_defer_direct_route_to_llm(question, *, provider_ready, route_name='', selected_action_code=''):
    if not provider_ready:
        return False
    if has_mutation_intent(question):
        return False
    if route_name in {'direct_task_resource_lookup'}:
        return True
    if route_name in {'direct_k8s_resource_lookup', 'direct_container_fastpath'}:
        return is_resource_inventory_question(question) and not has_explicit_k8s_scope(question)
    if selected_action_code and selected_action_code not in {'host_task.generate'}:
        return is_resource_inventory_question(question) and not has_explicit_k8s_scope(question)
    return False


def selected_action_should_preempt_llm(question, selected_action=None, *, provider_ready=False):
    if not selected_action:
        return False
    code = selected_action.get('code') or ''
    if code == 'host_task.generate':
        return True
    if should_defer_direct_route_to_llm(question, provider_ready=provider_ready, selected_action_code=code):
        return False
    return True


def build_routing_constraints(question, *, session_memory=None, analysis_only=False):
    constraints = []
    memory = session_memory or {}
    incident = memory.get('incident_context') or {}
    if any(keyword in str(question or '') for keyword in ['前面', '上次', '刚才', '之前', '执行失败', '失败了', '没成功']):
        constraints.append(
            '上下文约束：本轮是追问。必须先利用 incident_context、recent_aiops_tasks、recent_pending_actions 和 recent_assistant_facts 识别上次任务/命令/失败对象；如果需要实时状态，优先调用 query_host_tasks。不要把“执行失败了/解决下”当作新的 shell 命令内容。'
        )
    if incident.get('last_failed_task'):
        constraints.append(
            '事件上下文约束：检测到最近 AIOps 任务失败。回答必须先引用失败任务和失败目标；需要补充实时任务状态时调用 query_host_tasks。'
        )
    lowered = str(question or '').lower()
    if any(keyword in lowered for keyword in ['链路追踪', '调用链', 'trace', 'tracing']):
        constraints.append(
            '路由约束：本问题明确限定在链路追踪/Trace/调用链中排查服务异常，必须调用 query_traces；不要改用 query_alerts。query 参数只传服务名或 traceId，若用户问异常/错误则 errors_only=true。'
        )
    if any(keyword in lowered for keyword in ['日志', 'log', 'logs', 'loki', 'elk', 'sls']):
        constraints.append(
            '路由约束：本问题明确限定在日志中查询或分析，必须调用 query_logs；不要先调用 query_alerts。若用户同时提到警告和错误，使用 levels=["warning","error"]。'
        )
    if is_non_k8s_inventory_question(question):
        constraints.append(
            '资源路由约束：用户询问的是主机、机器、节点、中间件或泛称“集群”的数量/清单；除非用户明确提到 K8s/Kubernetes/Pod/命名空间/Deployment/Service/kubectl/Helm，否则必须优先调用 query_task_resources，不要调用 K8s 工具。'
        )
    if analysis_only:
        constraints.append(
            '请求约束：本轮为只分析模式，只能做查询、分析、解释和建议；禁止生成、创建、新建、安排待执行任务，禁止调用 generate_host_task。'
        )
    return constraints
