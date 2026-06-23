import json

from django.db.models import Q

from ops.models import HostTask

from .models import AIOpsChatMessage


EXCLUDED_HISTORY_PROCESSING_STATUSES = {'pending', 'running'}
FAILED_TASK_STATUSES = {'failed', 'partial'}


def _json_default(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _text_preview(value, limit=500):
    return str(value or '').replace('\n', ' ')[:limit]


def _compact_json(value, limit):
    try:
        text = json.dumps(value, ensure_ascii=False, default=_json_default)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit]


def build_history_messages(session, config, before_message=None):
    queryset = session.messages.order_by('-created_at', '-id')
    if before_message and getattr(before_message, 'id', None):
        queryset = queryset.filter(
            Q(created_at__lt=before_message.created_at)
            | Q(created_at=before_message.created_at, id__lt=before_message.id)
        )
    history = list(queryset[: max(getattr(config, 'max_history_messages', 4), 4)])
    history.reverse()
    return [
        {'role': item.role, 'content': item.content}
        for item in history
        if item.role in {AIOpsChatMessage.ROLE_USER, AIOpsChatMessage.ROLE_ASSISTANT}
        and str(item.content or '').strip()
        and (item.metadata or {}).get('processing_status') not in EXCLUDED_HISTORY_PROCESSING_STATUSES
    ]


def summarize_action_payload_for_memory(payload):
    payload = payload or {}
    command = ((payload.get('payload') or {}).get('command') or '').strip()
    target_hosts = payload.get('target_hosts') or []
    return {
        'name': payload.get('name') or '',
        'task_type': payload.get('task_type') or '',
        'execution_mode': payload.get('execution_mode') or '',
        'risk_level': payload.get('risk_level') or '',
        'host_count': payload.get('host_count') or len(target_hosts),
        'resource_ids': payload.get('resource_ids') or [],
        'command_preview': command[:500],
        'request_summary': payload.get('request_summary') or '',
    }


def _task_failed(task):
    return (
        task.status in FAILED_TASK_STATUSES
        or task.lifecycle_status in FAILED_TASK_STATUSES
        or (task.failed_count or 0) > 0
    )


def build_incident_context(memory):
    current_environment = memory.get('current_environment') or {}
    analysis_scope = memory.get('analysis_scope') or {}
    failed_tasks = [
        item
        for item in memory.get('recent_aiops_tasks') or []
        if item.get('status') in FAILED_TASK_STATUSES
        or item.get('lifecycle_status') in FAILED_TASK_STATUSES
        or (item.get('failed_count') or 0) > 0
    ]
    open_actions = [
        item
        for item in memory.get('recent_pending_actions') or []
        if item.get('status') in {'pending', 'waiting', 'created', 'draft'}
    ]
    last_evidence = []
    for fact in memory.get('recent_assistant_facts') or []:
        for tool_name in fact.get('tool_calls') or []:
            if tool_name not in last_evidence:
                last_evidence.append(tool_name)
    resource_scope = {
        'task_resource_environment_ids': analysis_scope.get('task_resource_environment_ids') or [],
        'k8s_cluster_ids': analysis_scope.get('k8s_cluster_ids') or [],
        'docker_host_ids': analysis_scope.get('docker_host_ids') or [],
        'metric_datasource_ids': analysis_scope.get('metric_datasource_ids') or [],
        'log_datasource_ids': analysis_scope.get('log_datasource_ids') or [],
        'tracing_datasource_ids': analysis_scope.get('tracing_datasource_ids') or [],
    }
    if failed_tasks:
        next_step = '先用 query_host_tasks 核对上次失败任务，再决定是否需要新的只读排查或任务草稿。'
    elif open_actions:
        next_step = '先说明待确认动作状态，只有用户明确确认后才能继续执行类动作。'
    elif resource_scope.get('task_resource_environment_ids'):
        next_step = '涉及主机、机器、节点、中间件或非 K8s 集群清单时，优先用 query_task_resources 查资源底座事实。'
    else:
        next_step = '根据问题选择最相关的只读工具收集证据后再回答。'
    return {
        'environment': current_environment.get('name') if isinstance(current_environment, dict) else current_environment,
        'resource_scope': resource_scope,
        'recent_user_intents': memory.get('recent_user_intents') or [],
        'last_evidence_tools': last_evidence[:8],
        'last_failed_task': failed_tasks[0] if failed_tasks else None,
        'open_pending_actions': open_actions[:3],
        'suggested_next_step': next_step,
    }


