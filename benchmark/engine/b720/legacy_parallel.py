"""Exact, dynamically sized bit-sliced integer physics.

The ripple arithmetic follows frozen FM1, but no counter or field width is
fixed. Python integers hold independent frame planes, not floating values.
"""


def constant(value, mask, width):
    return [mask if (value >> bit) & 1 else 0 for bit in range(width)]


def add(left, right):
    if len(left) != len(right):
        raise ValueError('unequal arithmetic widths')
    result, carry = [], 0
    for first, second in zip(left, right):
        difference = first ^ second
        result.append(difference ^ carry)
        carry = (first & second) | (carry & difference)
    return result


def negate(value, mask):
    return add([mask ^ plane for plane in value], constant(1, mask, len(value)))


def multiply(value, coefficient, mask):
    # General integer shift/add also keeps the arithmetic correct beyond ±1/±2.
    result = [0] * len(value)
    magnitude, shifted = abs(coefficient), list(value)
    while magnitude:
        if magnitude & 1:
            result = add(result, shifted)
        shifted = [0] + shifted[:-1]
        magnitude >>= 1
    return negate(result, mask) if coefficient < 0 else result


def field_width(material):
    sizes = [mode['height'] * mode['width'] for mode in material['modes']]
    maximum = max([1, *sizes, *(1 + sum(abs(a) * sizes[g] for g, a in zip(row, coefficients))
                    for row, coefficients in zip(material['links'], material['coefficients']))])
    # A signed W-bit number must represent BOTH +maximum and -maximum.
    # Include 2*P, used transiently in q=P-2*count, even for unlinked modes.
    maximum = max(maximum, max((2 * size for size in sizes), default=1))
    return maximum.bit_length() + 1


def response(material, configuration, mask):
    width = field_width(material)
    quantities = []
    for mode in material['modes']:
        columns, rows = mode['width'], mode['height']
        terms = rows * columns
        negative = [mask ^ configuration[port] if sign == 1 else configuration[port]
                    for port, sign in zip(mode['ports'], mode['polarities'])]
        # Counts include the endpoint P, so powers of two need an extra bit.
        counts = [0] * terms.bit_length()
        for row in range(rows):
            below = (row + 1) % rows
            for column in range(columns):
                right = (column + 1) % columns
                carry = (negative[row * columns + column] ^ negative[row * columns + right]
                         ^ negative[below * columns + column] ^ negative[below * columns + right])
                for bit, previous in enumerate(counts):
                    counts[bit] = previous ^ carry
                    carry &= previous
                if carry:
                    raise ArithmeticError('plaquette counter overflow')
        twice_counts = [0] + counts + [0] * (width - len(counts) - 1)
        quantities.append(add(constant(terms, mask, width), negate(twice_counts, mask)))
    outputs = []
    for j, (links, coefficients) in enumerate(zip(material['links'], material['coefficients'])):
        field = add(constant(-1, mask, width),
                    [0, configuration[material['shared'] + j]] + [0] * (width - 2))
        for group, coefficient in zip(links, coefficients):
            field = add(field, multiply(quantities[group], coefficient, mask))
        # In this family q is even and the handle is ±1: zero is impossible.
        outputs.append(mask ^ field[-1])
    return outputs
