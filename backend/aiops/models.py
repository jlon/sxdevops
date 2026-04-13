import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


User = get_user_model()


def _build_fernet():
    seed = f"{settings.SECRET_KEY}:aiops:model-provider".encode('utf-8')
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


class AIOpsModelProvider(models.Model):
    PROVIDER_OPENAI_COMPATIBLE = 'openai_compatible'
    PROVIDER_CHOICES = [
        (PROVIDER_OPENAI_COMPATIBLE, 'OpenAI Compatible'),
    ]

    STATUS_UNKNOWN = 'unknown'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_UNKNOWN, '未知'),
        (STATUS_SUCCESS, '成功'),
        (STATUS_FAILED, '失败'),
    ]

    name = models.CharField('提供商名称', max_length=128, unique=True)
    provider_type = models.CharField('提供商类型', max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_OPENAI_COMPATIBLE)
    base_url = models.CharField('Base URL', max_length=255, blank=True, default='')
    api_key_encrypted = models.TextField('API Key 密文', blank=True, default='')
    default_model = models.CharField('默认模型', max_length=128, blank=True, default='')
    backup_model = models.CharField('备用模型', max_length=128, blank=True, default='')
    temperature = models.FloatField('温度', default=0.2)
    max_tokens = models.PositiveIntegerField('最大 Tokens', default=1200)
    timeout_seconds = models.PositiveIntegerField('超时(秒)', default=30)
    is_enabled = models.BooleanField('启用', default=True)
    last_test_status = models.CharField('最近测试状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_UNKNOWN)
    last_test_message = models.CharField('最近测试信息', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'AIOps 模型提供商'
        verbose_name_plural = 'AIOps 模型提供商'

    def __str__(self):
        return self.name

    @property
    def has_api_key(self):
        return bool(self.api_key_encrypted)

    def set_api_key(self, value):
        value = (value or '').strip()
        if not value:
            self.api_key_encrypted = ''
            return
        self.api_key_encrypted = _build_fernet().encrypt(value.encode('utf-8')).decode('utf-8')

    def get_api_key(self):
        if not self.api_key_encrypted:
            return ''
        try:
            return _build_fernet().decrypt(self.api_key_encrypted.encode('utf-8')).decode('utf-8')
        except (InvalidToken, TypeError, ValueError):
            return ''


class AIOpsAgentConfig(models.Model):
    name = models.CharField('配置名称', max_length=64, default='default', unique=True)
    default_provider = models.ForeignKey(
        AIOpsModelProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_configs',
        verbose_name='默认模型提供商',
    )
    system_prompt = models.TextField('系统提示词', blank=True, default='')
    welcome_message = models.CharField('欢迎语', max_length=255, blank=True, default='你好，我可以帮你结合平台上下文查询资源、分析告警、成本分析、生成待执行任务等。')
    suggested_questions = models.JSONField('建议问题', default=list, blank=True)
    is_enabled = models.BooleanField('启用机器人', default=True)
    allow_action_execution = models.BooleanField('允许执行动作', default=True)
    require_confirmation = models.BooleanField('执行前确认', default=True)
    show_evidence = models.BooleanField('展示证据来源', default=True)
    allow_analysis = models.BooleanField('允许关联分析', default=True)
    enabled_mcp_server_ids = models.JSONField('启用的 MCP', default=list, blank=True)
    enabled_skill_ids = models.JSONField('启用的 Skill', default=list, blank=True)
    max_history_messages = models.PositiveIntegerField('最大历史消息数', default=12)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'AIOps 机器人配置'
        verbose_name_plural = 'AIOps 机器人配置'

    def __str__(self):
        return self.name


class AIOpsMCPServer(models.Model):
    SERVER_HTTP = 'http'
    SERVER_STDIO = 'stdio'
    SERVER_PLATFORM_BUILTIN = 'platform_builtin'
    SERVER_TYPE_CHOICES = [
        (SERVER_HTTP, 'HTTP'),
        (SERVER_STDIO, 'STDIO'),
        (SERVER_PLATFORM_BUILTIN, '平台内置'),
    ]

    name = models.CharField('名称', max_length=128, unique=True)
    server_type = models.CharField('类型', max_length=16, choices=SERVER_TYPE_CHOICES, default=SERVER_HTTP)
    endpoint_or_command = models.CharField('地址或命令', max_length=255, blank=True, default='')
    description = models.CharField('描述', max_length=255, blank=True, default='')
    auth_config = models.JSONField('鉴权配置', default=dict, blank=True)
    tool_whitelist = models.JSONField('启用工具', default=list, blank=True)
    is_builtin = models.BooleanField('内置', default=False)
    is_enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'AIOps MCP 服务'
        verbose_name_plural = 'AIOps MCP 服务'

    def __str__(self):
        return self.name


class AIOpsSkill(models.Model):
    SOURCE_INLINE = 'inline'
    SOURCE_LOCAL = 'local'
    SOURCE_CHOICES = [
        (SOURCE_INLINE, '平台内置'),
        (SOURCE_LOCAL, '本地文件'),
    ]

    name = models.CharField('名称', max_length=128, unique=True)
    slug = models.SlugField('标识', max_length=128, unique=True)
    description = models.CharField('描述', max_length=255, blank=True, default='')
    source_type = models.CharField('来源类型', max_length=16, choices=SOURCE_CHOICES, default=SOURCE_INLINE)
    content = models.TextField('内容', blank=True, default='')
    allowed_role_codes = models.JSONField('允许角色', default=list, blank=True)
    is_builtin = models.BooleanField('内置', default=False)
    is_enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'AIOps Skill'
        verbose_name_plural = 'AIOps Skill'

    def __str__(self):
        return self.name


class AIOpsChatSession(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '进行中'),
        (STATUS_ARCHIVED, '已归档'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='aiops_sessions', verbose_name='用户')
    mirror_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mirrored_sessions',
        verbose_name='?????',
    )
    title = models.CharField('标题', max_length=128, default='新会话')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    last_message_at = models.DateTimeField('最后消息时间', default=timezone.now)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-last_message_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'mirror_source'], name='aiops_session_user_mirror_source_uniq'),
        ]
        verbose_name = 'AIOps 会话'
        verbose_name_plural = 'AIOps 会话'

    def __str__(self):
        return f'{self.user.username} / {self.title}'


