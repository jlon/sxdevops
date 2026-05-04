from rest_framework import serializers

from cmdb.models import CIRelation, ConfigItem, ResourceNode

from .host_task_schedules import CronExpressionError, compute_next_run, preview_next_runs, validate_cron_expression
from .models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    FireMapSystem,
    GrafanaSetting,
    Host,
    HostTask,
    HostTaskExecution,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogDataSource,
    LogEntry,
    NginxCertificate,
    NginxDomain,
    NginxEnvironment,
    NginxRoute,
    ObservabilityDataSourceLink,
    TracingDataSource,
    TransactionTicket,
)

LOG_SENSITIVE_KEYS = {
    'password',
    'api_key',
    'token',
    'bearer_token',
    'access_key_id',
    'access_key_secret',
    'authorization',
    'client_secret',
}


def normalize_json_object(value):
    return value if isinstance(value, dict) else {}


def validate_host_task_payload(task_type, payload):
    payload = normalize_json_object(payload)
    if task_type == HostTask.TASK_RUN_COMMAND and not (payload.get('command') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要执行的命令'})
    if task_type == HostTask.TASK_RUN_PLAYBOOK and not (payload.get('playbook_content') or '').strip():
        raise serializers.ValidationError({'payload': '请填写 Playbook 内容'})
    if task_type == HostTask.TASK_SERVICE_STATUS and not (payload.get('service_name') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要巡检的服务名'})
    return payload


def normalize_schedule_hosts(value):
    value = value or []
    return list(dict.fromkeys(int(item) for item in value if item))


def validate_schedule_definition(attrs, instance=None):
    schedule_type = attrs.get('schedule_type') or getattr(instance, 'schedule_type', HostTaskSchedule.SCHEDULE_TYPE_CRON)
    timezone_name = attrs.get('timezone') or getattr(instance, 'timezone', 'Asia/Shanghai')
    cron_expression = (attrs.get('cron_expression') if 'cron_expression' in attrs else getattr(instance, 'cron_expression', '')) or ''
    interval_seconds = attrs.get('interval_seconds') if 'interval_seconds' in attrs else getattr(instance, 'interval_seconds', None)
    run_at = attrs.get('run_at') if 'run_at' in attrs else getattr(instance, 'run_at', None)

    if schedule_type == HostTaskSchedule.SCHEDULE_TYPE_CRON:
        if not str(cron_expression).strip():
            raise serializers.ValidationError({'cron_expression': '请填写 Cron 表达式'})
        try:
            validate_cron_expression(cron_expression)
        except CronExpressionError as exc:
            raise serializers.ValidationError({'cron_expression': str(exc)}) from exc
        attrs['interval_seconds'] = None
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_INTERVAL:
        if not interval_seconds:
            raise serializers.ValidationError({'interval_seconds': '请填写间隔秒数'})
        if int(interval_seconds) < 60:
            raise serializers.ValidationError({'interval_seconds': '间隔任务至少间隔 60 秒'})
        attrs['cron_expression'] = ''
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_ONCE:
        if not run_at:
            raise serializers.ValidationError({'run_at': '请选择执行时间'})
        attrs['cron_expression'] = ''
        attrs['interval_seconds'] = None
    else:
        raise serializers.ValidationError({'schedule_type': '不支持的调度类型'})

    preview_source = {
        'schedule_type': schedule_type,
        'cron_expression': attrs.get('cron_expression', cron_expression),
        'interval_seconds': attrs.get('interval_seconds', interval_seconds),
        'run_at': attrs.get('run_at', run_at),
        'timezone': timezone_name,
    }
    attrs['computed_next_run_at'] = compute_next_run(preview_source)
    return attrs


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.SerializerMethodField()

    class Meta:
        model = Host
        fields = '__all__'

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if business_line and not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '\u6240\u9009\u4e1a\u52a1\u7ebf\u672a\u5728\u8d44\u6e90\u6811\u4e2d\u914d\u7f6e'})

        if environment:
            if not business_line:
                raise serializers.ValidationError({'environment': '\u8bf7\u5148\u9009\u62e9\u4e1a\u52a1\u7ebf'})
            if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
                raise serializers.ValidationError({'environment': '\u6240\u9009\u73af\u5883\u672a\u5728\u5f53\u524d\u4e1a\u52a1\u7ebf\u4e0b\u914d\u7f6e'})

        attrs['business_line'] = business_line
        return attrs


class HostTaskExecutionSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = HostTaskExecution
        fields = [
            'id',
            'host',
            'host_name',
            'host_ip',
            'status',
            'status_display',
            'command',
            'output',
            'error_message',
            'duration_ms',
            'started_at',
            'finished_at',
            'created_at',
        ]


class HostTaskSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = HostTask
        fields = [
            'id',
            'name',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'trigger_source',
            'trigger_source_display',
            'status',
            'status_display',
            'description',
            'payload',
            'selection_filters',
            'target_snapshot',
            'execution_strategy',
            'timeout_seconds',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'success_rate',
            'cancel_requested',
            'cancel_requested_by',
            'cancel_requested_at',
            'created_by',
            'summary',
            'started_at',
            'finished_at',
            'created_at',
            'updated_at',
        ]

    def get_success_rate(self, obj):
        if not obj.target_count:
            return 0
        return round((obj.success_count / obj.target_count) * 100, 1)


class HostTaskDetailSerializer(HostTaskSerializer):
    executions = HostTaskExecutionSerializer(many=True, read_only=True)

    class Meta(HostTaskSerializer.Meta):
        fields = HostTaskSerializer.Meta.fields + ['executions']


class HostTaskTemplateSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)

    class Meta:
        model = HostTaskTemplate
        fields = [
            'id',
            'name',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'description',
            'payload',
            'execution_strategy',
            'timeout_seconds',
            'is_builtin',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['is_builtin', 'created_by', 'created_at', 'updated_at']

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskSubmitSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=120, default=15)

    def validate_host_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        if not deduplicated:
            raise serializers.ValidationError('\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u53f0\u4e3b\u673a')
        return deduplicated

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type')
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskBatchCancelSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)

    def validate_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        if not deduplicated:
            raise serializers.ValidationError('\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u4e2a\u4efb\u52a1')
        return deduplicated


class HostTaskTargetSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = [
            'id',
            'hostname',
            'ip_address',
            'business_line',
            'environment',
            'environment_display',
            'admin_user',
            'os_type',
            'status',
            'status_display',
        ]

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''


class HostTaskScheduleExecutionSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source='schedule.name', read_only=True)
    host_task_name = serializers.CharField(source='host_task.name', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = HostTaskScheduleExecution
        fields = [
            'id',
            'schedule',
            'schedule_name',
            'host_task',
            'host_task_name',
            'trigger_source',
            'trigger_source_display',
            'status',
            'status_display',
            'summary',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'error_message',
            'requested_by',
            'requested_at',
            'started_at',
            'finished_at',
            'created_at',
        ]


class HostTaskScheduleSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    schedule_type_display = serializers.CharField(source='get_schedule_type_display', read_only=True)
    overlap_policy_display = serializers.CharField(source='get_overlap_policy_display', read_only=True)
    last_status_display = serializers.SerializerMethodField()
    next_runs_preview = serializers.SerializerMethodField()

    class Meta:
        model = HostTaskSchedule
        fields = [
            'id',
            'name',
            'description',
            'enabled',
            'task_type',
            'task_type_display',
            'payload',
            'selection_filters',
            'target_host_ids',
            'target_snapshot',
            'target_count',
            'execution_mode',
            'execution_mode_display',
            'execution_strategy',
            'timeout_seconds',
            'schedule_type',
            'schedule_type_display',
            'cron_expression',
            'interval_seconds',
            'run_at',
            'timezone',
            'overlap_policy',
            'overlap_policy_display',
            'next_run_at',
            'next_runs_preview',
            'last_run_at',
            'last_status',
            'last_status_display',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'target_snapshot',
            'target_count',
            'next_run_at',
            'last_run_at',
            'last_status',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]

    def get_last_status_display(self, obj):
        return obj.get_last_status_display() if obj.last_status else ''

    def get_next_runs_preview(self, obj):
        return preview_next_runs(obj, count=3)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        validate_host_task_payload(task_type, attrs.get('payload') if 'payload' in attrs else getattr(self.instance, 'payload', {}))
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs, instance=self.instance)


