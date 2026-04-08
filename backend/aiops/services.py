import json
import re
import time
from collections import Counter
from decimal import Decimal

import requests
from django.db.models import Q
from django.utils import timezone

from cmdb.models import ConfigItem
from eventwall.models import EventRecord
from eventwall.services import record_event
from iac.models import TerraformExecution, TerraformStack
from multicloud.models import CloudAsset
from ops.host_tasks import start_host_task
from ops.models import Alert, Deployment, DockerHost, Host, HostTask, K8sCluster, LogDataSource, LogEntry, NginxEnvironment
from ops.observability_views import DEMO_TRACES
from rbac.services import user_has_permissions

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsToolInvocation,
)


DEFAULT_SUGGESTED_QUESTIONS = [
    '当前未确认的严重告警有哪些？',
    '生产环境有哪些离线主机？',
    '分析 payment-service 最近异常。',
    '生成一份 Redis 巡检任务。',
]

STOPWORDS = {
    '帮我', '一下', '当前', '最近', '平台', '资源', '信息', '告警', '分析', '排查', '问题',
    '哪些', '多少', '怎么', '情况', '查看', '查询', '生成', '执行', '触发', '自动', '任务', '中心',
}

DANGEROUS_COMMAND_PATTERNS = [
    'rm -rf',
    'shutdown',
    'reboot',
    'mkfs',
    'userdel',
    'kill -9',
]


def get_agent_config():
    config, _ = AIOpsAgentConfig.objects.get_or_create(
        name='default',
        defaults={
            'suggested_questions': DEFAULT_SUGGESTED_QUESTIONS,
            'system_prompt': (
                '你是 SxDevOps 平台内的 AIOps 智能助手。'
                '回答必须基于提供的结构化数据，不允许编造不存在的资源、告警或执行结果。'
                '请始终区分事实、推断和建议。'
            ),
        },
    )
    if not config.suggested_questions:
        config.suggested_questions = DEFAULT_SUGGESTED_QUESTIONS
        config.save(update_fields=['suggested_questions'])
    return config


def get_active_provider(config=None):
    config = config or get_agent_config()
    provider = config.default_provider
    if provider and provider.is_enabled:
        return provider
    return AIOpsModelProvider.objects.filter(is_enabled=True).order_by('id').first()


