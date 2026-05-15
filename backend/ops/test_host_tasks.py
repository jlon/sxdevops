from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from ops.host_tasks import AnsibleControllerError
from ops.models import Host, HostTask, HostTaskTemplate, K8sCluster
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


class HostTaskApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.client = APIClient()
        self.user = get_user_model().objects.create_user('task-admin', password='Admin@123456')
        role = Role.objects.get(code='ops-admin')
        role.users.add(self.user)
        self.client.force_authenticate(user=self.user)
        self.host = Host.objects.create(
            hostname='app-01',
            ip_address='10.10.10.10',
            business_line='payment',
            environment='prod',
            status='online',
            ssh_user='root',
            ssh_password='secret',
        )

    def _mock_client(self, outputs):
        client = MagicMock()

        def exec_command(command, timeout=None):
            stdout = MagicMock()
            stderr = MagicMock()
            stdout.channel.recv_exit_status.return_value = outputs[command]['exit_status']
            stdout.read.return_value = outputs[command].get('stdout', '').encode('utf-8')
            stderr.read.return_value = outputs[command].get('stderr', '').encode('utf-8')
            return None, stdout, stderr

        client.exec_command.side_effect = exec_command
        return client

    @patch('ops.host_tasks.open_ssh_client')
    def test_run_command_task_records_successful_execution(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': '10:00 up 12 days, load average: 0.10'},
        })

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'batch-load-check',
                'task_type': 'run_command',
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_SSH)
        self.assertEqual(payload['success_count'], 1)
        self.assertEqual(payload['executions'][0]['status'], 'success')
        self.assertIn('load average', payload['executions'][0]['output'])

    @patch('ops.host_tasks.allow_ansible_fallback_to_ssh', return_value=True)
    @patch('ops.host_tasks.execute_ansible_command')
    @patch('ops.host_tasks.open_ssh_client')
    def test_ansible_mode_falls_back_to_ssh_when_controller_unavailable(self, mock_open_ssh_client, mock_execute_ansible_command, _mock_allow_fallback):
        mock_execute_ansible_command.side_effect = AnsibleControllerError('ansible controller unavailable')
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'fallback-ok'},
        })

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'ansible-fallback-demo',
                'task_type': 'run_command',
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(payload['success_count'], 1)
        self.assertIn('Ansible', payload['summary'])
        self.assertIn('SSH', payload['summary'])
        self.assertEqual(payload['executions'][0]['output'], 'fallback-ok')

    @patch('ops.host_tasks.execute_ansible_playbook')
    def test_run_playbook_task_executes_with_ansible_mode(self, mock_execute_ansible_playbook):
        mock_execute_ansible_playbook.return_value = ('PLAY [targets]\\nTASK [ping]\\nok: [app-01]', '')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-smoke-check',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'smoke-check.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks:\\n    - name: ping\\n      ping:',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(payload['executions'][0]['command'], 'ansible-playbook smoke-check.yml')
        self.assertIn('PLAY [targets]', payload['executions'][0]['output'])

    @patch('ops.host_tasks.allow_ansible_fallback_to_ssh', return_value=True)
    @patch('ops.host_tasks.execute_ansible_playbook')
    @patch('ops.host_tasks.open_ssh_client')
    def test_run_playbook_does_not_fallback_to_ssh(self, mock_open_ssh_client, mock_execute_ansible_playbook, _mock_allow_fallback):
        mock_execute_ansible_playbook.side_effect = AnsibleControllerError('playbook controller unavailable')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-no-fallback',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'deploy.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks: []',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'failed')
        self.assertEqual(payload['failed_count'], 1)
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertNotIn('SSH', payload['summary'])
        mock_open_ssh_client.assert_not_called()

    @patch('ops.host_tasks.collect_host_metrics')
    @patch('ops.host_tasks.open_ssh_client')
    def test_refresh_metrics_task_updates_host_usage(self, mock_open_ssh_client, mock_collect_host_metrics):
        mock_open_ssh_client.return_value = MagicMock()
        mock_collect_host_metrics.return_value = (
            {'cpu_usage': 12.5, 'memory_usage': 48.2, 'disk_usage': 66.0},
            {},
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'refresh-prod-host-metrics',
                'task_type': 'refresh_metrics',
                'host_ids': [self.host.id],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.host.refresh_from_db()
        self.assertEqual(self.host.status, 'online')
        self.assertEqual(self.host.cpu_usage, 12.5)
        self.assertEqual(self.host.memory_usage, 48.2)
        self.assertEqual(self.host.disk_usage, 66.0)

    def test_host_tasks_require_execute_permission(self):
        viewer = get_user_model().objects.create_user('host-viewer', password='Admin@123456')
        role = Role.objects.create(code='host-viewer-role', name='Host Viewer')
        role.permissions.set([])
        role.users.add(viewer)
        self.client.force_authenticate(user=viewer)

        response = self.client.get('/api/host-tasks/')

        self.assertEqual(response.status_code, 403)

    def test_k8s_pod_exec_task_records_non_host_execution(self):
        cluster = K8sCluster.objects.create(name='demo-k8s', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'pod-diagnostic',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'namespace': 'production',
                        'name': 'api-server-5f8b7c6d4-r9p2w',
                        'kind': 'pod',
                    },
                ],
                'payload': {'command': 'pwd'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_K8S_API)
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        self.assertEqual(payload['success_count'], 1)
        self.assertEqual(payload['executions'][0]['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['executions'][0]['target_namespace'], 'production')
        self.assertIn('demo-exec', payload['executions'][0]['output'])

    @patch('ops.host_tasks.open_ssh_client')
    def test_rerun_reuses_original_targets_and_mode(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'ok'},
        })
        create_response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'initial-run',
                'task_type': 'run_command',
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )
        task_id = create_response.json()['id']

        rerun_response = self.client.post(f'/api/host-tasks/{task_id}/rerun/', {}, format='json')

        self.assertEqual(rerun_response.status_code, 201)
        rerun_payload = rerun_response.json()
        self.assertEqual(rerun_payload['target_count'], 1)
        self.assertEqual(rerun_payload['created_by'], self.user.username)
        self.assertEqual(rerun_payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertTrue(HostTask.objects.filter(id=rerun_payload['id']).exists())

    def test_update_personal_template(self):
        template = HostTaskTemplate.objects.create(
            name='health-check',
            task_type='run_command',
            description='before update',
            payload={'command': 'uptime'},
            execution_mode=HostTask.EXECUTION_MODE_SSH,
            execution_strategy=HostTask.STRATEGY_CONTINUE,
            timeout_seconds=20,
            created_by=self.user.username,
        )

        response = self.client.put(
            f'/api/host-task-templates/{template.id}/',
            {
                'name': 'health-check-v2',
                'task_type': 'run_command',
                'description': 'after update',
                'payload': {'command': 'hostname && uptime'},
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'execution_strategy': 'stop_on_error',
                'timeout_seconds': 35,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        template.refresh_from_db()
        self.assertEqual(template.name, 'health-check-v2')
        self.assertEqual(template.payload['command'], 'hostname && uptime')
        self.assertEqual(template.execution_mode, HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(template.execution_strategy, HostTask.STRATEGY_STOP_ON_ERROR)
        self.assertEqual(template.timeout_seconds, 35)

    def test_create_playbook_template_forces_ansible_mode(self):
        response = self.client.post(
            '/api/host-task-templates/',
            {
                'name': 'deploy-playbook',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'description': 'deploy app',
                'payload': {
                    'playbook_name': 'deploy-app.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks: []',
                },
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
                'timeout_seconds': 40,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)

    def test_cannot_update_builtin_template(self):
        template = HostTaskTemplate.objects.create(
            name='builtin-template',
            task_type='refresh_metrics',
            description='demo',
            payload={},
            execution_mode=HostTask.EXECUTION_MODE_SSH,
            execution_strategy=HostTask.STRATEGY_CONTINUE,
            timeout_seconds=15,
            is_builtin=True,
            created_by='system',
        )

        response = self.client.put(
            f'/api/host-task-templates/{template.id}/',
            {
                'name': 'builtin-template-v2',
                'task_type': 'refresh_metrics',
                'description': 'updated',
                'payload': {},
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': 'continue',
                'timeout_seconds': 15,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        template.refresh_from_db()
        self.assertEqual(template.name, 'builtin-template')
