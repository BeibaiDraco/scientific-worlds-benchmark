"""Exact bit-sliced quartic physics; signed widths include every coupling term."""
from .legacy_parallel import constant, add, negate, multiply
from .monomials import components, output_links


def field_width(material):
    sizes = [len(terms) for terms in components(material)]
    bound = max([1, *(2*n for n in sizes),
                 *(1+sum(abs(a)*sizes[g] for g,a in output_links(material,j))
                   for j in range(material['outputs']))])
    return bound.bit_length()+1


def response(material, configuration, mask):
    width = field_width(material)
    values = []
    for terms in components(material):
        counts = [0] * len(terms).bit_length()
        for ports, sign in terms:
            carry = mask if sign < 0 else 0
            for port in ports:
                carry ^= configuration[port]
            for bit, previous in enumerate(counts):
                counts[bit] = previous ^ carry
                carry &= previous
            if carry:
                raise ArithmeticError('quartic counter overflow')
        twice = [0]+counts+[0]*(width-len(counts)-1)
        values.append(add(constant(len(terms),mask,width),negate(twice,mask)))
    outputs = []
    for j in range(material['outputs']):
        field = add(constant(-1,mask,width),
                    [0,configuration[material['shared']+j]]+[0]*(width-2))
        for group, coefficient in output_links(material,j):
            field = add(field,multiply(values[group],coefficient,mask))
        outputs.append(mask ^ field[-1])
    return outputs
