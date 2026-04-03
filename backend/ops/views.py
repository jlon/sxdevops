from datetime import timedelta
import paramiko
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import build_json_preview, build_resource, record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission

from . import deployer
from .host_task_schedules import (
    build_schedule_snapshot,
    preview_next_runs,
    resolve_schedule_hosts,
    trigger_schedule,
)
from .host_tasks import build_host_target_queryset, start_host_task
from .models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalStep,
    Host,
    HostTask,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    LogEntry,
)
from .serializers import (
    AlertSerializer,
    ApprovalActionSerializer,
    DeploymentActionSerializer,
    DeploymentApprovalFlowSerializer,
    DeploymentSerializer,
    HostSerializer,
    HostTaskBatchCancelSerializer,
    HostTaskDetailSerializer,
    HostTaskScheduleExecutionSerializer,
    HostTaskSchedulePreviewSerializer,
    HostTaskScheduleSerializer,
    HostTaskSerializer,
    HostTaskSubmitSerializer,
    HostTaskTargetSerializer,
    HostTaskTemplateSerializer,
    LogEntrySerializer,
)


def _resolve_approval_flow(environment):
    flow = DeploymentApprovalFlow.objects.filter(is_active=True, environment=environment).prefetch_related('nodes').first()
    if flow:
        return flow
    return DeploymentApprovalFlow.objects.filter(is_active=True, environment='').prefetch_related('nodes').first()


def _initialize_approval_steps(deployment):
    flow = _resolve_approval_flow(deployment.environment)
    deployment.approval_flow = flow
    deployment.save(update_fields=['approval_flow'])
    deployment.approval_steps.all().delete()
    if not flow:
        return
    steps = []
    nodes = list(flow.nodes.all().order_by('order', 'id'))
    for index, node in enumerate(nodes):
        steps.append(
            DeploymentApprovalStep(
                deployment=deployment,
                flow=flow,
                node_name=node.name,
                node_order=node.order,
                approver_type=node.approver_type,
                approver_value=node.approver_value,
                is_current=index == 0,
            )
        )
    DeploymentApprovalStep.objects.bulk_create(steps)


def _match_step_approver(user, step):
    if user.is_superuser:
        return True
    if not step or not step.approver_value:
        return True
    if step.approver_type == 'user':
        return user.username == step.approver_value
    if step.approver_type == 'role':
        return user.rbac_roles.filter(code=step.approver_value).exists()
    if step.approver_type == 'group':
        return user.rbac_groups.filter(code=step.approver_value).exists()
    return True


class HostViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    search_fields = ['hostname', 'ip_address']
    filterset_fields = ['status', 'business_line', 'environment']
    event_module = 'ops'
    event_resource_type = 'host'
    event_resource_label = '主机'
    event_resource_name_fields = ('hostname',)
    event_exclude_fields = ('ssh_password',)
    rbac_permissions = {
        'list': ['ops.host.view'],
        'retrieve': ['ops.host.view'],
        'create': ['ops.host.manage'],
        'update': ['ops.host.manage'],
        'partial_update': ['ops.host.manage'],
        'destroy': ['ops.host.manage'],
        'test_connection': ['ops.host.manage'],
        'refresh_info': ['ops.host.manage'],
    }

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )
            stdin, stdout, stderr = client.exec_command('uname -a', timeout=5)
            uname = stdout.read().decode('utf-8', errors='replace').strip()
            client.close()
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_connection',
                title='\u6d4b\u8bd5\u4e3b\u673a\u8fde\u901a\u6027',
                summary=f'\u4e3b\u673a {host.hostname} \u8fde\u901a\u6027\u6d4b\u8bd5\u6210\u529f',
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'ip_address': host.ip_address},
            )
            return Response({'success': True, 'message': f'\u8fde\u63a5\u6210\u529f: {uname}'})
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_connection',
                title='\u6d4b\u8bd5\u4e3b\u673a\u8fde\u901a\u6027',
                summary=f'\u4e3b\u673a {host.hostname} \u8fde\u901a\u6027\u6d4b\u8bd5\u5931\u8d25',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'ip_address': host.ip_address, 'error': str(exc)},
            )
            return Response({'success': False, 'message': f'\u8fde\u63a5\u5931\u8d25: {str(exc)}'})

    @action(detail=True, methods=['post'])
    def refresh_info(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )

            def run_cmd(command):
                stdin, stdout, stderr = client.exec_command(command, timeout=5)
                return stdout.read().decode('utf-8', errors='replace').strip()

            try:
                host.cpu_usage = round(float(run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.memory_usage = round(float(run_cmd("free | grep Mem | awk '{printf(\"%.1f\", $3/$2*100)}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.disk_usage = round(float(run_cmd("df / | tail -1 | awk '{print $5}' | tr -d '%'")), 1)
            except (ValueError, TypeError):
                pass

            host.status = 'online'
            host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
            client.close()
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='refresh_info',
                title='\u5237\u65b0\u4e3b\u673a\u72b6\u6001',
                summary=f'\u4e3b\u673a {host.hostname} \u72b6\u6001\u5df2\u5237\u65b0',
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={
                    'cpu_usage': host.cpu_usage,
                    'memory_usage': host.memory_usage,
                    'disk_usage': host.disk_usage,
                },
            )
            return Response(HostSerializer(host).data)
        except Exception as exc:
            host.status = 'offline'
            host.save(update_fields=['status'])
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='refresh_info',
                title='\u5237\u65b0\u4e3b\u673a\u72b6\u6001',
                summary=f'\u4e3b\u673a {host.hostname} \u5237\u65b0\u5931\u8d25\uff0c\u5df2\u6807\u8bb0\u79bb\u7ebf',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'error': str(exc)},
            )
            return Response({'detail': f'\u83b7\u53d6\u4fe1\u606f\u5931\u8d25: {str(exc)}'}, status=400)


class HostTaskTemplateViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = HostTaskTemplateSerializer
    search_fields = ['name', 'description', 'created_by']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    event_module = 'ops'
    event_resource_type = 'host_task_template'
    event_resource_label = '主机任务模板'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.host.execute'],
        'retrieve': ['ops.host.execute'],
        'create': ['ops.host.execute'],
        'update': ['ops.host.execute'],
        'partial_update': ['ops.host.execute'],
        'destroy': ['ops.host.execute'],
    }

    def get_queryset(self):
        username = self.request.user.username
        return HostTaskTemplate.objects.filter(Q(is_builtin=True) | Q(created_by=username)).order_by('-is_builtin', 'name', '-id')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)

    def _validate_editable(self, instance):
        if instance.is_builtin:
            return Response({'detail': '\u5185\u7f6e\u6a21\u677f\u4e0d\u5141\u8bb8\u4fee\u6539\u6216\u5220\u9664'}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().destroy(request, *args, **kwargs)


class HostTaskViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = HostTask.objects.prefetch_related('executions').all()
    search_fields = ['name', 'description', 'created_by']
    filterset_fields = ['task_type', 'status', 'created_by']
    http_method_names = ['get', 'post', 'head', 'options']
    rbac_permissions = {
        'list': ['ops.host.execute'],
        'retrieve': ['ops.host.execute'],
        'create': ['ops.host.execute'],
        'rerun': ['ops.host.execute'],
        'cancel': ['ops.host.execute'],
        'batch_cancel': ['ops.host.execute'],
        'stats': ['ops.host.execute'],
        'host_options': ['ops.host.execute'],
    }

    def get_serializer_class(self):
        if self.action == 'create':
            return HostTaskSubmitSerializer
        if self.action == 'retrieve':
            return HostTaskDetailSerializer
        return HostTaskSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        host_ids = validated['host_ids']
        host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
        hosts = [host_map[item] for item in host_ids if item in host_map]
        if len(hosts) != len(host_ids):
            return Response({'detail': '\u5b58\u5728\u65e0\u6548\u7684\u76ee\u6807\u4e3b\u673a\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5'}, status=status.HTTP_400_BAD_REQUEST)

        task = HostTask.objects.create(
            name=validated['name'],
            task_type=validated['task_type'],
            description=validated.get('description', ''),
            payload=validated.get('payload') or {},
            selection_filters=validated.get('selection_filters') or {},
            execution_mode=validated.get('execution_mode', HostTask.EXECUTION_MODE_SSH),
            execution_strategy=validated.get('execution_strategy', HostTask.STRATEGY_CONTINUE),
            timeout_seconds=validated.get('timeout_seconds', 15),
            created_by=request.user.username,
            summary='\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u7b49\u5f85\u8c03\u5ea6\u6267\u884c',
        )
        start_host_task(task, hosts)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='create_task',
            title='\u521b\u5efa\u4e3b\u673a\u4efb\u52a1',
            summary=f'\u4e3b\u673a\u4efb\u52a1 {task.name} \u5df2\u521b\u5efa\uff0c\u76ee\u6807\u4e3b\u673a {len(hosts)} \u53f0',
            result=EventRecord.RESULT_PENDING,
            resource_type='host_task',
            resource_id=task.id,
            resource_name=task.name,
            correlation_id=f'host-task:{task.id}',
            related_resources=[
                build_resource('ops', 'host', host.id, host.hostname, environment=host.environment, business_line=host.business_line)
                for host in hosts[:10]
            ],
            metadata={
                'task_type': task.task_type,
                'execution_mode': task.execution_mode,
                'payload_preview': build_json_preview(task.payload),
            },
        )
        data = HostTaskDetailSerializer(self.get_queryset().get(pk=task.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        total = queryset.count()
        success = queryset.filter(status=HostTask.STATUS_SUCCESS).count()
        partial = queryset.filter(status=HostTask.STATUS_PARTIAL).count()
        failed = queryset.filter(status=HostTask.STATUS_FAILED).count()
        running = queryset.filter(status=HostTask.STATUS_RUNNING).count()
        pending = queryset.filter(status=HostTask.STATUS_PENDING).count()
        canceled = queryset.filter(status=HostTask.STATUS_CANCELED).count()
        target_total = sum(item.target_count for item in queryset[:50]) if total else 0
        latest = queryset.first()
        rate_base = success + partial + failed + canceled
        success_rate = round(((success + partial) / rate_base) * 100, 1) if rate_base else 0
        return Response({
            'total': total,
            'running': running,
            'pending': pending,
            'success': success,
            'partial': partial,
            'failed': failed,
            'canceled': canceled,
            'target_total': target_total,
            'success_rate': success_rate,
            'latest_finished_at': latest.finished_at if latest else None,
        })

    @action(detail=False, methods=['get'])
    def host_options(self, request):
        filters = {
            'search': request.query_params.get('search', ''),
            'status': request.query_params.get('status', ''),
            'business_line': request.query_params.get('business_line', ''),
            'environment': request.query_params.get('environment', ''),
        }
        queryset = build_host_target_queryset(filters)
        data = HostTaskTargetSerializer(queryset[:200], many=True).data
        return Response(data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        source = self.get_object()
        host_ids = [item.get('id') for item in (source.target_snapshot or []) if item.get('id')]
        host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
        hosts = [host_map[item] for item in host_ids if item in host_map]
        if not hosts:
            return Response({'detail': '\u5df2\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42\uff0c\u7b49\u5f85\u6267\u884c\u5668\u505c\u6b62\u4efb\u52a1'}, status=status.HTTP_400_BAD_REQUEST)

        rerun_task = HostTask.objects.create(
            name=f'{source.name} / \u91cd\u8dd1',
            task_type=source.task_type,
            description=source.description,
            payload=dict(source.payload or {}),
            selection_filters=dict(source.selection_filters or {}),
            execution_mode=source.execution_mode or HostTask.EXECUTION_MODE_SSH,
            execution_strategy=source.execution_strategy,
            timeout_seconds=source.timeout_seconds,
            created_by=request.user.username,
            summary='\u91cd\u8dd1\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u7b49\u5f85\u8c03\u5ea6\u6267\u884c',
        )
        start_host_task(rerun_task, hosts)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='rerun_task',
            title='\u91cd\u8dd1\u4e3b\u673a\u4efb\u52a1',
            summary=f'\u4e3b\u673a\u4efb\u52a1 {source.name} \u5df2\u53d1\u8d77\u91cd\u8dd1',
            result=EventRecord.RESULT_PENDING,
            resource_type='host_task',
            resource_id=rerun_task.id,
            resource_name=rerun_task.name,
            correlation_id=f'host-task:{source.id}',
            related_resources=[build_resource('ops', 'host_task', source.id, source.name)],
            metadata={'source_task_id': source.id, 'target_count': len(hosts)},
        )
        data = HostTaskDetailSerializer(self.get_queryset().get(pk=rerun_task.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        task = self.get_object()
        if task.status not in [HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING]:
            return Response({'detail': '\u5f53\u524d\u4efb\u52a1\u72b6\u6001\u4e0d\u5141\u8bb8\u7ec8\u6b62'}, status=status.HTTP_400_BAD_REQUEST)
        if task.cancel_requested:
            return Response({'detail': '\u8be5\u4efb\u52a1\u5df2\u63d0\u4ea4\u7ec8\u6b62\u7533\u8bf7'}, status=status.HTTP_400_BAD_REQUEST)
        task.cancel_requested = True
        task.cancel_requested_by = request.user.username
        task.cancel_requested_at = timezone.now()
        task.summary = '\u5df2\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42\uff0c\u7b49\u5f85\u6267\u884c\u5668\u505c\u6b62\u4efb\u52a1'
        task.save(update_fields=['cancel_requested', 'cancel_requested_by', 'cancel_requested_at', 'summary'])
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='cancel_task',
            title='\u7ec8\u6b62\u4e3b\u673a\u4efb\u52a1',
            summary=f'\u4e3b\u673a\u4efb\u52a1 {task.name} \u5df2\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='host_task',
            resource_id=task.id,
            resource_name=task.name,
            correlation_id=f'host-task:{task.id}',
        )
        return Response(HostTaskSerializer(task).data)

    @action(detail=False, methods=['post'])
    def batch_cancel(self, request):
        serializer = HostTaskBatchCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['ids']
        queryset = self.get_queryset().filter(id__in=ids, status__in=[HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING])
        tasks = list(queryset)
        if not tasks:
            return Response({'detail': '\u6ca1\u6709\u53ef\u7ec8\u6b62\u7684\u4efb\u52a1'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        queryset.update(
            cancel_requested=True,
            cancel_requested_by=request.user.username,
            cancel_requested_at=now,
            summary='\u5df2\u6279\u91cf\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42\uff0c\u7b49\u5f85\u6267\u884c\u5668\u505c\u6b62\u4efb\u52a1',
        )
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='batch_cancel_task',
            title='\u6279\u91cf\u7ec8\u6b62\u4e3b\u673a\u4efb\u52a1',
            summary=f'\u5df2\u6279\u91cf\u63d0\u4ea4 {len(tasks)} \u4e2a\u4e3b\u673a\u4efb\u52a1\u7684\u7ec8\u6b62\u8bf7\u6c42',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='host_task_batch',
            resource_id='batch_cancel',
            resource_name='鎵归噺缁堟浠诲姟',
            correlation_id=f'host-task-batch-cancel:{now.strftime("%Y%m%d%H%M%S")}',
            metadata={'ids': [item.id for item in tasks]},
        )
        return Response({
            'count': len(tasks),
            'ids': [item.id for item in tasks],
            'detail': f'\u5df2\u63d0\u4ea4 {len(tasks)} \u4e2a\u4efb\u52a1\u7684\u7ec8\u6b62\u8bf7\u6c42',
        })


class HostTaskScheduleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = HostTaskSchedule.objects.all()
    serializer_class = HostTaskScheduleSerializer
    search_fields = ['name', 'description', 'created_by', 'updated_by']
    filterset_fields = ['enabled', 'task_type', 'execution_mode', 'schedule_type']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    event_module = 'ops'
    event_resource_type = 'host_task_schedule'
    event_resource_label = '主机定时任务'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.host.schedule.view'],
        'retrieve': ['ops.host.schedule.view'],
        'create': ['ops.host.schedule.manage'],
        'update': ['ops.host.schedule.manage'],
        'partial_update': ['ops.host.schedule.manage'],
        'destroy': ['ops.host.schedule.manage'],
        'stats': ['ops.host.schedule.view'],
        'preview_next_runs': ['ops.host.schedule.manage'],
        'toggle_enabled': ['ops.host.schedule.manage'],
        'run_now': ['ops.host.schedule.execute'],
    }

    def get_queryset(self):
        return HostTaskSchedule.objects.order_by('-enabled', 'next_run_at', '-id')

    def _persist_schedule(self, serializer, created=False):
        next_run_at = serializer.validated_data.pop('computed_next_run_at', None)
        actor_field = {'created_by': self.request.user.username} if created else {}
        schedule = serializer.save(updated_by=self.request.user.username, **actor_field)
        hosts = resolve_schedule_hosts(schedule)
        schedule.target_count = len(hosts)
        schedule.target_snapshot = build_schedule_snapshot(hosts)
        schedule.next_run_at = next_run_at if schedule.enabled else None
        schedule.save(update_fields=['updated_by', 'target_count', 'target_snapshot', 'next_run_at', 'updated_at'])
        return schedule

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = self._persist_schedule(serializer, created=True)
        return Response(self.get_serializer(schedule).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        schedule = self._persist_schedule(serializer, created=False)
        return Response(self.get_serializer(schedule).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        now = timezone.now()
        total = queryset.count()
        enabled = queryset.filter(enabled=True).count()
        running = queryset.filter(generated_tasks__status__in=[HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING]).distinct().count()
        due_soon = queryset.filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=now + timedelta(hours=1)).count()
        recent_executions = HostTaskScheduleExecution.objects.filter(schedule__in=queryset, requested_at__gte=now - timedelta(days=7))
        finished_total = recent_executions.filter(status__in=[HostTask.STATUS_SUCCESS, HostTask.STATUS_PARTIAL, HostTask.STATUS_FAILED, HostTask.STATUS_CANCELED]).count()
        success_total = recent_executions.filter(status__in=[HostTask.STATUS_SUCCESS, HostTask.STATUS_PARTIAL]).count()
        success_rate = round((success_total / finished_total) * 100, 1) if finished_total else 0
        latest = recent_executions.order_by('-requested_at').first()
        return Response({
            'total': total,
            'enabled': enabled,
            'disabled': max(total - enabled, 0),
            'running': running,
            'due_soon': due_soon,
            'success_rate': success_rate,
            'latest_requested_at': latest.requested_at if latest else None,
        })

    @action(detail=False, methods=['post'])
    def preview_next_runs(self, request):
        serializer = HostTaskSchedulePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hosts = resolve_schedule_hosts(serializer.validated_data)
        return Response({
            'next_run_at': serializer.validated_data.get('computed_next_run_at'),
            'next_runs': preview_next_runs(serializer.validated_data, count=5),
            'target_count': len(hosts),
            'target_snapshot': build_schedule_snapshot(hosts[:12]),
        })

    @action(detail=True, methods=['post'])
    def toggle_enabled(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = not schedule.enabled
        schedule.updated_by = request.user.username
        if schedule.enabled:
            next_runs = preview_next_runs(schedule, count=1)
            schedule.next_run_at = next_runs[0] if next_runs else None
        else:
            schedule.next_run_at = None
        schedule.save(update_fields=['enabled', 'updated_by', 'next_run_at', 'updated_at'])
        record_event(
            request=request,
            module='ops',
            category='workflow',
            action='toggle_schedule',
            title='\u5207\u6362\u5b9a\u65f6\u4efb\u52a1\u72b6\u6001',
            summary=f'\u5b9a\u65f6\u4efb\u52a1 {schedule.name} \u5df2{"\u542f\u7528" if schedule.enabled else "\u505c\u7528"}',
            resource_type='host_task_schedule',
            resource_id=schedule.id,
            resource_name=schedule.name,
            correlation_id=f'host-task-schedule:{schedule.id}',
            metadata={'enabled': schedule.enabled, 'next_run_at': schedule.next_run_at},
        )
        return Response(self.get_serializer(schedule).data)

    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        schedule = self.get_object()
        execution, _task = trigger_schedule(
            schedule,
            actor=request.user.username,
            trigger_source=HostTaskScheduleExecution.TRIGGER_MANUAL,
            scheduled_run=False,
        )
        if not execution:
            return Response(
                {'detail': '\u5f53\u524d\u5df2\u6709\u6267\u884c\u4e2d\u7684\u540c\u540d\u7f16\u6392\uff0c\u5df2\u6309\u5e76\u53d1\u7b56\u7565\u8df3\u8fc7\u672c\u6b21\u89e6\u53d1'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='run_schedule',
            title='\u624b\u52a8\u89e6\u53d1\u5b9a\u65f6\u4efb\u52a1',
            summary=f'\u5df2\u624b\u52a8\u89e6\u53d1\u5b9a\u65f6\u4efb\u52a1 {schedule.name}',
            result=EventRecord.RESULT_PENDING,
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='host_task_schedule',
            resource_id=schedule.id,
            resource_name=schedule.name,
            correlation_id=f'host-task-schedule:{schedule.id}',
            related_resources=[build_resource('ops', 'host_task', _task.id, _task.name)] if _task else [],
            metadata={'execution_id': execution.id},
        )
        return Response(HostTaskScheduleExecutionSerializer(execution).data, status=status.HTTP_201_CREATED)


class HostTaskScheduleExecutionViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = HostTaskScheduleExecutionSerializer
    search_fields = ['schedule__name', 'summary', 'requested_by', 'host_task__name']
    filterset_fields = ['schedule', 'status', 'trigger_source']
    http_method_names = ['get', 'head', 'options']
    rbac_permissions = {
        'list': ['ops.host.schedule.view'],
        'retrieve': ['ops.host.schedule.view'],
    }

    def get_queryset(self):
        queryset = HostTaskScheduleExecution.objects.select_related('schedule', 'host_task').order_by('-requested_at', '-id')
        schedule_id = self.request.query_params.get('schedule')
        if schedule_id:
            queryset = queryset.filter(schedule_id=schedule_id)
        return queryset

class DeploymentApprovalFlowViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = DeploymentApprovalFlow.objects.prefetch_related('nodes').all()
    serializer_class = DeploymentApprovalFlowSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'deployment_approval_flow'
    event_resource_label = '\u53d1\u5e03\u5ba1\u6279\u6d41'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)


class DeploymentViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Deployment.objects.select_related(
        'host',
        'docker_host',
        'cluster',
        'approval_flow',
        'previous_success',
        'rollback_source',
        'rerun_source',
    ).prefetch_related('approval_steps').all()
    serializer_class = DeploymentSerializer
    search_fields = ['app_name', 'business_line', 'version', 'image', 'submitter', 'deployer']
    filterset_fields = ['business_line', 'environment', 'deploy_mode', 'approval_status', 'status', 'release_strategy']
    event_module = 'ops'
    event_resource_type = 'deployment'
    event_resource_label = '发布单'
    event_resource_name_fields = ('app_name',)
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
        'approve': ['ops.deployment.approve'],
        'reject': ['ops.deployment.approve'],
        'stop': ['ops.deployment.manage'],
        'start': ['ops.deployment.manage'],
        'remove': ['ops.deployment.manage'],
        'logs': ['ops.deployment.view'],
        'status_detail': ['ops.deployment.view'],
        'rerun': ['ops.deployment.manage'],
        'rollback': ['ops.deployment.manage'],
        'advance_batch': ['ops.deployment.manage'],
    }

    def perform_create(self, serializer):
        deployment = serializer.save(submitter=self.request.user.username)
        _initialize_approval_steps(deployment)

    def eventwall_should_record(self, action, instance=None):
        return False

    def eventwall_related_resources(self, instance):
        related = []
        if instance.cluster_id:
            related.append(build_resource('ops', 'k8s_cluster', instance.cluster_id, instance.cluster.name))
        if instance.docker_host_id:
            related.append(build_resource('ops', 'docker_host', instance.docker_host_id, instance.docker_host.name))
        if instance.host_id:
            related.append(build_resource('ops', 'host', instance.host_id, instance.host.hostname))
        return related

    def _clone_release(
        self,
        source,
        actor,
        action_type,
        change_summary='',
        previous_success=None,
        rollback_source=None,
        rerun_source=None,
    ):
        deployment = Deployment.objects.create(
            app_name=source.app_name,
            business_line=source.business_line,
            version=source.version,
            image=source.image,
            environment=source.environment,
            deploy_mode=source.deploy_mode,
            release_strategy=source.release_strategy,
            submitter=actor,
            host=source.host,
            docker_host=source.docker_host,
            cluster=source.cluster,
            namespace=source.namespace,
            release_name=source.release_name,
            replicas=source.replicas,
            container_port=source.container_port,
            service_port=source.service_port,
            canary_percent=source.canary_percent,
            batch_total=source.batch_total,
            batch_size=source.batch_size,
            strategy_config=dict(source.strategy_config or {}),
            env_config=dict(source.env_config or {}),
            description=source.description,
            change_summary=change_summary,
            action_type=action_type,
            previous_success=previous_success,
            rollback_source=rollback_source,
            rerun_source=rerun_source,
        )
        _initialize_approval_steps(deployment)
        return deployment

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '\u53ea\u80fd\u5ba1\u6279\u5f85\u5ba1\u6279\u7684\u53d1\u5e03\u5355'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '\u5f53\u524d\u8d26\u53f7\u4e0d\u5728\u8be5\u5ba1\u6279\u8282\u70b9\u7684\u5ba1\u6279\u8303\u56f4\u5185'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'approved'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])

            next_step = deployment.approval_steps.filter(status='pending').order_by('node_order', 'id').first()
            deployment.approver = request.user.username
            deployment.approval_comment = comment
            if next_step:
                next_step.is_current = True
                next_step.save(update_fields=['is_current'])
                deployment.save(update_fields=['approver', 'approval_comment'])
                return Response(DeploymentSerializer(deployment).data)

        deployment.approval_status = 'approved'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.deployer = request.user.username
        deployment.save(update_fields=['approval_status', 'approver', 'approval_comment', 'approved_at', 'deployer'])
        deployer.start_deployment_thread(deployment.id)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '\u53ea\u80fd\u9a73\u56de\u5f85\u5ba1\u6279\u7684\u53d1\u5e03\u5355'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '\u5f53\u524d\u8d26\u53f7\u4e0d\u5728\u8be5\u5ba1\u6279\u8282\u70b9\u7684\u5ba1\u6279\u8303\u56f4\u5185'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'rejected'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])
            deployment.approval_steps.filter(status='pending').update(is_current=False)

        deployment.approval_status = 'rejected'
        deployment.status = 'rejected'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.save(update_fields=['approval_status', 'status', 'approver', 'approval_comment', 'approved_at'])
        record_event(
            request=request,
            module='ops',
            category='workflow',
            action='reject',
            title='驳回发布单',
            summary=f'发布单 {deployment.app_name} 已被驳回',
            result=EventRecord.RESULT_REJECTED,
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata={'comment': comment},
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            deployment,
            actor=request.user.username,
            action_type='rerun',
            change_summary=serializer.validated_data.get('change_summary') or f'闁插秵鏌婇幍褑顢?#{deployment.id}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rerun_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        deployment = self.get_object()
        previous_release = deployment.get_previous_successful_release()
        if not previous_release:
            return Response({'detail': '\u672a\u627e\u5230\u53ef\u56de\u6eda\u7684\u5386\u53f2\u6210\u529f\u7248\u672c'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            previous_release,
            actor=request.user.username,
            action_type='rollback',
            change_summary=serializer.validated_data.get('change_summary') or f'閸ョ偞绮撮崚?v{previous_release.version}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rollback_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def advance_batch(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployer.advance_batch(
                deployment,
                actor=request.user.username,
                change_summary=serializer.validated_data.get('change_summary', ''),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        deployment = self.get_object()
        deployer.stop_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='stop',
            title='停止应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行停止操作',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        deployment = self.get_object()
        deployer.start_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='start',
            title='启动应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行启动操作',
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        deployment = self.get_object()
        deployer.remove_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='remove',
            title='下线应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行下线操作',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        deployment = self.get_object()
        tail = int(request.query_params.get('tail', 100))
        return Response({'logs': deployer.get_service_logs(deployment, tail=tail)})

    @action(detail=True, methods=['get'])
    def status_detail(self, request, pk=None):
        deployment = self.get_object()
        return Response(deployer.get_service_status(deployment))


class AlertViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('host').all()
    serializer_class = AlertSerializer
    search_fields = ['title', 'source', 'message']
    rbac_permissions = {
        'list': ['ops.alert.view'],
        'retrieve': ['ops.alert.view'],
        'create': ['ops.alert.manage'],
        'update': ['ops.alert.manage'],
        'partial_update': ['ops.alert.manage'],
        'destroy': ['ops.alert.manage'],
    }


class LogEntryViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = LogEntry.objects.select_related('host').all()
    serializer_class = LogEntrySerializer
    search_fields = ['service', 'message']
    rbac_permissions = {
        'list': ['ops.log.entry.view'],
        'retrieve': ['ops.log.entry.view'],
        'create': ['ops.log.entry.manage'],
        'update': ['ops.log.entry.manage'],
        'partial_update': ['ops.log.entry.manage'],
        'destroy': ['ops.log.entry.manage'],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.dashboard.view')])
def dashboard_stats(request):
    host_total = Host.objects.count()
    host_status = dict(Host.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count'))
    host_avg = Host.objects.aggregate(
        avg_cpu=Avg('cpu_usage'),
        avg_memory=Avg('memory_usage'),
        avg_disk=Avg('disk_usage'),
    )

    deploy_total = Deployment.objects.count()
    deploy_running = Deployment.objects.filter(status='running', is_current=True).count()
    deploy_failed = Deployment.objects.filter(status__in=['failed', 'rejected']).count()
    deploy_success = Deployment.objects.filter(status__in=['running', 'stopped', 'removed']).count()

    alert_total = Alert.objects.count()
    alert_unacked = Alert.objects.filter(is_acknowledged=False).count()
    alert_levels = dict(Alert.objects.values_list('level').annotate(count=Count('id')).values_list('level', 'count'))

    recent_deploys = DeploymentSerializer(
        Deployment.objects.select_related('host', 'docker_host', 'cluster', 'approval_flow').prefetch_related('approval_steps').all()[:10],
        many=True,
    ).data
    recent_alerts = AlertSerializer(
        Alert.objects.select_related('host').filter(is_acknowledged=False)[:10],
        many=True,
    ).data

    return Response({
        'hosts': {
            'total': host_total,
            'online': host_status.get('online', 0),
            'offline': host_status.get('offline', 0),
            'warning': host_status.get('warning', 0),
            'avg_cpu': round(host_avg['avg_cpu'] or 0, 1),
            'avg_memory': round(host_avg['avg_memory'] or 0, 1),
            'avg_disk': round(host_avg['avg_disk'] or 0, 1),
        },
        'deployments': {
            'total': deploy_total,
            'success': deploy_success,
            'failed': deploy_failed,
            'running': deploy_running,
        },
        'alerts': {
            'total': alert_total,
            'unacknowledged': alert_unacked,
            'critical': alert_levels.get('critical', 0),
            'warning': alert_levels.get('warning', 0),
            'info': alert_levels.get('info', 0),
        },
        'recent_deploys': recent_deploys,
        'recent_alerts': recent_alerts,
    })


