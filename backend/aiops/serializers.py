from rest_framework import serializers

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsSkill,
    AIOpsToolInvocation,
)
from .services import get_model_provider_setup_hint


class AIOpsModelProviderSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_api_key = serializers.BooleanField(read_only=True)
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = [
            'id', 'name', 'provider_type', 'base_url', 'api_key', 'has_api_key', 'default_model', 'backup_model',
            'temperature', 'max_tokens', 'timeout_seconds', 'is_enabled', 'runtime_ready', 'setup_hint',
            'last_test_status', 'last_test_message',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['runtime_ready', 'setup_hint', 'last_test_status', 'last_test_message', 'created_at', 'updated_at', 'has_api_key']

    def create(self, validated_data):
        api_key = validated_data.pop('api_key', '')
        instance = super().create(validated_data)
        if api_key:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop('api_key', None)
        instance = super().update(instance, validated_data)
        if api_key is not None:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsModelProviderLiteSerializer(serializers.ModelSerializer):
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = ['id', 'name', 'provider_type', 'default_model', 'is_enabled', 'runtime_ready', 'setup_hint']

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsAgentConfigSerializer(serializers.ModelSerializer):
    default_provider_id = serializers.PrimaryKeyRelatedField(
        queryset=AIOpsModelProvider.objects.all(),
        source='default_provider',
        write_only=True,
        allow_null=True,
        required=False,
    )
    default_provider = AIOpsModelProviderLiteSerializer(read_only=True)

    class Meta:
        model = AIOpsAgentConfig
        fields = [
            'id', 'name', 'default_provider', 'default_provider_id', 'system_prompt', 'welcome_message',
            'suggested_questions', 'is_enabled', 'allow_action_execution', 'require_confirmation', 'show_evidence',
            'allow_analysis', 'enabled_mcp_server_ids', 'enabled_skill_ids', 'max_history_messages',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class AIOpsMCPServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsMCPServer
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('name', None)
            validated_data.pop('server_type', None)
        return super().update(instance, validated_data)


class AIOpsSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsSkill
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('slug', None)
            validated_data.pop('source_type', None)
        return super().update(instance, validated_data)


class AIOpsPendingActionSerializer(serializers.ModelSerializer):
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsPendingAction
        fields = [
            'id', 'action_type', 'title', 'risk_level', 'risk_level_display', 'status', 'status_display',
            'action_payload', 'result_payload', 'confirmed_by', 'confirmed_at', 'created_at', 'updated_at',
        ]


class AIOpsChatMessageSerializer(serializers.ModelSerializer):
    pending_action = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatMessage
        fields = ['id', 'role', 'message_type', 'content', 'citations', 'tool_calls', 'metadata', 'pending_action', 'created_at']

    def get_pending_action(self, obj):
        action = obj.pending_actions.order_by('-id').first()
        return AIOpsPendingActionSerializer(action).data if action else None


class AIOpsChatSessionSerializer(serializers.ModelSerializer):
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatSession
        fields = ['id', 'title', 'status', 'last_message_at', 'created_at', 'updated_at', 'latest_message']

    def get_latest_message(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        if not message:
            return None
        return {
            'role': message.role,
            'content': message.content[:120],
            'created_at': message.created_at,
        }


class AIOpsAuditSessionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AIOpsChatSession
        fields = ['id', 'title', 'status', 'username', 'message_count', 'last_message_at', 'created_at', 'updated_at']


class AIOpsChatInputSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000)


class AIOpsCreateSessionSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')


class AIOpsToolInvocationSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(source='session.title', read_only=True)
    username = serializers.CharField(source='session.user.username', read_only=True)

    class Meta:
        model = AIOpsToolInvocation
        fields = [
            'id', 'session', 'session_title', 'username', 'message', 'tool_name', 'status', 'latency_ms',
            'request_payload', 'response_summary', 'created_at',
        ]
