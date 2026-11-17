"""Strict fixed-denominator aggregation of independently audited episode records."""
import csv
import hashlib
import json
import math
from pathlib import Path
from panel import ARMS, FAMILIES, VERSION, validate_panel, digest

VALID_STATES = ('valid', 'unresolved')
TIMEOUT_REASON = 'no_delivery_at_campaign_deadline_pending_bill_unknown'


def valid_sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def validate_record(row, expected):
    for key in ('episode_id', 'task_id', 'model_id', 'condition', 'attempt'):
        if row.get(key) != expected[key]:
            raise ValueError('episode identity mismatch: ' + key)
    if row.get('state') not in VALID_STATES:
        raise ValueError('record state must be valid or unresolved; absence means unstarted')
    if not isinstance(row.get('reason'), str) or not row['reason']:
        raise ValueError('reason required')
    if row['state'] == 'unresolved':
        if row.get('score') is not None:
            raise ValueError('operationally unresolved episode cannot carry a scientific score')
    else:
        if type(row.get('score')) is not int or row['score'] not in (0, 1):
            raise ValueError('valid primary score must be integer 0 or 1')
        if type(row.get('token_usage_complete')) is not bool:
            raise ValueError('explicit usage completeness required')
        if not row['token_usage_complete'] and not (row['score'] == 0 and row['reason'] == TIMEOUT_REASON):
            raise ValueError('unknown usage only supports the declared elapsed-time zero')
        if row['reason'] not in ('complete_budgeted_episode', TIMEOUT_REASON):
            raise ValueError('operational or unqualified adjudication cannot be a valid result')
        allowed = {'survived','dead','stopped_without_delivery','wall_cap','turn_cap','research_cap','worker_timeout'}
        if row.get('raw_status') not in allowed or (row['score']==1) != (row['raw_status']=='survived'):
            raise ValueError('terminal status and score disagree')
        if row['reason']==TIMEOUT_REASON and row['raw_status']!='wall_cap':
            raise ValueError('pending-call policy requires the campaign deadline')
    if not valid_sha(row.get('audit_sha256')):
        raise ValueError('bound independent audit hash required')


def import_audit(panel, episode_id, audit_path):
    """Consume the future host auditor's bound receipt, never a model-written score.

    The native auditor must first verify physical replay, source, prompt, usage
    and identity. This checks its panel/task envelope rather than re-running it.
    """
    validate_panel(panel)
    episode=next((e for e in panel['episodes'] if e['episode_id']==episode_id),None)
    if episode is None:raise ValueError('unknown episode')
    task=next(t for t in panel['tasks'] if t['task_id']==episode['task_id'])
    if panel.get('engineering_only') or panel.get('scientific_seeds_sampled') is not True or task.get('binding_status')!='bound':
        raise ValueError('independent scientific packet binding required')
    expected_prompt=task.get('initial_prompts',{}).get(episode['condition'])
    if not all(valid_sha(value) for value in (task.get('packet_sha256'),expected_prompt,panel.get('source_release_sha256'))):
        raise ValueError('complete 64-hex packet/prompt/source bindings required')
    data=Path(audit_path).read_bytes();audit=json.loads(data);binding=audit['binding']
    for key,want in {'episode_id':episode_id,'panel_sha256':digest(panel),
                     'packet_sha256':task['packet_sha256'],'prompt_version':panel['prompt_version']}.items():
        if binding.get(key)!=want:raise ValueError('audit binding mismatch: '+key)
    if binding.get('prompt_sha256') != expected_prompt:
        raise ValueError('audit prompt mismatch')
    if not panel.get('source_release_sha256') or binding.get('source_release_sha256')!=panel['source_release_sha256']:
        raise ValueError('audit source release mismatch')
    score=audit.get('primary_score');reason=audit.get('protocol_adjudication')
    row={**episode,'state':'unresolved' if score is None else 'valid','score':score,
         'reason':reason,'raw_status':audit.get('raw_runner_status'),
         'token_usage_complete':audit.get('token_usage_complete'),
         'audit_sha256':hashlib.sha256(data).hexdigest(),
         'audit_path':str(Path(audit_path).resolve()),'audit_binding':binding}
    validate_record(row,episode)
    if score is not None and audit.get('physical_replay_verified') is not True:
        raise ValueError('valid result lacks independently verified physical replay')
    return row


def exact_binomial_interval(wins, total, alpha=.05):
    """Clopper-Pearson by binomial-tail bisection; standard library only."""
    if not 0 <= wins <= total or total <= 0 or not 0 < alpha < 1:
        raise ValueError('invalid binomial parameters')
    def upper_tail(p, k):
        return sum(math.comb(total, i) * p**i * (1-p)**(total-i) for i in range(k, total+1))
    def solve(k, target):
        lo, hi = 0., 1.
        for _ in range(80):
            mid = (lo+hi)/2
            if upper_tail(mid, k) < target: lo = mid
            else: hi = mid
        return (lo+hi)/2
    return [0. if wins == 0 else solve(wins, alpha/2),
            1. if wins == total else solve(wins+1, 1-alpha/2)]


