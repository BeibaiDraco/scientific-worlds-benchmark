"""Dimension-explicit FM1 Boolean circuits; no gate or driver count ceiling.

Adapted from frozen feedforward_manufacturing_2026-11-07/fm_circuits.py.
All indices refer to original ambient/target inputs or preceding gates.
"""

ARITY = {'const': 1, 'not': 1, 'and': 2, 'or': 2, 'xor': 2, 'mux': 3}


def node_index(value, count):
    if type(value) is not int or not 0 <= value < count:
        raise ValueError('invalid circuit node')
    return value


def validate(value, shared, outputs=20):
    if type(shared) is not int or shared <= 0 or type(outputs) is not int or outputs <= 0:
        raise ValueError('invalid circuit dimensions')
    inputs = shared + outputs
    if not isinstance(value, dict) or not {'gates', 'drives'} <= set(value) <= {'gates', 'drives', 'handles'}:
        raise ValueError('invalid circuit fields')
    if not isinstance(value['gates'], list) or not isinstance(value['drives'], list):
        raise ValueError('circuit gates and drives must be lists')
    gates = []
    for gate in value['gates']:
        if (not isinstance(gate, (list, tuple)) or not gate
                or not isinstance(gate[0], str) or gate[0] not in ARITY):
            raise ValueError('invalid gate')
        operation = gate[0]
        if len(gate) != ARITY[operation] + 1:
            raise ValueError('invalid gate arity')
        if operation == 'const':
            if type(gate[1]) not in (int, bool) or gate[1] not in (0, 1):
                raise ValueError('invalid constant')
            operands = [int(gate[1])]
        else:
            operands = [node_index(node, inputs + len(gates)) for node in gate[1:]]
        gates.append([operation, *operands])
    drives, seen = [], set()
    for drive in value['drives']:
        if not isinstance(drive, (list, tuple)) or len(drive) != 2:
            raise ValueError('invalid drive')
        port, node = drive
        if type(port) is not int or not 0 <= port < shared or port in seen:
            raise ValueError('invalid or repeated driven port')
        seen.add(port)
        drives.append([port, node_index(node, inputs + len(gates))])
    handles = value.get('handles', list(range(shared, inputs)))
    if not isinstance(handles, list) or len(handles) != outputs:
        raise ValueError(f'{outputs} handle outputs are required')
    handles = [node_index(node, inputs + len(gates)) for node in handles]
    return dict(gates=gates, drives=drives, handles=handles)


def price(circuit):
    """Price validated hardware, including unused gates and redundant drives."""
    return 10 + len(circuit['drives']) + (len(circuit['gates']) + 7) // 8


def evaluate(circuit, ambient, target, mask):
    """Execute a validated circuit on bit planes. All drives act simultaneously."""
    nodes = list(ambient) + [mask if bit else 0 for bit in target]
    for operation, *operands in circuit['gates']:
        if operation == 'const':
            value = mask if operands[0] else 0
        elif operation == 'not':
            value = mask ^ nodes[operands[0]]
        elif operation == 'and':
            value = nodes[operands[0]] & nodes[operands[1]]
        elif operation == 'or':
            value = nodes[operands[0]] | nodes[operands[1]]
        elif operation == 'xor':
            value = nodes[operands[0]] ^ nodes[operands[1]]
        elif operation == 'mux':
            condition, yes, no = (nodes[index] for index in operands)
            value = (condition & yes) | ((mask ^ condition) & no)
        else:
            raise ValueError('unvalidated gate operation')
        nodes.append(value)
    driven = list(ambient)
    for port, node in circuit['drives']:
        driven[port] = nodes[node]
    return driven + [nodes[node] for node in circuit['handles']]
