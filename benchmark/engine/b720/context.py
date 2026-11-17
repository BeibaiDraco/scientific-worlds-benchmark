"""Deterministic bounded view; all earlier interactions remain in read-only files."""
import json
import os
import stat
from .resources import CONTRACT


def safe_notes(work):
    path = work / 'NOTES.md'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {'status': 'absent', 'text': '', 'truncated': False}
    except OSError:
        return {'status': 'unreadable_or_unsafe', 'text': '', 'truncated': False}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return {'status': 'unreadable_or_unsafe', 'text': '', 'truncated': False}
        data = os.read(fd, CONTRACT['notes_bytes'] + 1)
        text = data[:CONTRACT['notes_bytes']].decode('utf-8', errors='ignore')
        truncated = len(data) > CONTRACT['notes_bytes']
        # JSON escaping can expand control characters sixfold. Bound the actual
        # serialized prompt contribution as well as the underlying file read.
        if len(json.dumps(text, ensure_ascii=False).encode()) > CONTRACT['notes_bytes']:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(json.dumps(text[:mid], ensure_ascii=False).encode()) <= CONTRACT['notes_bytes']:
                    lo = mid
                else:
                    hi = mid - 1
            text, truncated = text[:lo], True
        return {'status': 'ok', 'text': text, 'truncated': truncated}
    finally:
        os.close(fd)


def history_view(history):
    # A textual suffix has an exact byte bound even for a single oversized turn.
    # It need not be valid JSON; the cut is explicit and complete JSON files remain available.
    full = json.dumps(history, ensure_ascii=False)
    raw = full.encode('utf-8')
    tail = raw[-CONTRACT['history_bytes']:].decode('utf-8', errors='ignore')
    return {'earlier_bytes_omitted': len(raw) - len(tail.encode('utf-8')), 'text': tail}


def prefix(initial, history, notes):
    view = history_view(history)
    return (initial + '\n\nParticipant-authored NOTES.md (JSON envelope):\n'
            + json.dumps(notes, ensure_ascii=False)
            + '\nPrior visible interaction, recent suffix (earlier UTF-8 bytes omitted: '
            + str(view['earlier_bytes_omitted']) + '):\n' + view['text']
            + '\nCurrent resources before this turn:\n')


SUFFIX = '\nReturn your next Python block or FINISH.'


def build(initial, history, notes, budget):
    prompt = prefix(initial, history, notes) + json.dumps(budget) + SUFFIX
    if len(prompt.encode('utf-8')) > CONTRACT['prompt_bytes']:
        raise ValueError('bounded prompt exceeded qualified capacity')
    return prompt
