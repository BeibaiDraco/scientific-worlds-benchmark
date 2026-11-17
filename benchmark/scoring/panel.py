"""Pure panel/schedule planning. No world sampling, processes, or provider calls."""
from hashlib import sha256
import itertools
import json
import random

VERSION = 'B720-neural-release-v1'
ARMS = ('N0', 'M', 'F')
FAMILIES = ('S', 'B', 'C')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def opaque(kind, *values):
    return kind + '_' + digest([VERSION, kind, *values])[:20]


def build_panel(stage, model_id='astra_max'):
    if stage not in ('pilot', 'formal') or not isinstance(model_id, str) or not model_id:
        raise ValueError('invalid stage/model')
    per_family = 1 if stage == 'pilot' else 5
    tasks = []
    for family in FAMILIES:
        for index in range(per_family):
            task = {'task_id': opaque('t', stage, family, index), 'family': family,
                    'replicate': index + 1, 'packet_sha256': None,
                    'binding_status': 'unsampled', 'episode_conditions': list(ARMS)}
            tasks.append(task)
    episodes = [{'episode_id': opaque('e', stage, model_id, t['task_id'], arm),
                 'task_id': t['task_id'], 'model_id': model_id, 'condition': arm,
                 'attempt': 1} for t in tasks for arm in ARMS]
    return {'version': VERSION, 'stage': stage, 'model_id': model_id,
            'prompt_version': 'synthetic-neural-v1', 'tasks': tasks, 'episodes': episodes,
            'tasks_per_family': per_family, 'planned_per_condition': 3 * per_family,
            'main_condition': 'N0', 'official_score_eligible': stage == 'formal',
            'task_sampling': 'one matched sibling block' if stage == 'pilot' else 'independent master seed per task across families',
            'master_seed_relationship': 'all three tasks share compatible base streams' if stage == 'pilot' else '15 distinct independent masters',
            'scientific_seeds_sampled': False, 'automatic_followup': False,
            'one_attempt_only': True, 'world_binding_required_before_launch': True}


def validate_panel(panel):
    expected = build_panel(panel['stage'], panel['model_id'])
    for key in ('version', 'prompt_version', 'planned_per_condition', 'main_condition',
                'official_score_eligible', 'tasks_per_family', 'episodes'):
        if panel.get(key) != expected[key]:
            raise ValueError('panel contract differs: ' + key)
    if len(panel['tasks']) != len(expected['tasks']):
        raise ValueError('wrong task count')
    for actual, wanted in zip(panel['tasks'], expected['tasks']):
        for key in ('task_id', 'family', 'replicate', 'episode_conditions'):
            if actual.get(key) != wanted[key]:
                raise ValueError('task specification differs')
    return True


def schedule(panel, slots, schedule_seed=20261110):
    """Fixed waves, no refill after a result; 2-slot Latin arm ordering is balanced."""
    validate_panel(panel)
    if slots not in (2, 3, 6) or type(schedule_seed) is not int:
        raise ValueError('supported slots are 2, 3, 6; integer schedule seed required')
    rng = random.Random(schedule_seed)
    # Interleave independently shuffled family lists, then rotate the arm order.
    family_order = list(FAMILIES); rng.shuffle(family_order)
    by_family = {f: [t for t in panel['tasks'] if t['family'] == f] for f in FAMILIES}
    for values in by_family.values():
        rng.shuffle(values)
    ordered = [by_family[f][i] for i in range(panel['tasks_per_family']) for f in family_order]
    arms = list(ARMS); rng.shuffle(arms)
    lookup = {(e['task_id'], e['condition']): e['episode_id'] for e in panel['episodes']}
    flat = []
    for i, task in enumerate(ordered):
        # Rotate across both family position and replicate: a family must not
        # give one condition the same slot throughout its five formal tasks.
        rotation = (i % 3 + i // 3) % 3
        order = arms[rotation:] + arms[:rotation]
        flat.extend(lookup[(task['task_id'], arm)] for arm in order)
    waves = [{'wave': i // slots + 1,
              'slots': [{'slot': j + 1, 'episode_id': episode} for j, episode in enumerate(flat[i:i + slots])]} for i in range(0, len(flat), slots)]
    return {'version': VERSION, 'panel_sha256': digest(panel), 'slots': slots,
            'schedule_seed': schedule_seed, 'schedule_seed_is_not_a_world_seed': True,
            'policy': 'fixed waves; all members finish/audit before next wave; stop scheduling on operational fault',
            'refill_policy': 'none', 'waves': waves, 'wave_count': len(waves),
            'maximum_active_hours_excluding_overhead': len(waves) * 12,
            'nominal_generated_allowance': len(flat) * 1200000,
            'native_concurrency_qualified': False, 'queue_created': False}


def pilot_decision(panel, summary):
    if panel['stage'] != 'pilot' or summary['stage'] != 'pilot':
        raise ValueError('pilot required')
    complete = all(summary['conditions'][a]['complete'] for a in ARMS)
    return {'pilot_audits_complete': complete, 'automatic_formal_launch': False,
            'decision': 'review_required' if complete else 'await_all_valid_audits',
            'no_score_pattern_is_automatic_launch_approval': True,
            'required_review': ['paid acquisition and actual routes', 'primary-score floor/ceiling',
                                'retain all legal successes', 'freeze final family distribution before independent formal sampling']}
