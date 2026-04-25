from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from cmdb.models import CIType, ConfigItem
from ops.models import Alert, Deployment, Host, HostTask, K8sCluster, TracingDataSource, TransactionTicket
from rbac.models import Role
from rbac.services import ensure_builtin_rbac

from .models import AIOpsChatMessage, AIOpsChatSession, AIOpsMCPServer, AIOpsModelProvider
from .services import (
    DEFAULT_WELCOME_MESSAGE,
    _ensure_followup_line,
    _formatter_repair_issue,
    _is_formatted_answer_valid,
    _normalize_formatter_output,
    _request_model_completion,
    recover_masked_suggested_question,
    _should_materialize_host_task,
    build_task_draft,
    confirm_action,
    create_pending_task_action_from_draft,
    get_active_provider,
    get_agent_config,
    list_model_provider_models,
    build_markdown_answer,
    query_alerts,
    query_cost_report,
    query_cmdb_items,
    query_hosts,
    query_k8s_cluster_summary,
    query_recent_changes,
    query_traces,
    query_workorders,
)


User = get_user_model()


class AIOpsApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='aiops_user', password='Passw0rd!123')
        platform_admin = Role.objects.get(code='platform-admin')
        self.user.rbac_roles.add(platform_admin)
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        Host.objects.create(hostname='prod-web-01', ip_address='10.0.0.10', environment='prod', status='online')

    def test_bootstrap_returns_runtime(self):
        response = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertTrue(response.data['active_mcp_servers'])
        self.assertTrue(response.data['active_skills'])
        active_mcp_names = {item['name'] for item in response.data['active_mcp_servers']}
        active_skill_names = {item['name'] for item in response.data['active_skills']}
        self.assertTrue({
            'CMDB MCP',
            '可观测性 MCP',
            '工单系统 MCP',
            '任务中心 MCP',
            '事件墙 MCP',
            '容器管理 MCP',
            '中间件 MCP',
            'SkyWalking MCP',
            'Grafana MCP',
        }.issubset(active_mcp_names))
        self.assertTrue(any(item['name'] == 'N9E 监控 MCP' for item in response.data['active_mcp_servers']))
        self.assertIn('回答整形器', active_skill_names)

    def test_get_agent_config_creates_n9e_mcp_preset(self):
        get_agent_config()
        server = AIOpsMCPServer.objects.get(name='N9E 监控 MCP')
        self.assertEqual(server.server_type, AIOpsMCPServer.SERVER_STDIO)
        self.assertIn('@n9e/n9e-mcp-server', server.endpoint_or_command)
        self.assertTrue(server.is_builtin)

    def test_get_agent_config_creates_default_experience_provider(self):
        config = get_agent_config()
        provider = AIOpsModelProvider.objects.get(name='智能助手体验版')
        self.assertEqual(provider.provider_type, AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE)
        self.assertEqual(provider.default_model, 'gpt-4o-mini')
        self.assertFalse(provider.has_api_key)
        self.assertEqual(provider.last_test_message, '预置体验配置，需替换为真实 API Key 后使用')
        self.assertEqual(config.default_provider_id, provider.id)

    def test_active_provider_skips_unconfigured_experience_provider(self):
        config = get_agent_config()
        real_provider = AIOpsModelProvider.objects.create(
            name='real-runtime-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://real.example.com/v1',
            default_model='real-model',
            is_enabled=True,
        )
        real_provider.set_api_key('real-key')
        real_provider.save(update_fields=['api_key_encrypted'])

        self.assertEqual(config.default_provider.name, '智能助手体验版')
        self.assertEqual(get_active_provider(config).id, real_provider.id)

    def test_get_agent_config_clears_placeholder_experience_api_key(self):
        get_agent_config()
        provider = AIOpsModelProvider.objects.get(name='智能助手体验版')
        provider.set_api_key('demo-openai-compatible-key')
        provider.last_test_status = AIOpsModelProvider.STATUS_SUCCESS
        provider.save(update_fields=['api_key_encrypted', 'last_test_status'])

        get_agent_config()
        provider.refresh_from_db()

        self.assertFalse(provider.has_api_key)
        self.assertEqual(provider.last_test_status, AIOpsModelProvider.STATUS_UNKNOWN)

    def test_get_agent_config_keeps_existing_default_provider(self):
        custom_provider = AIOpsModelProvider.objects.create(
            name='custom-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://real.example.com/v1',
            default_model='real-model',
            is_enabled=True,
        )
        custom_provider.set_api_key('real-key')
        custom_provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = custom_provider
        config.save(update_fields=['default_provider'])

        refreshed = get_agent_config()
        self.assertEqual(refreshed.default_provider_id, custom_provider.id)

    def test_get_agent_config_repairs_mojibake_welcome_message(self):
        config = get_agent_config()
        config.welcome_message = DEFAULT_WELCOME_MESSAGE.encode('utf-8').decode('latin1')
        config.save(update_fields=['welcome_message'])

        repaired = get_agent_config()

        self.assertEqual(repaired.welcome_message, DEFAULT_WELCOME_MESSAGE)

    def test_get_agent_config_keeps_user_edited_experience_provider(self):
        config = get_agent_config()
        provider = AIOpsModelProvider.objects.get(name='智能助手体验版')
        provider.base_url = 'https://custom-openai.example.com/v1'
        provider.default_model = 'custom-model'
        provider.save(update_fields=['base_url', 'default_model'])

        get_agent_config()
        provider.refresh_from_db()
        self.assertEqual(provider.base_url, 'https://custom-openai.example.com/v1')
        self.assertEqual(provider.default_model, 'custom-model')

    def test_mcp_and_skill_list_endpoints_bootstrap_builtin_assets(self):
        mcp_response = self.client.get('/api/aiops/admin/mcp-servers/')
        skill_response = self.client.get('/api/aiops/admin/skills/')
        self.assertEqual(mcp_response.status_code, 200)
        self.assertEqual(skill_response.status_code, 200)
        self.assertTrue(any(item['name'] == 'CMDB MCP' and item['server_type'] == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'N9E 监控 MCP' for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'SkyWalking MCP' and item['server_type'] == AIOpsMCPServer.SERVER_STDIO for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'Grafana MCP' and item['server_type'] == AIOpsMCPServer.SERVER_HTTP for item in mcp_response.data))
        self.assertTrue(any(item['slug'] == 'evidence-first-responder' for item in skill_response.data))
        self.assertTrue(any(item['slug'] == 'answer-formatter' for item in skill_response.data))

    @mock.patch('aiops.views.test_model_provider_connection')
    def test_provider_test_connection_endpoint_uses_real_check(self, mocked_test_connection):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-check',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        mocked_test_connection.return_value = {'status': 'success', 'message': '模型连接成功（实际调用模型：gpt-5.2-low）'}

        response = self.client.post(f'/api/aiops/admin/providers/{provider.id}/test_connection/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('gpt-5.2-low', response.data['message'])

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_falls_back_to_low_variant(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-fallback',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        empty_response = mock.Mock()
        empty_response.status_code = 200
        empty_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': None}}],
        }
        low_response = mock.Mock()
        low_response.status_code = 200
        low_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': '连接成功'}}],
        }
        mocked_post.side_effect = [empty_response, low_response]

        result = _request_model_completion(provider, {
            'model': 'gpt-5.2',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 16,
        })
        self.assertEqual(result['choices'][0]['message']['content'], '连接成功')
        self.assertEqual(result['_meta']['resolved_model'], 'gpt-5.2-low')

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_falls_back_to_cc_alias(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-cc-fallback',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2-low',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        empty_response = mock.Mock()
        empty_response.status_code = 200
        empty_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': None}}],
        }
        cc_response = mock.Mock()
        cc_response.status_code = 200
        cc_response.json.return_value = {
            'model': 'gpt-5.2',
            'choices': [{'message': {'role': 'assistant', 'content': '连接成功'}}],
        }
        mocked_post.side_effect = [empty_response, cc_response]

        result = _request_model_completion(provider, {
            'model': 'gpt-5.2-low',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 16,
        })

        self.assertEqual(result['choices'][0]['message']['content'], '连接成功')
        self.assertEqual(result['_meta']['resolved_model'], 'cc-gpt-5.2')

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_uses_developer_role_for_cc_models(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-developer-role',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='cc-gpt-5.3-codex',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': '连接成功'}}],
        }
        mocked_post.return_value = response

        result = _request_model_completion(provider, {
            'model': 'cc-gpt-5.3-codex',
            'messages': [
                {'role': 'system', 'content': 'system prompt'},
                {'role': 'user', 'content': 'ping'},
            ],
            'max_tokens': 16,
        })

        sent_messages = mocked_post.call_args.kwargs['json']['messages']
        self.assertEqual(sent_messages[0]['role'], 'developer')
        self.assertEqual(result['choices'][0]['message']['content'], '连接成功')

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_retries_system_role_as_developer(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-system-retry',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        failed_response = mock.Mock()
        failed_response.status_code = 400
        failed_response.json.return_value = {
            'error': {'message': 'openai_error', 'type': 'bad_response_status_code', 'code': 'bad_response_status_code'},
        }
        success_response = mock.Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': '连接成功'}}],
        }
        mocked_post.side_effect = [failed_response, success_response]

        result = _request_model_completion(provider, {
            'model': 'mock-model',
            'messages': [
                {'role': 'system', 'content': 'system prompt'},
                {'role': 'user', 'content': 'ping'},
            ],
            'max_tokens': 16,
        })

        self.assertEqual(mocked_post.call_count, 2)
        self.assertEqual(mocked_post.call_args.kwargs['json']['messages'][0]['role'], 'developer')
        self.assertEqual(result['choices'][0]['message']['content'], '连接成功')

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_converts_tool_role_for_cc_models(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-tool-role',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='cc-gpt-5.3-codex',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': '已根据工具结果回答'}}],
        }
        mocked_post.return_value = response

        result = _request_model_completion(provider, {
            'model': 'cc-gpt-5.3-codex',
            'messages': [
                {'role': 'system', 'content': 'system prompt'},
                {'role': 'user', 'content': 'ping'},
                {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_ping',
                        'type': 'function',
                        'function': {'name': 'ping_tool', 'arguments': '{}'},
                    }],
                },
                {'role': 'tool', 'tool_call_id': 'call_ping', 'content': '{"ok": true}'},
            ],
            'max_tokens': 16,
        })

        sent_messages = mocked_post.call_args.kwargs['json']['messages']
        self.assertEqual(sent_messages[0]['role'], 'developer')
        self.assertNotIn('tool', {item.get('role') for item in sent_messages})
        self.assertTrue(any('工具调用结果' in item.get('content', '') for item in sent_messages))
        self.assertFalse(any(item.get('tool_calls') for item in sent_messages))
        self.assertEqual(result['choices'][0]['message']['content'], '已根据工具结果回答')

    @mock.patch('aiops.services.requests.post')
    @mock.patch('aiops.services.requests.get')
    def test_list_model_provider_models_recommends_tool_calling_model(self, mocked_get, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-models',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2-low',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        models_response = mock.Mock()
        models_response.status_code = 200
        models_response.json.return_value = {
            'data': [
                {'id': 'gpt-5.2-low', 'owned_by': 'custom'},
                {'id': 'cc-gpt-5.2', 'owned_by': 'custom'},
            ],
        }
        mocked_get.return_value = models_response

        text_response = mock.Mock()
        text_response.status_code = 200
        text_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': 'ping'}}],
        }
        tool_response = mock.Mock()
        tool_response.status_code = 200
        tool_response.json.return_value = {
            'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_ping',
                        'type': 'function',
                        'function': {'name': 'ping_tool', 'arguments': '{}'},
                    }],
                },
            }],
        }
        mocked_post.side_effect = [text_response, tool_response]

        result = list_model_provider_models(provider)

        self.assertEqual(result['count'], 2)
        self.assertEqual(result['recommendation']['model'], 'gpt-5.2-low')
        self.assertTrue(result['recommendation']['supports_tool_calling'])

    @mock.patch('aiops.views.list_model_provider_models')
    def test_provider_models_endpoint_lists_available_models(self, mocked_list_models):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-models-endpoint',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        mocked_list_models.return_value = {
            'models': [{'id': 'mock-model'}],
            'count': 1,
            'recommendation': {'model': 'mock-model', 'verified': True},
        }

        response = self.client.get(f'/api/aiops/admin/providers/{provider.id}/models/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['recommendation']['model'], 'mock-model')

    def test_query_recent_changes_does_not_use_missing_updated_at_field(self):
        session = AIOpsChatSession.objects.create(user=self.user, title='changes-check')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='最近发版')
        result = query_recent_changes(session, user_message, self.user, limit=5)
        self.assertNotIn('error', result)
        self.assertIn('sections', result)

    def test_query_alerts_handles_generic_chinese_alert_question(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='Disk usage warning',
            level='warning',
            source='monitor',
            message='disk > 80%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-check')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        result = query_alerts(session, user_message, self.user, query='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f', level='critical', only_unacknowledged=True)
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertEqual(result['alerts'][0].level, 'critical')

    def test_query_alerts_infers_filters_from_natural_language_query(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='Disk usage warning',
            level='warning',
            source='monitor',
            message='disk > 80%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-infer')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        result = query_alerts(session, user_message, self.user, query='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertEqual(result['alerts'][0].level, 'critical')

    def test_query_alerts_infers_filters_from_model_style_expression(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='CPU usage high acknowledged',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=True,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-expression')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='type:alert severity:critical acknowledged:false status:active')
        result = query_alerts(session, user_message, self.user, query='type:alert severity:critical acknowledged:false status:active')
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertFalse(result['alerts'][0].is_acknowledged)

    def test_query_alerts_handles_order_center_incident_query(self):
        prod_host = Host.objects.create(hostname='commerce-prod-hz-app-01', ip_address='10.20.1.10', environment='prod', status='online')
        Alert.objects.create(
            title='order-center 下游依赖重试激增',
            level='critical',
            source='APM',
            message='inventory-service retry rate exceeded threshold in prod',
            is_acknowledged=False,
            host=prod_host,
        )
        Alert.objects.create(
            title='order-center 库存校验超时',
            level='critical',
            source='APM',
            message='order-service inventory timeout in prod',
            is_acknowledged=False,
        )
        Alert.objects.create(
            title='feature-x 发布后健康检查失败',
            level='critical',
            source='APM',
            message='post-release health check failed in dev',
            is_acknowledged=False,
            host=Host.objects.create(hostname='feature-x-dev-01', ip_address='10.20.9.10', environment='dev', status='online'),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='order-center-alerts')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='分析生产 order-center 最近异常')

        result = query_alerts(session, user_message, self.user, query='分析生产 order-center 最近异常')

        self.assertEqual(result['summary']['count'], 2)
        self.assertTrue(any('order-center 下游依赖重试激增' in item for item in result['sections'][0]['items']))
        self.assertTrue(any('order-center 库存校验超时' in item for item in result['sections'][0]['items']))

    def test_query_workorders_filters_by_business_line_and_environment(self):
        TransactionTicket.objects.create(
            title='生产数据库白名单开通',
            ticket_type=TransactionTicket.TYPE_ACCESS,
            business_line='电商线',
            environment='prod',
            applicant='ops-demo',
            status=TransactionTicket.STATUS_PENDING,
        )
        TransactionTicket.objects.create(
            title='网关限流策略紧急调整',
            ticket_type=TransactionTicket.TYPE_INCIDENT,
            business_line='电商线',
            environment='prod',
            applicant='ops-demo',
            status=TransactionTicket.STATUS_PROCESSING,
        )
        TransactionTicket.objects.create(
            title='夜间链路巡检任务',
            ticket_type=TransactionTicket.TYPE_INSPECTION,
            business_line='数据平台',
            environment='test',
            applicant='ops-demo',
            status=TransactionTicket.STATUS_APPROVED,
        )
        Deployment.objects.create(
            app_name='erp-platform',
            business_line='电商线',
            version='v3.2.1',
            image='registry.demo.local/erp-platform:v3.2.1',
            environment='prod',
            deploy_mode='k8s',
            status='pending',
            approval_status='pending',
            release_strategy='standard',
            submitter='ops-demo',
            change_summary='ERP 平台生产正式发布',
            description='典型案例：生产 K8s 标准发布',
        )
        Deployment.objects.create(
            app_name='gateway-service',
            business_line='电商线',
            version='v2.1.0',
            image='registry.demo.local/gateway-service:v2.1.0',
            environment='prod',
            deploy_mode='k8s',
            status='running',
            approval_status='approved',
            release_strategy='canary',
            submitter='ops-demo',
            change_summary='网关服务 20% 灰度发布',
            description='典型案例：生产 K8s 灰度发布',
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='workorders-filter')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='最近电商线生产有哪些工单')

        result = query_workorders(session, user_message, self.user, query='最近电商线生产有哪些工单')

        self.assertEqual(result['summary']['count'], 4)
        self.assertEqual(result['summary']['ticket_count'], 2)
        self.assertEqual(result['summary']['deployment_count'], 2)
        self.assertEqual(result['summary']['business_line'], '电商线')
        self.assertEqual(result['summary']['environment'], 'prod')
        section_titles = [item['title'] for item in result['sections']]
        self.assertIn('事务工单', section_titles)
        self.assertIn('应用发布', section_titles)
        self.assertTrue(any('生产数据库白名单开通' in item for section in result['sections'] for item in section['items']))
        self.assertTrue(any('网关限流策略紧急调整' in item for section in result['sections'] for item in section['items']))
        self.assertTrue(any('erp-platform v3.2.1' in item for section in result['sections'] for item in section['items']))
        self.assertTrue(any('gateway-service v2.1.0' in item for section in result['sections'] for item in section['items']))

        all_status_result = query_workorders(session, user_message, self.user, query='电商线 生产', status='all', limit=10)
        self.assertEqual(all_status_result['summary']['count'], 4)
        self.assertEqual(all_status_result['summary']['ticket_count'], 2)
        self.assertEqual(all_status_result['summary']['deployment_count'], 2)

    def test_query_hosts_filters_prod_offline_hosts(self):
        Host.objects.create(hostname='legacy-data-sync', ip_address='10.20.30.20', environment='prod', status='offline', business_line='电商线')
        Host.objects.create(hostname='feature-x-dev-01', ip_address='10.20.40.20', environment='dev', status='offline', business_line='电商线')
        session = AIOpsChatSession.objects.create(user=self.user, title='offline-hosts')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='生产环境有哪些离线主机？')

        result = query_hosts(session, user_message, self.user, query='生产环境有哪些离线主机？')

        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['environment'], 'prod')
        self.assertEqual(result['summary']['status'], 'offline')
        self.assertIn('legacy-data-sync', result['sections'][0]['items'][0])

    def test_query_cost_report_filters_business_line_and_environment(self):
        ci_type = CIType.objects.create(name='云主机')
        ConfigItem.objects.create(
            name='data-prod-warehouse',
            ci_type=ci_type,
            business_line='数据平台',
            environment='prod',
            status='active',
            attributes={'monthly_cost': 2400},
        )
        ConfigItem.objects.create(
            name='data-test-spark',
            ci_type=ci_type,
            business_line='数据平台',
            environment='test',
            status='active',
            attributes={'monthly_cost': 760},
        )
        ConfigItem.objects.create(
            name='commerce-prod-redis',
            ci_type=ci_type,
            business_line='电商线',
            environment='prod',
            status='active',
            attributes={'monthly_cost': 980},
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='cost-report')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='数据平台生产环境月成本多少')

        result = query_cost_report(session, user_message, self.user, query='数据平台生产环境月成本多少')

        self.assertEqual(result['summary']['business_line'], '数据平台')
        self.assertEqual(result['summary']['environment'], 'prod')
        self.assertEqual(result['summary']['total_monthly_cost'], 2400.0)
        self.assertIn('月成本合计：2400.00 元', result['sections'][0]['items'][3])

    def test_query_k8s_cluster_summary_returns_abnormal_pod_facts(self):
        cluster = K8sCluster.objects.create(
            name='app-prod-k8s',
            api_server='https://app-prod-k8s.example.local:6443',
            kubeconfig='demo',
            status='connected',
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='k8s-summary')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='app-prod-k8s集群有没有异常的pod')

        result = query_k8s_cluster_summary(session, user_message, self.user, query='app-prod-k8s集群有没有异常的pod')

        self.assertEqual(result['summary']['cluster_name'], cluster.name)
        self.assertGreaterEqual(result['summary']['pods_abnormal'], 1)
        self.assertTrue(any('异常 Pod：' in item for item in result['sections'][0]['items']))

    @mock.patch('aiops.services._provider_handlers')
    @mock.patch('aiops.services._resolve_provider')
    def test_query_traces_uses_live_tracing_provider(self, mocked_resolve_provider, mocked_provider_handlers):
        TracingDataSource.objects.create(
            name='Tracing SkyWalking',
            provider='skywalking',
            is_enabled=True,
            is_default=True,
            config={'oap_url': '', 'ui_url': 'http://skywalking.example.com'},
        )
        mocked_resolve_provider.return_value = ('skywalking', {})
        mocked_provider_handlers.return_value = {
            'skywalking': {
                'services': lambda config, layer='': [{
                    'id': 'svc-bcp',
                    'name': 'bcp-server@梧桐港-SaaS-PRO',
                    'short_name': 'bcp-server@梧桐港-SaaS-PRO',
                }],
                'search': lambda config, payload, services: [{
                    'trace_id': 'trace-live-1',
                    'segment_id': 'segment-live-1',
                    'service_id': 'svc-bcp',
                    'service_name': 'bcp-server@梧桐港-SaaS-PRO',
                    'instance_name': '',
                    'endpoint_names': ['xxl-job/MethodJob/citic.cph.bcp.scheduler.BcmClearScheduler.queryBcmClearInfo'],
                    'duration_ms': 8,
                    'start': '2026-04-23T12:00:00+08:00',
                    'is_error': True,
                    'state': 'ERROR',
                    'summary': '',
                    'source_provider': 'skywalking',
                }],
            }
        }

        session = AIOpsChatSession.objects.create(user=self.user, title='trace-live')
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role='user',
            content='帮我看看链路追踪里面的服务"bcp-server@梧桐港-SaaS-PRO" 最近有没有异常',
        )

        result = query_traces(
            session,
            user_message,
            self.user,
            query='bcp-server@梧桐港-SaaS-PRO',
            errors_only=True,
            limit=5,
            duration_minutes=60,
        )

        self.assertEqual(len(result['traces']), 1)
        self.assertEqual(result['traces'][0]['trace_id'], 'trace-live-1')
        self.assertEqual(result['tracing']['provider'], 'skywalking')
        self.assertTrue(any('bcp-server@梧桐港-SaaS-PRO' in item for item in result['sections'][0]['items']))

    def test_send_message_creates_session_messages(self):
        session_response = self.client.post('/api/aiops/sessions/', {'title': '测试会话'}, format='json')
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生产环境有哪些主机？'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIOpsChatSession.objects.get(pk=session_id).messages.count(), 2)

    def test_send_message_returns_error_when_no_model_available(self):
        get_agent_config()
        AIOpsModelProvider.objects.all().update(is_enabled=False)
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'no-model'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '?????????'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['assistant_message']['message_type'], AIOpsChatMessage.TYPE_ERROR)
        self.assertEqual(response.data['assistant_message']['metadata']['error_code'], 'provider_unavailable')

    def test_recover_masked_suggested_question(self):
        self.assertEqual(recover_masked_suggested_question('????????????'), '最近电商线生产有哪些工单')
        self.assertEqual(recover_masked_suggested_question('app-prod-k8s????????pod'), 'app-prod-k8s集群有没有异常的pod')

    @mock.patch('aiops.views.start_async_chat_processing')
    def test_send_message_async_returns_placeholder_assistant(self, mocked_start_async):
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'async-chat'}, format='json')
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message_async/',
            {'content': 'async alert question'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIOpsChatSession.objects.get(pk=session_id).messages.count(), 2)
        self.assertEqual(response.data['assistant_message']['metadata']['processing_status'], 'pending')
        mocked_start_async.assert_called_once()

    def test_demo_account_send_message_is_temporarily_disabled(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        demo_client = APIClient()
        demo_token = Token.objects.create(user=demo_user)
        demo_client.credentials(HTTP_AUTHORIZATION=f'Token {demo_token.key}')

        session_response = demo_client.post('/api/aiops/sessions/', {'title': 'demo-chat'}, format='json')
        self.assertEqual(session_response.status_code, 201)

        response = demo_client.post(
            f"/api/aiops/sessions/{session_response.data['id']}/send_message/",
            {'content': '当前未确认的严重告警有哪些？'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], '演示账号问答权限已临时关闭，如需体验请联系作者：592095766@qq.com')

    @mock.patch('aiops.views.start_async_chat_processing')
    def test_demo_account_send_message_async_is_temporarily_disabled(self, mocked_start_async):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        demo_client = APIClient()
        demo_token = Token.objects.create(user=demo_user)
        demo_client.credentials(HTTP_AUTHORIZATION=f'Token {demo_token.key}')

        session_response = demo_client.post('/api/aiops/sessions/', {'title': 'demo-chat-async'}, format='json')
        self.assertEqual(session_response.status_code, 201)

        response = demo_client.post(
            f"/api/aiops/sessions/{session_response.data['id']}/send_message_async/",
            {'content': '当前未确认的严重告警有哪些？'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], '演示账号问答权限已临时关闭，如需体验请联系作者：592095766@qq.com')
        mocked_start_async.assert_not_called()

    @mock.patch('aiops.services._request_model_completion')
    def test_task_request_creates_pending_action(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-task-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])
        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_task_1',
                            'type': 'function',
                            'function': {
                                'name': 'generate_host_task',
                                'arguments': '{"request_summary":"为 legacy-data-sync 生成巡检任务","environment":"prod"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '???????????????',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '- 已生成任务草稿\n- 目标主机：legacy-data-sync\n- 下一步：确认后将在任务中心创建待执行任务。',
                    },
                }],
            },
        ]
        session_response = self.client.post('/api/aiops/sessions/', {'title': '??????'}, format='json')
        session_id = session_response.data['id']
        Host.objects.create(hostname='legacy-data-sync', ip_address='10.20.30.20', environment='prod', status='offline')
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '为 legacy-data-sync 生成巡检任务'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.data['pending_action'])
    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_returns_error_when_model_does_not_call_tools(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-no-tool-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])
        mocked_completion.return_value = {
            'choices': [{
                'message': {
                    'content': '????????????????',
                },
            }],
        }
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'no-tool-call'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '?????????'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['assistant_message']['message_type'], AIOpsChatMessage.TYPE_ERROR)
        self.assertEqual(response.data['assistant_message']['metadata']['error_code'], 'no_tool_called')


    def test_task_request_respects_action_execution_switch(self):
        config = get_agent_config()
        config.allow_action_execution = False
        config.save(update_fields=['allow_action_execution'])
        session_response = self.client.post('/api/aiops/sessions/', {'title': '任务会话'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生成一份 Redis 巡检任务'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['pending_action'])

    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_uses_llm_tool_calling_runtime(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_1',
                            'type': 'function',
                            'function': {
                                'name': 'query_cmdb_items',
                                'arguments': '{"query":"生产 主机"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '已通过 MCP 查询到平台资源，并整理出主机结果。',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '- 结论：已查询到生产环境相关 CMDB 资源。\n- 概要：结果已按主机信息整理输出。\n- 可继续查看：CMDB。',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'tool-calling'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '请帮我看下生产环境 CMDB 资源'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('query_cmdb_items', response.data['assistant_message']['tool_calls'])
        step_titles = [item.get('title') for item in response.data['assistant_message']['metadata'].get('processing_steps', [])]
        self.assertIn('加载 MCP 与 Skill', step_titles)
        self.assertIn('模型规划', step_titles)
        self.assertIn('生成工具计划', step_titles)
        self.assertIn('生成回复', step_titles)
        self.assertIn('Skill 模板整形', step_titles)
        self.assertNotIn('接收问题', step_titles)

    @mock.patch('aiops.services._request_model_completion')
    def test_alert_answer_falls_back_when_llm_claims_zero_results(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-alert-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

        host = Host.objects.create(hostname='prod-alert-host', ip_address='10.1.1.10', environment='prod', status='online')
        Alert.objects.create(
            title='payment-worker Deployment 副本不可用',
            level='critical',
            source='Prometheus',
            message='replicas unavailable',
            is_acknowledged=False,
            host=host,
        )

        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_alerts',
                            'type': 'function',
                            'function': {
                                'name': 'query_alerts',
                                'arguments': '{"query":"当前未确认的严重告警有哪些？","level":"critical","only_unacknowledged":true}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '当前未确认的严重告警共有 0 条。',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '当前未确认的严重告警共有 0 条。',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'alert-fallback'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '当前未确认的严重告警有哪些？'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        content = response.data['assistant_message']['content']
        self.assertIn('结论：', content)
        self.assertIn('依据：', content)
        self.assertIn('建议操作：', content)
        self.assertIn('payment-worker Deployment 副本不可用', content)
        self.assertNotIn('0 条', content)

    @mock.patch('aiops.services._request_model_completion')
    def test_alert_answer_formatter_retries_and_uses_skill_result(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-alert-retry-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

        host = Host.objects.create(hostname='k8s-node-01', ip_address='10.30.1.11', environment='prod', status='online')
        Alert.objects.create(
            title='payment-worker Deployment 副本不可用',
            level='critical',
            source='Prometheus',
            message='replicas unavailable',
            is_acknowledged=False,
            host=host,
        )

        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_alerts_retry',
                            'type': 'function',
                            'function': {
                                'name': 'query_alerts',
                                'arguments': '{"query":"当前未确认的严重告警有哪些？","level":"critical","only_unacknowledged":true}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '当前有告警，请查看告警中心。',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '有一些严重告警。',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '结论：\n当前未确认的严重告警共 1 条，风险集中在 K8s Deployment 可用性。\n依据：\n告警明细\n- 严重 / payment-worker Deployment 副本不可用 / Prometheus / k8s-node-01\n建议操作：\n- 优先检查相关 Deployment 的副本数、事件、滚动发布进度与 Pod 就绪状态。\n- 结合 Prometheus 指标确认告警触发窗口与错误趋势。\n可继续查看：告警中心',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'alert-retry'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '当前未确认的严重告警有哪些？'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        content = response.data['assistant_message']['content']
        self.assertIn('结论：', content)
        self.assertIn('payment-worker Deployment 副本不可用', content)
        self.assertEqual(response.data['assistant_message']['metadata'].get('formatter_mode'), 'skill')

    def test_formatter_normalizes_markdown_style_headings(self):
        content = '\n'.join([
            '**结论：** 已定位到 order-center 的近期异常，发现 2 条相关告警。',
            '### 依据',
            '告警明细',
            '- 严重 / order-center 库存校验超时 / APM / order-api-ecs-01',
            '**建议** 优先检查最近发布、下游依赖耗时与错误率。',
            '### 可继续查看',
            '告警中心、链路追踪',
        ])

        normalized = _normalize_formatter_output(content)

        self.assertIn('结论：已定位到 order-center 的近期异常', normalized)
        self.assertIn('依据：', normalized)
        self.assertIn('建议操作：优先检查最近发布、下游依赖耗时与错误率。', normalized)
        self.assertIn('可继续查看：告警中心、链路追踪', normalized)
        self.assertTrue(_is_formatted_answer_valid(normalized, profile='incident'))

    def test_formatter_normalizes_multiline_followup_links_to_single_line(self):
        content = '\n'.join([
            '结论：已查询到相关结果。',
            '关键点：',
            '- 当前命中 2 条记录。',
            '可继续查看：',
            '- 工单系统:`/workorders`',
            '- 应用发布（/deployments）',
        ])

        normalized = _normalize_formatter_output(content)

        self.assertIn('可继续查看：工单系统、应用发布。', normalized)
        self.assertNotIn('/workorders', normalized)
        self.assertNotIn('/deployments', normalized)
        self.assertNotIn('可继续查看：\n', normalized)

    def test_build_markdown_answer_keeps_followup_links_on_one_line(self):
        content = build_markdown_answer(
            '智能助手回复',
            [{'title': '关键点', 'items': ['命中 2 条结果']}],
            [{'title': '工单系统'}, {'title': '应用发布'}],
            intro='已基于平台工具完成查询。',
        )

        self.assertIn('可继续查看：工单系统、应用发布。', content)

    def test_ensure_followup_line_appends_when_missing(self):
        content = _ensure_followup_line(
            '结论：已查询到相关结果。\n关键点：\n- 当前命中 2 条记录。',
            [{'title': '工单系统', 'path': '/workorders'}, {'title': '应用发布', 'path': '/deployments'}],
        )

        self.assertTrue(content.endswith('可继续查看：工单系统、应用发布。'))

    def test_ensure_followup_line_dedupes_existing_followup(self):
        content = _ensure_followup_line(
            '结论：已查询到相关结果。\n\n可继续查看：工单系统:/workorders\n可继续查看：应用发布:/deployments',
            [{'title': '工单系统', 'path': '/workorders'}, {'title': '应用发布', 'path': '/deployments'}],
        )

        self.assertEqual(content.count('可继续查看：'), 1)
        self.assertIn('可继续查看：工单系统、应用发布。', content)

    def test_formatter_repair_issue_reports_missing_headings(self):
        issue = _formatter_repair_issue(
            '结论：已查到相关告警。',
            profile='alerts',
            collected_tool_outputs=[],
        )
        self.assertIn('缺少标题', issue)
        self.assertIn('依据：', issue)
        self.assertIn('建议操作：', issue)

    def test_query_cmdb_items_returns_ip_for_natural_language_query(self):
        ci_type = CIType.objects.create(name='应用服务')
        ci = ConfigItem.objects.create(
            name='order-service',
            ci_type=ci_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={
                'ip_address': '10.10.1.100',
                'repo': 'git@example.com/order-service.git',
            },
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='cmdb-ip-test')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='order-service 的 IP 是多少')

        result = query_cmdb_items(session, user_message, self.user, query='order-service 的 IP 是多少', limit=3)

        self.assertEqual(result['summary']['tokens'], ['order-service'])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['id'], ci.id)
        self.assertEqual(result['items'][0]['ip_address'], '10.10.1.100')
        self.assertIn('10.10.1.100', result['sections'][0]['items'][0])

    def test_generate_task_draft_requires_explicit_target_host(self):
        Host.objects.create(hostname='legacy-data-sync', ip_address='10.20.30.20', environment='prod', status='offline')

        exact_draft = build_task_draft(self.user, '为 legacy-data-sync 生成巡检任务', {'request_summary': '为 legacy-data-sync 生成巡检任务'})
        self.assertEqual(exact_draft['host_count'], 1)
        self.assertEqual(exact_draft['target_hosts'][0]['hostname'], 'legacy-data-sync')

        generic_draft = build_task_draft(self.user, '生成一份 Redis 巡检任务。', {'request_summary': '生成一份 Redis 巡检任务。'})
        self.assertIn('error', generic_draft)

    def test_build_task_draft_resolves_config_item_id_before_conflicting_ip(self):
        ci_type, _ = CIType.objects.get_or_create(name='云主机(ECS)')
        target_host = Host.objects.create(
            hostname='order-api-ecs-02',
            ip_address='10.10.1.11',
            environment='prod',
            status='online',
        )
        ConfigItem.objects.create(
            id=496,
            name='order-api-ecs-02',
            ci_type=ci_type,
            business_line='commerce',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.10.1.11'},
        )
        Host.objects.create(
            hostname='commerce-prod-hz-batch-01',
            ip_address='10.10.1.11',
            environment='prod',
            status='online',
        )

        draft = build_task_draft(
            self.user,
            '在生产环境对主机 order-api-ecs-02（10.10.1.11，host_id=496）生成 Redis 巡检任务，巡检 10.10.1.11:6789。',
            {
                'request_summary': '在生产环境对主机 order-api-ecs-02（10.10.1.11，host_id=496）生成 Redis 巡检任务，巡检 10.10.1.11:6789。',
                'environment': 'prod',
                'target_host_ids': [496],
                'service_name': 'Redis',
            },
        )

        self.assertEqual(draft['host_count'], 1)
        self.assertEqual(draft['host_ids'], [target_host.id])
        self.assertEqual(draft['target_hosts'][0]['hostname'], 'order-api-ecs-02')

    def test_confirm_action_creates_pending_task_from_config_item_id_target(self):
        ci_type, _ = CIType.objects.get_or_create(name='云主机(ECS)')
        target_host = Host.objects.create(
            hostname='order-api-ecs-02',
            ip_address='10.10.1.11',
            environment='prod',
            status='online',
        )
        ConfigItem.objects.create(
            id=496,
            name='order-api-ecs-02',
            ci_type=ci_type,
            business_line='commerce',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.10.1.11'},
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='redis-task')
        assistant_message = AIOpsChatMessage.objects.create(session=session, role='assistant', content='已生成任务草稿')
        draft = build_task_draft(
            self.user,
            '在生产环境对主机 order-api-ecs-02（10.10.1.11，host_id=496）生成 Redis 巡检任务，巡检 10.10.1.11:6789。',
            {
                'request_summary': '在生产环境对主机 order-api-ecs-02（10.10.1.11，host_id=496）生成 Redis 巡检任务，巡检 10.10.1.11:6789。',
                'environment': 'prod',
                'target_host_ids': [496],
                'service_name': 'Redis',
            },
        )

        action = create_pending_task_action_from_draft(session, assistant_message, draft)
        task = confirm_action(action, self.user)

        self.assertEqual(task.target_count, 1)
        self.assertEqual(task.status, HostTask.STATUS_PENDING)
        self.assertEqual(task.target_snapshot[0]['hostname'], 'order-api-ecs-02')
        self.assertEqual(task.target_snapshot[0]['ip_address'], '10.10.1.11')
        self.assertEqual(task.selection_filters['request_summary'], draft['request_summary'])
        self.assertEqual(task.payload.get('service_name'), 'Redis')
        self.assertEqual(task.created_by, self.user.username)
        self.assertEqual(task.id, action.result_payload['task_id'])
        self.assertEqual(target_host.id, task.target_snapshot[0]['id'])

    def test_generate_task_never_materializes_before_confirmation(self):
        decision = _should_materialize_host_task(
            '为 legacy-data-sync 生成巡检任务',
            {'tool_calls': ['generate_host_task']},
            {'host_ids': [1], 'name': 'test'},
        )
        self.assertFalse(decision)

    @mock.patch('aiops.views.test_mcp_server_connection')
    def test_mcp_test_connection_endpoint(self, mocked_test_connection):
        server = AIOpsMCPServer.objects.create(
            name='HTTP MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            is_enabled=True,
        )
        mocked_test_connection.return_value = {'status': 'success', 'message': 'ok'}
        response = self.client.post(f'/api/aiops/admin/mcp-servers/{server.id}/test_connection/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')

    @mock.patch('aiops.views.list_mcp_server_tools')
    def test_mcp_list_tools_endpoint(self, mocked_list_tools):
        server = AIOpsMCPServer.objects.create(
            name='HTTP MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            is_enabled=True,
        )
        mocked_list_tools.return_value = {'count': 1, 'tools': [{'name': 'status'}]}
        response = self.client.get(f'/api/aiops/admin/mcp-servers/{server.id}/list_tools/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    @mock.patch('aiops.services._create_mcp_client_session')
    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_uses_external_mcp_tool(self, mocked_completion, mocked_create_session):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-external',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        mcp_server = AIOpsMCPServer.objects.create(
            name='External Ops MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            tool_whitelist=['server_status'],
            is_enabled=True,
        )

        config = get_agent_config()
        config.default_provider = provider
        config.enabled_mcp_server_ids = list(dict.fromkeys([*(config.enabled_mcp_server_ids or []), mcp_server.id]))
        config.save(update_fields=['default_provider', 'enabled_mcp_server_ids'])

        fake_session = mock.Mock()
        fake_session.list_tools.return_value = [
            {
                'name': 'server_status',
                'description': '返回外部系统状态',
                'inputSchema': {'type': 'object', 'properties': {'service': {'type': 'string'}}},
            },
        ]
        fake_session.call_tool.return_value = {
            'content': [{'type': 'text', 'text': 'external-ok'}],
            'structuredContent': {'status': 'ok'},
        }
        mocked_create_session.return_value = fake_session
        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_external',
                            'type': 'function',
                            'function': {
                                'name': 'mcp__External_Ops_MCP__server_status',
                                'arguments': '{"service":"gateway"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '已通过外部 MCP 工具获取 gateway 状态。',
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '- 结论：gateway 当前状态正常。\n- 依据：已通过外部 MCP 工具返回 external-ok。\n- 建议：继续观察外部系统状态。',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'external-mcp'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '查询 gateway 的外部状态'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('mcp__External_Ops_MCP__server_status', response.data['assistant_message']['tool_calls'])
        self.assertGreaterEqual(fake_session.initialize.call_count, 1)
        fake_session.call_tool.assert_called_once_with('server_status', {'service': 'gateway'})
