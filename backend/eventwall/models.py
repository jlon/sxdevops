from django.db import models
from django.utils import timezone


class EventRecord(models.Model):
    RESULT_SUCCESS = 'success'
    RESULT_FAILED = 'failed'
    RESULT_PARTIAL = 'partial'
    RESULT_PENDING = 'pending'
    RESULT_REJECTED = 'rejected'

    RESULT_CHOICES = [
        (RESULT_SUCCESS, '成功'),
        (RESULT_FAILED, '失败'),
        (RESULT_PARTIAL, '部分成功'),
        (RESULT_PENDING, '待处理'),
        (RESULT_REJECTED, '已拒绝'),
    ]

    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_DANGER = 'danger'

    SEVERITY_CHOICES = [
        (SEVERITY_INFO, '信息'),
        (SEVERITY_WARNING, '提示'),
        (SEVERITY_DANGER, '高风险'),
    ]

    SOURCE_HTTP = 'http'
    SOURCE_ASYNC = 'async'
    SOURCE_SCHEDULER = 'scheduler'
    SOURCE_SYSTEM = 'system'
    SOURCE_SEED = 'seed'
    SOURCE_WEBSOCKET = 'websocket'

    SOURCE_CHOICES = [
        (SOURCE_HTTP, 'HTTP'),
        (SOURCE_ASYNC, '异步任务'),
        (SOURCE_SCHEDULER, '调度器'),
        (SOURCE_SYSTEM, '系统'),
        (SOURCE_SEED, '演示数据'),
        (SOURCE_WEBSOCKET, 'WebSocket'),
    ]

    ACTOR_USER = 'user'
    ACTOR_SYSTEM = 'system'

    ACTOR_TYPE_CHOICES = [
        (ACTOR_USER, '用户'),
        (ACTOR_SYSTEM, '系统'),
    ]

    occurred_at = models.DateTimeField('发生时间', default=timezone.now, db_index=True)
    module = models.CharField('模块', max_length=32, db_index=True)
    category = models.CharField('分类', max_length=32, db_index=True)
    action = models.CharField('动作', max_length=32, db_index=True)
    result = models.CharField('结果', max_length=16, choices=RESULT_CHOICES, default=RESULT_SUCCESS, db_index=True)
    severity = models.CharField('风险级别', max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    title = models.CharField('事件标题', max_length=255)
    summary = models.CharField('事件摘要', max_length=255, blank=True, default='')
    detail = models.TextField('详情', blank=True, default='')
    actor_type = models.CharField('操作者类型', max_length=16, choices=ACTOR_TYPE_CHOICES, default=ACTOR_USER)
    actor_username = models.CharField('操作者', max_length=64, blank=True, default='', db_index=True)
    actor_display = models.CharField('操作者展示名', max_length=128, blank=True, default='')
    source_type = models.CharField('来源类型', max_length=16, choices=SOURCE_CHOICES, default=SOURCE_HTTP)
    request_method = models.CharField('请求方法', max_length=12, blank=True, default='')
    source_path = models.CharField('来源路径', max_length=255, blank=True, default='')
    ip_address = models.CharField('IP 地址', max_length=64, blank=True, default='')
    correlation_id = models.CharField('关联链路', max_length=128, blank=True, default='', db_index=True)
    parent_event = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='children',
        on_delete=models.SET_NULL,
        verbose_name='父事件',
    )
    resource_module = models.CharField('资源模块', max_length=32, blank=True, default='')
    resource_type = models.CharField('资源类型', max_length=64, blank=True, default='', db_index=True)
    resource_id = models.CharField('资源 ID', max_length=64, blank=True, default='', db_index=True)
    resource_name = models.CharField('资源名称', max_length=255, blank=True, default='', db_index=True)
    business_line = models.CharField('业务线', max_length=64, blank=True, default='')
    environment = models.CharField('环境', max_length=32, blank=True, default='')
    tags = models.JSONField('标签', default=list, blank=True)
    related_resources = models.JSONField('关联资源', default=list, blank=True)
    changes = models.JSONField('变更内容', default=dict, blank=True)
    metadata = models.JSONField('元数据', default=dict, blank=True)
    is_demo = models.BooleanField('演示数据', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    application = models.CharField('Application', max_length=128, blank=True, default='', db_index=True)

    class Meta:
        verbose_name = '事件记录'
        verbose_name_plural = '事件记录'
        ordering = ['-occurred_at', '-id']
        indexes = [
            models.Index(fields=['module', 'occurred_at']),
            models.Index(fields=['module', 'result', 'occurred_at']),
            models.Index(fields=['resource_type', 'resource_id', 'occurred_at']),
            models.Index(fields=['actor_username', 'occurred_at']),
        ]

    def __str__(self):
        return f'[{self.module}] {self.title}'
