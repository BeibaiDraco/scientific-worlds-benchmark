"""Expand physical interactions into signed quartics for exact bit-plane physics."""


def term(mode, indices):
    sign = 1
    ports = []
    for index in indices:
        sign *= mode['polarities'][index]
        ports.append(mode['ports'][index])
    return tuple(ports), sign


def components(material):
    result = []
    for mode in material['modes']:
        h, w = mode['height'], mode['width']
        terms = []
        for a in range(h):
            for b in range(w):
                terms.append(term(mode, [a*w+b, a*w+(b+1)%w,
                                        ((a+1)%h)*w+b, ((a+1)%h)*w+(b+1)%w]))
        result.append(terms)
    for bridge in material.get('bridges', []):
        factors = []
        for g, edge in zip(bridge['materials'], bridge['edges']):
            mode = material['modes'][g]; w = mode['width']
            rows = (0,2) if material['selectors'][g] == 'A' else (1,3)
            factors.append([term(mode, [a*w+edge, a*w+(edge+1)%w]) for a in rows])
        result.append([(p+q, s*t) for p,s in factors[0] for q,t in factors[1]])
    return result


def output_links(material, j):
    row = list(zip(material['links'][j], material['coefficients'][j]))
    offset = len(material['modes'])
    if material.get('bridges'):
        row += [(offset+b, coefficient) for b,coefficient in
                zip(material['bridge_links'][j],material['beta'][j])]
    return row
