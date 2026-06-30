from datetime import datetime, timedelta, time as datetime_time

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import pagination, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.models import EventRecord
from eventwall.services import record_event
from ops.models import Alert, DockerHost, GrafanaSetting, HostTask, K8sCluster, LogDataSource, MetricDataSource, ObservabilityDataSourceLink, TaskResource, TaskResourceGroup, TracingDataSource
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import is_demo_account, user_has_permissions

from .models import (
    AIOpsAgentProfile,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsExternalTask,
    AIOpsIncident,
    AIOpsIncidentAction,
    AIOpsKnowledgeEnvironment,
    AIOpsMCPServer,
    AIOpsModelInvocation,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsReviewKnowledge,
    AIOpsRunbook,
    AIOpsRunbookVersion,
    AIOpsSkill,
    AIOpsToolInvocation,
)
from .action_handlers import normalize_page_context
from .serializers import (
    AIOpsAgentConfigSerializer,
    AIOpsAgentProfileSerializer,
    AIOpsAuditSessionSerializer,
    AIOpsAuditTraceReader,
    AIOpsChatInputSerializer,
    AIOpsChatMessageSerializer,
    AIOpsChatSessionSerializer,
    AIOpsCreateSessionSerializer,
    AIOpsExternalTaskSerializer,
    AIOpsIncidentListSerializer,
    AIOpsIncidentSerializer,
    AIOpsKnowledgeEnvironmentSerializer,
    AIOpsMCPServerSerializer,
    AIOpsModelInvocationSerializer,
    AIOpsModelProviderSerializer,
    AIOpsPendingActionSerializer,
    AIOpsReviewKnowledgeSerializer,
    AIOpsRunbookSerializer,
    AIOpsRunbookVersionSerializer,
    AIOpsSkillSerializer,
    AIOpsToolInvocationSerializer,
)
from .services import (
    _ensure_task_draft_title,
    archive_runbook,
    auto_ingest_incident_review_knowledge,
    auto_ingest_review_knowledge,
    bind_runtime_resource_to_agents,
    build_action_preflight_contract,
    build_incident_runbook_draft,
    build_incident_chat_suggested_question,
    build_platform_mcp_manifest,
    build_action_registry_summary,
    agent_runtime_payload_for_user,
    bootstrap_payload_for_user,
    build_audit_overview,
    build_model_cost_overview,
    build_runbook_draft_from_payload,
    build_runbook_draft_from_session,
    build_skill_marketplace_catalog,
    cancel_action,
    cancel_external_task,
    clone_skill_to_team,
    confirm_action,
    create_incident_skill_pending_action,
    create_external_task,
    dispatch_chat,
    ensure_default_agent_profile,
    _apply_dispatch_result_to_message,
    _build_lightweight_chat_result,
    _is_canned_lightweight_chat_question,
    get_agent_config,
    get_or_create_incident_chat_session,
    resolve_agent_profile_for_user,
    resolve_agent_chat_environment,
    runtime_config_for_agent,
    interrupt_external_task,
    invoke_platform_mcp_tool,
    list_model_provider_models,
    list_model_provider_presets,
    list_mcp_server_tools,
    list_action_registry,
    list_platform_mcp_tools,
    publish_runbook,
    recover_masked_suggested_question,
    run_external_task_orchestration,
    start_async_chat_processing,
    sync_admin_sessions_to_demo,
    sync_session_to_demo_if_needed,
    test_model_provider_connection,
    test_mcp_server_connection,
    DEPRECATED_BUILTIN_MCP_SERVER_NAMES,
)
from .incident_investigation import run_readonly_investigation
from .knowledge_graph import build_knowledge_graph

K8S_NAMESPACE_OPTIONS_CACHE_TTL = 60
K8S_NAMESPACE_OPTIONS_STALE_CACHE_TTL = 300
AUDIT_RECENT_PAGE_SIZE = 20


DEMO_CHAT_DISABLED_MESSAGE = '演示账号问答权限已临时关闭，如需体验请联系作者：592095766@qq.com'


def _request_includes_agent_binding(request):
    return isinstance(getattr(request, 'data', None), dict) and 'bind_agent_ids' in request.data


def _request_bind_agent_ids(request):
    if not _request_includes_agent_binding(request):
        return None
    value = request.data.get('bind_agent_ids')
    if value in (None, ''):
        return []
    if not isinstance(value, list):
        raise ValidationError({'bind_agent_ids': '必须为数组'})
    normalized = []
    for item in value:
        try:
            agent_id = int(item)
        except (TypeError, ValueError):
            raise ValidationError({'bind_agent_ids': 'Agent ID 必须为正整数'})
        if agent_id <= 0:
            raise ValidationError({'bind_agent_ids': 'Agent ID 必须为正整数'})
        if agent_id > 0 and agent_id not in normalized:
            normalized.append(agent_id)
    existing_ids = set(AIOpsAgentProfile.objects.filter(id__in=normalized).values_list('id', flat=True))
    missing_ids = [item for item in normalized if item not in existing_ids]
    if missing_ids:
        raise ValidationError({'bind_agent_ids': f'Agent 不存在: {", ".join(str(item) for item in missing_ids)}'})
    return normalized


def _assert_agent_binding_permission(request):
    if _request_includes_agent_binding(request) and not user_has_permissions(request.user, ['aiops.agent.manage']):
        raise PermissionDenied('绑定 Agent 需要 aiops.agent.manage 权限')


def _incident_action_approval_session(user, incident):
    title = f'Incident #{incident.id} 审批'
    session = AIOpsChatSession.objects.filter(user=user, title=title).order_by('id').first()
    if session:
        return session
    return AIOpsChatSession.objects.create(
        user=user,
        title=title,
        context={
            'source': 'incident',
            'incident_id': incident.id,
            'environment': incident.environment,
            'cluster': incident.cluster,
            'namespace': incident.namespace,
            'service': incident.service,
        },
    )


def _incident_action_task_draft(incident, incident_action):
    payload = incident_action.action_payload if isinstance(incident_action.action_payload, dict) else {}
    draft = payload.get('task_draft') if isinstance(payload.get('task_draft'), dict) else payload
    task_type = draft.get('task_type') or ''
    target_type = draft.get('target_type') or ''
    task_payload = draft.get('payload') if isinstance(draft.get('payload'), dict) else {}
    has_targets = bool(draft.get('target_refs') or draft.get('host_ids') or draft.get('resource_ids') or draft.get('k8s_targets'))
    if not task_type:
        raise ValidationError({'detail': '建议动作缺少任务类型，不能生成审批草案。'})
    if not target_type:
        raise ValidationError({'detail': '建议动作缺少目标类型，不能生成审批草案。'})
    if not task_payload:
        raise ValidationError({'detail': '建议动作缺少任务载荷，不能生成审批草案。'})
    if not has_targets:
        raise ValidationError({'detail': '建议动作缺少目标资源，不能生成审批草案。'})
    draft = {
        **draft,
        'name': draft.get('name') or incident_action.title or f'Incident #{incident.id} 处置任务',
        'description': draft.get('description') or f'由 Incident #{incident.id} 建议动作生成的待确认任务。',
        'risk_level': draft.get('risk_level') or incident_action.risk_level,
        'request_summary': draft.get('request_summary') or incident_action.title or incident.title,
        'reason': draft.get('reason') or f'incident_action:{incident_action.id}',
        'resource_environment': draft.get('resource_environment') or incident.environment,
        'environment_name': draft.get('environment_name') or incident.environment,
        'knowledge_environment': draft.get('knowledge_environment') or incident.environment,
        'incident_id': incident.id,
        'incident_action_id': incident_action.id,
    }
    return _ensure_task_draft_title(draft)


class AIOpsModelProviderViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AIOpsModelProvider.objects.all()
    serializer_class = AIOpsModelProviderSerializer
    pagination_class = None
    search_fields = ['name', 'provider_type', 'base_url', 'default_model']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
        'test_connection': ['aiops.config.manage'],
        'list_models': ['aiops.config.manage'],
        'presets': ['aiops.config.view'],
    }

    def perform_create(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('provider', instance.id, bind_agent_ids, replace_existing=True)

    def perform_update(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('provider', instance.id, bind_agent_ids, replace_existing=True)

    @action(detail=False, methods=['get'])
    def presets(self, request):
        return Response({'presets': list_model_provider_presets()})

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        provider = self.get_object()
        try:
            result = test_model_provider_connection(provider)
            provider.last_test_status = (
                AIOpsModelProvider.STATUS_SUCCESS
                if result.get('status') == 'success'
                else AIOpsModelProvider.STATUS_FAILED
            )
            provider.last_test_message = result.get('message') or '模型测试完成'
            payload = result
            status_code = status.HTTP_200_OK if result.get('status') == 'success' else status.HTTP_400_BAD_REQUEST
        except Exception as exc:
            provider.last_test_status = AIOpsModelProvider.STATUS_FAILED
            provider.last_test_message = str(exc)[:255]
            payload = {'status': 'failed', 'message': str(exc)}
            status_code = status.HTTP_400_BAD_REQUEST
        provider.save(update_fields=['last_test_status', 'last_test_message', 'updated_at'])
        return Response(payload, status=status_code)

    @action(detail=True, methods=['get'], url_path='models')
    def list_models(self, request, pk=None):
        provider = self.get_object()
        probe = str(request.query_params.get('probe', 'true')).lower() not in {'0', 'false', 'no'}
        try:
            return Response(list_model_provider_models(provider, probe=probe))
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.config.view')])
def model_provider_presets(request):
    return Response({'presets': list_model_provider_presets()})


class AIOpsAgentProfileViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsAgentProfileSerializer
    pagination_class = None
    search_fields = ['name', 'slug', 'description']
    rbac_permissions = {
        'list': ['aiops.agent.view'],
        'retrieve': ['aiops.agent.view'],
        'create': ['aiops.agent.manage'],
        'update': ['aiops.agent.manage'],
        'partial_update': ['aiops.agent.manage'],
        'destroy': ['aiops.agent.manage'],
        'set_default': ['aiops.agent.manage'],
        'runtime': ['aiops.chat.view'],
    }

    def get_queryset(self):
        ensure_default_agent_profile(get_agent_config())
        return AIOpsAgentProfile.objects.select_related('default_provider', 'default_knowledge_environment').order_by('-is_default', 'name', 'id')

    @action(detail=True, methods=['get'])
    def runtime(self, request, pk=None):
        agent = self.get_object()
        try:
            return Response(agent_runtime_payload_for_user(request.user, agent.slug))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)

    def perform_create(self, serializer):
        is_default = bool(serializer.validated_data.get('is_default'))
        with transaction.atomic():
            default_agent = ensure_default_agent_profile(get_agent_config())
            seed_fields = {}
            if not serializer.validated_data.get('default_provider') and default_agent.default_provider_id:
                seed_fields['default_provider'] = default_agent.default_provider
            if not serializer.validated_data.get('default_knowledge_environment') and default_agent.default_knowledge_environment_id:
                seed_fields['default_knowledge_environment'] = default_agent.default_knowledge_environment
            for field in ['system_prompt', 'welcome_message']:
                if not serializer.validated_data.get(field) and getattr(default_agent, field, ''):
                    seed_fields[field] = getattr(default_agent, field)
            for field in ['suggested_questions', 'enabled_mcp_server_ids', 'enabled_skill_ids', 'allowed_knowledge_environment_ids']:
                if not serializer.validated_data.get(field) and getattr(default_agent, field, None):
                    seed_fields[field] = list(getattr(default_agent, field) or [])
            if is_default:
                AIOpsAgentProfile.objects.update(is_default=False)
            serializer.save(**seed_fields, created_by=self.request.user.username, updated_by=self.request.user.username)

    def perform_update(self, serializer):
        is_default = bool(serializer.validated_data.get('is_default'))
        with transaction.atomic():
            if is_default:
                AIOpsAgentProfile.objects.exclude(pk=serializer.instance.pk).update(is_default=False)
            serializer.save(updated_by=self.request.user.username)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_builtin:
            return Response({'detail': '内置 Agent 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        if instance.is_default:
            return Response({'detail': '默认 Agent 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        instance = self.get_object()
        if not instance.is_enabled:
            return Response({'detail': '停用 Agent 不能设为默认'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            AIOpsAgentProfile.objects.exclude(pk=instance.pk).update(is_default=False)
            instance.is_default = True
            instance.updated_by = request.user.username
            instance.save(update_fields=['is_default', 'updated_by', 'updated_at'])
        return Response(self.get_serializer(instance).data)


class AIOpsMCPServerViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsMCPServerSerializer
    pagination_class = None
    search_fields = ['name', 'description', 'endpoint_or_command']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
        'test_connection': ['aiops.config.manage'],
        'list_tools': ['aiops.config.manage'],
    }

    def perform_create(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('mcp', instance.id, bind_agent_ids, replace_existing=True)

    def perform_update(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('mcp', instance.id, bind_agent_ids, replace_existing=True)

    def get_queryset(self):
        get_agent_config()
        return AIOpsMCPServer.objects.exclude(name__in=DEPRECATED_BUILTIN_MCP_SERVER_NAMES).order_by('is_builtin', 'name', 'id')

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        server = self.get_object()
        try:
            result = test_mcp_server_connection(server)
            return Response(result)
        except Exception as exc:
            return Response({'status': 'failed', 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def list_tools(self, request, pk=None):
        server = self.get_object()
        try:
            result = list_mcp_server_tools(server)
            return Response(result)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_builtin:
            return Response({'detail': '内置 MCP 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class AIOpsSkillViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsSkillSerializer
    pagination_class = None
    search_fields = ['name', 'slug', 'description']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
        'marketplace': ['aiops.config.view'],
        'clone': ['aiops.config.manage'],
    }

    def perform_create(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('skill', instance.id, bind_agent_ids, replace_existing=True)

    def perform_update(self, serializer):
        _assert_agent_binding_permission(self.request)
        bind_agent_ids = _request_bind_agent_ids(self.request)
        with transaction.atomic():
            instance = serializer.save()
            if bind_agent_ids is not None:
                bind_runtime_resource_to_agents('skill', instance.id, bind_agent_ids, replace_existing=True)

    def get_queryset(self):
        get_agent_config()
        return AIOpsSkill.objects.all().order_by('is_builtin', 'name', 'id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_builtin:
            return Response({'detail': '内置 Skill 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def marketplace(self, request):
        return Response(build_skill_marketplace_catalog(user=request.user))

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        source = self.get_object()
        _assert_agent_binding_permission(request)
        bind_agent_ids = _request_bind_agent_ids(request)
        cloned = clone_skill_to_team(
            source,
            user=request.user,
            name=request.data.get('name', ''),
            slug=request.data.get('slug', ''),
        )
        if bind_agent_ids is not None:
            bind_runtime_resource_to_agents('skill', cloned.id, bind_agent_ids, replace_existing=True)
        record_event(
            request=request,
            module='aiops',
            category='configuration',
            action='clone_skill',
            title='克隆 AIOps Skill',
            summary=f'已克隆 Skill《{source.name}》为《{cloned.name}》',
            resource_type='aiops_skill',
            resource_id=cloned.id,
            resource_name=cloned.name,
            correlation_id=f'aiops-skill:{cloned.id}',
            metadata={'source_skill_id': source.id, 'source_skill_slug': source.slug},
        )
        return Response(AIOpsSkillSerializer(cloned).data, status=status.HTTP_201_CREATED)


class AIOpsIncidentViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AIOpsIncidentSerializer
    search_fields = ['title', 'impact_summary', 'service', 'resource', 'dedupe_key']
    filterset_fields = ['status', 'severity', 'source_type', 'environment', 'cluster', 'namespace', 'service', 'owner']
    rbac_permissions = {
        'list': ['aiops.incident.view'],
        'retrieve': ['aiops.incident.view'],
        'close': ['aiops.incident.close'],
        'run_action': ['aiops.incident.investigate'],
        'materialize_action': ['aiops.incident.view', 'aiops.task.generate'],
        'materialize_skill': ['aiops.incident.view', 'aiops.config.manage'],
        'materialize_runbook': ['aiops.incident.view', 'aiops.runbook.manage'],
        'chat_session': ['aiops.incident.view', 'aiops.chat.view'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return AIOpsIncidentListSerializer
        return AIOpsIncidentSerializer

    def get_queryset(self):
        queryset = AIOpsIncident.objects.order_by('-last_seen_at', '-id')
        if self.action in {
            'retrieve',
            'close',
            'run_action',
            'materialize_action',
            'materialize_skill',
            'materialize_runbook',
            'chat_session',
        }:
            queryset = queryset.prefetch_related(
                'alert_links__alert',
                'evidence_items__source_task',
                'evidence_items__tool_invocation',
                'hypotheses__source_task',
                'incident_actions__pending_action',
                'incident_actions__host_task',
            )
        params = self.request.query_params
        if params.get('only_open') in {'1', 'true', 'True'}:
            queryset = queryset.exclude(status__in=[AIOpsIncident.STATUS_RESOLVED, AIOpsIncident.STATUS_CLOSED])
        alert_id = params.get('alert_id')
        if alert_id:
            queryset = queryset.filter(alert_links__alert_id=alert_id).distinct()
        return queryset

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        incident = self.get_object()
        incident.status = AIOpsIncident.STATUS_CLOSED
        incident.closed_at = timezone.now()
        incident.owner = incident.owner or request.user.username
        incident.save(update_fields=['status', 'closed_at', 'owner', 'updated_at'])
        review_knowledge = auto_ingest_incident_review_knowledge(incident, user=request.user, reason='manual_close')
        record_event(
            request=request,
            module='aiops',
            category='incident',
            action='close_incident',
            title='关闭 Incident',
            summary=f'{request.user.username} 关闭 Incident #{incident.id}',
            resource_type='aiops_incident',
            resource_id=incident.id,
            resource_name=incident.title,
            environment=incident.environment,
            application=incident.service,
            severity=EventRecord.SEVERITY_INFO,
            correlation_id=f'aiops_incident:{incident.id}',
            metadata={'review_knowledge_id': review_knowledge.id if review_knowledge else None},
        )
        return Response(self.get_serializer(incident).data)

    @action(detail=True, methods=['post'], url_path=r'actions/(?P<action_id>\d+)/run')
    def run_action(self, request, pk=None, action_id=None):
        incident = self.get_object()
        incident_action = AIOpsIncidentAction.objects.filter(incident=incident, id=action_id).first()
        if not incident_action:
            return Response({'detail': '建议动作不存在。'}, status=status.HTTP_404_NOT_FOUND)
        if (
            incident_action.action_type != AIOpsIncidentAction.ACTION_INVESTIGATE
            or incident_action.risk_level != AIOpsIncidentAction.RISK_READ_ONLY
        ):
            return Response({'detail': '当前只允许触发只读调查建议。'}, status=status.HTTP_400_BAD_REQUEST)
        if incident_action.status == AIOpsIncidentAction.STATUS_RUNNING:
            return Response({'detail': '该建议动作正在执行中。'}, status=status.HTTP_409_CONFLICT)
        if incident_action.status == AIOpsIncidentAction.STATUS_COMPLETED:
            return Response({'detail': '该建议动作已完成。'}, status=status.HTTP_409_CONFLICT)

        runnable_statuses = {AIOpsIncidentAction.STATUS_PROPOSED, AIOpsIncidentAction.STATUS_FAILED}
        if incident_action.status not in runnable_statuses:
            return Response({'detail': '该建议动作当前状态不可执行。'}, status=status.HTTP_409_CONFLICT)
        updated = AIOpsIncidentAction.objects.filter(
            id=incident_action.id,
            status__in=runnable_statuses,
        ).update(
            status=AIOpsIncidentAction.STATUS_RUNNING,
            verification_status='running',
            result_summary=f'{request.user.username} 已触发只读补查。',
            updated_at=timezone.now(),
        )
        if not updated:
            return Response({'detail': '该建议动作状态已变化，请刷新后重试。'}, status=status.HTTP_409_CONFLICT)
        incident_action.refresh_from_db()
        try:
            task = run_readonly_investigation(incident, reason='manual_followup')
        except Exception as exc:
            incident_action.refresh_from_db()
            incident_action.status = AIOpsIncidentAction.STATUS_FAILED
            incident_action.verification_status = 'failed'
            incident_action.result_summary = f'只读补查失败：{str(exc)[:180]}'
            incident_action.save(update_fields=['status', 'verification_status', 'result_summary', 'updated_at'])
            record_event(
                request=request,
                module='aiops',
                category='incident',
                action='run_incident_action',
                result=EventRecord.RESULT_FAILED,
                title='Incident 建议动作失败',
                summary=f'{request.user.username} 触发 Incident #{incident.id} 只读补查失败',
                resource_type='aiops_incident_action',
                resource_id=incident_action.id,
                resource_name=incident_action.title,
                environment=incident.environment,
                application=incident.service,
                severity=EventRecord.SEVERITY_WARNING,
                correlation_id=f'aiops_incident:{incident.id}',
                metadata={'incident_id': incident.id, 'action_id': incident_action.id, 'error': str(exc)[:255]},
            )
            return Response({'detail': '只读补查失败。', 'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        incident_action.refresh_from_db()
        incident_action.status = AIOpsIncidentAction.STATUS_COMPLETED
        incident_action.verification_status = 'readonly_completed'
        incident_action.result_summary = f'只读补查已完成，任务 {task.public_id}。'
        incident_action.save(update_fields=['status', 'verification_status', 'result_summary', 'updated_at'])
        record_event(
            request=request,
            module='aiops',
            category='incident',
            action='run_incident_action',
            title='Incident 建议动作已执行',
            summary=f'{request.user.username} 触发 Incident #{incident.id} 只读补查',
            resource_type='aiops_incident_action',
            resource_id=incident_action.id,
            resource_name=incident_action.title,
            environment=incident.environment,
            application=incident.service,
            severity=EventRecord.SEVERITY_INFO,
            correlation_id=f'aiops_incident:{incident.id}',
            metadata={'incident_id': incident.id, 'action_id': incident_action.id, 'task_id': task.id, 'task_public_id': str(task.public_id)},
        )
        incident = self.get_queryset().get(id=incident.id)
        return Response(self.get_serializer(incident).data)

    @action(detail=True, methods=['post'], url_path='retrospective/skill')
    def materialize_skill(self, request, pk=None):
        incident = self.get_object()
        try:
            pending_action, created = create_incident_skill_pending_action(incident, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if created:
            record_event(
                request=request,
                module='aiops',
                category='incident',
                action='materialize_incident_skill',
                title='Incident 生成 Skill 草案',
                summary=f'{request.user.username} 从 Incident #{incident.id} 生成 Skill 审批事项 #{pending_action.id}',
                result=EventRecord.RESULT_PENDING,
                resource_type='aiops_pending_action',
                resource_id=pending_action.id,
                resource_name=pending_action.title,
                environment=incident.environment,
                application=incident.service,
                severity=EventRecord.SEVERITY_INFO,
                correlation_id=f'aiops_incident:{incident.id}',
                metadata={
                    'incident_id': incident.id,
                    'pending_action_id': pending_action.id,
                    'action_type': pending_action.action_type,
                },
            )
        incident = self.get_queryset().get(id=incident.id)
        return Response({
            'incident': self.get_serializer(incident).data,
            'pending_action': AIOpsPendingActionSerializer(pending_action).data,
            'created': created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='retrospective/runbook')
    def materialize_runbook(self, request, pk=None):
        incident = self.get_object()
        runbook, created = build_incident_runbook_draft(incident, user=request.user)
        if created:
            record_event(
                request=request,
                module='aiops',
                category='incident',
                action='materialize_incident_runbook',
                title='Incident 生成 Runbook 草案',
                summary=f'{request.user.username} 从 Incident #{incident.id} 生成 Runbook 草案《{runbook.title}》',
                result=EventRecord.RESULT_SUCCESS,
                resource_type='aiops_runbook',
                resource_id=runbook.id,
                resource_name=runbook.title,
                environment=incident.environment,
                application=incident.service,
                severity=EventRecord.SEVERITY_INFO,
                correlation_id=f'aiops_incident:{incident.id}',
                metadata={'incident_id': incident.id, 'runbook_id': runbook.id},
            )
        incident = self.get_queryset().get(id=incident.id)
        return Response({
            'incident': self.get_serializer(incident).data,
            'runbook': AIOpsRunbookSerializer(runbook).data,
            'created': created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='chat-session')
    def chat_session(self, request, pk=None):
        incident = self.get_object()
        session, created = get_or_create_incident_chat_session(incident, request.user)
        if created:
            record_event(
                request=request,
                module='aiops',
                category='incident',
                action='open_incident_chat',
                title='Incident 追问智能助手',
                summary=f'{request.user.username} 从 Incident #{incident.id} 打开智能助手追问会话',
                result=EventRecord.RESULT_SUCCESS,
                resource_type='aiops_chat_session',
                resource_id=session.id,
                resource_name=session.title,
                environment=incident.environment,
                application=incident.service,
                severity=EventRecord.SEVERITY_INFO,
                correlation_id=f'aiops_incident:{incident.id}',
                metadata={'incident_id': incident.id, 'session_id': session.id},
            )
        return Response({
            'session': AIOpsChatSessionSerializer(session).data,
            'created': created,
            'suggested_question': build_incident_chat_suggested_question(incident),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path=r'actions/(?P<action_id>\d+)/materialize')
    def materialize_action(self, request, pk=None, action_id=None):
        incident = self.get_object()
        event_payload = None
        with transaction.atomic():
            incident_action = (
                AIOpsIncidentAction.objects
                .select_for_update()
                .select_related('pending_action')
                .filter(incident=incident, id=action_id)
                .first()
            )
            if not incident_action:
                return Response({'detail': '建议动作不存在。'}, status=status.HTTP_404_NOT_FOUND)
            if incident_action.risk_level == AIOpsIncidentAction.RISK_READ_ONLY:
                return Response({'detail': '只读建议请直接触发只读补查，不需要生成执行审批。'}, status=status.HTTP_400_BAD_REQUEST)
            if incident_action.status in {AIOpsIncidentAction.STATUS_RUNNING, AIOpsIncidentAction.STATUS_COMPLETED}:
                return Response({'detail': '该建议动作当前状态不可生成审批。'}, status=status.HTTP_409_CONFLICT)
            if (
                incident_action.pending_action_id
                and incident_action.pending_action
                and incident_action.pending_action.status != AIOpsPendingAction.STATUS_CANCELED
            ):
                incident = self.get_queryset().get(id=incident.id)
                return Response(self.get_serializer(incident).data)

            draft = _incident_action_task_draft(incident, incident_action)
            session = _incident_action_approval_session(request.user, incident)
            pending_action = AIOpsPendingAction.objects.create(
                session=session,
                action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
                title=draft.get('name') or incident_action.title,
                risk_level=draft.get('risk_level') or incident_action.risk_level,
                action_payload=draft,
            )
            incident_action.pending_action = pending_action
            incident_action.verification_status = 'approval_pending'
            incident_action.result_summary = f'已生成审批事项 #{pending_action.id}，等待确认载入并执行。'
            incident_action.save(update_fields=['pending_action', 'verification_status', 'result_summary', 'updated_at'])
            event_payload = {
                'action_id': incident_action.id,
                'action_title': incident_action.title,
                'pending_action_id': pending_action.id,
                'risk_level': incident_action.risk_level,
            }
        record_event(
            request=request,
            module='aiops',
            category='incident',
            action='materialize_incident_action',
            title='Incident 建议动作生成审批',
            summary=f'{request.user.username} 为 Incident #{incident.id} 生成审批事项 #{event_payload["pending_action_id"]}',
            result=EventRecord.RESULT_PENDING,
            resource_type='aiops_incident_action',
            resource_id=event_payload['action_id'],
            resource_name=event_payload['action_title'],
            environment=incident.environment,
            application=incident.service,
            severity=EventRecord.SEVERITY_INFO,
            correlation_id=f'aiops_incident:{incident.id}',
            metadata={
                'incident_id': incident.id,
                'action_id': event_payload['action_id'],
                'pending_action_id': event_payload['pending_action_id'],
                'risk_level': event_payload['risk_level'],
            },
        )
        incident = self.get_queryset().get(id=incident.id)
        return Response(self.get_serializer(incident).data)


class _AuditRecentPagination(pagination.PageNumberPagination):
    page_size = AUDIT_RECENT_PAGE_SIZE
    page_size_query_param = 'page_size'
    max_page_size = 100


def _audit_query_param(request, *names):
    for name in names:
        value = request.query_params.get(name)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _audit_range_datetime(value, end_of_day=False):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        parsed_date = parse_date(str(value))
        if parsed_date:
            parsed = datetime.combine(
                parsed_date,
                datetime_time.max if end_of_day else datetime_time.min,
            )
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _filter_audit_time_range(queryset, request, field_name):
    start_at = _audit_range_datetime(_audit_query_param(request, 'start', 'start_at'))
    end_at = _audit_range_datetime(_audit_query_param(request, 'end', 'end_at'), end_of_day=True)
    if start_at:
        queryset = queryset.filter(**{f'{field_name}__gte': start_at})
    if end_at:
        queryset = queryset.filter(**{f'{field_name}__lte': end_at})
    return queryset


def _audit_overview_window(request):
    range_type = _audit_query_param(request, 'range').lower()
    if range_type == 'all':
        return None, None
    start_at = _audit_range_datetime(_audit_query_param(request, 'start', 'start_at'))
    end_at = _audit_range_datetime(_audit_query_param(request, 'end', 'end_at'), end_of_day=True)
    if start_at or end_at:
        return start_at, end_at
    try:
        days = int(_audit_query_param(request, 'days') or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    end_at = timezone.now()
    return end_at - timedelta(days=days), end_at


def _filter_audit_window(queryset, field_name, start_at=None, end_at=None):
    if start_at:
        queryset = queryset.filter(**{f'{field_name}__gte': start_at})
    if end_at:
        queryset = queryset.filter(**{f'{field_name}__lte': end_at})
    return queryset


def _audit_trace_message_queryset(request):
    queryset = AIOpsChatMessage.objects.select_related('session', 'session__user').filter(
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        session__mirror_source__isnull=True,
    )
    username = _audit_query_param(request, 'username', 'user')
    if username:
        queryset = queryset.filter(session__user__username__icontains=username)
    queryset = _filter_audit_time_range(queryset, request, 'created_at')
    return queryset.order_by('-created_at', '-id')


def _audit_text_matches(query, *values):
    if not query:
        return True
    needle = str(query).strip().lower()
    if not needle:
        return True
    text = ' '.join(str(value or '') for value in values).lower()
    return needle in text


def _paginate_audit_rows(request, rows):
    paginator = _AuditRecentPagination()
    page = paginator.paginate_queryset(rows, request)
    if page is not None:
        return paginator.get_paginated_response(page)
    return Response(rows)


def _audit_message_base_payload(message):
    session = message.session
    user = getattr(session, 'user', None)
    return {
        'message_id': message.id,
        'session': session.id,
        'session_title': session.title,
        'username': getattr(user, 'username', ''),
        'created_at': message.created_at,
    }


def _normalize_audit_trace_list(values):
    normalized = []
    for item in values or []:
        value = str(item or '').strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _audit_display_list(values, display_map):
    display_values = []
    for value in _normalize_audit_trace_list(values):
        display_value = str(display_map.get(value) or value).strip()
        if display_value and display_value not in display_values:
            display_values.append(display_value)
    return display_values


def _audit_skill_display_map():
    return {
        skill.slug: skill.name or skill.slug
        for skill in AIOpsSkill.objects.all().only('slug', 'name')
        if skill.slug
    }


def _audit_action_display_map(user=None):
    return {
        item.get('code'): item.get('display_name') or item.get('code')
        for item in list_action_registry(user=user, include_unavailable=True)
        if item.get('code')
    }


def _audit_hidden_trace_ids(message, trace_type):
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    hidden_ids = metadata.get(f'audit_hidden_{trace_type}_trace_ids') or []
    return set(_normalize_audit_trace_list(hidden_ids))


def _audit_trace_item_id(message, index, item, trace_type):
    if trace_type == 'skill':
        suffix = item.get('slug') or item.get('id') or item.get('name') or 'trace'
        return f'skill-{message.id}-{index}-{suffix}'
    if trace_type == 'action':
        return f'action-{message.id}-{item.get("code") or "trace"}'
    return ''


def _audit_invocation_distribution(request):
    start_at, end_at = _audit_overview_window(request)
    tool_queryset = AIOpsToolInvocation.objects.filter(session__mirror_source__isnull=True)
    tool_queryset = _filter_audit_window(tool_queryset, 'created_at', start_at, end_at)
    message_queryset = AIOpsChatMessage.objects.select_related('session', 'session__user').filter(
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        session__mirror_source__isnull=True,
    )
    message_queryset = _filter_audit_window(message_queryset, 'created_at', start_at, end_at)

    reader = AIOpsAuditTraceReader()
    skill_counts = {}
    action_counts = {}
    action_display_map = _audit_action_display_map(user=getattr(request, 'user', None))
    for message in message_queryset.iterator():
        hidden_skill_ids = _audit_hidden_trace_ids(message, 'skill')
        skill_trace = reader._skill_trace_for_message(message)
        skill_items = skill_trace.get('items') if isinstance(skill_trace, dict) else []
        for index, item in enumerate(skill_items or []):
            if not isinstance(item, dict):
                continue
            item_status = item.get('status') or 'available'
            used_tools = _normalize_audit_trace_list(item.get('used_tools') or [])
            is_hit = item_status != 'available' or bool(used_tools) or bool(item.get('action_code'))
            if is_hit and _audit_trace_item_id(message, index, item, 'skill') not in hidden_skill_ids:
                key = str(item.get('slug') or item.get('name') or item.get('id') or 'unknown').strip()
                label = str(item.get('name') or item.get('slug') or '未命名 Skill').strip()
                if key not in skill_counts:
                    skill_counts[key] = {'key': key, 'label': label, 'count': 0}
                skill_counts[key]['count'] += 1

        action_trace = reader._action_trace_for_message(message)
        if isinstance(action_trace, dict) and action_trace:
            hidden_action_ids = _audit_hidden_trace_ids(message, 'action')
            if _audit_trace_item_id(message, 0, action_trace, 'action') not in hidden_action_ids:
                code = str(action_trace.get('code') or 'unknown').strip()
                label = str(action_display_map.get(code) or action_trace.get('display_name') or action_trace.get('code') or '未命名运行策略').strip()
                if code not in action_counts:
                    action_counts[code] = {'key': code, 'label': label, 'count': 0}
                action_counts[code]['count'] += 1

    mcp_tools = [
        {
            'key': item.get('tool_name') or 'unknown',
            'label': item.get('tool_name') or '未命名工具',
            'count': item.get('count') or 0,
        }
        for item in tool_queryset.values('tool_name').annotate(count=Count('id')).order_by('-count', 'tool_name')
    ]
    skills = sorted(skill_counts.values(), key=lambda item: (-item['count'], item['label']))
    actions = sorted(action_counts.values(), key=lambda item: (-item['count'], item['label']))
    mcp_tool_calls = sum(item['count'] for item in mcp_tools)
    skill_hits = sum(item['count'] for item in skills)
    action_hits = sum(item['count'] for item in actions)
    total = mcp_tool_calls + skill_hits + action_hits
    return {
        'mcp_tool_calls': mcp_tool_calls,
        'skill_hits': skill_hits,
        'action_hits': action_hits,
        'total': total,
        'mcp_tools': mcp_tools,
        'skills': skills,
        'actions': actions,
    }


def _audit_trace_message_id(trace_id, trace_type):
    prefix = f'{trace_type}-'
    text = str(trace_id or '').strip()
    if not text.startswith(prefix):
        return None
    message_id = text[len(prefix):].split('-', 1)[0]
    return int(message_id) if message_id.isdigit() else None


def _hide_audit_trace_rows(request, trace_type, label):
    trace_ids = request.data.get('trace_ids')
    if trace_ids is None:
        trace_ids = request.data.get(f'{trace_type}_trace_ids')
    if trace_ids is None:
        trace_ids = request.data.get('ids')
    if not isinstance(trace_ids, list):
        return Response({'detail': 'trace_ids 必须为数组'}, status=status.HTTP_400_BAD_REQUEST)
    normalized_ids = _normalize_audit_trace_list(trace_ids)
    if not normalized_ids:
        return Response({'detail': f'请至少选择一个{label}记录'}, status=status.HTTP_400_BAD_REQUEST)

    ids_by_message = {}
    for trace_id in normalized_ids:
        message_id = _audit_trace_message_id(trace_id, trace_type)
        if message_id:
            ids_by_message.setdefault(message_id, []).append(trace_id)
    if not ids_by_message:
        return Response({'detail': '未找到可删除的审计记录'}, status=status.HTTP_404_NOT_FOUND)

    messages = list(AIOpsChatMessage.objects.filter(
        id__in=ids_by_message.keys(),
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        session__mirror_source__isnull=True,
    ))
    deleted_count = 0
    metadata_key = f'audit_hidden_{trace_type}_trace_ids'
    for message in messages:
        metadata = dict(message.metadata or {})
        hidden_ids = _normalize_audit_trace_list(metadata.get(metadata_key) or [])
        before_count = len(hidden_ids)
        for trace_id in ids_by_message.get(message.id, []):
            if trace_id not in hidden_ids:
                hidden_ids.append(trace_id)
        if len(hidden_ids) == before_count:
            continue
        metadata[metadata_key] = hidden_ids
        message.metadata = metadata
        message.save(update_fields=['metadata'])
        deleted_count += len(hidden_ids) - before_count

    if not deleted_count:
        return Response({'detail': '未找到可删除的审计记录'}, status=status.HTTP_404_NOT_FOUND)

    record_event(
        request=request,
        module='aiops',
        category='audit',
        action=f'bulk_delete_{trace_type}_traces',
        title=f'批量删除 AIOps {label}审计',
        summary=f'已批量删除 {deleted_count} 个{label}记录',
        resource_type=f'aiops_{trace_type}_trace',
        resource_id=deleted_count,
        resource_name=label,
        correlation_id=f'aiops-{trace_type}-trace-bulk:{deleted_count}',
        metadata={'trace_ids': normalized_ids[:50]},
    )
    return Response({'deleted': deleted_count}, status=status.HTTP_200_OK)


def _clean_catalog_value(value):
    return str(value or '').strip()


def _is_demoish_catalog_item(*values):
    text = ' '.join(str(value or '') for value in values).lower()
    return any(keyword in text for keyword in ['demo', '演示', '示例', '样例'])


def _is_invalid_environment_value(value):
    text = _clean_catalog_value(value)
    if not text:
        return True
    lowered = text.lower()
    return (
        lowered.startswith('env-')
        or set(text) == {'?'}
        or text in {'未知', 'unknown', 'null', 'none', '-'}
    )


def _grafana_folder_key(value):
    text = _clean_catalog_value(value)
    return text


def _k8s_namespace_options_cache_key(cluster_id):
    return f'aiops:k8s:namespaces:{cluster_id}'


def _k8s_namespace_options(cluster):
    try:
        from ops.k8s_views import DEMO_NAMESPACES, _get_k8s_client, _is_demo
    except Exception:
        return []
    try:
        if _is_demo(cluster):
            return [
                item.get('name')
                for item in DEMO_NAMESPACES
                if item.get('name')
            ]
        cache_key = _k8s_namespace_options_cache_key(cluster.id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        k8s = _get_k8s_client(cluster)
        v1 = k8s.CoreV1Api()
        data = sorted([
            item.metadata.name
            for item in v1.list_namespace().items
            if item.metadata and item.metadata.name
        ])
        cache.set(cache_key, data, K8S_NAMESPACE_OPTIONS_CACHE_TTL)
        cache.set(f'{cache_key}:stale', data, K8S_NAMESPACE_OPTIONS_STALE_CACHE_TTL)
        return data
    except Exception:
        stale = cache.get(f"{_k8s_namespace_options_cache_key(cluster.id)}:stale")
        if stale is not None:
            return stale
        return []


class AIOpsKnowledgeEnvironmentViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsKnowledgeEnvironmentSerializer
    pagination_class = None
    search_fields = ['name', 'description']
    demo_account_allowed_actions = {'create', 'update', 'partial_update', 'destroy'}
    rbac_permissions = {
        'list': ['aiops.knowledge.view'],
        'retrieve': ['aiops.knowledge.view'],
        'catalog': ['aiops.knowledge.view'],
        'create': ['aiops.knowledge.manage'],
        'update': ['aiops.knowledge.manage'],
        'partial_update': ['aiops.knowledge.manage'],
        'destroy': ['aiops.knowledge.manage'],
    }

    def get_queryset(self):
        return AIOpsKnowledgeEnvironment.objects.all().order_by('-is_default', 'name', 'id')

    def _ensure_single_default(self, instance):
        if instance.is_default:
            AIOpsKnowledgeEnvironment.objects.exclude(id=instance.id).filter(is_default=True).update(is_default=False)

    @action(detail=False, methods=['get'])
    def catalog(self, request):
        event_environments = list(
            EventRecord.objects
            .filter(is_demo=False)
            .exclude(source_type=EventRecord.SOURCE_SEED)
            .exclude(environment='')
            .values_list('environment', flat=True)
            .distinct()
            .order_by('environment')[:100]
        )
        alert_environments = list(
            Alert.objects
            .exclude(environment='')
            .values_list('environment', flat=True)
            .distinct()
            .order_by('environment')[:100]
        )
        log_datasources = [
            {
                'id': item.id,
                'name': item.name,
                'provider': item.provider,
                'provider_display': item.get_provider_display(),
                'description': item.description,
            }
            for item in LogDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
            if not _is_demoish_catalog_item(item.name, item.description, item.provider)
        ]
        tracing_datasources = [
            {
                'id': item.id,
                'name': item.name,
                'provider': item.provider,
                'provider_display': item.get_provider_display(),
                'description': item.description,
            }
            for item in TracingDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
            if not _is_demoish_catalog_item(item.name, item.description, item.provider)
        ]
        metric_datasources = [
            {
                'id': item.id,
                'name': item.name,
                'provider': item.provider,
                'provider_display': item.get_provider_display(),
                'description': item.description,
                'environment': item.environment,
                'cluster_name': item.cluster_name,
                'tsdb_type': item.tsdb_type,
                'is_default': item.is_default,
            }
            for item in MetricDataSource.objects.filter(is_enabled=True).order_by('environment', '-is_default', 'name')
            if not _is_demoish_catalog_item(item.name, item.description, item.provider)
        ]
        observability_links = [
            {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'log_datasource_id': item.log_datasource_id,
                'log_datasource_name': item.log_datasource.name if item.log_datasource else '',
                'tracing_datasource_id': item.tracing_datasource_id,
                'tracing_datasource_name': item.tracing_datasource.name if item.tracing_datasource else '',
                'grafana_dashboard_key': item.grafana_dashboard_key,
                'is_default': item.is_default,
            }
            for item in ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True).order_by('-is_default', 'name')
            if not _is_demoish_catalog_item(
                item.name,
                item.description,
                getattr(item.log_datasource, 'name', ''),
                getattr(item.tracing_datasource, 'name', ''),
            )
        ]
        k8s_clusters = [
            {
                'id': item.id,
                'name': item.name,
                'api_server': item.api_server,
                'status': item.status,
                'description': item.description,
                'namespaces': _k8s_namespace_options(item),
            }
            for item in K8sCluster.objects.order_by('name', 'id')
            if not _is_demoish_catalog_item(item.name, item.description, item.api_server)
        ]
        docker_hosts = [
            {
                'id': item.id,
                'name': item.name,
                'ip_address': item.ip_address,
                'status': item.status,
                'description': item.description,
            }
            for item in DockerHost.objects.order_by('name', 'id')
            if not _is_demoish_catalog_item(item.name, item.description, item.ip_address)
        ]
        resource_counts = TaskResource.objects.values('environment_id').annotate(total=Count('id'))
        env_counts = {}
        for item in resource_counts:
            env_counts[item['environment_id']] = env_counts.get(item['environment_id'], 0) + item['total']
        task_resource_environments = [
            {
                'id': item.id,
                'name': item.name,
                'code': item.code,
                'description': item.description,
                'resource_count': env_counts.get(item.id, 0),
            }
            for item in TaskResourceGroup.objects.filter(group_type=TaskResourceGroup.GROUP_ENVIRONMENT).order_by('sort_order', 'name', 'id')
        ]

        folder_map = {}
        for setting in GrafanaSetting.objects.filter(enabled=True).order_by('name'):
            folders = setting.folders if isinstance(setting.folders, list) else []
            dashboards = setting.dashboards if isinstance(setting.dashboards, list) else []
            for folder in folders:
                key = _grafana_folder_key(folder.get('path') or folder.get('folder') or folder.get('name'))
                if _is_demoish_catalog_item(key, folder.get('description')):
                    continue
                if key:
                    folder_map.setdefault(key, {'key': key, 'label': key, 'setting': setting.name, 'dashboard_count': 0})
            for dashboard in dashboards:
                if _is_demoish_catalog_item(dashboard.get('key'), dashboard.get('title'), dashboard.get('name'), dashboard.get('description')):
                    continue
                folder_key = _grafana_folder_key(dashboard.get('folder'))
                if not folder_key:
                    continue
                item = folder_map.setdefault(folder_key, {'key': folder_key, 'label': folder_key, 'setting': setting.name, 'dashboard_count': 0})
                item['dashboard_count'] += 1

        return Response({
            'event_environments': [
                _clean_catalog_value(item)
                for item in event_environments
                if not _is_invalid_environment_value(item)
            ],
            'grafana_folders': sorted(folder_map.values(), key=lambda item: item['label']),
            'metric_datasources': metric_datasources,
            'log_datasources': log_datasources,
            'tracing_datasources': tracing_datasources,
            'observability_links': observability_links,
            'alert_environments': [_clean_catalog_value(item) for item in alert_environments if _clean_catalog_value(item)],
            'k8s_clusters': k8s_clusters,
            'docker_hosts': docker_hosts,
            'task_resource_environments': task_resource_environments,
        })

    def perform_create(self, serializer):
        instance = serializer.save(
            created_by=getattr(self.request.user, 'username', ''),
            updated_by=getattr(self.request.user, 'username', ''),
        )
        self._ensure_single_default(instance)
        record_event(
            request=self.request,
            module='aiops',
            category='knowledge',
            action='create_knowledge_environment',
            title='创建知识图谱环境关联',
            summary=f'已创建知识图谱环境《{instance.name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=instance.id,
            resource_name=instance.name,
            correlation_id=f'aiops-knowledge-env:{instance.id}',
        )

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=getattr(self.request.user, 'username', ''))
        self._ensure_single_default(instance)
        record_event(
            request=self.request,
            module='aiops',
            category='knowledge',
            action='update_knowledge_environment',
            title='更新知识图谱环境关联',
            summary=f'已更新知识图谱环境《{instance.name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=instance.id,
            resource_name=instance.name,
            correlation_id=f'aiops-knowledge-env:{instance.id}',
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        resource_id = instance.id
        resource_name = instance.name
        response = super().destroy(request, *args, **kwargs)
        record_event(
            request=request,
            module='aiops',
            category='knowledge',
            action='delete_knowledge_environment',
            title='删除知识图谱环境关联',
            summary=f'已删除知识图谱环境《{resource_name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=resource_id,
            resource_name=resource_name,
            correlation_id=f'aiops-knowledge-env:{resource_id}',
        )
        return response


class AIOpsChatSessionViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsChatSessionSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    demo_account_allowed_actions = {'create', 'send_message', 'send_message_async'}
    rbac_permissions = {
        'list': ['aiops.chat.view'],
        'retrieve': ['aiops.chat.view'],
        'create': ['aiops.chat.view'],
        'destroy': ['aiops.chat.view'],
        'delete_session': ['aiops.chat.view'],
        'messages': ['aiops.chat.view'],
        'send_message': ['aiops.chat.view'],
        'send_message_async': ['aiops.chat.view'],
    }

    def get_queryset(self):
        if getattr(self.request.user, 'username', '') == 'demo':
            sync_admin_sessions_to_demo()
        return AIOpsChatSession.objects.filter(user=self.request.user).order_by('-last_message_at', '-id')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, 'action', '') == 'list':
            context['skip_latest_message'] = True
        return context

    def _agent_context(self, agent, runtime_config=None):
        context = {
            'agent_slug': agent.slug,
            'agent': {
                'id': agent.id,
                'name': agent.name,
                'slug': agent.slug,
                'execution_policy': agent.execution_policy,
            },
        }
        if runtime_config:
            context['runtime'] = {
                'allow_action_execution': runtime_config.allow_action_execution,
                'require_confirmation': runtime_config.require_confirmation,
            }
        return context

    def _resolve_agent(self, request, serializer, session=None, config=None):
        try:
            return resolve_agent_profile_for_user(
                request.user,
                serializer.validated_data.get('agent_slug'),
                session=session,
                config=config,
            )
        except ValueError as exc:
            raise ValidationError({'agent_slug': str(exc)})

    def _resolve_environment_for_request(self, agent, *, environment_name='', page_context=None, session=None):
        try:
            return resolve_agent_chat_environment(
                agent,
                explicit_environment_name=environment_name,
                page_context=page_context,
                session=session,
            )
        except ValueError as exc:
            raise ValidationError({'environment_name': str(exc)})

    def _apply_environment_context(self, context, environment):
        if environment:
            context['current_environment'] = {
                'id': environment.get('id'),
                'name': environment.get('name'),
                'aliases': environment.get('aliases') or [],
            }
        return context

    def create(self, request, *args, **kwargs):
        serializer = AIOpsCreateSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page_context = normalize_page_context(serializer.validated_data.get('page_context'))
        config = get_agent_config()
        agent = self._resolve_agent(request, serializer, config=config)
        runtime_config = runtime_config_for_agent(config, agent)
        context = self._agent_context(agent, runtime_config)
        if page_context:
            context['page_context'] = page_context
        environment = self._resolve_environment_for_request(
            agent,
            environment_name=serializer.validated_data.get('environment_name'),
            page_context=page_context,
        )
        self._apply_environment_context(context, environment)
        session = AIOpsChatSession.objects.create(
            user=request.user,
            title=serializer.validated_data.get('title') or '新会话',
            context=context,
        )
        sync_session_to_demo_if_needed(session)
        return Response(AIOpsChatSessionSerializer(session).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        session_id = instance.id
        session_title = instance.title
        response = super().destroy(request, *args, **kwargs)
        if getattr(request.user, 'username', '') == 'admin':
            sync_admin_sessions_to_demo()
        record_event(
            request=request,
            module='aiops',
            category='chat',
            action='delete_session',
            title='删除 AIOps 会话',
            summary=f'已删除会话《{session_title}》',
            resource_type='aiops_chat_session',
            resource_id=session_id,
            resource_name=session_title,
            correlation_id=f'aiops-chat-session:{session_id}',
        )
        return response

    @action(detail=True, methods=['post'])
    def delete_session(self, request, pk=None):
        return self.destroy(request, pk=pk)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        session = self.get_object()
        messages = session.messages.order_by('created_at', 'id')
        return Response(AIOpsChatMessageSerializer(messages, many=True).data)

    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        session = self.get_object()
        if is_demo_account(request.user):
            return Response({'detail': DEMO_CHAT_DISABLED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        if getattr(request.user, 'username', '') == 'demo' and session.mirror_source_id:
            return Response({'detail': '演示账号同步会话为只读，请先新建会话后提问。'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AIOpsChatInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = recover_masked_suggested_question(serializer.validated_data['content'].strip())
        analysis_only = bool(serializer.validated_data.get('analysis_only'))
        page_context = normalize_page_context(serializer.validated_data.get('page_context'))
        agent = self._resolve_agent(request, serializer, session=session)
        session_context = session.context if isinstance(session.context, dict) else {}
        context_patch = {**session_context, **self._agent_context(agent)}
        if page_context:
            context_patch['page_context'] = page_context
        environment = self._resolve_environment_for_request(
            agent,
            environment_name=serializer.validated_data.get('environment_name'),
            page_context=page_context,
            session=session,
        )
        self._apply_environment_context(context_patch, environment)
        if context_patch != session_context:
            session.context = context_patch
            session.save(update_fields=['context', 'updated_at'])
        user_metadata = {
            'agent_slug': agent.slug,
            'agent_name': agent.name,
            'agent_execution_policy': agent.execution_policy,
        }
        if analysis_only:
            user_metadata['analysis_only'] = True
        if page_context:
            user_metadata['page_context'] = page_context
        if environment:
            user_metadata['environment'] = environment.get('name')
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content=content,
            metadata=user_metadata,
        )
        assistant_message, pending_action = dispatch_chat(session, user_message, request.user, user_message.content, analysis_only=analysis_only)
        return Response({
            'user_message': AIOpsChatMessageSerializer(user_message).data,
            'assistant_message': AIOpsChatMessageSerializer(assistant_message).data,
            'pending_action': AIOpsPendingActionSerializer(pending_action).data if pending_action else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def send_message_async(self, request, pk=None):
        session = self.get_object()
        if is_demo_account(request.user):
            return Response({'detail': DEMO_CHAT_DISABLED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        if getattr(request.user, 'username', '') == 'demo' and session.mirror_source_id:
            return Response({'detail': '演示账号同步会话为只读，请先新建会话后提问。'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AIOpsChatInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = recover_masked_suggested_question(serializer.validated_data['content'].strip())
        analysis_only = bool(serializer.validated_data.get('analysis_only'))
        page_context = normalize_page_context(serializer.validated_data.get('page_context'))
        agent = self._resolve_agent(request, serializer, session=session)
        session_context = session.context if isinstance(session.context, dict) else {}
        context_patch = {**session_context, **self._agent_context(agent)}
        if page_context:
            context_patch['page_context'] = page_context
        environment = self._resolve_environment_for_request(
            agent,
            environment_name=serializer.validated_data.get('environment_name'),
            page_context=page_context,
            session=session,
        )
        self._apply_environment_context(context_patch, environment)
        if context_patch != session_context:
            session.context = context_patch
            session.save(update_fields=['context', 'updated_at'])
        user_metadata = {
            'agent_slug': agent.slug,
            'agent_name': agent.name,
            'agent_execution_policy': agent.execution_policy,
        }
        if analysis_only:
            user_metadata['analysis_only'] = True
        if page_context:
            user_metadata['page_context'] = page_context
        if environment:
            user_metadata['environment'] = environment.get('name')
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content=content,
            metadata=user_metadata,
        )
        is_canned_light_chat = _is_canned_lightweight_chat_question(content)
        placeholder_content = '正在回复，请稍等...' if is_canned_light_chat else '正在处理请求，请稍等...'
        processing_text = '正在生成轻量回复' if is_canned_light_chat else '请求已提交，正在排队处理'
        processing_detail = '已收到轻量问答，正在生成回复' if is_canned_light_chat else '已收到问题，正在准备上下文'
        assistant_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            message_type=AIOpsChatMessage.TYPE_TEXT,
            content=placeholder_content,
            metadata={
                'processing_status': 'pending',
                'processing_text': processing_text,
                'analysis_only': analysis_only,
                'page_context': page_context,
                'agent_slug': agent.slug,
                'agent_name': agent.name,
                'agent_execution_policy': agent.execution_policy,
                'environment': environment.get('name') if environment else '',
                'processing_steps': [{
                    'title': '排队中',
                    'detail': processing_detail,
                    'status': 'pending',
                    'timestamp': timezone.now().isoformat(),
                }],
                'tool_events': [],
            },
        )
        session.last_message_at = timezone.now()
        if session.title == '新会话':
            session.title = content[:48] or '新会话'
        session.save(update_fields=['last_message_at', 'title', 'updated_at'])
        sync_session_to_demo_if_needed(session)
        if is_canned_light_chat:
            result = _build_lightweight_chat_result(content)
            assistant_message, pending_action = _apply_dispatch_result_to_message(
                session,
                assistant_message,
                result,
                request.user,
                enable_stream=False,
                question=content,
                analysis_only=analysis_only,
            )
            return Response({
                'user_message': AIOpsChatMessageSerializer(user_message).data,
                'assistant_message': AIOpsChatMessageSerializer(assistant_message).data,
                'pending_action': AIOpsPendingActionSerializer(pending_action).data if pending_action else None,
            }, status=status.HTTP_201_CREATED)
        start_async_chat_processing(session, user_message, request.user, assistant_message, analysis_only=analysis_only)
        return Response({
            'user_message': AIOpsChatMessageSerializer(user_message).data,
            'assistant_message': AIOpsChatMessageSerializer(assistant_message).data,
            'pending_action': None,
        }, status=status.HTTP_201_CREATED)


class AIOpsAuditSessionViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsAuditSessionSerializer
    pagination_class = _AuditRecentPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
        'destroy': ['aiops.audit.manage'],
    }

    def get_queryset(self):
        queryset = AIOpsChatSession.objects.filter(mirror_source__isnull=True).select_related('user').annotate(
            message_count=Count('messages', distinct=True),
            tool_invocation_count=Count('tool_invocations', distinct=True),
            pending_action_count=Count(
                'pending_actions',
                filter=Q(pending_actions__mirror_source__isnull=True),
                distinct=True,
            ),
        )
        query = _audit_query_param(self.request, 'q', 'search')
        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(user__username__icontains=query))
        status_value = _audit_query_param(self.request, 'status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        username = _audit_query_param(self.request, 'username', 'user')
        if username:
            queryset = queryset.filter(user__username__icontains=username)
        queryset = _filter_audit_time_range(queryset, self.request, 'last_message_at')
        return queryset.order_by('-last_message_at', '-id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        session_id = instance.id
        session_title = instance.title
        session_user = getattr(instance.user, 'username', '')
        response = super().destroy(request, *args, **kwargs)
        if session_user == 'admin':
            sync_admin_sessions_to_demo()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='delete_session',
            title='删除 AIOps 审计会话',
            summary=f'已删除会话《{session_title}》',
            resource_type='aiops_session',
            resource_id=session_id,
            resource_name=session_title,
            correlation_id=f'aiops-session:{session_id}',
            metadata={'session_user': session_user},
        )
        return response

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        session_ids = request.data.get('session_ids')
        if not isinstance(session_ids, list):
            return Response({'detail': 'session_ids 必须为数组'}, status=status.HTTP_400_BAD_REQUEST)
        normalized_ids = [int(item) for item in session_ids if str(item).isdigit()]
        if not normalized_ids:
            return Response({'detail': '请至少选择一个会话'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(id__in=normalized_ids)
        sessions = list(queryset)
        if not sessions:
            return Response({'detail': '未找到可删除的会话'}, status=status.HTTP_404_NOT_FOUND)

        deleted_count = len(sessions)
        deleted_titles = [item.title for item in sessions[:5]]
        admin_deleted = any(getattr(item.user, 'username', '') == 'admin' for item in sessions)
        session_meta = [
            {'id': item.id, 'title': item.title, 'username': getattr(item.user, 'username', '')}
            for item in sessions
        ]
        queryset.delete()
        if admin_deleted:
            sync_admin_sessions_to_demo()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='bulk_delete_sessions',
            title='批量删除 AIOps 审计会话',
            summary=f'已批量删除 {deleted_count} 个会话',
            resource_type='aiops_session',
            resource_id=deleted_count,
            resource_name='、'.join(deleted_titles),
            correlation_id=f'aiops-session-bulk:{deleted_count}',
            metadata={'sessions': session_meta},
        )
        return Response({'deleted': deleted_count}, status=status.HTTP_200_OK)


class AIOpsToolInvocationViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsToolInvocationSerializer
    pagination_class = _AuditRecentPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
        'destroy': ['aiops.audit.manage'],
    }

    def get_queryset(self):
        queryset = AIOpsToolInvocation.objects.select_related('session', 'session__user', 'message')
        query = _audit_query_param(self.request, 'q', 'search')
        if query:
            queryset = queryset.filter(
                Q(tool_name__icontains=query)
                | Q(session__title__icontains=query)
                | Q(session__user__username__icontains=query)
            )
        status_value = _audit_query_param(self.request, 'status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        username = _audit_query_param(self.request, 'username', 'user')
        if username:
            queryset = queryset.filter(session__user__username__icontains=username)
        queryset = _filter_audit_time_range(queryset, self.request, 'created_at')
        return queryset.order_by('-created_at', '-id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        invocation_id = instance.id
        tool_name = instance.tool_name
        response = super().destroy(request, *args, **kwargs)
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='delete_tool_invocation',
            title='删除 AIOps 工具调用审计',
            summary=f'已删除工具调用《{tool_name}》',
            resource_type='aiops_tool_invocation',
            resource_id=invocation_id,
            resource_name=tool_name,
            correlation_id=f'aiops-tool-invocation:{invocation_id}',
        )
        return response

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        invocation_ids = request.data.get('invocation_ids')
        if not isinstance(invocation_ids, list):
            return Response({'detail': 'invocation_ids 必须为数组'}, status=status.HTTP_400_BAD_REQUEST)
        normalized_ids = [int(item) for item in invocation_ids if str(item).isdigit()]
        if not normalized_ids:
            return Response({'detail': '请至少选择一个工具调用'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(id__in=normalized_ids)
        invocations = list(queryset)
        if not invocations:
            return Response({'detail': '未找到可删除的工具调用'}, status=status.HTTP_404_NOT_FOUND)

        deleted_count = len(invocations)
        deleted_names = [item.tool_name for item in invocations[:5]]
        invocation_meta = [
            {'id': item.id, 'tool_name': item.tool_name, 'username': getattr(getattr(item.session, 'user', None), 'username', '')}
            for item in invocations
        ]
        queryset.delete()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='bulk_delete_tool_invocations',
            title='批量删除 AIOps 工具调用审计',
            summary=f'已批量删除 {deleted_count} 个工具调用',
            resource_type='aiops_tool_invocation',
            resource_id=deleted_count,
            resource_name='、'.join(deleted_names),
            correlation_id=f'aiops-tool-invocation-bulk:{deleted_count}',
            metadata={'tool_invocations': invocation_meta},
        )
        return Response({'deleted': deleted_count}, status=status.HTTP_200_OK)


class AIOpsPendingActionViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsPendingActionSerializer
    pagination_class = _AuditRecentPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
        'destroy': ['aiops.audit.manage'],
    }

    def get_queryset(self):
        queryset = AIOpsPendingAction.objects.filter(mirror_source__isnull=True, session__mirror_source__isnull=True).select_related('session', 'session__user', 'message')
        query = _audit_query_param(self.request, 'q', 'search')
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(action_type__icontains=query)
                | Q(confirmed_by__icontains=query)
                | Q(session__title__icontains=query)
                | Q(session__user__username__icontains=query)
            )
        status_value = _audit_query_param(self.request, 'status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        risk_level = _audit_query_param(self.request, 'risk_level', 'risk')
        if risk_level:
            queryset = queryset.filter(risk_level=risk_level)
        username = _audit_query_param(self.request, 'username', 'user')
        if username:
            queryset = queryset.filter(session__user__username__icontains=username)
        queryset = _filter_audit_time_range(queryset, self.request, 'updated_at')
        return queryset.order_by('-created_at', '-id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        action_id = instance.id
        action_title = instance.title
        response = super().destroy(request, *args, **kwargs)
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='delete_pending_action',
            title='删除 AIOps 执行审批审计',
            summary=f'已删除审批事项《{action_title}》',
            resource_type='aiops_pending_action',
            resource_id=action_id,
            resource_name=action_title,
            correlation_id=f'aiops-pending-action:{action_id}',
        )
        return response

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        action_ids = request.data.get('action_ids')
        if not isinstance(action_ids, list):
            return Response({'detail': 'action_ids 必须为数组'}, status=status.HTTP_400_BAD_REQUEST)
        normalized_ids = [int(item) for item in action_ids if str(item).isdigit()]
        if not normalized_ids:
            return Response({'detail': '请至少选择一个审批事项'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(id__in=normalized_ids)
        actions = list(queryset)
        if not actions:
            return Response({'detail': '未找到可删除的审批事项'}, status=status.HTTP_404_NOT_FOUND)

        deleted_count = len(actions)
        deleted_titles = [item.title for item in actions[:5]]
        action_meta = [
            {'id': item.id, 'title': item.title, 'username': getattr(getattr(item.session, 'user', None), 'username', '')}
            for item in actions
        ]
        queryset.delete()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='bulk_delete_pending_actions',
            title='批量删除 AIOps 执行审批审计',
            summary=f'已批量删除 {deleted_count} 个审批事项',
            resource_type='aiops_pending_action',
            resource_id=deleted_count,
            resource_name='、'.join(deleted_titles),
            correlation_id=f'aiops-pending-action-bulk:{deleted_count}',
            metadata={'actions': action_meta},
        )
        return Response({'deleted': deleted_count}, status=status.HTTP_200_OK)


class AIOpsModelInvocationViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsModelInvocationSerializer
    pagination_class = _AuditRecentPagination
    http_method_names = ['get', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
        'destroy': ['aiops.audit.manage'],
    }

    def get_queryset(self):
        queryset = AIOpsModelInvocation.objects.select_related('provider', 'session', 'session__user', 'message')
        query = _audit_query_param(self.request, 'q', 'search')
        if query:
            queryset = queryset.filter(
                Q(provider__name__icontains=query)
                | Q(requested_model__icontains=query)
                | Q(resolved_model__icontains=query)
                | Q(username__icontains=query)
                | Q(session__title__icontains=query)
            )
        status_value = _audit_query_param(self.request, 'status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        purpose = _audit_query_param(self.request, 'purpose')
        if purpose:
            queryset = queryset.filter(purpose=purpose)
        currency = _audit_query_param(self.request, 'currency', 'estimated_cost_currency')
        if currency:
            queryset = queryset.filter(estimated_cost_currency=currency.upper())
        username = _audit_query_param(self.request, 'username', 'user')
        if username:
            queryset = queryset.filter(username__icontains=username)
        queryset = _filter_audit_time_range(queryset, self.request, 'created_at')
        return queryset.order_by('-created_at', '-id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        invocation_id = instance.id
        model_name = instance.resolved_model or instance.requested_model
        response = super().destroy(request, *args, **kwargs)
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='delete_model_invocation',
            title='删除 AIOps 模型调用审计',
            summary=f'已删除模型调用《{model_name}》',
            resource_type='aiops_model_invocation',
            resource_id=invocation_id,
            resource_name=model_name,
            correlation_id=f'aiops-model-invocation:{invocation_id}',
        )
        return response


class AIOpsExternalTaskViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsExternalTaskSerializer
    lookup_field = 'public_id'
    http_method_names = ['get', 'post', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.a2a.view'],
        'retrieve': ['aiops.a2a.view'],
        'create': ['aiops.a2a.invoke'],
        'cancel': ['aiops.a2a.invoke'],
        'run': ['aiops.a2a.invoke'],
        'interrupt': ['aiops.a2a.invoke'],
    }

    def get_queryset(self):
        return AIOpsExternalTask.objects.select_related('created_by').order_by('-created_at', '-id')

    def create(self, request, *args, **kwargs):
        try:
            task = create_external_task(request.data, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='a2a',
            action='create_external_task',
            title='创建 AIOps A2A 任务',
            summary=f'已创建外部任务《{task.title}》',
            resource_type='aiops_external_task',
            resource_id=task.id,
            resource_name=str(task.public_id),
            correlation_id=f'aiops-a2a-task:{task.public_id}',
            metadata={'action_code': task.action_code, 'source_agent': task.source_agent},
        )
        return Response(AIOpsExternalTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, public_id=None):
        task = self.get_object()
        try:
            task = cancel_external_task(task, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='a2a',
            action='cancel_external_task',
            title='取消 AIOps A2A 任务',
            summary=f'已取消外部任务《{task.title}》',
            resource_type='aiops_external_task',
            resource_id=task.id,
            resource_name=str(task.public_id),
            correlation_id=f'aiops-a2a-task:{task.public_id}',
        )
        return Response(AIOpsExternalTaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def run(self, request, public_id=None):
        task = self.get_object()
        try:
            task = run_external_task_orchestration(task, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='a2a',
            action='run_external_task',
            title='运行 AIOps 多 Agent 编排',
            summary=f'已运行外部任务《{task.title}》',
            resource_type='aiops_external_task',
            resource_id=task.id,
            resource_name=str(task.public_id),
            correlation_id=f'aiops-a2a-task:{task.public_id}',
        )
        return Response(AIOpsExternalTaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def interrupt(self, request, public_id=None):
        task = self.get_object()
        try:
            task = interrupt_external_task(task, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='a2a',
            action='interrupt_external_task',
            title='中断 AIOps 多 Agent 编排',
            summary=f'已中断外部任务《{task.title}》',
            resource_type='aiops_external_task',
            resource_id=task.id,
            resource_name=str(task.public_id),
            correlation_id=f'aiops-a2a-task:{task.public_id}',
        )
        return Response(AIOpsExternalTaskSerializer(task).data)


class AIOpsRunbookViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsRunbookSerializer
    rbac_permissions = {
        'list': ['aiops.runbook.view'],
        'retrieve': ['aiops.runbook.view'],
        'create': ['aiops.runbook.manage'],
        'update': ['aiops.runbook.manage'],
        'partial_update': ['aiops.runbook.manage'],
        'destroy': ['aiops.runbook.manage'],
        'draft': ['aiops.runbook.manage'],
        'from_session': ['aiops.runbook.manage'],
        'publish': ['aiops.runbook.manage'],
        'archive': ['aiops.runbook.manage'],
        'versions': ['aiops.runbook.view'],
    }

    def get_queryset(self):
        return AIOpsRunbook.objects.select_related('source_task', 'source_session').annotate(version_count=Count('versions')).order_by('-updated_at', '-id')

    def perform_create(self, serializer):
        serializer.save(
            created_by=getattr(self.request.user, 'username', ''),
            updated_by=getattr(self.request.user, 'username', ''),
        )

    def perform_update(self, serializer):
        serializer.save(updated_by=getattr(self.request.user, 'username', ''))

    @action(detail=False, methods=['post'])
    def draft(self, request):
        source_task = None
        source_task_id = request.data.get('source_task')
        if source_task_id:
            source_task = AIOpsExternalTask.objects.filter(id=source_task_id).first()
        source_session = None
        source_session_id = request.data.get('source_session')
        if source_session_id:
            source_session = AIOpsChatSession.objects.filter(id=source_session_id).first()
        runbook = build_runbook_draft_from_payload(
            request.data,
            user=request.user,
            source_task=source_task,
            source_session=source_session,
        )
        record_event(
            request=request,
            module='aiops',
            category='runbook',
            action='create_runbook_draft',
            title='生成 AIOps Runbook 草案',
            summary=f'已生成 Runbook 草案《{runbook.title}》',
            resource_type='aiops_runbook',
            resource_id=runbook.id,
            resource_name=runbook.title,
            correlation_id=f'aiops-runbook:{runbook.id}',
        )
        return Response(AIOpsRunbookSerializer(runbook).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='from-session')
    def from_session(self, request):
        source_session_id = request.data.get('source_session') or request.data.get('session_id')
        source_session = AIOpsChatSession.objects.filter(id=source_session_id).first()
        if not source_session:
            return Response({'detail': '来源会话不存在'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            runbook = build_runbook_draft_from_session(source_session, user=request.user, payload=request.data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='runbook',
            action='create_runbook_from_session',
            title='从事故会话生成 Runbook',
            summary=f'已从会话《{source_session.title}》生成 Runbook《{runbook.title}》',
            resource_type='aiops_runbook',
            resource_id=runbook.id,
            resource_name=runbook.title,
            correlation_id=f'aiops-runbook:{runbook.id}',
        )
        return Response(AIOpsRunbookSerializer(runbook).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        runbook = self.get_object()
        versions = runbook.versions.all().order_by('-version', '-id')
        return Response(AIOpsRunbookVersionSerializer(versions, many=True).data)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        runbook = self.get_object()
        try:
            runbook, version = publish_runbook(runbook, user=request.user, change_note=request.data.get('change_note', ''))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='runbook',
            action='publish_runbook',
            title='发布 AIOps Runbook',
            summary=f'已发布 Runbook《{runbook.title}》v{version.version}',
            resource_type='aiops_runbook',
            resource_id=runbook.id,
            resource_name=runbook.title,
            correlation_id=f'aiops-runbook:{runbook.id}',
            metadata={'version': version.version},
        )
        return Response(AIOpsRunbookSerializer(runbook).data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        runbook = self.get_object()
        try:
            runbook, version = archive_runbook(runbook, user=request.user, change_note=request.data.get('change_note', ''))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_event(
            request=request,
            module='aiops',
            category='runbook',
            action='archive_runbook',
            title='归档 AIOps Runbook',
            summary=f'已归档 Runbook《{runbook.title}》v{version.version}',
            resource_type='aiops_runbook',
            resource_id=runbook.id,
            resource_name=runbook.title,
            correlation_id=f'aiops-runbook:{runbook.id}',
            metadata={'version': version.version},
        )
        return Response(AIOpsRunbookSerializer(runbook).data)


class AIOpsReviewKnowledgeViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsReviewKnowledgeSerializer
    rbac_permissions = {
        'list': ['aiops.review.view'],
        'retrieve': ['aiops.review.view'],
        'create': ['aiops.review.manage'],
        'update': ['aiops.review.manage'],
        'partial_update': ['aiops.review.manage'],
        'destroy': ['aiops.review.manage'],
        'auto_ingest': ['aiops.review.manage'],
    }

    def get_queryset(self):
        queryset = AIOpsReviewKnowledge.objects.select_related('source_session', 'source_task', 'source_runbook').order_by('-updated_at', '-id')
        query = str(self.request.query_params.get('q') or self.request.query_params.get('search') or '').strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(summary__icontains=query)
                | Q(environment__icontains=query)
                | Q(service__icontains=query)
            )
        source_type = str(self.request.query_params.get('source_type') or '').strip()
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            created_by=getattr(self.request.user, 'username', ''),
            updated_by=getattr(self.request.user, 'username', ''),
        )

    def perform_update(self, serializer):
        serializer.save(updated_by=getattr(self.request.user, 'username', ''))

    @action(detail=False, methods=['post'], url_path='auto-ingest')
    def auto_ingest(self, request):
        source_session = None
        source_task = None
        source_runbook = None
        if request.data.get('source_session'):
            source_session = AIOpsChatSession.objects.filter(id=request.data.get('source_session')).first()
        if request.data.get('source_task'):
            source_task = AIOpsExternalTask.objects.filter(id=request.data.get('source_task')).first()
        if request.data.get('source_runbook'):
            source_runbook = AIOpsRunbook.objects.filter(id=request.data.get('source_runbook')).first()
        if not any([source_session, source_task, source_runbook]):
            return Response({'detail': '请提供可沉淀的会话、协同任务或 Runbook 来源'}, status=status.HTTP_400_BAD_REQUEST)
        knowledge = auto_ingest_review_knowledge(
            source_session=source_session,
            source_task=source_task,
            source_runbook=source_runbook,
            user=request.user,
            payload=request.data,
        )
        record_event(
            request=request,
            module='aiops',
            category='review',
            action='auto_ingest_review_knowledge',
            title='自动沉淀 AIOps 复盘知识',
            summary=f'已沉淀复盘知识《{knowledge.title}》',
            resource_type='aiops_review_knowledge',
            resource_id=knowledge.id,
            resource_name=knowledge.title,
            correlation_id=f'aiops-review:{knowledge.id}',
        )
        return Response(AIOpsReviewKnowledgeSerializer(knowledge).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.mcp.view')])
def platform_mcp_manifest(request):
    return Response(build_platform_mcp_manifest(user=request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.mcp.view')])
def platform_mcp_tools(request):
    return Response({'tools': list_platform_mcp_tools(user=request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.mcp.invoke')])
def platform_mcp_call(request):
    tool_name = request.data.get('name') or request.data.get('tool')
    arguments = request.data.get('arguments') or {}
    try:
        result = invoke_platform_mcp_tool(tool_name, arguments=arguments, user=request.user, request=request)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.mcp.invoke')])
def platform_mcp_rpc(request):
    rpc_id = request.data.get('id')
    method = str(request.data.get('method') or '').strip()
    params = request.data.get('params') if isinstance(request.data.get('params'), dict) else {}

    def ok(result):
        return Response({'jsonrpc': '2.0', 'id': rpc_id, 'result': result})

    def error(code, message):
        return Response({'jsonrpc': '2.0', 'id': rpc_id, 'error': {'code': code, 'message': message}}, status=status.HTTP_400_BAD_REQUEST)

    if method in {'initialize', 'server/initialize'}:
        return ok({
            'protocolVersion': '2025-11-25',
            'serverInfo': {'name': 'sxdevops-aiops', 'version': '2.1'},
            'capabilities': {'tools': {'listChanged': False}},
        })
    if method in {'ping', 'server/ping'}:
        return ok({})
    if method == 'tools/list':
        return ok({'tools': list_platform_mcp_tools(user=request.user)})
    if method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        try:
            return ok(invoke_platform_mcp_tool(tool_name, arguments=arguments, user=request.user, request=request))
        except ValueError as exc:
            return error(-32000, str(exc))
    return error(-32601, 'MCP 方法不存在')


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.config.view')])
def action_registry(request):
    actions = list_action_registry(user=request.user, include_unavailable=True)
    return Response({
        'summary': build_action_registry_summary(actions),
        'actions': actions,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.chat.analyze')])
def action_preflight(request):
    action_code = str(request.data.get('action_code') or '').strip()
    if not action_code:
        return Response({'detail': 'action_code 不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(build_action_preflight_contract(action_code, request.data, user=request.user))
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.chat.view')])
def bootstrap(request):
    return Response(bootstrap_payload_for_user(request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.knowledge.view')])
def knowledge_graph(request):
    return Response(build_knowledge_graph(request.query_params))


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.config.view')])
def agent_config_view(request):
    config = get_agent_config()
    if request.method == 'GET':
        return Response(AIOpsAgentConfigSerializer(config).data)
    if not user_has_permissions(request.user, ['aiops.config.manage']):
        return Response({'detail': '缺少 aiops.config.manage 权限'}, status=status.HTTP_403_FORBIDDEN)
    serializer = AIOpsAgentConfigSerializer(instance=config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    record_event(
        request=request,
        module='aiops',
        category='configuration',
        action='update_agent_config',
        title='更新 AIOps 配置',
        summary='已更新 AIOps 机器人配置',
        resource_type='aiops_config',
        resource_id=config.id,
        resource_name=config.name,
        correlation_id=f'aiops-config:{config.id}',
    )
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.view')])
def audit_skill_traces(request):
    query = _audit_query_param(request, 'q', 'search')
    status_value = _audit_query_param(request, 'status')
    reader = AIOpsAuditTraceReader()
    action_display_map = _audit_action_display_map(user=request.user)
    rows = []

    for message in _audit_trace_message_queryset(request).iterator():
        hidden_ids = _audit_hidden_trace_ids(message, 'skill')
        trace = reader._skill_trace_for_message(message)
        items = trace.get('items') if isinstance(trace, dict) else []
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            item_status = item.get('status') or 'available'
            used_tools = _normalize_audit_trace_list(item.get('used_tools') or [])
            is_hit = item_status != 'available' or bool(used_tools) or bool(item.get('action_code'))
            if not is_hit:
                continue
            if status_value and item_status != status_value:
                continue
            declared_tools = _normalize_audit_trace_list(item.get('declared_tools') or [])
            applicable_actions = _normalize_audit_trace_list(item.get('applicable_actions') or [])
            applicable_action_names = _audit_display_list(applicable_actions, action_display_map)
            action_code = item.get('action_code') or ''
            payload = {
                **_audit_message_base_payload(message),
                'id': f'skill-{message.id}-{index}-{item.get("slug") or item.get("id") or item.get("name") or "trace"}',
                'skill_id': item.get('id'),
                'name': item.get('name') or item.get('slug') or '',
                'slug': item.get('slug') or '',
                'category': item.get('category') or '',
                'risk_level': item.get('risk_level') or '',
                'status': item_status,
                'hit_reason': item.get('hit_reason') or '',
                'action_code': action_code,
                'action_display_name': action_display_map.get(action_code, action_code) if action_code else '',
                'applicable_actions': applicable_actions,
                'applicable_action_names': applicable_action_names,
                'declared_tools': declared_tools,
                'used_tools': used_tools,
                'inferred': bool(trace.get('inferred')) if isinstance(trace, dict) else False,
            }
            if payload['id'] in hidden_ids:
                continue
            if not _audit_text_matches(
                query,
                payload['name'],
                payload['slug'],
                payload['category'],
                payload['hit_reason'],
                payload['action_code'],
                payload['action_display_name'],
                payload['session_title'],
                payload['username'],
                ' '.join(applicable_actions),
                ' '.join(applicable_action_names),
                ' '.join(declared_tools),
                ' '.join(used_tools),
            ):
                continue
            rows.append(payload)

    return _paginate_audit_rows(request, rows)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.view')])
def audit_action_traces(request):
    query = _audit_query_param(request, 'q', 'search')
    status_value = _audit_query_param(request, 'status')
    risk_level = _audit_query_param(request, 'risk_level', 'risk')
    reader = AIOpsAuditTraceReader()
    skill_display_map = _audit_skill_display_map()
    rows = []

    for message in _audit_trace_message_queryset(request).iterator():
        hidden_ids = _audit_hidden_trace_ids(message, 'action')
        trace = reader._action_trace_for_message(message)
        if not isinstance(trace, dict) or not trace:
            continue
        trace_status = trace.get('status') or ('matched' if trace.get('hit') else '')
        if status_value and trace_status != status_value:
            continue
        if risk_level and (trace.get('risk_level') or '') != risk_level:
            continue
        skills = _normalize_audit_trace_list(trace.get('skills') or [])
        skill_names = _audit_display_list(skills, skill_display_map)
        allowed_tools = _normalize_audit_trace_list(trace.get('allowed_tools') or [])
        decision = trace.get('decision') if isinstance(trace.get('decision'), dict) else {}
        payload = {
            **_audit_message_base_payload(message),
            'id': f'action-{message.id}-{trace.get("code") or "trace"}',
            'code': trace.get('code') or '',
            'display_name': trace.get('display_name') or trace.get('code') or '',
            'risk_level': trace.get('risk_level') or '',
            'risk_level_display': trace.get('risk_level_display') or '',
            'status': trace_status,
            'route': trace.get('route') or '',
            'skills': skills,
            'skill_names': skill_names,
            'allowed_tools': allowed_tools,
            'draft_generated': bool(trace.get('draft_generated')),
            'pending_action': trace.get('pending_action') if isinstance(trace.get('pending_action'), dict) else {},
            'decision': decision,
        }
        if payload['id'] in hidden_ids:
            continue
        if not _audit_text_matches(
            query,
            payload['display_name'],
            payload['code'],
            payload['route'],
            payload['session_title'],
            payload['username'],
            decision.get('task_name'),
            decision.get('reason'),
            ' '.join(skills),
            ' '.join(skill_names),
            ' '.join(allowed_tools),
        ):
            continue
        rows.append(payload)

    return _paginate_audit_rows(request, rows)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.manage')])
def audit_skill_traces_bulk_delete(request):
    return _hide_audit_trace_rows(request, 'skill', 'Skill 命中')


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.manage')])
def audit_action_traces_bulk_delete(request):
    return _hide_audit_trace_rows(request, 'action', '运行策略命中')


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.view')])
def audit_overview(request):
    data = build_audit_overview()
    data['session_status'] = list(AIOpsChatSession.objects.filter(mirror_source__isnull=True).values('status').annotate(count=Count('id')).order_by('status'))
    data['action_status'] = list(AIOpsPendingAction.objects.filter(mirror_source__isnull=True, session__mirror_source__isnull=True).values('status').annotate(count=Count('id')).order_by('status'))
    data['invocation_distribution'] = _audit_invocation_distribution(request)
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.view')])
def audit_cost_overview(request):
    return Response(build_model_cost_overview(
        days=request.query_params.get('days', 7),
        range_type=request.query_params.get('range', ''),
        start=request.query_params.get('start'),
        end=request.query_params.get('end'),
    ))


def _pending_action_confirm_permissions(action):
    if action.action_type == AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL:
        return ['aiops.config.manage']
    return ['aiops.task.execute']


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_pending_action(request, pk):
    action = AIOpsPendingAction.objects.select_related('session', 'message').filter(pk=pk).first()
    if not action:
        return Response({'detail': '审批事项不存在'}, status=status.HTTP_404_NOT_FOUND)
    required_permissions = _pending_action_confirm_permissions(action)
    if not user_has_permissions(request.user, required_permissions):
        return Response({'detail': f"缺少权限：{', '.join(required_permissions)}"}, status=status.HTTP_403_FORBIDDEN)
    try:
        confirmed_payload = confirm_action(action, request.user, request=request)
        action.refresh_from_db()
        result_payload = action.result_payload if isinstance(action.result_payload, dict) else {}
        if action.action_type == AIOpsPendingAction.ACTION_CREATE_AIOPS_SKILL:
            return Response({
                'success': True,
                'skill_id': result_payload.get('skill_id'),
                'skill_name': result_payload.get('skill_name'),
                'skill_slug': result_payload.get('skill_slug'),
                'skill_draft': confirmed_payload,
                'materialized_as_skill': bool(result_payload.get('materialized_as_skill')),
            })
        task = HostTask.objects.filter(pk=result_payload.get('task_id')).first()
        task_summary = None
        if task:
            task_summary = {
                'id': task.id,
                'name': task.name,
                'status': task.status,
                'lifecycle_status': task.lifecycle_status,
                'trigger_source': task.trigger_source,
            }
        return Response({
            'success': True,
            'task_name': result_payload.get('task_name') or confirmed_payload['name'],
            'task_id': result_payload.get('task_id'),
            'execution_started': bool(result_payload.get('execution_started')),
            'task': task_summary,
            'task_draft': confirmed_payload,
        })
    except ValueError as exc:
        action.status = AIOpsPendingAction.STATUS_FAILED
        action.result_payload = {'error': str(exc)}
        action.save(update_fields=['status', 'result_payload', 'updated_at'])
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.task.generate')])
def cancel_pending_action(request, pk):
    action = AIOpsPendingAction.objects.select_related('session', 'message').filter(pk=pk).first()
    if not action:
        return Response({'detail': '审批事项不存在'}, status=status.HTTP_404_NOT_FOUND)
    try:
        cancel_action(action, request.user)
        return Response({'success': True})
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
