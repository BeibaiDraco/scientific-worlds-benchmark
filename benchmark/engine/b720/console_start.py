import json
import os
import sys
sys.path.insert(0, os.environ['SCIPY_DIR'])
sys.path.insert(0, os.getcwd())
import numpy as np
_reader = os.fdopen(int(os.environ['LAB_READ']), 'r')
_writer = os.fdopen(int(os.environ['LAB_WRITE']), 'w')


def _native(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def act(request, **fields):
    if isinstance(request, str):
        request = dict(op=request, **fields)
    _writer.write(json.dumps(request, default=_native, allow_nan=False) + '\n')
    _writer.flush()
    response = json.loads(_reader.readline())
    if 'error' in response:
        raise ValueError(response['error'])
    return response['value']


exec(compile(sys.stdin.read(), '<console>', 'exec'))
