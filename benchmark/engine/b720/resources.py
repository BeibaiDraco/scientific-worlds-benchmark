"""One frozen resource contract, loaded independently by runner and audit."""
import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[1] / 'RESOURCE.json'
CONTRACT = json.loads(CONTRACT_PATH.read_text())
for key in ('wall_seconds', 'worker_cpu_seconds', 'generated_tokens', 'turns',
            'rss_bytes', 'file_bytes', 'history_bytes', 'notes_bytes', 'prompt_bytes'):
    if type(CONTRACT[key]) is not int or CONTRACT[key] <= 0:
        raise ValueError('invalid resource field: ' + key)
assert CONTRACT['automatic_retries'] == 0
assert CONTRACT['provider'] == 'astra' and CONTRACT['model'] == 'gpt-6-astra'
assert CONTRACT['effort'] == 'max'
WALL_SECONDS = CONTRACT['wall_seconds']
CPU_LIMIT = CONTRACT['worker_cpu_seconds']
TOKEN_LIMIT = CONTRACT['generated_tokens']
TURNS = CONTRACT['turns']


def call_key(path):
    import re
    match = re.fullmatch(r'call_(\d{6})_0\.json', Path(path).name)
    if match is None:
        raise ValueError('invalid or unqualified call filename: ' + str(path))
    return int(match.group(1))
