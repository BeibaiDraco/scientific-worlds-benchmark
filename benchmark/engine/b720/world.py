"""Versioned S/B/C physics and unchanged paid action ledger.

Engineering packets use named streams; these seeds are not legacy seed aliases.
Native participant evaluation is held separately pending Voltron qualification.
"""
from copy import deepcopy
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

from .circuits import evaluate, price, validate
from .parallel import response as parallel_response
from .family import family_text

BANKS = 8
FRAMES = 100000
SWITCH_PROPOSALS = 20000
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
STREAMS = ('ports', 'polarities', 'mode_order', 'base_incidence', 'base_coefficients',
           'selectors', 'cycle', 'endpoints', 'bridge_incidence', 'bridge_coefficients',
           'targets', 'environments')


def get_spec(grade):
    if grade == 'B720':
        grade = 'B'
    if grade not in ('S', 'B', 'C'):
        raise ValueError('family must be S, B or C')
    shapes = [[4, 6]] * 30 if grade == 'S' else [[4, w] for w in (4, 6, 8) for _ in range(10)]
    return dict(grade=grade, shared=720, outputs=20, width=740, capital=5200,
                shapes=shapes, materials=30, row_degree=6, material_degree=4)


def public_task(spec):
    # The exact same operating document is visible in every family/arm.
    return json.loads((ASSETS / 'task.json').read_text())


def stream_seed(master, name):
    if type(master) is not int or name not in STREAMS:
        raise ValueError('invalid explicit seed or named stream')
    return int.from_bytes(hashlib.sha256(f'b720-structural-v1:{master}:{name}'.encode()).digest(), 'big')


def incidence(rng, sources, outputs, degree):
    if sources * degree % outputs:
        raise ValueError('nonintegral output degree')
    edges = [(g, (degree*g+t) % outputs) for g in range(sources) for t in range(degree)]
    occupied = set(edges)
    accepted = 0
    for _ in range(SWITCH_PROPOSALS):
        first, second = rng.sample(range(len(edges)), 2)
        g, j = edges[first]
        h, k = edges[second]
        if g == h or j == k or (g, k) in occupied or (h, j) in occupied:
            continue
        occupied.remove((g, j)); occupied.remove((h, k))
        edges[first], edges[second] = (g, k), (h, j)
        occupied.update((edges[first], edges[second])); accepted += 1
    source_labels, output_labels = list(range(sources)), list(range(outputs))
    rng.shuffle(source_labels); rng.shuffle(output_labels)
    links = [[] for _ in range(outputs)]
    for g, j in edges:
        links[output_labels[j]].append(source_labels[g])
    return links, dict(method='finite_edge_switch', proposals=SWITCH_PROPOSALS,
                       accepted=accepted, rejected=SWITCH_PROPOSALS-accepted,
                       source_labels=source_labels, output_labels=output_labels,
                       exact_uniform_claim=False)


def make_material(seed, grade):
    spec = get_spec(grade)
    rng = {key: random.Random(stream_seed(seed, key)) for key in STREAMS}
    ports = list(range(720)); rng['ports'].shuffle(ports)
    signs = [rng['polarities'].choice((-1, 1)) for _ in ports]
    modes, cursor = [], 0
    for height, width in spec['shapes']:
        members = ports[cursor:cursor+height*width]; cursor += height*width
        modes.append(dict(height=height, width=width, ports=members,
                          polarities=[signs[p] for p in members]))
    rng['mode_order'].shuffle(modes)
    links, sampling = incidence(rng['base_incidence'], 30, 20, 4)
    coefficients = [[rng['base_coefficients'].choice((-2,-1,1,2)) for _ in row] for row in links]
    result = dict(grade=spec['grade'], shared=720, outputs=20, modes=modes, links=links,
                  coefficients=coefficients, sampling=sampling, qualification_attempts={'incidence':1})
    if spec['grade'] == 'C':
        selectors = [rng['selectors'].choice(('A','B')) for _ in modes]
        cycle = list(range(30)); rng['cycle'].shuffle(cycle)
        bridges = []
        for i, g in enumerate(cycle):
            h = cycle[(i+1) % 30]
            bridges.append(dict(materials=[g,h], edges=[rng['endpoints'].randrange(modes[g]['width']),
                                                       rng['endpoints'].randrange(modes[h]['width'])]))
        bridge_links, bridge_sampling = incidence(rng['bridge_incidence'], 30, 20, 2)
        beta = [[rng['bridge_coefficients'].choice((-2,-1,1,2)) for _ in row] for row in bridge_links]
        result.update(selectors=selectors, cycle=cycle, bridges=bridges,
                      bridge_links=bridge_links, beta=beta, bridge_sampling=bridge_sampling)
    return result