def _cell(episodes, records):
    n = len(episodes); valid = []; unresolved = unstarted = 0
    for e in episodes:
        row = records.get(e['episode_id'])
        if row is None: unstarted += 1
        elif row['state'] == 'unresolved': unresolved += 1
        else: valid.append(row)
    wins = sum(r['score'] for r in valid); failures = len(valid)-wins
    unknown = sum(not r['token_usage_complete'] for r in valid)
    complete = len(valid) == n
    return {'planned': n, 'valid': len(valid), 'wins': wins, 'failures': failures,
            'unresolved': unresolved, 'unstarted': unstarted, 'complete': complete,
            'score_100': 100*wins/n if complete else None,
            'completion_range_100': [100*wins/n, 100*(wins+unresolved+unstarted)/n],
            'valid_unknown_usage_deadline_zeros': unknown,
            'fully_metered_sensitivity_range_100': [100*wins/n, 100*(wins+unresolved+unstarted+unknown)/n],
            'completion_range_is_confidence_interval': False}


def aggregate(panel, input_records, *, data_kind='audited'):
    validate_panel(panel)
    if data_kind not in ('audited', 'synthetic_fixture'):
        raise ValueError('invalid data provenance')
    if input_records and data_kind == 'audited':
        if panel.get('engineering_only') or panel.get('scientific_seeds_sampled') is not True:
            raise ValueError('development fixtures and unsampled plans cannot supply official results')
        for task in panel['tasks']:
            if task.get('binding_status') != 'bound' or not valid_sha(task.get('packet_sha256')):
                raise ValueError('real results require a prospectively bound task panel')
    expected = {e['episode_id']: e for e in panel['episodes']}
    records = {}
    for row in input_records:
        key = row.get('episode_id')
        if key not in expected or key in records:
            raise ValueError('unknown or duplicate episode; retries/best-of-N forbidden')
        validate_record(row, expected[key])
        if data_kind == 'audited':
            if not row.get('audit_path') or not isinstance(row.get('audit_binding'),dict):
                raise ValueError('official aggregation requires retained bound audit evidence')
            verified=import_audit(panel,key,row['audit_path'])
            if any(row.get(field)!=value for field,value in verified.items()):
                raise ValueError('normalized row or retained audit changed after import')
        records[key] = row
    tasks = {t['task_id']: t for t in panel['tasks']}
    conditions = {}
    for arm in ARMS:
        selected = [e for e in panel['episodes'] if e['condition'] == arm]
        cell = _cell(selected, records)
        cell['families'] = {}
        for family in FAMILIES:
            members = [e for e in selected if tasks[e['task_id']]['family'] == family]
            group = _cell(members, records)
            group['binomial_95_interval'] = exact_binomial_interval(group['wins'], group['planned']) if group['complete'] and panel['stage'] == 'formal' else None
            cell['families'][family] = group
        if cell['complete'] and panel['stage'] == 'formal':
            simultaneous = [exact_binomial_interval(g['wins'], g['planned'], .05/3) for g in cell['families'].values()]
            cell['equal_family_conservative_95_interval_100'] = [100*sum(x[j] for x in simultaneous)/3 for j in (0,1)]
        else:
            cell['equal_family_conservative_95_interval_100'] = None
        conditions[arm] = cell
    paired = {}
    lookup = {(e['task_id'], e['condition']): records.get(e['episode_id']) for e in panel['episodes']}
    for assisted in ('M', 'F'):
        counts = {'both_win': 0, 'both_fail': 0, 'N0_only': 0, 'assisted_only': 0, 'unavailable': 0}
        for task in tasks:
            left, right = lookup[(task,'N0')], lookup[(task,assisted)]
            if left is None or right is None or left['state'] != 'valid' or right['state'] != 'valid':
                counts['unavailable'] += 1
            else:
                counts[{(1,1):'both_win',(0,0):'both_fail',(1,0):'N0_only',(0,1):'assisted_only'}[(left['score'],right['score'])]] += 1
        paired['N0_vs_'+assisted] = counts
    return {'version': VERSION, 'panel_sha256': digest(panel), 'stage': panel['stage'],
            'model_id': panel['model_id'], 'main_condition': 'N0',
            'data_kind': data_kind,
            'official_score_eligible': data_kind=='audited' and panel['stage']=='formal' and conditions['N0']['complete'],
            'main_score_100': conditions['N0']['score_100'] if panel['stage']=='formal' else None,
            'conditions': conditions, 'paired': paired,
            'independent_world_claim': 'within-family independent formal tasks' if panel['stage']=='formal' else 'matched pilot siblings; no population interval',
            'assisted_scores_never_combined_with_main': True}


def export(panel, records, directory, *, data_kind='audited'):
    summary = aggregate(panel, records, data_kind=data_kind)
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    (directory/'scores.json').write_text(json.dumps(summary,indent=2)+'\n')
    lookup = {r['episode_id']:r for r in records}; tasks={t['task_id']:t for t in panel['tasks']}
    with (directory/'episodes.csv').open('w',newline='') as stream:
        fields=['episode_id','task_id','family','condition','model_id','attempt','state','score','token_usage_complete','reason','raw_status','audit_sha256']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for e in panel['episodes']:
            r=lookup.get(e['episode_id'],{}); writer.writerow({**e,'family':tasks[e['task_id']]['family'],
                **{k:r.get(k,'unstarted' if k=='state' else '') for k in fields if k not in e and k!='family'}})
    return summary
