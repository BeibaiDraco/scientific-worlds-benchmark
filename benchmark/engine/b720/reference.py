"""Constructive upper bounds, not optimality claims or contestant requirements.

Adapted from frozen FM1 reference.py; adaptive phase follows the prior symbolic
certificate in fm1_scaling_review_2026-11-07/STATIC_SCALING.json.
"""
from copy import deepcopy

from .circuits import evaluate, validate


def assistance(material):
    pairs = []
    for mode in material['modes']:
        width = mode['width']
        for column in range(width):
            first, second = column, 2 * width + column
            relation = mode['polarities'][first] * mode['polarities'][second]
            relation *= -1 if column % 2 else 1
            pairs.append(dict(ports=sorted((mode['ports'][first], mode['ports'][second])), relation=relation))
    groups = sorted((sorted(mode['ports']) for mode in material['modes']), key=lambda group: group[0])
    return dict(objects=dict(modes=deepcopy(material['modes'])),
                pairs=dict(pairs=sorted(pairs, key=lambda pair: pair['ports'])), groups=dict(groups=groups))


def compile_circuit(data, shared, constant=False):
    if 'modes' in data:
        data = assistance(data)['pairs']
    inputs = shared + 20
    gates = [['const', 0], ['const', 1]] if constant else []
    drives = []
    for pair in data['pairs']:
        first, second = pair['ports']
        if constant:
            drives.append([first, inputs])
            drives.append([second, inputs if pair['relation'] == 1 else inputs + 1])
        elif pair['relation'] == 1:
            drives.append([second, first])
        else:
            gates.append(['not', first])
            drives.append([second, inputs + len(gates) - 1])
    return dict(gates=gates, drives=drives)


def compile_phase(data, shared):
    """Leave column zero undriven; use its ambient relative phase everywhere.

    r_2b = (-1)^b r_0b r_20 r_00. For each material this needs L-1
    drivers, one phase XOR, at most one phase NOT, and L-1 output XORs.
    Consequently D=N/4-G and K<=N/4+G for the supported family.
    """
    gates, drives = [], []
    inputs = shared + 20
    for mode in data['modes']:
        width = mode['width']
        if mode['height'] != 4 or width % 2:
            raise ValueError('phase reference requires height four and even width')
        ports, signs = mode['ports'], mode['polarities']
        gates.append(['xor', ports[0], ports[2 * width]])
        phase = inputs + len(gates) - 1
        gates.append(['not', phase])
        inverse = inputs + len(gates) - 1
        for column in range(1, width):
            offset = column % 2
            for position in (column, 2 * width + column, 0, 2 * width):
                offset ^= int(signs[position] == -1)
            gates.append(['xor', ports[column], inverse if offset else phase])
            drives.append([ports[2 * width + column], inputs + len(gates) - 1])
    return dict(gates=gates, drives=drives)


def manufacture(act, circuit):
    state = act(dict(op='state'))
    if state['phase'] == 'A':
        state = act(dict(op='transfer'))
    for bank in range(8):
        state = act(dict(op='install', bank=bank, circuit=circuit))
        if state['phase'] == 'dead':
            return state
    return act(dict(op='commission'))


def operate(act, data, shared, constant=False):
    return manufacture(act, compile_circuit(data, shared, constant))


def fully_clamped(act, data, shared):
    point = evaluate(validate(compile_circuit(data, shared), shared), [0] * shared, [0] * 20, 1)
    state = act(dict(op='state'))
    if state['phase'] == 'A':
        state = act(dict(op='transfer'))
    for bank, target in enumerate(state['targets']):
        x = point.copy()
        x[shared:] = target
        result = act(dict(op='install', bank=bank, x=x))
        if result['phase'] == 'dead':
            return result
    return act(dict(op='commission'))


def compile_interfaces(data, strategy='selected', shared=720):
    """Reference given interface-oriented signed layouts, not only local-q models."""
    modes = data['modes']
    if strategy == 'selected':
        choices = [[s] for s in data['selectors']]
    elif strategy == 'both':
        choices = [['A','B'] for _ in modes]
    elif strategy == 'cover':
        cycle = data['cycle']
        cover = min((cycle[::2],cycle[1::2]), key=lambda part:sum(modes[g]['width']-1 for g in part))
        choices = [['A','B'] if g in cover else ['A'] for g in range(len(modes))]
    elif strategy == 'base':
        choices = [['A'] for _ in modes]
    else:
        raise ValueError('unknown reference strategy')
    gates, drives = [], []
    inputs = shared+20
    for mode, selectors in zip(modes, choices):
        w = mode['width']; ports = mode['ports']; signs = mode['polarities']
        if mode['height'] != 4 or w % 2:
            raise ValueError('unsupported oriented layout')
        for selector in selectors:
            a,b = (0,2) if selector == 'A' else (1,3)
            gates.append(['xor',ports[a*w],ports[b*w]])
            phase = inputs+len(gates)-1
            gates.append(['not',phase]); inverse = inputs+len(gates)-1
            for u in range(1,w):
                offset = u % 2
                for position in (a*w+u,b*w+u,a*w,b*w):
                    offset ^= int(signs[position] == -1)
                gates.append(['xor',ports[a*w+u],inverse if offset else phase])
                drives.append([ports[b*w+u],inputs+len(gates)-1])
    return dict(gates=gates,drives=drives)