def generation_parameters(spec):
    return dict(generator='b720-structural-v1', spec=deepcopy(spec), named_streams=list(STREAMS),
                seed_derivation='SHA256 of b720-structural-v1:decimal_master:stream_name, big endian',
                prng='Python random.Random MT19937', python_version=list(sys.version_info[:3]),
                legacy_seed_compatible=False, outcome_filtering=False,
                switch_proposals=SWITCH_PROPOSALS, banks=BANKS, frames=FRAMES)


def bits(value, width):
    return [(value >> i) & 1 for i in range(width)]


def packed(values):
    return sum(int(value) << i for i, value in enumerate(values))


def quantities(material, configuration):
    values = []
    for mode in material['modes']:
        width, height = mode['width'], mode['height']
        spins = [sign * (2 * configuration[port] - 1)
                 for port, sign in zip(mode['ports'], mode['polarities'])]
        total = 0
        for row in range(height):
            below = (row + 1) % height
            for column in range(width):
                right = (column + 1) % width
                total += (spins[row * width + column] * spins[row * width + right]
                          * spins[below * width + column] * spins[below * width + right])
        values.append(total)
    return values


def interface_factor(material, configuration, group, edge, selector):
    mode = material['modes'][group]
    width = mode['width']
    rows = (0,2) if selector == 'A' else (1,3)
    result = 0
    for row in rows:
        indices = (row*width+edge, row*width+(edge+1)%width)
        value = 1
        for i in indices:
            value *= mode['polarities'][i] * (2*configuration[mode['ports'][i]]-1)
        result += value
    return result


def bridge_quantities(material, configuration):
    values = []
    for bridge in material.get('bridges', []):
        value = 1
        for group, edge in zip(bridge['materials'], bridge['edges']):
            value *= interface_factor(material, configuration, group, edge, material['selectors'][group])
        values.append(value)
    return values


def response(material, configuration):
    q = quantities(material, configuration)
    c = bridge_quantities(material, configuration)
    outputs = []
    for j, (links, coefficients) in enumerate(zip(material['links'], material['coefficients'])):
        field = 2 * configuration[material['shared']+j] - 1
        field += sum(a*q[g] for g,a in zip(links,coefficients))
        if c:
            field += sum(beta*c[b] for b,beta in zip(material['bridge_links'][j],material['beta'][j]))
        if field % 2 != 1:
            raise ArithmeticError('physical field must be odd')
        outputs.append(int(field > 0))
    return packed(outputs)