class AIOpsChatMessage(models.Model):
    ROLE_SYSTEM = 'system'
    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_CHOICES = [
        (ROLE_SYSTEM, '系统'),
        (ROLE_USER, '用户'),
        (ROLE_ASSISTANT, '助手'),
    ]

    TYPE_TEXT = 'text'
    TYPE_ANALYSIS = 'analysis'
    TYPE_ACTION = 'action'
    TYPE_ERROR = 'error'
    TYPE_CHOICES = [
        (TYPE_TEXT, '文本'),
        (TYPE_ANALYSIS, '分析'),
        (TYPE_ACTION, '动作'),
        (TYPE_ERROR, '错误'),
    ]

    session = models.ForeignKey(AIOpsChatSession, on_delete=models.CASCADE, related_name='messages', verbose_name='会话')
    mirror_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mirrored_messages',
        verbose_name='?????',
    )
    role = models.CharField('角色', max_length=16, choices=ROLE_CHOICES)
    message_type = models.CharField('消息类型', max_length=16, choices=TYPE_CHOICES, default=TYPE_TEXT)
    content = models.TextField('内容')
    citations = models.JSONField('引用', default=list, blank=True)
    tool_calls = models.JSONField('工具调用', default=list, blank=True)
    metadata = models.JSONField('元数据', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['session', 'mirror_source'], name='aiops_message_session_mirror_source_uniq'),
        ]
        verbose_name = 'AIOps 消息'
        verbose_name_plural = 'AIOps 消息'

    def __str__(self):
        return f'{self.session_id} / {self.role}'


class AIOpsPendingAction(models.Model):
    ACTION_EXECUTE_HOST_TASK = 'execute_host_task'
    ACTION_CHOICES = [
        (ACTION_EXECUTE_HOST_TASK, '执行主机任务'),
    ]

    RISK_LOW = 'low'
    RISK_MEDIUM = 'medium'
    RISK_HIGH = 'high'
    RISK_CRITICAL = 'critical'
    RISK_CHOICES = [
        (RISK_LOW, '低'),
        (RISK_MEDIUM, '中'),
        (RISK_HIGH, '高'),
        (RISK_CRITICAL, '极高'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELED = 'canceled'
    STATUS_EXECUTED = 'executed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待确认'),
        (STATUS_CONFIRMED, '已确认'),
        (STATUS_CANCELED, '已取消'),
        (STATUS_EXECUTED, '已执行'),
        (STATUS_FAILED, '执行失败'),
    ]

    session = models.ForeignKey(AIOpsChatSession, on_delete=models.CASCADE, related_name='pending_actions', verbose_name='会话')
    mirror_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mirrored_actions',
        verbose_name='?????',
    )
    message = models.ForeignKey(
        AIOpsChatMessage,
        on_delete=models.CASCADE,
        related_name='pending_actions',
        verbose_name='消息',
        null=True,
        blank=True,
    )
    action_type = models.CharField('动作类型', max_length=32, choices=ACTION_CHOICES)
    title = models.CharField('动作标题', max_length=128, default='')
    risk_level = models.CharField('风险等级', max_length=16, choices=RISK_CHOICES, default=RISK_LOW)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    action_payload = models.JSONField('动作参数', default=dict, blank=True)
    result_payload = models.JSONField('执行结果', default=dict, blank=True)
    confirmed_by = models.CharField('确认人', max_length=64, blank=True, default='')
    confirmed_at = models.DateTimeField('确认时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['session', 'mirror_source'], name='aiops_action_session_mirror_source_uniq'),
        ]
        verbose_name = 'AIOps 待确认动作'
        verbose_name_plural = 'AIOps 待确认动作'

    def __str__(self):
        return f'{self.session_id} / {self.action_type}'


class AIOpsToolInvocation(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待处理'),
        (STATUS_SUCCESS, '成功'),
        (STATUS_FAILED, '失败'),
    ]

    session = models.ForeignKey(AIOpsChatSession, on_delete=models.CASCADE, related_name='tool_invocations', verbose_name='会话')
    message = models.ForeignKey(
        AIOpsChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tool_invocations',
        verbose_name='消息',
    )
    tool_name = models.CharField('工具名称', max_length=64)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    latency_ms = models.PositiveIntegerField('耗时', default=0)
    request_payload = models.JSONField('请求参数', default=dict, blank=True)
    response_summary = models.JSONField('响应摘要', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'AIOps 工具调用'
        verbose_name_plural = 'AIOps 工具调用'

    def __str__(self):
        return f'{self.tool_name} / {self.status}'
