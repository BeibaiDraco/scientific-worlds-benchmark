"""Objective terminal functionality and cost; no subjective theory judging."""
import json
from pathlib import Path
import random
import time

from .circuits import evaluate
from .parallel import response
from .world import World, FRAMES, bits


def terminal_scores(world, *, status, seconds=None, cpu_s=None, generated=None,
                    operational=False):
    before = world.state()
    started = time.process_time()
    mask=(1 << FRAMES)-1
    valid=[]
    for circuit,target,seed in zip(world.installed,world.targets,world.environments):
        if circuit is None:
            valid.append(False)
            continue
        rng=random.Random(seed)
        ambient=[rng.getrandbits(FRAMES) for _ in range(world.spec['shared'])]
        target_bits=bits(target,world.spec['outputs'])
        x=evaluate(circuit,ambient,target_bits,mask)
        actual=response(world.material,x,mask)
        valid.append(all(value==(mask if bit else 0) for value,bit in zip(actual,target_bits)))
    if world.state() != before:
        raise RuntimeError('diagnostic scoring changed the campaign ledger')
    survived=world.phase=='survived' and status=='survived' and not operational
    research=world.readings_a+4*world.readings_b
    reserve=world.cash-FRAMES if survived else None
    return dict(delivery_score=None if operational else int(survived),
                valid_installed_devices=sum(valid),device_flags=valid,
                functionality_score_100=100*sum(valid)/8,
                functionality_is_diagnostic_only=True,
                physical_research_spend=research,physical_manufacturing_spend=world.manufacturing_spend,
                physical_investment=research+world.manufacturing_spend,
                startup_reserve=reserve,startup_reserve_fraction=reserve/world.spec['capital'] if survived else None,
                active_wall_seconds=seconds,worker_cpu_seconds=cpu_s,known_generated_tokens=generated,
                diagnostic_referee_cpu_seconds=time.process_time()-started,
                status=status,operationally_affected=operational)


def score_episode(packet,run):
    run=Path(run);world=World(packet)
    trace=run/'physical.jsonl'
    if trace.exists():
        for line in trace.read_text().splitlines():
            row=json.loads(line)
            if world.act(row['request']) != row['result']:
                raise ValueError('physical trace does not replay')
    result=json.loads((run/'result.json').read_text())
    operational=result['status'] in {'provider_error','provider_timeout','unparseable_provider_result',
                                     'out_of_band_tool','unverified_usage','unexpected_model_identity','harness_error','archive_error'}
    return terminal_scores(world,status=result['status'],seconds=result['seconds'],
              cpu_s=result['ledger']['cpu_s'],generated=result['ledger']['generated_tokens'],operational=operational)
