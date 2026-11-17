"""Truthful instance-independent F disclosures, selected only by trusted code."""
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('family disclosure template drift')
    return text.replace(old, new)


def family_text(family):
    base = (Path(__file__).resolve().parents[1] / 'assets/FAMILY.md').read_text()
    if family == 'B':
        return base
    if family == 'S':
        return replace_once(base, '10 of size 4 by 4, 10 of size 4 by 6, 10 of size 4 by 8',
                            '30 of size 4 by 6')
    if family != 'C':
        raise ValueError('unknown family')
    base = replace_once(base, '`z_j = int((2*x_(720+j)-1) + sum_g alpha_jg*q_g > 0)`.',
                        '`z_j = int((2*x_(720+j)-1) + sum_g alpha_jg*q_g + sum_b beta_jb*c_b > 0)`.')
    base = replace_once(base, 'Every output receives 6 distinct materials; every material reaches\n4 distinct outputs.',
                        'In the direct alpha/q contribution, every output receives 6 distinct\nmaterials and every material reaches 4 distinct outputs. Bridges add further\nphysical influence beyond this direct incidence.')
    return base + '''
## Inter-material interface law

For each horizontal edge e=(u,u+1) on material g, with periodic columns, define
`A_g,e = r_0,u*r_0,u+1 + r_2,u*r_2,u+1` and
`B_g,e = r_1,u*r_1,u+1 + r_3,u*r_3,u+1`.
These definitions also give `q_g = sum_e A_g,e*B_g,e`.
Independently for each material, one fixed unknown fair selector chooses either
A or B; write the selected factor as S_g,e. A uniform random permutation of the
30 materials gives an undirected cycle, including its last-to-first edge.
For each of its 30 bridges b=(g,h), select one horizontal edge e on g and one
horizontal edge f on h independently and uniformly. Its contribution is
`c_b = S_g,e*S_h,f`. These are instantaneous interactions; there is no memory.

Each bridge reaches two distinct outputs; each output receives three bridges.
Start with edges (b,(2*b+t)%20) for b=0,...,29 and t=0,1. Perform exactly 20000
uniform ordered-pair edge-switch proposals with the same equal-endpoint and
duplicate-cross-edge rejection rule as above, then independent uniform bridge
and output label permutations. No success filtering or exact-uniform graph
sampling claim is made. Each occupied beta coefficient is independently uniform
in {-2,-1,1,2}. The cycle, selectors, interface edges and beta realization are
unknown. All structure is fixed across research and the manufactured copies.
'''
