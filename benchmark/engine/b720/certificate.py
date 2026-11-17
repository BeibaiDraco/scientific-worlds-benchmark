"""Exact parity-circuit audit for all targets/ambient inputs, no paid observations."""
from collections import defaultdict
from .monomials import components, output_links
from .circuits import validate


def accumulate(p,mask,value):
    p[mask]+=value
    if p[mask] == 0: del p[mask]


def certify(material,submitted):
    n=material['shared'];m=material['outputs'];circuit=validate(submitted,n,m)
    nodes=[(1,1<<i) for i in range(n+m)]
    for op,*args in circuit['gates']:
        if op=='const': value=(2*args[0]-1,0)
        elif op=='not':
            sign,mask=nodes[args[0]];value=(-sign,mask)
        elif op=='xor':
            a,x=nodes[args[0]];b,y=nodes[args[1]];value=(-a*b,x^y)
        else: return {'supported':False,'unsupported_gate':op}
        nodes.append(value)
    configuration=nodes[:n]+[nodes[i] for i in circuit['handles']]
    for port,node in circuit['drives']: configuration[port]=nodes[node]
    quantities=[]
    for terms in components(material):
        p=defaultdict(int)
        for ports,polarity in terms:
            sign,mask=polarity,0
            for port in ports:
                s,t=configuration[port];sign*=s;mask^=t
            accumulate(p,mask,sign)
        quantities.append(p)
    margins=[]
    for j in range(m):
        p=defaultdict(int)
        sign,mask=configuration[n+j];accumulate(p,mask,sign)
        for g,a in output_links(material,j):
            for mask,coefficient in quantities[g].items(): accumulate(p,mask,a*coefficient)
        desired={mask^(1<<(n+j)):coefficient for mask,coefficient in p.items()}
        margins.append(desired.get(0,0)-sum(abs(v) for k,v in desired.items() if k))
    return {'supported':True,'all_component_polynomials_zero':all(not q for q in quantities),
            'universal_target_margin_lower_bounds':margins,
            'all_targets_all_ambient_certified':min(margins)>0}