def build_session_memory_snapshot(session, *, limit=5):
    context = session.context if isinstance(getattr(session, 'context', None), dict) else {}
    memory = {
        'current_environment': context.get('current_environment') or {},
        'analysis_scope': context.get('analysis_scope') or {},
        'recent_user_intents': [],
        'recent_assistant_facts': [],
        'recent_pending_actions': [],
        'recent_aiops_tasks': [],
    }
    for message in session.messages.filter(role=AIOpsChatMessage.ROLE_USER).order_by('-created_at', '-id')[:limit]:
        if str(message.content or '').strip():
            memory['recent_user_intents'].append({
                'message_id': message.id,
                'content_preview': _text_preview(message.content, 300),
            })

    for message in session.messages.filter(role=AIOpsChatMessage.ROLE_ASSISTANT).order_by('-created_at', '-id')[:limit]:
        metadata = message.metadata or {}
        if metadata.get('processing_status') in EXCLUDED_HISTORY_PROCESSING_STATUSES:
            continue
        fact = {
            'message_id': message.id,
            'message_type': message.message_type,
            'execution_mode': metadata.get('execution_mode') or '',
            'tool_calls': message.tool_calls or [],
            'pending_action_id': metadata.get('pending_action_id'),
            'created_task_id': metadata.get('created_task_id'),
            'content_preview': _text_preview(message.content),
        }
        action_trace = metadata.get('action_trace') or {}
        if action_trace:
            fact['action_trace'] = action_trace
        if metadata.get('resource_base_summary'):
            fact['resource_base_summary'] = metadata.get('resource_base_summary')
        if metadata.get('incident_context'):
            fact['incident_context'] = metadata.get('incident_context')
        memory['recent_assistant_facts'].append(fact)

    for action in session.pending_actions.order_by('-created_at', '-id')[:limit]:
        memory['recent_pending_actions'].append({
            'id': action.id,
            'title': action.title,
            'status': action.status,
            'risk_level': action.risk_level,
            'action_type': action.action_type,
            'action_payload': summarize_action_payload_for_memory(action.action_payload),
            'result_payload': action.result_payload or {},
        })

    for task in HostTask.objects.filter(
        trigger_source=HostTask.TRIGGER_SOURCE_AIOPS,
        source_context__session_id=session.id,
    ).order_by('-created_at', '-id')[:limit]:
        executions = list(task.executions.order_by('id')[:10])
        memory['recent_aiops_tasks'].append({
            'id': task.id,
            'name': task.name,
            'status': task.status,
            'lifecycle_status': task.lifecycle_status,
            'task_type': task.task_type,
            'execution_mode': task.execution_mode,
            'target_count': task.target_count,
            'success_count': task.success_count,
            'failed_count': task.failed_count,
            'summary': task.summary,
            'request_summary': (task.source_context or {}).get('request_summary') or '',
            'payload': {
                'command_preview': str((task.payload or {}).get('command') or '')[:500],
                'script_kind': (task.payload or {}).get('script_kind') or '',
            },
            'executions': [
                {
                    'target': item.target_name or item.host_name or item.host_ip or item.target_id,
                    'status': item.status,
                    'error_message': item.error_message[:300],
                    'output_preview': item.output[:300],
                }
                for item in executions
            ],
        })
    memory['incident_context'] = build_incident_context(memory)
    return memory


def build_agent_context_prompt(knowledge_environment, analysis_scope, session_memory, scoped_question, collected_tool_outputs=None):
    incident_context = (session_memory or {}).get('incident_context') or {}
    return (
        '当前已确认知识图谱环境：'
        + ((knowledge_environment or {}).get('name') or '')
        + '\nanalysis_scope：'
        + _compact_json(analysis_scope or {}, 3000)
        + '\n事件上下文 incident_context：'
        + _compact_json(incident_context, 3000)
        + '\n会话短期记忆：'
        + _compact_json(session_memory or {}, 5000)
        + '\n用户问题：'
        + str(scoped_question or '')
        + '\n优先证据：'
        + _compact_json(collected_tool_outputs or [], 3000)
    )
