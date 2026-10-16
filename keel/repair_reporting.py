"""Read-only paired summaries; never infer success from absence of an error."""


def summarize(report):
    groups = {}
    for row in report['records']:
        key, arm = row['task_id'], row['repair_attempts']
        if type(arm) is not int or arm not in (0, 2):
            raise ValueError('Expected repair arms 0 and 2')
        if arm in groups.setdefault(key, {}):
            raise ValueError('Duplicate task/arm; repetitions must not inflate task count')
        if type(row.get('passed')) is not bool:
            raise ValueError('Explicit boolean passed required')
        if row['passed'] and (row.get('status') != 'completed' or row.get('executed') is not True):
            raise ValueError('Successful row must be completed and executed')
        groups[key][arm] = row
    paired, exclusions = [], []
    for task, arms in sorted(groups.items()):
        if set(arms) != {0, 2}:
            exclusions.append({'task_id': task, 'reason': 'missing_arm'})
        elif any(r.get('status') != 'completed' or r.get('executed') is not True for r in arms.values()):
            exclusions.append({'task_id': task, 'reason': 'incomplete_or_environment_or_runtime_error',
                               'statuses': {str(k): v.get('status') for k, v in arms.items()}})
        else:
            paired.append((task, arms))
    counts = {'both_passed': 0, 'enabled_only': 0, 'disabled_only': 0, 'both_failed': 0}
    details = []
    for task, arms in paired:
        disabled, enabled = arms[0], arms[2]
        outcome = ('both_passed' if enabled['passed'] else 'disabled_only') if disabled['passed'] else (
            'enabled_only' if enabled['passed'] else 'both_failed')
        counts[outcome] += 1
        details.append({'task_id': task, 'outcome': outcome,
            'arms': {str(k): {'passed': v['passed'], 'failure': v.get('failure'),
                'verification_rounds': v.get('verification_rounds'), 'budget': v.get('budget'),
                'seconds_including_baseline': v.get('seconds_including_baseline')} for k, v in arms.items()}})
    denominator = len(paired)
    rates = {str(arm): sum(arms[arm]['passed'] for _, arms in paired)/denominator if denominator else None
             for arm in (0, 2)}
    return {'observed_tasks': len(groups), 'paired_completed_tasks': denominator,
            'excluded_tasks': exclusions, 'paired_success_rate': rates, 'outcome_counts': counts,
            'enabled_minus_disabled_rate': rates['2']-rates['0'] if denominator else None,
            'tasks': details, 'heldout_tasks': report.get('heldout_tasks', 0), 'benchmark_ready': False,
            'limitations': 'One row per task/arm; no significance or causal claim. Completed pre-verification failures remain failures. Exclusions are explicit. Failure categories are preserved, not independently root-cause verified.'}


def markdown(summary):
    lines = ['# Paired feedback diagnostic', '',
             f"Paired completed tasks: {summary['paired_completed_tasks']}; excluded tasks: {len(summary['excluded_tasks'])}.", '',
             '| Task | Outcome | Disabled failure | Enabled failure |', '|---|---|---|---|']
    for row in summary['tasks']:
        failures = []
        for arm in ('0', '2'):
            error = row['arms'][arm]['failure'] or {}
            failures.append((str(error.get('stage', ''))+'/'+str(error.get('category', ''))).strip('/'))
        lines.append(f"| {row['task_id']} | {row['outcome']} | {failures[0]} | {failures[1]} |")
    lines.extend(['', summary['limitations'], ''])
    return '\n'.join(lines)