def bootstrap_payload_for_user(user):
    config = get_agent_config()
    provider = get_active_provider(config)
    return {
        'enabled': config.is_enabled and user_has_permissions(user, ['aiops.chat.view']),
        'welcome_message': config.welcome_message,
        'suggested_questions': config.suggested_questions or DEFAULT_SUGGESTED_QUESTIONS,
        'permissions': {
            'chat': user_has_permissions(user, ['aiops.chat.view']),
            'analyze': user_has_permissions(user, ['aiops.chat.analyze']),
            'generate_task': user_has_permissions(user, ['aiops.task.generate']),
            'execute_task': user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']),
            'config_view': user_has_permissions(user, ['aiops.config.view']),
            'config_manage': user_has_permissions(user, ['aiops.config.manage']),
        },
        'provider': {
            'name': provider.name if provider else '本地规则引擎',
            'model': provider.default_model if provider else '',
        },
        'runtime': {
            'allow_action_execution': config.allow_action_execution,
            'require_confirmation': config.require_confirmation,
            'show_evidence': config.show_evidence,
            'allow_analysis': config.allow_analysis,
        },
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _clean_tokens(text):
    chunks = re.split(r'[\s,，。！？；:：/\\|()\[\]{}]+', text or '')
    tokens = []
    for chunk in chunks:
        token = chunk.strip().strip('"\'')
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens[:6]


def _extract_environment(text):
    mapping = {
        '生产': 'prod',
        'prod': 'prod',
        '测试': 'test',
        'test': 'test',
        '开发': 'dev',
        'dev': 'dev',
    }
    lowered = (text or '').lower()
    for keyword, code in mapping.items():
        if keyword in lowered:
            return code
    return ''


def _contains_any(text, keywords):
    lowered = (text or '').lower()
    return any(keyword in lowered for keyword in keywords)


def infer_intent(text):
    lowered = (text or '').lower()
    if _contains_any(lowered, ['生成任务', '创建任务', '触发任务', '执行任务', '巡检', '批量命令', 'playbook', '执行命令']):
        return 'task'
    if _contains_any(lowered, ['分析', '排查', '根因', '异常', '故障', '关联']):
        return 'analysis'
    if _contains_any(lowered, ['告警', 'alert']):
        return 'alerts'
    return 'resources'


def _queryset_search(queryset, fields, tokens):
    if not tokens:
        return queryset
    condition = Q()
    for token in tokens:
        token_condition = Q()
        for field in fields:
            token_condition |= Q(**{f'{field}__icontains': token})
        condition &= token_condition
    return queryset.filter(condition)


def _create_tool_invocation(session, user_message, tool_name, request_payload):
    return AIOpsToolInvocation.objects.create(
        session=session,
        message=user_message,
        tool_name=tool_name,
        request_payload=request_payload,
    )


def _finish_tool_invocation(invocation, response_summary, started_at, success=True):
    invocation.status = AIOpsToolInvocation.STATUS_SUCCESS if success else AIOpsToolInvocation.STATUS_FAILED
    invocation.response_summary = response_summary
    invocation.latency_ms = max(int((time.time() - started_at) * 1000), 1)
    invocation.save(update_fields=['status', 'response_summary', 'latency_ms'])


def query_resources(session, user_message, user, question):
    started_at = time.time()
    tokens = _clean_tokens(question)
    environment = _extract_environment(question)
    invocation = _create_tool_invocation(session, user_message, 'query_resources', {'tokens': tokens, 'environment': environment})
    sections = []
    citations = []
    summary = {}

    if user_has_permissions(user, ['ops.host.view']):
        host_queryset = Host.objects.all()
        if environment:
            host_queryset = host_queryset.filter(environment=environment)
        host_queryset = _queryset_search(host_queryset, ['hostname', 'ip_address', 'business_line', 'admin_user', 'description'], tokens)
        hosts = list(host_queryset.order_by('-updated_at')[:6])
        if hosts:
            sections.append({
                'title': '主机资源',
                'items': [f'{host.hostname} ({host.ip_address}) - {host.get_status_display()}' for host in hosts],
            })
            summary['hosts'] = len(hosts)
            citations.append({'title': '主机中心', 'path': '/hosts/assets'})

    if user_has_permissions(user, ['cmdb.ci.view']):
        ci_queryset = ConfigItem.objects.select_related('ci_type').all()
        if environment:
            ci_queryset = ci_queryset.filter(environment=environment)
        ci_queryset = _queryset_search(ci_queryset, ['name', 'business_line', 'admin_user'], tokens)
        items = list(ci_queryset.order_by('-updated_at')[:6])
        if items:
            sections.append({
                'title': 'CMDB 配置项',
                'items': [f'{item.name} / {item.ci_type.name} / {item.get_status_display()}' for item in items],
            })
            summary['cmdb_items'] = len(items)
            citations.append({'title': 'CMDB', 'path': '/cmdb', 'query': {'tab': 'items'}})

    if user_has_permissions(user, ['ops.multicloud.view']):
        asset_queryset = CloudAsset.objects.select_related('environment').all()
        asset_queryset = _queryset_search(asset_queryset, ['name', 'resource_id', 'resource_type', 'region', 'vpc_name'], tokens)
        assets = list(asset_queryset.order_by('-updated_at')[:6])
        if assets:
            sections.append({
                'title': '多云资源',
                'items': [f'{asset.name} / {asset.resource_type} / {asset.get_status_display()}' for asset in assets],
            })
            summary['cloud_assets'] = len(assets)
            citations.append({'title': '多云环境', 'path': '/multicloud'})

    if user_has_permissions(user, ['ops.iac.view']):
        stack_queryset = _queryset_search(TerraformStack.objects.all(), ['name', 'description', 'region', 'zone'], tokens)
        stacks = list(stack_queryset.order_by('-updated_at')[:4])
        if stacks:
            sections.append({
                'title': 'IaC 方案',
                'items': [f'{stack.name} / {stack.get_cloud_provider_display()} / {stack.region}' for stack in stacks],
            })
            summary['iac_stacks'] = len(stacks)
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})

    if user_has_permissions(user, ['ops.k8s.view']):
        cluster_queryset = _queryset_search(K8sCluster.objects.all(), ['name', 'api_server', 'description'], tokens)
        clusters = list(cluster_queryset.order_by('-updated_at')[:5])
        if clusters:
            sections.append({
                'title': 'K8s 集群',
                'items': [f'{cluster.name} / {cluster.get_status_display()}' for cluster in clusters],
            })
            summary['k8s_clusters'] = len(clusters)
            citations.append({'title': 'K8s 集群', 'path': '/containers/k8s'})

    if user_has_permissions(user, ['ops.docker.view']):
        docker_queryset = _queryset_search(DockerHost.objects.all(), ['name', 'ip_address', 'description'], tokens)
        docker_hosts = list(docker_queryset.order_by('-updated_at')[:5])
        if docker_hosts:
            sections.append({
                'title': 'Docker 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in docker_hosts],
            })
            summary['docker_hosts'] = len(docker_hosts)
            citations.append({'title': 'Docker 环境', 'path': '/containers/docker'})

    if user_has_permissions(user, ['ops.nginx.view']):
        nginx_queryset = _queryset_search(NginxEnvironment.objects.all(), ['name', 'ip_address', 'description'], tokens)
        nginx_envs = list(nginx_queryset.order_by('-updated_at')[:5])
        if nginx_envs:
            sections.append({
                'title': 'Nginx 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in nginx_envs],
            })
            summary['nginx_envs'] = len(nginx_envs)
            citations.append({'title': 'Nginx 管理', 'path': '/middleware/nginx'})

    if user_has_permissions(user, ['ops.log.datasource.view']):
        datasource_queryset = _queryset_search(LogDataSource.objects.all(), ['name', 'provider', 'description'], tokens)
        datasources = list(datasource_queryset.order_by('-updated_at')[:5])
        if datasources:
            sections.append({
                'title': '日志数据源',
                'items': [f'{item.name} / {item.get_provider_display()} / {"启用" if item.is_enabled else "停用"}' for item in datasources],
            })
            summary['log_datasources'] = len(datasources)
            citations.append({'title': '日志数据源', 'path': '/logs/datasources'})

    response_summary = {'summary': summary, 'section_count': len(sections)}
    _finish_tool_invocation(invocation, response_summary, started_at, success=True)
    return {'summary': summary, 'sections': sections, 'citations': citations}


