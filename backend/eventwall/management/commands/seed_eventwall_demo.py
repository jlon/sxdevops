from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from marketplace.models import ServiceDeployment
from multicloud.models import CloudEnvironment, CloudSyncTask
from ops.models import Deployment, HostTask, HostTaskSchedule
from rbac.models import Role, UserGroup
from sqlaudit.models import SqlOrder

from eventwall.models import EventRecord
from eventwall.services import build_resource, record_event


class Command(BaseCommand):
    help = '生成事件墙演示数据'

    def handle(self, *args, **options):
        EventRecord.objects.all().delete()
        now = timezone.now()
        self.stdout.write('正在生成事件墙演示数据...')

        self.seed_rbac(now)
        self.seed_sqlaudit(now)
        self.seed_deployments(now)
        self.seed_host_tasks(now)
        self.seed_multicloud(now)
        self.seed_marketplace(now)
        self.seed_middleware(now)

        self.stdout.write(self.style.SUCCESS(f'事件墙演示数据生成完成，共 {EventRecord.objects.count()} 条事件。'))

    def seed_rbac(self, now):
        for role in Role.objects.all()[:4]:
            record_event(
                module='rbac',
                category='system',
                action='sync_role',
                title='同步内置角色',
                summary=f'角色 {role.name} 已同步到权限字典',
                source_type=EventRecord.SOURCE_SEED,
                actor_type=EventRecord.ACTOR_SYSTEM,
                actor_username='system',
                actor_display='System',
                resource_type='rbac_role',
                resource_id=role.id,
                resource_name=role.name,
                correlation_id=f'rbac-role:{role.id}',
                is_demo=True,
                occurred_at=now - timedelta(days=7, minutes=role.id),
            )

        for group in UserGroup.objects.all()[:4]:
            record_event(
                module='rbac',
                category='resource_change',
                action='bind_group',
                title='同步演示用户组',
                summary=f'用户组 {group.name} 已绑定内置角色',
                source_type=EventRecord.SOURCE_SEED,
                actor_type=EventRecord.ACTOR_SYSTEM,
                actor_username='system',
                actor_display='System',
                resource_type='rbac_group',
                resource_id=group.id,
                resource_name=group.name,
                correlation_id=f'rbac-group:{group.id}',
                is_demo=True,
                occurred_at=now - timedelta(days=6, minutes=group.id),
            )

    def seed_sqlaudit(self, now):
        for order in SqlOrder.objects.select_related('datasource').all():
            correlation_id = f'sql-order:{order.id}'
            related = [build_resource('sqlaudit', 'sql_datasource', order.datasource_id, order.datasource.name)]
            occurred_at = order.executed_at or order.reviewed_at or order.created_at or now - timedelta(hours=6)

            if order.executed_at:
                record_event(
                    module='sqlaudit',
                    category='execution',
                    action='execute',
                    title='执行 SQL 工单',
                    summary=f'SQL 工单 {order.title} 执行结果: {order.status}',
                    result=EventRecord.RESULT_SUCCESS if order.status == 'executed' else EventRecord.RESULT_FAILED,
                    severity=EventRecord.SEVERITY_WARNING,
                    source_type=EventRecord.SOURCE_SEED,
                    actor_username=order.reviewer or order.submitter,
                    actor_display=order.reviewer or order.submitter,
                    resource_type='sql_order',
                    resource_id=order.id,
                    resource_name=order.title,
                    application=order.database,
                    correlation_id=correlation_id,
                    related_resources=related,
                    metadata={
                        'database': order.database,
                        'sql_type': order.sql_type,
                        'affected_rows': order.affected_rows,
                        'duration_ms': order.duration_ms,
                    },
                    is_demo=True,
                    occurred_at=occurred_at,
                )
            elif order.status == 'rejected':
                record_event(
                    module='sqlaudit',
                    category='workflow',
                    action='reject',
                    title='驳回 SQL 工单',
                    summary=f'SQL 工单 {order.title} 已被驳回',
                    result=EventRecord.RESULT_REJECTED,
                    severity=EventRecord.SEVERITY_WARNING,
                    source_type=EventRecord.SOURCE_SEED,
                    actor_username=order.reviewer or order.submitter,
                    actor_display=order.reviewer or order.submitter,
                    resource_type='sql_order',
                    resource_id=order.id,
                    resource_name=order.title,
                    application=order.database,
                    correlation_id=correlation_id,
                    related_resources=related,
                    metadata={'database': order.database, 'comment': order.review_comment},
                    is_demo=True,
                    occurred_at=occurred_at,
                )

    def seed_deployments(self, now):
        for deployment in Deployment.objects.select_related('cluster', 'docker_host', 'host').all()[:8]:
            correlation_id = f'deployment:{deployment.id}'
            related = []
            if deployment.cluster_id:
                related.append(build_resource('ops', 'k8s_cluster', deployment.cluster_id, deployment.cluster.name))
            if deployment.docker_host_id:
                related.append(build_resource('ops', 'docker_host', deployment.docker_host_id, deployment.docker_host.name))
            if deployment.host_id:
                related.append(build_resource('ops', 'host', deployment.host_id, deployment.host.hostname))

            if deployment.executed_at:
                record_event(
                    module='ops',
                    category='execution',
                    action='deploy_finish',
                    title='执行应用发布',
                    summary=f'发布单 {deployment.app_name} 执行结果: {deployment.status}',
                    result=EventRecord.RESULT_SUCCESS if deployment.status == 'running' else EventRecord.RESULT_FAILED,
                    severity=EventRecord.SEVERITY_WARNING if deployment.status == 'failed' else EventRecord.SEVERITY_INFO,
                    source_type=EventRecord.SOURCE_SEED,
                    actor_username=deployment.deployer or deployment.submitter or 'ops_demo',
                    actor_display=deployment.deployer or deployment.submitter or 'ops_demo',
                    resource_type='deployment',
                    resource_id=deployment.id,
                    resource_name=deployment.app_name,
                    business_line=deployment.business_line,
                    environment=deployment.environment,
                    application=deployment.app_name,
                    correlation_id=correlation_id,
                    related_resources=related + [build_resource('cmdb', 'config_scope', deployment.id, deployment.app_name)],
                    metadata={'status': deployment.status, 'deploy_mode': deployment.deploy_mode},
                    is_demo=True,
                    occurred_at=deployment.executed_at,
                )
            elif deployment.approval_status == 'rejected':
                record_event(
                    module='ops',
                    category='workflow',
                    action='reject',
                    title='驳回发布单',
                    summary=f'发布单 {deployment.app_name} 已被驳回',
                    result=EventRecord.RESULT_REJECTED,
                    severity=EventRecord.SEVERITY_WARNING,
                    source_type=EventRecord.SOURCE_SEED,
                    actor_username=deployment.approver or deployment.submitter or 'ops_demo',
                    actor_display=deployment.approver or deployment.submitter or 'ops_demo',
                    resource_type='deployment',
                    resource_id=deployment.id,
                    resource_name=deployment.app_name,
                    business_line=deployment.business_line,
                    environment=deployment.environment,
                    application=deployment.app_name,
                    correlation_id=correlation_id,
                    related_resources=related,
                    metadata={'comment': deployment.approval_comment},
                    is_demo=True,
                    occurred_at=deployment.approved_at or now - timedelta(days=2),
                )

    def seed_host_tasks(self, now):
        for task in HostTask.objects.all()[:6]:
            record_event(
                module='ops',
                category='execution',
                action='host_task',
                title='执行主机任务',
                summary=f'主机任务 {task.name} 已触发，状态 {task.status}',
                result=EventRecord.RESULT_SUCCESS if task.status in {HostTask.STATUS_SUCCESS, HostTask.STATUS_PARTIAL} else EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING if task.status in {HostTask.STATUS_FAILED, HostTask.STATUS_PARTIAL} else EventRecord.SEVERITY_INFO,
                source_type=EventRecord.SOURCE_SEED,
                actor_username=task.created_by or 'ops_demo',
                actor_display=task.created_by or 'ops_demo',
                resource_type='host_task',
                resource_id=task.id,
                resource_name=task.name,
                correlation_id=f'host-task:{task.id}',
                metadata={'target_count': task.target_count, 'success_count': task.success_count, 'failed_count': task.failed_count},
                is_demo=True,
                occurred_at=task.created_at or now - timedelta(days=1),
            )

        for schedule in HostTaskSchedule.objects.all()[:4]:
            record_event(
                module='ops',
                category='workflow',
                action='schedule_update',
                title='同步定时任务配置',
                summary=f'定时任务 {schedule.name} 已同步，当前状态 {"启用" if schedule.enabled else "停用"}',
                source_type=EventRecord.SOURCE_SEED,
                actor_username=schedule.updated_by or schedule.created_by or 'ops_demo',
                actor_display=schedule.updated_by or schedule.created_by or 'ops_demo',
                resource_type='host_task_schedule',
                resource_id=schedule.id,
                resource_name=schedule.name,
                correlation_id=f'host-task-schedule:{schedule.id}',
                metadata={'enabled': schedule.enabled, 'target_count': schedule.target_count},
                is_demo=True,
                occurred_at=schedule.updated_at or now - timedelta(hours=12),
            )

    def seed_multicloud(self, now):
        for task in CloudSyncTask.objects.select_related('environment', 'credential').all()[:8]:
            related = []
            if task.environment_id:
                related.append(build_resource('multicloud', 'cloud_environment', task.environment_id, task.environment.name))
            if task.credential_id:
                related.append(build_resource('multicloud', 'cloud_credential', task.credential_id, task.credential.name))
            record_event(
                module='multicloud',
                category='sync',
                action=task.task_type,
                title='执行多云同步任务',
                summary=task.summary or task.target_display,
                result=EventRecord.RESULT_SUCCESS if task.status == 'success' else EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING if task.status == 'failed' else EventRecord.SEVERITY_INFO,
                source_type=EventRecord.SOURCE_SEED,
                actor_username=task.operator or 'ops_demo',
                actor_display=task.operator or 'ops_demo',
                resource_type='cloud_sync_task',
                resource_id=task.id,
                resource_name=task.target_display,
                business_line=getattr(task.environment, 'business_line', '') if task.environment_id else '',
                environment=getattr(task.environment, 'environment_type', '') if task.environment_id else '',
                correlation_id=f'cloud-sync:{task.id}',
                related_resources=related,
                metadata={'task_type': task.task_type, 'status': task.status},
                is_demo=True,
                occurred_at=task.created_at or now - timedelta(hours=10),
            )

        for environment in CloudEnvironment.objects.select_related('credential').all()[:4]:
            record_event(
                module='multicloud',
                category='resource_change',
                action='environment_sync',
                title='同步云环境',
                summary=f'云环境 {environment.name} 已与资源台账对齐',
                source_type=EventRecord.SOURCE_SEED,
                actor_username=environment.updated_by or environment.created_by or 'ops_demo',
                actor_display=environment.updated_by or environment.created_by or 'ops_demo',
                resource_type='cloud_environment',
                resource_id=environment.id,
                resource_name=environment.name,
                business_line=environment.business_line,
                environment=environment.environment_type,
                correlation_id=f'cloud-environment:{environment.id}',
                related_resources=[build_resource('multicloud', 'cloud_credential', environment.credential_id, environment.credential.name)],
                is_demo=True,
                occurred_at=environment.updated_at or now - timedelta(hours=8),
            )

    def seed_marketplace(self, now):
        for item in ServiceDeployment.objects.select_related('template', 'host', 'cluster').all()[:6]:
            related = [build_resource('marketplace', 'service_template', item.template_id, item.template.name)]
            if item.host_id:
                related.append(build_resource('ops', 'host', item.host_id, item.host.hostname))
            if item.cluster_id:
                related.append(build_resource('ops', 'k8s_cluster', item.cluster_id, item.cluster.name))
            record_event(
                module='marketplace',
                category='execution',
                action='deploy_finish',
                title='部署工具市场实例',
                summary=f'服务 {item.template.name} 当前状态 {item.status}',
                result=EventRecord.RESULT_SUCCESS if item.status in {'running', 'stopped'} else EventRecord.RESULT_FAILED,
                source_type=EventRecord.SOURCE_SEED,
                actor_username=item.deployer or 'ops_demo',
                actor_display=item.deployer or 'ops_demo',
                resource_type='service_deployment',
                resource_id=item.id,
                resource_name=item.template.name,
                application=item.template.name,
                correlation_id=f'marketplace-deployment:{item.id}',
                related_resources=related,
                metadata={'deploy_mode': item.deploy_mode, 'status': item.status, 'target': item.target_display},
                is_demo=True,
                occurred_at=item.created_at or now - timedelta(days=3),
            )

    def seed_middleware(self, now):
        record_event(
            module='ops',
            category='execution',
            action='middleware_rebalance',
            title='处理中间件运行事件',
            summary='RocketMQ audit-mq 执行了消费者重平衡并恢复积压',
            severity=EventRecord.SEVERITY_WARNING,
            source_type=EventRecord.SOURCE_SEED,
            actor_username='ops_demo',
            actor_display='ops_demo',
            resource_type='middleware_cluster',
            resource_id='audit-mq',
            resource_name='audit-mq',
            application='audit-mq',
            correlation_id='middleware:audit-mq',
            related_resources=[
                build_resource('ops', 'middleware_cluster', 'audit-mq', 'audit-mq'),
                build_resource('ops', 'log_datasource', 'demo-hz-audit', 'demo-hz-audit'),
            ],
            metadata={'module': 'rocketmq'},
            is_demo=True,
            occurred_at=now - timedelta(hours=5, minutes=20),
        )
