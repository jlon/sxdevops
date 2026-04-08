import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import paramiko
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models import Host, HostTask, HostTaskExecution

_TASK_THREADS = {}
_TASK_THREADS_LOCK = threading.Lock()


class AnsibleControllerError(RuntimeError):
    pass


def build_host_target_queryset(filters=None):
    filters = filters or {}
    queryset = Host.objects.all().order_by('hostname', 'id')

    search = (filters.get('search') or '').strip()
    if search:
        queryset = queryset.filter(Q(hostname__icontains=search) | Q(ip_address__icontains=search))

    status = (filters.get('status') or '').strip()
    if status:
        queryset = queryset.filter(status=status)

    business_line = (filters.get('business_line') or '').strip()
    if business_line:
        queryset = queryset.filter(business_line=business_line)

    environment = (filters.get('environment') or '').strip()
    if environment:
        queryset = queryset.filter(environment=environment)

    return queryset.order_by('hostname', 'id')


def get_ansible_binary():
    return getattr(settings, 'HOST_TASK_ANSIBLE_BINARY', 'ansible')


def get_ansible_playbook_binary():
    return getattr(settings, 'HOST_TASK_ANSIBLE_PLAYBOOK_BINARY', 'ansible-playbook')


def is_ansible_available():
    return bool(shutil.which(get_ansible_binary()))


def is_ansible_playbook_available():
    return bool(shutil.which(get_ansible_playbook_binary()))


def allow_ansible_fallback_to_ssh():
    configured = getattr(settings, 'HOST_TASK_ANSIBLE_FALLBACK_TO_SSH', None)
    if configured is not None:
        return configured
    return bool(getattr(settings, 'DEBUG', False))


def _ansible_ssh_common_args():
    return getattr(
        settings,
        'HOST_TASK_ANSIBLE_SSH_COMMON_ARGS',
        '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null',
    )


def _ansible_inventory_alias(host):
    return f"host_{host.id}_{slugify(host.hostname) or 'node'}"


def open_ssh_client(host, timeout_seconds):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host.ip_address,
        port=host.ssh_port or 22,
        username=host.ssh_user or 'root',
        password=host.ssh_password or None,
        timeout=timeout_seconds,
    )
    return client


def execute_remote_command(client, command, timeout_seconds):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    exit_status = stdout.channel.recv_exit_status()
    output = stdout.read().decode('utf-8', errors='replace').strip()
    error_output = stderr.read().decode('utf-8', errors='replace').strip()
    return exit_status, output, error_output


def _metrics_shell_command():
    return (
        "printf 'CPU='; top -bn1 | grep 'Cpu(s)' | awk '{print $2}'; "
        "printf '\\nMEM='; free | grep Mem | awk '{printf(\"%.1f\", $3/$2*100)}'; "
        "printf '\\nDISK='; df / | tail -1 | awk '{print $5}' | tr -d '%'"
    )


def _build_command_text(task):
    if task.task_type == HostTask.TASK_CHECK_CONNECTION:
        return 'hostname && uname -sr'
    if task.task_type == HostTask.TASK_REFRESH_METRICS:
        return 'metrics: cpu/memory/disk refresh'
    if task.task_type == HostTask.TASK_RUN_PLAYBOOK:
        playbook_name = ((task.payload or {}).get('playbook_name') or '').strip() or 'inline-playbook.yml'
        return f'ansible-playbook {playbook_name}'
    if task.task_type == HostTask.TASK_SERVICE_STATUS:
        service_name = (task.payload or {}).get('service_name', '').strip()
        return f"systemctl status {shlex.quote(service_name)} --no-pager --lines=12"
    return ((task.payload or {}).get('command') or '').strip()


def _build_remote_command(task):
    if task.task_type == HostTask.TASK_REFRESH_METRICS:
        return _metrics_shell_command()
    return _build_command_text(task)


def _parse_metrics_output(output):
    metrics = {}
    raw_outputs = {}
    mapping = {'CPU': 'cpu_usage', 'MEM': 'memory_usage', 'DISK': 'disk_usage'}
    for line in (output or '').splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip().upper()
        value = value.strip()
        if key not in mapping:
            continue
        raw_outputs[mapping[key]] = value
        try:
            metrics[mapping[key]] = round(float(value), 1)
        except (TypeError, ValueError):
            continue
    return metrics, raw_outputs