class HostTaskSchedulePreviewSerializer(serializers.Serializer):
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    target_host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=300, default=15)
    enabled = serializers.BooleanField(required=False, default=True)
    schedule_type = serializers.ChoiceField(choices=HostTaskSchedule.SCHEDULE_TYPE_CHOICES)
    cron_expression = serializers.CharField(required=False, allow_blank=True, default='')
    interval_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=60, max_value=2592000)
    run_at = serializers.DateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, allow_blank=True, default='Asia/Shanghai')
    overlap_policy = serializers.ChoiceField(choices=HostTaskSchedule.OVERLAP_POLICY_CHOICES, default=HostTaskSchedule.OVERLAP_SKIP)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        validate_host_task_payload(attrs.get('task_type'), attrs.get('payload') or {})
        if attrs.get('task_type') == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs)

class DeploymentApprovalNodeSerializer(serializers.ModelSerializer):
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalNode
        fields = [
            'id',
            'name',
            'order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'description',
        ]


class DeploymentApprovalStepSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalStep
        fields = [
            'id',
            'flow',
            'node_name',
            'node_order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'status',
            'status_display',
            'is_current',
            'approver',
            'comment',
            'acted_at',
            'created_at',
        ]


class DeploymentApprovalFlowSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    scope_display = serializers.CharField(read_only=True)
    nodes = DeploymentApprovalNodeSerializer(many=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentApprovalFlow
        fields = [
            'id',
            'name',
            'environment',
            'environment_display',
            'scope_display',
            'description',
            'is_active',
            'created_by',
            'node_count',
            'nodes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else '全部环境'

    def get_node_count(self, obj):
        return obj.nodes.count()

    def validate_nodes(self, value):
        if not value:
            raise serializers.ValidationError('至少需要配置一个审批节点')
        orders = [item.get('order') for item in value]
        if len(set(orders)) != len(orders):
            raise serializers.ValidationError('审批节点顺序不能重复')
        for item in value:
            if not item.get('name'):
                raise serializers.ValidationError('审批节点名称不能为空')
        return value

    def _sync_active_flow(self, instance):
        if instance.is_active:
            DeploymentApprovalFlow.objects.filter(
                environment=instance.environment,
                is_active=True,
            ).exclude(pk=instance.pk).update(is_active=False)

    def _replace_nodes(self, instance, nodes):
        instance.nodes.all().delete()
        DeploymentApprovalNode.objects.bulk_create([
            DeploymentApprovalNode(
                flow=instance,
                name=item['name'],
                order=item['order'],
                approver_type=item.get('approver_type') or 'user',
                approver_value=item.get('approver_value', ''),
                description=item.get('description', ''),
            )
            for item in sorted(nodes, key=lambda data: (data['order'], data.get('name', '')))
        ])

    def create(self, validated_data):
        nodes = validated_data.pop('nodes', [])
        instance = super().create(validated_data)
        self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance

    def update(self, instance, validated_data):
        nodes = validated_data.pop('nodes', None)
        instance = super().update(instance, validated_data)
        if nodes is not None:
            self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    deploy_mode_display = serializers.CharField(source='get_deploy_mode_display', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    release_strategy_display = serializers.CharField(source='get_release_strategy_display', read_only=True)
    docker_host_name = serializers.CharField(source='docker_host.name', read_only=True, default='')
    docker_host_ip = serializers.CharField(source='docker_host.ip_address', read_only=True, default='')
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')
    host_ip = serializers.CharField(source='host.ip_address', read_only=True, default='')
    cluster_name = serializers.CharField(source='cluster.name', read_only=True, default='')
    target_display = serializers.CharField(read_only=True)
    strategy_summary = serializers.CharField(read_only=True)
    approval_progress_text = serializers.CharField(read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')
    approval_steps = DeploymentApprovalStepSerializer(many=True, read_only=True)
    current_approval_step = serializers.SerializerMethodField()
    previous_success_version = serializers.CharField(source='previous_success.version', read_only=True, default='')
    rollback_source_version = serializers.CharField(source='rollback_source.version', read_only=True, default='')
    rerun_source_version = serializers.CharField(source='rerun_source.version', read_only=True, default='')
    can_rollback = serializers.SerializerMethodField()
    can_advance_batch = serializers.SerializerMethodField()
    cmdb_item_id = serializers.SerializerMethodField()
    cmdb_item_name = serializers.SerializerMethodField()
    cmdb_item_status = serializers.SerializerMethodField()
    cmdb_targets = serializers.SerializerMethodField()

    class Meta:
        model = Deployment
        fields = [
            'id',
            'app_name',
            'business_line',
            'version',
            'image',
            'environment',
            'environment_display',
            'deploy_mode',
            'deploy_mode_display',
            'status',
            'status_display',
            'approval_status',
            'approval_status_display',
            'action_type',
            'action_type_display',
            'release_strategy',
            'release_strategy_display',
            'strategy_summary',
            'canary_percent',
            'batch_total',
            'batch_current',
            'batch_size',
            'strategy_config',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'change_summary',
            'description',
            'env_config',
            'deploy_log',
            'deploy_dir',
            'release_name',
            'namespace',
            'replicas',
            'container_port',
            'service_port',
            'docker_host',
            'docker_host_name',
            'docker_host_ip',
            'host',
            'host_name',
            'host_ip',
            'cluster',
            'cluster_name',
            'target_display',
            'approval_flow',
            'approval_flow_name',
            'approval_progress_text',
            'approval_steps',
            'current_approval_step',
            'previous_success',
            'previous_success_version',
            'rollback_source',
            'rollback_source_version',
            'rerun_source',
            'rerun_source_version',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'can_rollback',
            'can_advance_batch',
            'cmdb_item_id',
            'cmdb_item_name',
            'cmdb_item_status',
            'cmdb_targets',
            'deployed_at',
        ]
        read_only_fields = [
            'status',
            'approval_status',
            'action_type',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'deploy_log',
            'deploy_dir',
            'approval_flow',
            'previous_success',
            'rollback_source',
            'rerun_source',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'batch_current',
            'deployed_at',
        ]

    def get_can_rollback(self, obj):
        return bool(obj.is_current and obj.get_previous_successful_release())

    def get_can_advance_batch(self, obj):
        return bool(
            obj.release_strategy == 'batch'
            and obj.approval_status == 'approved'
            and obj.is_current
            and (obj.batch_current or 0) < (obj.batch_total or 1)
        )

    def get_current_approval_step(self, obj):
        step = obj.current_approval_step
        return DeploymentApprovalStepSerializer(step).data if step else None

    def _get_cmdb_item(self, obj):
        cached = getattr(obj, '_cmdb_item_cache', None)
        if cached is not None:
            return cached
        item = ConfigItem.objects.filter(
            attributes__source='app_release',
            attributes__deployment_id=obj.id,
        ).first()
        setattr(obj, '_cmdb_item_cache', item)
        return item

    def get_cmdb_item_id(self, obj):
        item = self._get_cmdb_item(obj)
        return item.id if item else None

    def get_cmdb_item_name(self, obj):
        item = self._get_cmdb_item(obj)
        return item.name if item else ''

    def get_cmdb_item_status(self, obj):
        item = self._get_cmdb_item(obj)
        return item.get_status_display() if item else ''

    def get_cmdb_targets(self, obj):
        item = self._get_cmdb_item(obj)
        if not item:
            return []
        return [
            relation.target.name
            for relation in CIRelation.objects.select_related('target').filter(source=item, relation_type='runs_on')
        ]

    def validate_strategy_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('策略配置必须为 JSON 对象')
        return value

    def validate_env_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('环境变量必须为 JSON 对象')
        return value

    def validate(self, attrs):
        business_line = (attrs.get('business_line') or getattr(self.instance, 'business_line', '') or '').strip()
        environment = attrs.get('environment') or getattr(self.instance, 'environment', '')
        deploy_mode = attrs.get('deploy_mode') or getattr(self.instance, 'deploy_mode', 'docker_compose')
        docker_host = attrs.get('docker_host', getattr(self.instance, 'docker_host', None))
        host = attrs.get('host', getattr(self.instance, 'host', None))
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))
        namespace = attrs.get('namespace', getattr(self.instance, 'namespace', ''))
        strategy = attrs.get('release_strategy') or getattr(self.instance, 'release_strategy', 'standard')
        canary_percent = attrs.get('canary_percent', getattr(self.instance, 'canary_percent', 10))
        batch_total = attrs.get('batch_total', getattr(self.instance, 'batch_total', 1))
        batch_size = attrs.get('batch_size', getattr(self.instance, 'batch_size', 1))

        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择业务线'})
        biz_node = ResourceNode.objects.filter(node_type='biz', name=business_line).first()
        if not biz_node:
            raise serializers.ValidationError({'business_line': '所选业务线未在 CMDB 资源树中配置'})
        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent=biz_node, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未在 CMDB 中绑定到当前业务线'})
        attrs['business_line'] = business_line

        if deploy_mode == 'docker_compose':
            docker_host = docker_host or self._resolve_docker_host_from_legacy(host)
            if not docker_host:
                raise serializers.ValidationError({'docker_host': 'Docker 环境模式必须选择 Docker 环境'})
            attrs['docker_host'] = docker_host
            attrs['host'] = None
            attrs['cluster'] = None
            attrs['namespace'] = ''
        else:
            if not cluster:
                raise serializers.ValidationError({'cluster': 'K8s 集群模式必须选择目标集群'})
            attrs['docker_host'] = None
            attrs['host'] = None
            attrs['namespace'] = (namespace or 'default').strip() or 'default'

        if strategy == 'canary':
            if canary_percent <= 0 or canary_percent > 100:
                raise serializers.ValidationError({'canary_percent': '灰度比例必须在 1-100 之间'})
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1
        elif strategy == 'batch':
            if batch_total < 2:
                raise serializers.ValidationError({'batch_total': '批次发布至少需要 2 个批次'})
            if batch_size < 1:
                raise serializers.ValidationError({'batch_size': '单批规模必须大于 0'})
        else:
            attrs['canary_percent'] = 10
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1

        image = attrs.get('image') or getattr(self.instance, 'image', '')
        app_name = attrs.get('app_name') or getattr(self.instance, 'app_name', '')
        version = attrs.get('version') or getattr(self.instance, 'version', '')
        if not image:
            attrs['image'] = f'{app_name}:{version}'
        return attrs

    def _resolve_docker_host_from_legacy(self, host):
        if not host:
            return None
        docker_host = DockerHost.objects.filter(ip_address=host.ip_address).order_by('id').first()
        if docker_host:
            return docker_host
        docker_host = DockerHost.objects.filter(name=host.hostname).order_by('id').first()
        if docker_host:
            return docker_host
        status_map = {
            'online': 'connected',
            'offline': 'disconnected',
            'warning': 'error',
        }
        return DockerHost.objects.create(
            name=host.hostname,
            ip_address=host.ip_address,
            ssh_port=getattr(host, 'ssh_port', 22) or 22,
            ssh_user=getattr(host, 'ssh_user', 'root') or 'root',
            ssh_password=getattr(host, 'ssh_password', '') or '',
            status=status_map.get(getattr(host, 'status', ''), 'disconnected'),
            description='由应用发布主机目标自动映射',
        )


class ApprovalActionSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class DeploymentActionSerializer(serializers.Serializer):
    change_summary = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class TransactionTicketSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_ticket_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')

    class Meta:
        model = TransactionTicket
        fields = [
            'id',
            'title',
            'ticket_type',
            'type_display',
            'priority',
            'priority_display',
            'business_line',
            'environment',
            'environment_display',
            'approval_flow',
            'approval_flow_name',
            'owner',
            'applicant',
            'window',
            'description',
            'status',
            'status_display',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'applicant',
            'status',
            'created_at',
            'updated_at',
            'type_display',
            'priority_display',
            'status_display',
            'environment_display',
            'approval_flow_name',
        ]

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择业务线'})
        if not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '所选业务线未在资源树中配置'})

        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未在当前业务线下配置'})

        approval_flow = attrs.get('approval_flow') if 'approval_flow' in attrs else getattr(self.instance, 'approval_flow', None)
        if approval_flow and approval_flow.environment and approval_flow.environment != environment:
            raise serializers.ValidationError({'approval_flow': '所选审批流与当前环境不匹配'})

        attrs['business_line'] = business_line
        return attrs


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Alert
        fields = '__all__'


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'


class FireMapSystemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FireMapSystem
        fields = '__all__'
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def _validate_json_list(self, value, field_name):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f'{field_name} 必须是数组')
        return value

    def _validate_json_object(self, value, field_name):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError(f'{field_name} 必须是对象')
        return value

    def validate_name(self, value):
        name = str(value or '').strip()
        if not name:
            raise serializers.ValidationError('请填写业务系统名称')
        return name

    def validate_domain(self, value):
        return str(value or '').strip()

    def validate_tier(self, value):
        return str(value or '').strip()

    def validate_owner(self, value):
        return str(value or '').strip()

    def validate_summary(self, value):
        return str(value or '').strip()

    def validate_keywords(self, value):
        items = self._validate_json_list(value, 'keywords')
        return [str(item).strip() for item in items if str(item).strip()]

    def validate_north_star(self, value):
        item = self._validate_json_object(value, 'north_star')
        label = str(item.get('label') or '').strip()
        if not label:
            label = '可用率'
        return {
            'label': label,
            'value': item.get('value', 99),
            'target': item.get('target', 99.9),
            'unit': str(item.get('unit') or '%').strip(),
            'direction': str(item.get('direction') or 'higher').strip() or 'higher',
        }

    def validate_metrics(self, value):
        return self._validate_json_list(value, 'metrics')

    def validate_service_specs(self, value):
        return self._validate_json_list(value, 'service_specs')

    def validate_dependencies(self, value):
        return self._validate_json_list(value, 'dependencies')

    def validate_rule_config(self, value):
        return self._validate_json_object(value, 'rule_config')

    def validate_playbook(self, value):
        items = self._validate_json_list(value, 'playbook')
        return [str(item).strip() for item in items if str(item).strip()]

    def validate(self, attrs):
        attrs.setdefault('north_star', {
            'label': '可用率',
            'value': 99,
            'target': 99.9,
            'unit': '%',
            'direction': 'higher',
        })
        attrs.setdefault('rule_config', {})
        if attrs.get('health_score') is not None:
            attrs['health_score'] = max(0, min(100, int(attrs['health_score'])))
        return attrs


class LogDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = LogDataSource
        fields = '__all__'

    def validate_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('config 必须是对象')
        return value

    def validate(self, attrs):
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        config = dict(getattr(self.instance, 'config', {}) or {})
        incoming = attrs.get('config', {})

        for key, value in incoming.items():
            if key in LOG_SENSITIVE_KEYS and value in ('', None, 'configured'):
                if self.instance and key in config:
                    continue
                config.pop(key, None)
                continue
            config[key] = value

        attrs['config'] = config
        return attrs

    def _sync_default(self, instance):
        if instance.is_default:
            LogDataSource.objects.filter(provider=instance.provider, is_default=True).exclude(pk=instance.pk).update(
                is_default=False
            )

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._sync_default(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._sync_default(instance)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        masked = {}
        is_demo = bool((instance.config or {}).get('demo_mode'))
        for key, value in (instance.config or {}).items():
            if key in LOG_SENSITIVE_KEYS and not is_demo:
                masked[key] = 'configured' if value else ''
            else:
                masked[key] = value
        data['config'] = masked
        return data


class TracingDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = TracingDataSource
        fields = '__all__'

    def validate_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('config 必须是对象')
        return value

    def validate(self, attrs):
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        config = dict(getattr(self.instance, 'config', {}) or {})
        incoming = attrs.get('config', {})

        for key, value in incoming.items():
            if key in LOG_SENSITIVE_KEYS and value in ('', None, 'configured'):
                if self.instance and key in config:
                    continue
                config.pop(key, None)
                continue
            config[key] = value

        if provider == 'skywalking':
            config.setdefault('graphql_path', '/graphql')
        config['demo_mode'] = False

        attrs['config'] = config
        return attrs

    def _sync_default(self, instance):
        if instance.is_default:
            TracingDataSource.objects.filter(provider=instance.provider, is_default=True).exclude(pk=instance.pk).update(
                is_default=False
            )

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._sync_default(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._sync_default(instance)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        masked = {}
        is_demo = bool((instance.config or {}).get('demo_mode'))
        for key, value in (instance.config or {}).items():
            if key in LOG_SENSITIVE_KEYS and not is_demo:
                masked[key] = 'configured' if value else ''
            else:
                masked[key] = value
        data['config'] = masked
        return data


DEFAULT_TRACE_ID_FIELDS = ['trace_id', 'traceId', 'traceID']
DEFAULT_TRACE_ID_REGEX = r'"trace_id"\s*:\s*"([0-9a-fA-F]{16,32})"'
DEFAULT_LOG_QUERY_TEMPLATE = '${__tags} | json | trace_id="${__trace.traceId}"'
DEFAULT_LOG_LABEL_MAPPINGS = [
    {'trace_tag': 'service.name', 'log_label': 'container'},
    {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
]
DEFAULT_GRAFANA_VARIABLE_MAPPINGS = [
    {'trace_tag': 'service.name', 'variable': 'workload'},
    {'trace_tag': 'service.namespace', 'variable': 'namespace'},
]


class ObservabilityDataSourceLinkSerializer(serializers.ModelSerializer):
    log_datasource_name = serializers.CharField(source='log_datasource.name', read_only=True)
    log_provider = serializers.CharField(source='log_datasource.provider', read_only=True)
    tracing_datasource_name = serializers.CharField(source='tracing_datasource.name', read_only=True)
    tracing_provider = serializers.CharField(source='tracing_datasource.provider', read_only=True)

    class Meta:
        model = ObservabilityDataSourceLink
        fields = '__all__'

    def validate_trace_id_fields(self, value):
        if value in (None, ''):
            return DEFAULT_TRACE_ID_FIELDS
        if not isinstance(value, list):
            raise serializers.ValidationError('trace_id_fields 必须是数组')
        return [str(item).strip() for item in value if str(item).strip()]

    def validate_log_label_mappings(self, value):
        if value in (None, ''):
            return DEFAULT_LOG_LABEL_MAPPINGS
        if not isinstance(value, list):
            raise serializers.ValidationError('log_label_mappings 必须是数组')
        mappings = []
        for item in value:
            if not isinstance(item, dict):
                continue
            trace_tag = str(item.get('trace_tag') or '').strip()
            log_label = str(item.get('log_label') or '').strip()
            if trace_tag and log_label:
                mappings.append({'trace_tag': trace_tag, 'log_label': log_label})
        return mappings

    def validate_grafana_variable_mappings(self, value):
        if value in (None, ''):
            return DEFAULT_GRAFANA_VARIABLE_MAPPINGS
        if not isinstance(value, list):
            raise serializers.ValidationError('grafana_variable_mappings 必须是数组')
        mappings = []
        for item in value:
            if not isinstance(item, dict):
                continue
            trace_tag = str(item.get('trace_tag') or '').strip()
            variable = str(item.get('variable') or '').strip()
            if trace_tag and variable:
                mappings.append({'trace_tag': trace_tag, 'variable': variable})
        return mappings

    def validate(self, attrs):
        log_datasource = attrs.get('log_datasource') or getattr(self.instance, 'log_datasource', None)
        tracing_datasource = attrs.get('tracing_datasource') or getattr(self.instance, 'tracing_datasource', None)
        if log_datasource and log_datasource.provider != 'loki':
            raise serializers.ValidationError({'log_datasource': '当前关联跳转仅支持 Loki 日志数据源'})
        if tracing_datasource and tracing_datasource.provider != 'tempo':
            raise serializers.ValidationError({'tracing_datasource': '当前默认关联模板面向 Tempo 链路数据源'})

        attrs.setdefault('trace_id_fields', DEFAULT_TRACE_ID_FIELDS)
        attrs.setdefault('trace_id_regex', DEFAULT_TRACE_ID_REGEX)
        attrs.setdefault('log_query_template', DEFAULT_LOG_QUERY_TEMPLATE)
        attrs.setdefault('log_label_mappings', DEFAULT_LOG_LABEL_MAPPINGS)
        attrs.setdefault('grafana_variable_mappings', DEFAULT_GRAFANA_VARIABLE_MAPPINGS)
        return attrs

    def _sync_default(self, instance):
        if instance.is_default:
            ObservabilityDataSourceLink.objects.filter(is_default=True).exclude(pk=instance.pk).update(
                is_default=False
            )

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._sync_default(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._sync_default(instance)
        return instance


class GrafanaSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrafanaSetting
        fields = '__all__'
        read_only_fields = ['name', 'updated_by', 'created_at', 'updated_at']

    def validate_dashboards(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('dashboards 必须为数组')
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('dashboards 中的每一项都必须为对象')
            normalized.append(item)
        return normalized

    def validate_folders(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('folders 必须为数组')
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('folders 中的每一项都必须为对象')
            normalized.append(item)
        return normalized


class K8sClusterSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = K8sCluster
        fields = '__all__'
        extra_kwargs = {
            'kubeconfig': {'write_only': True},
        }


class DockerHostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DockerHost
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxEnvironmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NginxEnvironment
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxCertificateSerializer(serializers.ModelSerializer):
    environment_names = serializers.SerializerMethodField()

    class Meta:
        model = NginxCertificate
        fields = '__all__'
        extra_kwargs = {
            'domain': {'read_only': True},
            'expires_at': {'read_only': True},
            'cert_content': {'write_only': True},
            'key_content': {'write_only': True},
        }

    def get_environment_names(self, obj):
        return [{'id': item.id, 'name': item.name} for item in obj.environments.all()]


class NginxDomainSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    ssl_enabled = serializers.BooleanField(read_only=True)
    certificate_domain = serializers.CharField(source='certificate.domain', read_only=True, default=None)

    class Meta:
        model = NginxDomain
        fields = '__all__'


class NginxRouteSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(source='nginx_domain.domain', read_only=True)
    environment_name = serializers.CharField(source='nginx_domain.environment.name', read_only=True)

    class Meta:
        model = NginxRoute
        fields = '__all__'
