"""Condition differences are explicit, minimal and instance-independent."""
from pathlib import Path
from .resources import CONTRACT, WALL_SECONDS, CPU_LIMIT, TOKEN_LIMIT, TURNS
from .neural import INTRO, family_prior

ARMS = ('N0', 'F', 'M')
PRIOR_FILES = {'N0': (), 'F': ('FAMILY.md',), 'M': ('MICRO_PRIOR.en.md',)}
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
LAWS = Path(__file__).with_name('laws.txt')
HEADER = f'''Operate the persistent campaign through a Python console with NumPy and SciPy. Read the public manual and files in the current directory. Return one fenced Python block, or FINISH to end your attempt. Each block starts a new interpreter with act and np provided; files persist. Pass act explicitly into imported code. Many physical actions may run in one block. Every legal solver and control representation is accepted.
Budgets: {CPU_LIMIT} single-core worker CPU seconds, {TOKEN_LIMIT} known returned generated tokens, {TURNS} model turns, {WALL_SECONDS} active wall seconds, and the separately charged physical capital in the manual. Total wall time includes model/transport waits, execution and referee qualification. A physical action accepted before the deadline is allowed to finish qualification. Token usage is checked at call boundaries; if a returned call exceeds the remaining token budget its program is not executed. A pending call cut off by the deadline can have unknown usage. Failed returned calls count.
Each worker is sampled every 50 ms and stopped above 2 GiB RSS. Each file has a 2 GiB limit. One worker process; no child processes, network or software installation. A block has wall allowance remaining worker CPU plus 90 seconds, bounded by remaining campaign wall time. Action messages must fit in 8 MiB. The last 12000 bytes of block output are visible; full output is retained for auditing. Saved files and campaign persist after a memory stop. Each action reply includes research_budget, and each turn starts with current remaining resources. World validity and scientific delivery alone determine success; no particular grouping or theory report is required.
Memory: each turn receives the most recent {CONTRACT['history_bytes']} UTF-8 bytes of visible interaction and your own NOTES.md, if present (up to {CONTRACT['notes_bytes']} bytes, possibly less after JSON escaping). Earlier interaction is not automatically summarized. Complete interaction records are readable in the directory os.environ['CAMPAIGN_HISTORY'], as turn_000001.json etc. That directory is read-only; your own working files persist. Keep any notes you want to carry forward in NOTES.md. Unsafe links or non-regular notes files are not read. The prompt explicitly marks omitted history and truncated notes.'''


def initial(packet, arm):
    if arm not in ARMS:
        raise ValueError('unknown condition')
    text = INTRO + '\n\n' + HEADER + '\n\n' + (ASSETS / 'RULES.md').read_text()
    for name, content in disclosures(packet, arm).items():
        text += '\n\n' + content.decode('utf-8')
    return text


def disclosures(packet, arm):
    if arm not in ARMS: raise ValueError('unknown condition')
    result = {}
    for name in PRIOR_FILES[arm]:
        if name == 'FAMILY.md':
            result[name] = family_prior((Path(packet)/'priors'/name).read_text()).encode()
        else:
            result[name] = (ASSETS/name).read_bytes()
    return result