def collect_host_metrics(client, timeout_seconds):
    exit_status, output, error_output = execute_remote_command(client, _metrics_shell_command(), timeout_seconds)
    if exit_status != 0:
        return {}, {'metrics': error_output or output}
    return _parse_metrics_output(output)


def _mark_host_offline(host):
    if host.status != 'offline':
        host.status = 'offline'
        host.save(update_fields=['status'])


def _should_mark_host_offline(message):
    lowered = str(message or '').lower()
    keywords = ['unreachable', 'failed to connect', 'permission denied', 'timed out', 'connection refused', 'authentication failed']
    return any(keyword in lowered for keyword in keywords)


def _create_skipped_execution(task, host, message):
    HostTaskExecution.objects.create(
        task=task,
        host=host,
        host_name=host.hostname,
        host_ip=host.ip_address,
        status='skipped',
        command='',
        output='',
        error_message=message,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        duration_ms=0,
    )
    task.skipped_count += 1


def _create_failed_execution(task, host, command_text, message):
    return HostTaskExecution.objects.create(
        task=task,
        host=host,
        host_name=host.hostname,
        host_ip=host.ip_address,
        status='failed',
        command=command_text,
        output='',
        error_message=(message or '')[:4000],
        started_at=timezone.now(),
        finished_at=timezone.now(),
        duration_ms=0,
    )


def _build_ansible_extra_vars(host):
    extra_vars = {
        'ansible_connection': 'ssh',
        'ansible_user': host.ssh_user or 'root',
        'ansible_port': host.ssh_port or 22,
    }
    common_args = _ansible_ssh_common_args()
    if common_args:
        extra_vars['ansible_ssh_common_args'] = common_args
    if host.ssh_password:
        extra_vars['ansible_password'] = host.ssh_password
    return extra_vars


def _build_ansible_process_env():
    env = dict(**getattr(settings, 'HOST_TASK_ANSIBLE_ENV', {}))
    process_env = dict(os.environ)
    process_env.update({'ANSIBLE_HOST_KEY_CHECKING': 'False', 'PYTHONIOENCODING': 'utf-8'})
    process_env.update(env)
    return process_env


def _normalize_playbook_filename(playbook_name):
    raw_name = (playbook_name or '').strip()
    suffix = '.yaml' if raw_name.endswith('.yaml') else '.yml'
    stem = Path(raw_name).stem if raw_name else 'inline-playbook'
    normalized = slugify(stem) or 'inline-playbook'
    return f'{normalized}{suffix}'


def _extract_ansible_payload(text):
    content = (text or '').strip()
    if '>>' in content:
        content = content.split('>>', 1)[1].strip()
    return content


def _is_ansible_controller_error(message):
    lowered = str(message or '').lower()
    keywords = [
        'sshpass',
        'ansible command not found',
        'is not recognized as an internal or external command',
        'unsupported platform',
        'failed to create temporary directory',
        'no such file or directory',
    ]
    return any(keyword in lowered for keyword in keywords)


def execute_ansible_command(host, command_text, timeout_seconds):
    if not is_ansible_available():
        raise AnsibleControllerError('\u672a\u68c0\u6d4b\u5230 Ansible \u63a7\u5236\u7aef\u73af\u5883')

    alias = _ansible_inventory_alias(host)
    extra_vars = _build_ansible_extra_vars(host)
    process_env = _build_ansible_process_env()

    with tempfile.TemporaryDirectory(prefix='sxdevops_ansible_') as tmpdir:
        inventory_path = Path(tmpdir) / 'inventory.ini'
        inventory_path.write_text(f'[targets]\n{alias} ansible_host={host.ip_address}\n', encoding='utf-8')
        command = [
            get_ansible_binary(),
            alias,
            '-i',
            str(inventory_path),
            '-m',
            'raw',
            '-a',
            command_text,
            '-T',
            str(max(5, min(timeout_seconds, 120))),
            '-e',
            json.dumps(extra_vars, ensure_ascii=False),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(timeout_seconds + 20, 30),
                env=process_env,
            )
        except FileNotFoundError as exc:
            raise AnsibleControllerError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Ansible command timeout: {exc.timeout}s') from exc

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    payload = _extract_ansible_payload(stdout)
    if result.returncode == 0:
        return payload, ''

    message = stderr or payload or stdout or f'ansible exit code {result.returncode}'
    if _is_ansible_controller_error(message):
        raise AnsibleControllerError(message)
    raise RuntimeError(message)


