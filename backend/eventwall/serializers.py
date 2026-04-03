from rest_framework import serializers

from .models import EventRecord


class EventRecordSerializer(serializers.ModelSerializer):
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    resource_key = serializers.SerializerMethodField()
    related_count = serializers.SerializerMethodField()

    class Meta:
        model = EventRecord
        fields = [
            'id',
            'occurred_at',
            'module',
            'category',
            'action',
            'result',
            'result_display',
            'severity',
            'severity_display',
            'title',
            'summary',
            'detail',
            'actor_type',
            'actor_username',
            'actor_display',
            'source_type',
            'source_type_display',
            'request_method',
            'source_path',
            'ip_address',
            'correlation_id',
            'parent_event',
            'resource_module',
            'resource_type',
            'resource_id',
            'resource_name',
            'resource_key',
            'business_line',
            'environment',
            'application',
            'tags',
            'related_resources',
            'related_count',
            'changes',
            'metadata',
            'is_demo',
        ]

    def get_resource_key(self, obj):
        if obj.resource_type and obj.resource_id:
            return f'{obj.resource_type}:{obj.resource_id}'
        return ''

    def get_related_count(self, obj):
        return len(obj.related_resources or [])