def query_alerts(session, user_message, user, question):
    started_at = time.time()
    tokens = _clean_tokens(question)
    invocation = _create_tool_invocation(session, user_message, 'query_alerts', {'tokens': tokens})
    if not user_has_permissions(user, ['ops.alert.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'error': '当前账号无权查看告警。', 'sections': [], 'citations': []}

    queryset = Alert.objects.select_related('host').all()
    if '未确认' in question:
        queryset = queryset.filter(is_acknowledged=False)
    if '严重' in question:
        queryset = queryset.filter(level='critical')
    queryset = _queryset_search(queryset, ['title', 'source', 'message', 'host__hostname'], tokens)
    alerts = list(queryset.order_by('-created_at')[:8])
    counter = Counter(alert.level for alert in alerts)
    sections = [{
        'title': '告警明细',
        'items': [
            f'{alert.get_level_display()} / {alert.title} / {alert.source} / {alert.host.hostname if alert.host else "无主机关联"}'
            for alert in alerts
        ],
    }] if alerts else []
    citations = [{'title': '告警中心', 'path': '/alerts'}]
    response_summary = {
        'count': len(alerts),
        'critical': counter.get('critical', 0),
        'warning': counter.get('warning', 0),
        'info': counter.get('info', 0),
    }
    _finish_tool_invocation(invocation, response_summary, started_at, success=True)
    return {'summary': response_summary, 'sections': sections, 'citations': citations, 'alerts': alerts}


def query_events(session, user_message, user, question):
    started_at = time.time()
    tokens = _clean_tokens(question)
    invocation = _create_tool_invocation(session, user_message, 'query_events', {'tokens': tokens})
    if not user_has_permissions(user, ['eventwall.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = EventRecord.objects.all()
    queryset = _queryset_search(queryset, ['title', 'summary', 'resource_name', 'application', 'module'], tokens)
    events = list(queryset.order_by('-occurred_at')[:8])
    sections = [{
        'title': '关键事件',
        'items': [f'{event.title} / {event.module} / {event.result}' for event in events],
    }] if events else []
    _finish_tool_invocation(invocation, {'count': len(events)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '事件总览', 'path': '/events/overview'}], 'events': events}


def query_logs(session, user_message, user, question):
    started_at = time.time()
    tokens = _clean_tokens(question)
    invocation = _create_tool_invocation(session, user_message, 'query_logs', {'tokens': tokens})
    allowed = user_has_permissions(user, ['ops.log.entry.view']) or user_has_permissions(user, ['ops.log.query'])
    if not allowed:
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = _queryset_search(LogEntry.objects.select_related('host').all(), ['service', 'message', 'host__hostname'], tokens)
    logs = list(queryset.order_by('-timestamp')[:6])
    sections = [{
        'title': '相关日志',
        'items': [f'{log.get_level_display()} / {log.service} / {log.message[:80]}' for log in logs],
    }] if logs else []
    _finish_tool_invocation(invocation, {'count': len(logs)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '日志中心', 'path': '/logs/query'}], 'logs': logs}


def query_traces(session, user_message, user, question):
    started_at = time.time()
    tokens = _clean_tokens(question)
    invocation = _create_tool_invocation(session, user_message, 'query_traces', {'tokens': tokens})
    if not user_has_permissions(user, ['ops.trace.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    traces = []
    for item in DEMO_TRACES:
        haystack = ' '.join([item['trace_id'], item['service_name'], item['summary'], *item['endpoint_names']]).lower()
        if tokens and not all(token.lower() in haystack for token in tokens):
            continue
        if '错误' in question or '异常' in question:
            if not item['is_error']:
                continue
        traces.append(item)
    traces = traces[:6]
    sections = [{
        'title': '链路追踪',
        'items': [f"{item['service_name']} / {item['state']} / {item['duration_ms']}ms / {item['summary']}" for item in traces],
    }] if traces else []
    _finish_tool_invocation(invocation, {'count': len(traces)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '链路追踪', 'path': '/observability/tracing'}], 'traces': traces}


def query_recent_changes(session, user_message, user):
    started_at = time.time()
    invocation = _create_tool_invocation(session, user_message, 'query_recent_changes', {})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.deployment.view']):
        deployments = list(Deployment.objects.order_by('-updated_at')[:5])
        if deployments:
            sections.append({
                'title': '最近发布',
                'items': [f'{item.app_name} / {item.version} / {item.get_status_display()}' for item in deployments],
            })
            citations.append({'title': '应用发布', 'path': '/deployments'})
    if user_has_permissions(user, ['ops.iac.view']):
        executions = list(TerraformExecution.objects.select_related('stack').order_by('-created_at')[:5])
        if executions:
            sections.append({
                'title': '最近 IaC 执行',
                'items': [f'{item.stack.name} / {item.get_action_display()} / {item.get_status_display()}' for item in executions],
            })
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': citations}


def build_markdown_answer(title, sections, citations, intro=''):
    lines = []
    if intro:
        lines.append(intro)
        lines.append('')
    if title:
        lines.append(f'**{title}**')
    for section in sections:
        lines.append(f"- {section['title']}：")
        for item in section.get('items', []):
            lines.append(f'  {item}')
    if citations:
        lines.append('')
        lines.append('可继续查看：' + '、'.join(item['title'] for item in citations))
    return '\n'.join(lines).strip()


def _summarize_for_model(question, intent, tool_payload):
    config = get_agent_config()
    provider = get_active_provider(config)
    if not provider or not provider.base_url or not provider.get_api_key() or not provider.default_model:
        return ''
    endpoint = provider.base_url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint = f'{endpoint}/chat/completions'
    prompt = {'question': question, 'intent': intent, 'tool_payload': tool_payload}
    try:
        response = requests.post(
            endpoint,
            headers={
                'Authorization': f'Bearer {provider.get_api_key()}',
                'Content-Type': 'application/json',
            },
            json={
                'model': provider.default_model,
                'temperature': provider.temperature,
                'max_tokens': provider.max_tokens,
                'messages': [
                    {'role': 'system', 'content': config.system_prompt},
                    {
                        'role': 'user',
                        'content': (
                            '请基于以下平台内结构化数据，用中文给出简洁可靠的回答。'
                            '回答要分清事实、推断和建议，不允许编造数据。\n'
                            f'{json.dumps(prompt, ensure_ascii=False, default=_json_default)}'
                        ),
                    },
                ],
            },
            timeout=max(provider.timeout_seconds, 5),
        )
        payload = response.json()
        if response.status_code >= 400:
            raise ValueError(payload)
        return (((payload or {}).get('choices') or [{}])[0].get('message') or {}).get('content', '').strip()
    except Exception:
        return ''


def build_task_draft(user, question):
    if not user_has_permissions(user, ['aiops.task.generate']):
        return {'error': '当前账号无权生成任务草稿。'}

    environment = _extract_environment(question)
    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if '离线' in question:
        host_queryset = host_queryset.filter(status='offline')
    host_ids = list(host_queryset.values_list('id', flat=True)[:20]) or list(Host.objects.values_list('id', flat=True)[:10])
    if not host_ids:
        return {'error': '当前没有可用主机，无法生成任务。'}

    task_type = HostTask.TASK_REFRESH_METRICS
    payload = {}
    execution_mode = HostTask.EXECUTION_MODE_SSH
    execution_strategy = HostTask.STRATEGY_CONTINUE
    timeout_seconds = 30
    title = '智能巡检任务'
    description = '由 AIOps 智能助手生成的任务草稿'

    service_match = re.search(r'(nginx|redis|rocketmq|mysql|docker|kubelet|sshd)', question, re.IGNORECASE)
    command_match = re.search(r'(?:执行|运行|命令)\s+([a-zA-Z0-9_\-./ ]{3,120})', question)

    if service_match:
        service_name = service_match.group(1)
        task_type = HostTask.TASK_SERVICE_STATUS
        payload = {'service_name': service_name}
        title = f'{service_name} 服务状态巡检'
        description = f'检查 {service_name} 服务状态'
    elif command_match:
        command = command_match.group(1).strip()
        task_type = HostTask.TASK_RUN_COMMAND
        payload = {'command': command}
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        execution_strategy = HostTask.STRATEGY_STOP_ON_ERROR
        title = f'批量命令执行：{command[:32]}'
        description = '由聊天助手从自然语言生成的批量命令任务'
    elif _contains_any(question, ['连通', '连通性', 'ssh']):
        task_type = HostTask.TASK_CHECK_CONNECTION
        title = 'SSH 连通性检查'
        description = '检查目标主机 SSH 连通性'
    elif _contains_any(question, ['playbook']):
        task_type = HostTask.TASK_RUN_PLAYBOOK
        payload = {
            'playbook_name': 'aiops_generated',
            'playbook_content': '- hosts: all\n  gather_facts: false\n  tasks:\n    - name: ping\n      ping:\n',
        }
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        title = 'Ansible Playbook 执行'
        description = '由 AIOps 智能助手生成的 Playbook 任务'

    risk_level = AIOpsPendingAction.RISK_LOW
    if task_type == HostTask.TASK_RUN_COMMAND:
        risk_level = AIOpsPendingAction.RISK_HIGH
        command = payload.get('command', '').lower()
        if any(pattern in command for pattern in DANGEROUS_COMMAND_PATTERNS):
            risk_level = AIOpsPendingAction.RISK_CRITICAL
    elif task_type == HostTask.TASK_RUN_PLAYBOOK:
        risk_level = AIOpsPendingAction.RISK_HIGH
    elif task_type == HostTask.TASK_SERVICE_STATUS:
        risk_level = AIOpsPendingAction.RISK_MEDIUM

    return {
        'name': title,
        'description': description,
        'task_type': task_type,
        'payload': payload,
        'host_ids': host_ids,
        'execution_mode': execution_mode,
        'execution_strategy': execution_strategy,
        'timeout_seconds': timeout_seconds,
        'host_count': len(host_ids),
        'risk_level': risk_level,
    }


def create_pending_task_action(session, assistant_message, user, question):
    draft = build_task_draft(user, question)
    if draft.get('error'):
        return None, draft['error']
    action = AIOpsPendingAction.objects.create(
        session=session,
        message=assistant_message,
        action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
        title=draft['name'],
        risk_level=draft['risk_level'],
        action_payload=draft,
    )
    return action, ''


def _execute_host_task_action(action, user, request=None):
    payload = dict(action.action_payload or {})
    host_ids = payload.get('host_ids') or []
    host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
    hosts = [host_map[item] for item in host_ids if item in host_map]
    if not hosts:
        raise ValueError('没有找到有效的目标主机。')

    task = HostTask.objects.create(
        name=payload.get('name') or 'AIOps 智能任务',
        task_type=payload.get('task_type') or HostTask.TASK_REFRESH_METRICS,
        description=payload.get('description', ''),
        payload=payload.get('payload') or {},
        selection_filters={'source': 'aiops', 'session_id': action.session_id},
        execution_mode=payload.get('execution_mode') or HostTask.EXECUTION_MODE_SSH,
        execution_strategy=payload.get('execution_strategy') or HostTask.STRATEGY_CONTINUE,
        timeout_seconds=payload.get('timeout_seconds') or 30,
        created_by=user.username,
        summary='任务已由 AIOps 智能助手创建，等待执行完成',
    )
    start_host_task(task, hosts)
    action.status = AIOpsPendingAction.STATUS_EXECUTED
    action.result_payload = {'task_id': task.id, 'task_name': task.name}
    action.save(update_fields=['status', 'result_payload', 'updated_at'])
    record_event(
        request=request,
        module='aiops',
        category='execution',
        action='confirm_execute_task',
        title='AIOps 执行主机任务',
        summary=f'已通过 AIOps 执行主机任务 {task.name}',
        resource_type='aiops_action',
        resource_id=action.id,
        resource_name=action.title,
        correlation_id=f'aiops-action:{action.id}',
        related_resources=[{'module': 'ops', 'type': 'host_task', 'id': str(task.id), 'name': task.name}],
        metadata={'host_count': len(hosts), 'created_by': user.username},
    )
    return task


def confirm_action(action, user, request=None):
    config = get_agent_config()
    if not config.allow_action_execution:
        raise ValueError('管理员已关闭机器人动作执行。')
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可确认。')
    if action.session.user_id != user.id:
        raise ValueError('只能确认自己的动作。')
    if action.action_type == AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK:
        if not user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
            raise ValueError('当前账号无权执行机器人任务。')
        action.status = AIOpsPendingAction.STATUS_CONFIRMED
        action.confirmed_by = user.username
        action.confirmed_at = timezone.now()
        action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
        return _execute_host_task_action(action, user, request=request)
    raise ValueError('不支持的动作类型。')


def cancel_action(action, user):
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可取消。')
    if action.session.user_id != user.id:
        raise ValueError('只能取消自己的动作。')
    action.status = AIOpsPendingAction.STATUS_CANCELED
    action.confirmed_by = user.username
    action.confirmed_at = timezone.now()
    action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
    return action


def dispatch_chat(session, user_message, user, question):
    config = get_agent_config()
    intent = infer_intent(question)
    citations = []
    sections = []
    intro = ''
    pending_action = None
    message_type = AIOpsChatMessage.TYPE_TEXT
    tool_payload = {}
    draft = None

    if intent == 'resources':
        resource_payload = query_resources(session, user_message, user, question)
        sections.extend(resource_payload['sections'])
        citations.extend(resource_payload['citations'])
        tool_payload = resource_payload
        intro = '已根据当前账号可见的资源范围整理平台信息。'
    elif intent == 'alerts':
        alert_payload = query_alerts(session, user_message, user, question)
        if alert_payload.get('error'):
            intro = alert_payload['error']
        sections.extend(alert_payload['sections'])
        citations.extend(alert_payload['citations'])
        tool_payload = alert_payload
        intro = intro or '已整理相关告警信息。'
    elif intent == 'analysis':
        message_type = AIOpsChatMessage.TYPE_ANALYSIS
        if not user_has_permissions(user, ['aiops.chat.analyze']):
            intro = '当前账号无权使用关联分析能力。'
            tool_payload = {'error': 'missing aiops.chat.analyze'}
        else:
            alert_payload = query_alerts(session, user_message, user, question)
            event_payload = query_events(session, user_message, user, question)
            log_payload = query_logs(session, user_message, user, question)
            trace_payload = query_traces(session, user_message, user, question)
            change_payload = query_recent_changes(session, user_message, user)
            sections.extend(alert_payload.get('sections', []))
            sections.extend(event_payload.get('sections', []))
            sections.extend(log_payload.get('sections', []))
            sections.extend(trace_payload.get('sections', []))
            sections.extend(change_payload.get('sections', []))
            citations.extend(alert_payload.get('citations', []))
            citations.extend(event_payload.get('citations', []))
            citations.extend(log_payload.get('citations', []))
            citations.extend(trace_payload.get('citations', []))
            citations.extend(change_payload.get('citations', []))
            intro = '已结合告警、事件、日志、链路和最近变更做初步关联分析。'
            tool_payload = {
                'alerts': alert_payload.get('summary', {}),
                'events': len(event_payload.get('events', [])),
                'logs': len(log_payload.get('logs', [])),
                'traces': len(trace_payload.get('traces', [])),
            }
    else:
        message_type = AIOpsChatMessage.TYPE_ACTION
        draft = build_task_draft(user, question)
        if draft.get('error'):
            intro = draft['error']
            tool_payload = draft
        else:
            sections.append({
                'title': '任务草稿',
                'items': [
                    f"任务名称：{draft['name']}",
                    f"任务类型：{draft['task_type']}",
                    f"目标主机：{draft['host_count']} 台",
                    f"执行方式：{draft['execution_mode']}",
                    f"执行策略：{draft['execution_strategy']}",
                ],
            })
            if draft.get('payload', {}).get('command'):
                sections.append({'title': '命令内容', 'items': [draft['payload']['command']]})
            if draft.get('payload', {}).get('service_name'):
                sections.append({'title': '服务名', 'items': [draft['payload']['service_name']]})
            citations.append({'title': '任务中心', 'path': '/hosts/tasks'})
            intro = '已生成任务草稿。确认后将调用现有任务中心执行。'
            tool_payload = draft

    llm_answer = _summarize_for_model(question, intent, tool_payload)
    assistant_message = AIOpsChatMessage.objects.create(
        session=session,
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        message_type=message_type,
        content=llm_answer or build_markdown_answer('智能助手回复', sections, citations, intro=intro),
        citations=citations,
        tool_calls=[item.tool_name for item in session.tool_invocations.filter(message=user_message).order_by('created_at')],
    )

    if intent == 'task' and draft and not draft.get('error'):
        if not config.allow_action_execution:
            assistant_message.metadata = {'action_execution_disabled': True}
            assistant_message.save(update_fields=['metadata'])
        else:
            action, error = create_pending_task_action(session, assistant_message, user, question)
            if not error:
                pending_action = action
                assistant_message.metadata = {'pending_action_id': action.id}
                assistant_message.save(update_fields=['metadata'])
                if not config.require_confirmation and user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
                    try:
                        task = confirm_action(action, user)
                        pending_action.refresh_from_db()
                        assistant_message.content = (
                            f"{assistant_message.content}\n\n已根据当前配置自动执行任务：{task.name}（#{task.id}）。"
                        )
                        assistant_message.save(update_fields=['content'])
                    except ValueError:
                        pending_action.refresh_from_db()

    session.last_message_at = timezone.now()
    if session.title == '新会话':
        session.title = (question or '新会话')[:48]
    session.save(update_fields=['last_message_at', 'title', 'updated_at'])
    return assistant_message, pending_action


def build_audit_overview():
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        'sessions_today': AIOpsChatSession.objects.filter(created_at__gte=today_start).count(),
        'messages_today': AIOpsChatMessage.objects.filter(created_at__gte=today_start).count(),
        'actions_today': AIOpsPendingAction.objects.filter(created_at__gte=today_start).count(),
        'failed_actions_today': AIOpsPendingAction.objects.filter(
            created_at__gte=today_start,
            status=AIOpsPendingAction.STATUS_FAILED,
        ).count(),
        'providers_total': AIOpsModelProvider.objects.count(),
        'mcp_total': AIOpsMCPServer.objects.filter(is_enabled=True).count(),
    }