def execute_ansible_playbook(host, playbook_content, timeout_seconds, playbook_name='', extra_vars=None):
    if not is_ansible_playbook_available():
        raise AnsibleControllerError('\u672a\u68c0\u6d4b\u5230 Ansible Playbook \u63a7\u5236\u7aef\u73af\u5883')

    alias = _ansible_inventory_alias(host)
    merged_extra_vars = _build_ansible_extra_vars(host)
    if isinstance(extra_vars, dict):
        merged_extra_vars.update(extra_vars)
    process_env = _build_ansible_process_env()

    with tempfile.TemporaryDirectory(prefix='sxdevops_playbook_') as tmpdir:
        inventory_path = Path(tmpdir) / 'inventory.ini'
        playbook_path = Path(tmpdir) / _normalize_playbook_filename(playbook_name)
        inventory_path.write_text(f'[targets]\n{alias} ansible_host={host.ip_address}\n', encoding='utf-8')
        playbook_path.write_text((playbook_content or '').strip() + '\n', encoding='utf-8')
        command = [
            get_ansible_playbook_binary(),
            '-i',
            str(inventory_path),
            str(playbook_path),
            '--limit',
            alias,
            '-e',
            json.dumps(merged_extra_vars, ensure_ascii=False),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(timeout_seconds + 20, 30),
                env=process_env,
            )
        except FileNotFoundError as exc:
            raise AnsibleControllerError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Ansible playbook timeout: {exc.timeout}s') from exc

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    if result.returncode == 0:
        return stdout, stderr

    message = stderr or stdout or f'ansible-playbook exit code {result.returncode}'
    if _is_ansible_controller_error(message):
        raise AnsibleControllerError(message)
    raise RuntimeError(message)


