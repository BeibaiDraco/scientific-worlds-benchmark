"""Catch soft supervisor interruption; hard kills remain incomplete claims."""
from contextlib import contextmanager
from functools import wraps
import signal
ACTIVE=False


@contextmanager
def guard():
    global ACTIVE
    if ACTIVE:
        yield
        return
    ACTIVE=True
    previous={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT)}
    def stop(number,frame):
        # Let the first handler reach durable failure/unknown-accounting output.
        # The scheduler's eventual SIGKILL still cannot be intercepted.
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        raise InterruptedError('supervisor_signal_'+str(number))
    for number in previous:signal.signal(number,stop)
    try:yield
    finally:
        ACTIVE=False
        for number,handler in previous.items():signal.signal(number,handler)


def guarded(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with guard():return function(*args,**kwargs)
    return wrapped