class World:
    def __init__(self, packet):
        packet = Path(packet)
        self.material = json.loads((packet / 'judge/material.json').read_text())
        self.spec = get_spec(self.material['grade'])
        if any(self.material[key] != self.spec[key] for key in ('shared', 'outputs')):
            raise ValueError('inconsistent material dimensions')
        if json.loads((packet / 'public/task.json').read_text()) != public_task(self.spec):
            raise ValueError('inconsistent public task')
        self.targets = json.loads((packet / 'judge/targets.json').read_text())
        self.environments = json.loads((packet / 'judge/environments.json').read_text())
        if (len(self.targets) != BANKS or len(self.environments) != BANKS
                or any(type(t) is not int or not 0 <= t < 1 << self.spec['outputs'] for t in self.targets)
                or any(type(s) is not int or s < 0 for s in self.environments)):
            raise ValueError('invalid target or deployment streams')
        self.cash = self.low = self.spec['capital']
        self.phase = 'A'
        self.shots = self.readings_a = self.readings_b = self.frames = 0
        self.manufacturing_spend = 0
        self.installed = [None] * BANKS
        self.verification_cpu_s = 0.0

    def state(self):
        value = dict(phase=self.phase, capital=self.cash, minimum=self.low, shots=self.shots,
                     readings_a=self.readings_a, readings_b=self.readings_b,
                     installed=sum(circuit is not None for circuit in self.installed), frames=self.frames,
                     manufacturing_spend=self.manufacturing_spend,
                     grade=self.spec['grade'], shared=self.spec['shared'],
                     outputs=self.spec['outputs'], width=self.spec['width'])
        if self.phase != 'A':
            value['targets'] = [bits(target, self.spec['outputs']) for target in self.targets]
        return value

    def pay(self, fee):
        self.cash = max(0, self.cash - fee)
        self.low = min(self.low, self.cash)
        if self.cash == 0:
            self.phase = 'dead'
        return self.cash > 0

    def configuration(self, value):
        if not isinstance(value, list) or len(value) != self.spec['width']:
            raise ValueError(f"a configuration has {self.spec['width']} binary entries")
        if any(type(bit) not in (int, bool) or bit not in (0, 1) for bit in value):
            raise ValueError('configuration entries must be binary')
        return list(map(int, value))

    def commission(self):
        started = time.process_time()
        try:
            mask = (1 << FRAMES) - 1
            matches = []
            for circuit, target, seed in zip(self.installed, self.targets, self.environments):
                if circuit is None:
                    matches.append(False)
                    continue
                rng = random.Random(seed)
                ambient = [rng.getrandbits(FRAMES) for _ in range(self.spec['shared'])]
                target_bits = bits(target, self.spec['outputs'])
                configuration = evaluate(circuit, ambient, target_bits, mask)
                reading = parallel_response(self.material, configuration, mask)
                matches.append(all(value == (mask if bit else 0) for value, bit in zip(reading, target_bits)))
        finally:
            self.verification_cpu_s += time.process_time() - started
        if all(matches):
            self.frames = FRAMES
            self.cash += self.frames
            self.phase = 'survived'
        else:
            self.frames = self.cash
            self.cash = self.low = 0
            self.phase = 'dead'
        return dict(matches=matches, qualification_frames_per_device=FRAMES, **self.state())

    def act(self, request):
        if not isinstance(request, dict):
            raise ValueError('expected an action object')
        op = request.get('op')
        if op == 'state' and set(request) == {'op'}:
            return self.state()
        if self.phase in ('dead', 'survived'):
            raise ValueError('terminal campaign')
        if op == 'observe' and set(request) == {'op', 'x'}:
            x = self.configuration(request['x'])
            in_lab = self.phase == 'A'
            self.shots += 1
            self.readings_a += int(in_lab)
            self.readings_b += int(not in_lab)
            if self.pay(1 if in_lab else 4):
                return dict(reading=bits(response(self.material, x), self.spec['outputs']), **self.state())
            return self.state()
        if op == 'transfer' and set(request) == {'op'} and self.phase == 'A':
            self.phase = 'B'
            return self.state()
        if op == 'install' and self.phase == 'B':
            if set(request) == {'op', 'bank', 'x'}:
                x = self.configuration(request['x'])
                width, shared = self.spec['width'], self.spec['shared']
                submitted = dict(gates=[['const', 0], ['const', 1]],
                                 drives=[[port, width + x[port]] for port in range(shared)],
                                 handles=[width + bit for bit in x[shared:]])
            elif set(request) == {'op', 'bank', 'circuit'}:
                submitted = request['circuit']
            else:
                raise ValueError('invalid installation fields')
            bank = request['bank']
            if type(bank) is not int or not 0 <= bank < BANKS:
                raise ValueError('invalid bank')
            circuit = validate(submitted, self.spec['shared'], self.spec['outputs'])
            fee = price(circuit)
            self.manufacturing_spend += min(fee, self.cash)
            if self.pay(fee):
                self.installed[bank] = circuit
            return dict(installation_fee=fee, **self.state())
        if op == 'commission' and set(request) == {'op'} and self.phase == 'B':
            return self.commission()
        raise ValueError('invalid or unavailable action')


def _publish_directory(stage, destination):
    """Atomic rename without replacing even an empty competing destination.

    os.rename alone can replace an existing empty directory on POSIX. Use the
    native exclusive operation on the supported macOS/Linux judge hosts.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(stage), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1)  # NOREPLACE
    else:
        raise OSError(errno.ENOTSUP, 'exclusive directory rename requires macOS or Linux renameat2')
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def generate(destination, grade, recipe=None):
    """Explicit public engineering fixture only; no scientific sampling in this stage."""
    if (not isinstance(recipe, dict) or set(recipe) != {'master','purpose'}
            or type(recipe['master']) is not int or recipe['purpose'] != 'engineering'):
        raise ValueError('explicit engineering master seed required; scientific sampling is held')
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    spec = get_spec(grade)
    seed = recipe['master']
    material = make_material(seed, grade)
    target_rng = random.Random(stream_seed(seed,'targets'))
    environment_rng = random.Random(stream_seed(seed,'environments'))
    targets = [target_rng.getrandbits(20) for _ in range(BANKS)]
    environments = [environment_rng.getrandbits(128) for _ in range(BANKS)]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.structural-stage-',dir=destination.parent) as tmp:
        stage = Path(tmp)/'packet'
        for part in ('public','judge','priors'):
            (stage/part).mkdir(parents=True,mode=0o700)
        (stage/'public/RULES.md').write_bytes((ASSETS/'RULES.md').read_bytes())
        (stage/'public/task.json').write_bytes((ASSETS/'task.json').read_bytes())
        (stage/'priors/FAMILY.md').write_text(family_text(spec['grade']))
        documents = dict(material=material,targets=targets,environments=environments,
                         recipe=dict(**recipe,grade=spec['grade'],parameters=generation_parameters(spec)))
        for name,data in documents.items():
            (stage/'judge'/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
        _publish_directory(stage,destination)
