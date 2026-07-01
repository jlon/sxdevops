import json
from collections import Counter, defaultdict


DEFAULT_MAX_TOOL_CALLS = 10
DEFAULT_MAX_CALLS_PER_TOOL = 3
DEFAULT_MAX_EMPTY_RESULTS_PER_TOOL = 2

EMPTY_RESULT_KEYS = (
    'items',
    'results',
    'alerts',
    'logs',
    'traces',
    'resources',
    'nodes',
    'clusters',
    'events',
    'workloads',
    'series',
    'values',
    'samples',
)


def build_tool_budget_prompt(max_tool_calls=DEFAULT_MAX_TOOL_CALLS):
    return (
        f'工具预算约束：本轮最多调用 {max_tool_calls} 次工具。'
        '每次调用前必须说明它能让你更接近答案或根因。'
        '同一工具不要调用超过 3 次。'
        '同一方向连续 2 次返回空结果或错误时，停止这条方向，把“空结果”作为证据写入结论，并换方向或总结现有事实。'
        '到第 7 次工具调用后必须开始收敛答案，不要为了凑证据反复尝试相似查询。'
    )


def tool_output_is_empty(tool_output):
    if tool_output is None:
        return True
    if isinstance(tool_output, str):
        return not tool_output.strip()
    if isinstance(tool_output, list):
        return len(tool_output) == 0
    if not isinstance(tool_output, dict):
        return False
    if tool_output.get('error'):
        return True
    summary = tool_output.get('summary') if isinstance(tool_output.get('summary'), dict) else {}
    for key in ('count', 'total', 'node_count', 'cluster_count', 'log_count', 'trace_count', 'alert_count', 'series_count', 'sample_count'):
        if key in summary:
            try:
                return int(summary.get(key) or 0) <= 0
            except (TypeError, ValueError):
                return False
    if any(isinstance(tool_output.get(key), list) and tool_output.get(key) for key in EMPTY_RESULT_KEYS):
        return False
    if any(key in tool_output for key in EMPTY_RESULT_KEYS):
        return True
    content = tool_output.get('content')
    if isinstance(content, list):
        return len(content) == 0
    return False


def tool_call_signature(tool_name, arguments):
    try:
        payload = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(arguments or {})
    return f'{tool_name}:{payload}'


class ToolRuntimeBudget:
    def __init__(
        self,
        max_tool_calls=DEFAULT_MAX_TOOL_CALLS,
        max_calls_per_tool=DEFAULT_MAX_CALLS_PER_TOOL,
        max_empty_results_per_tool=DEFAULT_MAX_EMPTY_RESULTS_PER_TOOL,
    ):
        self.max_tool_calls = max_tool_calls
        self.max_calls_per_tool = max_calls_per_tool
        self.max_empty_results_per_tool = max_empty_results_per_tool
        self.total_calls = 0
        self.tool_counts = Counter()
        self.empty_counts = defaultdict(int)
        self.signatures = Counter()
        self.stops = []

    def allow(self, tool_name, arguments=None):
        tool_name = str(tool_name or '').strip()
        if not tool_name:
            return False, '工具名为空，已跳过。'
        if self.total_calls >= self.max_tool_calls:
            return False, f'已达到本轮工具预算上限 {self.max_tool_calls} 次，请基于已有证据总结。'
        if self.tool_counts[tool_name] >= self.max_calls_per_tool:
            return False, f'{tool_name} 已调用 {self.tool_counts[tool_name]} 次，停止重复调用并基于已有证据总结。'
        if self.empty_counts[tool_name] >= self.max_empty_results_per_tool:
            return False, f'{tool_name} 已连续 {self.empty_counts[tool_name]} 次返回空结果或错误，停止该方向。'
        signature = tool_call_signature(tool_name, arguments)
        if self.signatures[signature] >= 1:
            return False, f'{tool_name} 使用相同参数已调用过，禁止重复空转。'
        return True, ''

    def record(self, tool_name, arguments=None, tool_output=None):
        tool_name = str(tool_name or '').strip()
        self.total_calls += 1
        self.tool_counts[tool_name] += 1
        self.signatures[tool_call_signature(tool_name, arguments)] += 1
        empty = tool_output_is_empty(tool_output)
        if empty:
            self.empty_counts[tool_name] += 1
        else:
            self.empty_counts[tool_name] = 0
        return empty

    def stop(self, tool_name, reason):
        item = {'tool_name': tool_name, 'reason': reason}
        self.stops.append(item)
        return item

    def trace(self):
        return {
            'max_tool_calls': self.max_tool_calls,
            'max_calls_per_tool': self.max_calls_per_tool,
            'max_empty_results_per_tool': self.max_empty_results_per_tool,
            'total_calls': self.total_calls,
            'tool_counts': dict(self.tool_counts),
            'empty_counts': dict(self.empty_counts),
            'stops': list(self.stops),
        }