def _run_single_task_with_ssh(task, host):
    started_at = timezone.now()
    monotonic_started = time.monotonic()
    command_text = _build_command_text(task)
    output = ''
    error_message = ''
    status = 'success'

    try:
        client = open_ssh_client(host, task.timeout_seconds)
        try:
            if task.task_type == HostTask.TASK_CHECK_CONNECTION:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                host.status = 'online'
                host.save(update_fields=['status'])
                status = 'success' if exit_status == 0 else 'failed'
            elif task.task_type == HostTask.TASK_REFRESH_METRICS:
                metrics, raw_outputs = collect_host_metrics(client, task.timeout_seconds)
                for key, value in metrics.items():
                    setattr(host, key, value)
                host.status = 'online'
                host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
                output = f'CPU {host.cpu_usage}% | \u5185\u5b58 {host.memory_usage}% | \u78c1\u76d8 {host.disk_usage}%'
                if raw_outputs and not metrics:
                    error_message = '; '.join([f'{key}: {value}' for key, value in raw_outputs.items() if value])
                status = 'success'
            elif task.task_type == HostTask.TASK_SERVICE_STATUS:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                status = 'success' if exit_status == 0 else 'failed'
            else:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                status = 'success' if exit_status == 0 else 'failed'
        finally:
            client.close()
    except Exception as exc:
        _mark_host_offline(host)
        status = 'failed'
        error_message = str(exc)

    finished_at = timezone.now()
    duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    return HostTaskExecution.objects.create(
        task=task,
        host=host,
        host_name=host.hostname,
        host_ip=host.ip_address,
        status=status,
        command=command_text,
        output=output[:8000],
        error_message=error_message[:4000],
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


def _run_single_task_with_ansible(task, host):
    started_at = timezone.now()
    monotonic_started = time.monotonic()
    command_text = _build_command_text(task)
    output = ''
    error_message = ''
    status = 'success'

    try:
        if task.task_type == HostTask.TASK_RUN_PLAYBOOK:
            raw_output, raw_error = execute_ansible_playbook(
                host,
                (task.payload or {}).get('playbook_content', ''),
                task.timeout_seconds,
                (task.payload or {}).get('playbook_name', ''),
                (task.payload or {}).get('extra_vars') or {},
            )
        else:
            raw_output, raw_error = execute_ansible_command(host, _build_remote_command(task), task.timeout_seconds)
        if task.task_type == HostTask.TASK_REFRESH_METRICS:
            metrics, raw_outputs = _parse_metrics_output(raw_output)
            for key, value in metrics.items():
                setattr(host, key, value)
            host.status = 'online'
            host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
            output = f'CPU {host.cpu_usage}% | \u5185\u5b58 {host.memory_usage}% | \u78c1\u76d8 {host.disk_usage}%'
            if raw_outputs and not metrics:
                error_message = '; '.join([f'{key}: {value}' for key, value in raw_outputs.items() if value])
        else:
            output = raw_output
            if task.task_type == HostTask.TASK_CHECK_CONNECTION:
                host.status = 'online'
                host.save(update_fields=['status'])
    except AnsibleControllerError:
        raise
    except Exception as exc:
        status = 'failed'
        error_message = str(exc)
        if _should_mark_host_offline(error_message):
            _mark_host_offline(host)

    finished_at = timezone.now()
    duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    return HostTaskExecution.objects.create(
        task=task,
        host=host,
        host_name=host.hostname,
        host_ip=host.ip_address,
        status=status,
        command=command_text,
        output=output[:8000],
        error_message=error_message[:4000],
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


def _run_single_task(task, host, execution_mode):
    if execution_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        return _run_single_task_with_ansible(task, host)
    return _run_single_task_with_ssh(task, host)


def execute_host_task(task, hosts):
    hosts = list(hosts)
    task.refresh_from_db()
    requested_mode = task.execution_mode or HostTask.EXECUTION_MODE_SSH
    active_mode = requested_mode
    fallback_message = ''
    task.status = HostTask.STATUS_RUNNING
    task.started_at = timezone.now()
    task.target_count = len(hosts)
    task.target_snapshot = [
        {
            'id': host.id,
            'hostname': host.hostname,
            'ip_address': host.ip_address,
            'business_line': host.business_line,
            'environment': host.environment,
            'status': host.status,
        }
        for host in hosts
    ]
    task.success_count = 0
    task.failed_count = 0
    task.skipped_count = 0
    if requested_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        task.summary = '\u4efb\u52a1\u6267\u884c\u4e2d\uff0c\u6b63\u5728\u901a\u8fc7 Ansible \u8fde\u63a5\u76ee\u6807\u4e3b\u673a'
    else:
        task.summary = '\u4efb\u52a1\u6267\u884c\u4e2d\uff0c\u6b63\u5728\u8fde\u63a5\u76ee\u6807\u4e3b\u673a'
    task.save(
        update_fields=[
            'status',
            'started_at',
            'target_count',
            'target_snapshot',
            'success_count',
            'failed_count',
            'skipped_count',
            'summary',
        ]
    )

    failure_hosts = []
    stop_on_error = task.execution_strategy == HostTask.STRATEGY_STOP_ON_ERROR
    halted = False
    canceled = False

    for index, host in enumerate(hosts):
        task.refresh_from_db(fields=['cancel_requested'])
        if task.cancel_requested:
            canceled = True
            for remaining_host in hosts[index:]:
                _create_skipped_execution(task, remaining_host, '\u4efb\u52a1\u5df2\u6536\u5230\u7ec8\u6b62\u8bf7\u6c42\uff0c\u5269\u4f59\u4e3b\u673a\u5df2\u8df3\u8fc7\u6267\u884c')
            break

        if halted:
            _create_skipped_execution(task, host, '\u524d\u5e8f\u4e3b\u673a\u6267\u884c\u5931\u8d25\uff0c\u7b56\u7565\u4e3a\u5931\u8d25\u5373\u505c\uff0c\u5f53\u524d\u4e3b\u673a\u5df2\u8df3\u8fc7')
            continue

        try:
            execution = _run_single_task(task, host, active_mode)
        except AnsibleControllerError as exc:
            if (
                requested_mode == HostTask.EXECUTION_MODE_ANSIBLE
                and task.task_type != HostTask.TASK_RUN_PLAYBOOK
                and allow_ansible_fallback_to_ssh()
            ):
                active_mode = HostTask.EXECUTION_MODE_SSH
                fallback_message = str(exc)
                execution = _run_single_task(task, host, active_mode)
            else:
                execution = _create_failed_execution(task, host, _build_command_text(task), str(exc))
        if execution.status == 'success':
            task.success_count += 1
        else:
            task.failed_count += 1
            failure_hosts.append(execution.host_name)
            if stop_on_error:
                halted = True

    task.finished_at = timezone.now()
    if canceled:
        task.status = HostTask.STATUS_CANCELED
    elif task.failed_count and task.success_count:
        task.status = HostTask.STATUS_PARTIAL
    elif task.failed_count:
        task.status = HostTask.STATUS_FAILED
    else:
        task.status = HostTask.STATUS_SUCCESS

    summary = f'\u5171 {task.target_count} \u53f0\uff0c\u6210\u529f {task.success_count}\uff0c\u5931\u8d25 {task.failed_count}'
    if task.skipped_count:
        summary += f'\uff0c\u8df3\u8fc7 {task.skipped_count}'
    if failure_hosts:
        summary += f'\uff0c\u5931\u8d25\u4e3b\u673a\uff1a{", ".join(failure_hosts[:5])}'
        if len(failure_hosts) > 5:
            summary += ' ...'
    if canceled:
        summary += '\uff0c\u4efb\u52a1\u5df2\u6309\u7533\u8bf7\u7ec8\u6b62'
    if requested_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        if active_mode == HostTask.EXECUTION_MODE_SSH:
            summary += '\uff0cAnsible \u4e0d\u53ef\u7528\u5df2\u56de\u9000 SSH'
            if fallback_message:
                summary += f' ({fallback_message[:48]})'
        else:
            summary += '\uff0c\u6267\u884c\u65b9\u5f0f\uff1aAnsible'
    task.summary = summary[:255]
    task.save(
        update_fields=[
            'status',
            'success_count',
            'failed_count',
            'skipped_count',
            'finished_at',
            'summary',
        ]
    )
    if task.schedule_id:
        from .host_task_schedules import sync_schedule_after_task

        sync_schedule_after_task(task)
    return task


def should_run_async():
    configured = getattr(settings, 'HOST_TASK_RUN_ASYNC', None)
    if configured is not None:
        return configured
    return 'test' not in sys.argv


def _execute_host_task_thread(task_id, host_ids):
    close_old_connections()
    try:
        task = HostTask.objects.get(pk=task_id)
        host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
        hosts = [host_map[item] for item in host_ids if item in host_map]
        execute_host_task(task, hosts)
    finally:
        close_old_connections()
        with _TASK_THREADS_LOCK:
            _TASK_THREADS.pop(task_id, None)


def start_host_task(task, hosts):
    host_list = list(hosts)
    task.target_count = len(host_list)
    task.target_snapshot = [
        {
            'id': host.id,
            'hostname': host.hostname,
            'ip_address': host.ip_address,
            'business_line': host.business_line,
            'environment': host.environment,
            'status': host.status,
        }
        for host in host_list
    ]
    if should_run_async():
        if task.execution_mode == HostTask.EXECUTION_MODE_ANSIBLE:
            task.summary = '\u4efb\u52a1\u5df2\u5165\u961f\uff0c\u7b49\u5f85\u540e\u53f0\u901a\u8fc7 Ansible \u6267\u884c'
        else:
            task.summary = '\u4efb\u52a1\u5df2\u5165\u961f\uff0c\u7b49\u5f85\u540e\u53f0\u6267\u884c'
        task.save(update_fields=['target_count', 'target_snapshot', 'summary'])
        host_ids = [host.id for host in host_list]
        worker = threading.Thread(target=_execute_host_task_thread, args=(task.id, host_ids), daemon=True)
        with _TASK_THREADS_LOCK:
            _TASK_THREADS[task.id] = worker
        worker.start()
        return task

    execute_host_task(task, host_list)
    return task
