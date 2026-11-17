"""Portable, no-model engineering entry point. Never launches formal science."""
from pathlib import Path
import argparse, hashlib, json, random, sys, tempfile, time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmark/engine'))

def verify():
    origin = json.loads((ROOT/'benchmark/ORIGIN.json').read_text())
    for row in origin['files']:
        p=ROOT/row['path']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Scientific source/prompt mismatch: '+row['path'])
    return {'passed':True,'exact_files':len(origin['files']),'scientific_contract_changed':False}

def self_test():
    verify()
    from b720.world import World, generate, response, bits, packed
    from b720.parallel import response as parallel
    from b720.reference import compile_interfaces, manufacture
    from b720.certificate import certify
    from b720.prompts import initial
    started=time.monotonic(); rows=[]
    with tempfile.TemporaryDirectory(prefix='sw-public-engineering-') as tmp:
        for family in ('S','B','C'):
            packet=Path(tmp)/family
            generate(packet,family,{'master':101,'purpose':'engineering'})
            world=World(packet); other=World(packet)
            rng=random.Random(491); configs=[[rng.randrange(2) for _ in range(740)] for _ in range(8)]
            mask=(1<<len(configs))-1
            values=parallel(world.material,[packed(x[i] for x in configs) for i in range(740)],mask)
            transcript=[]
            for i,x in enumerate(configs):
                expected=bits(response(world.material,x),20)
                assert expected==[(v>>i)&1 for v in values]
                request={'op':'observe','x':x}; answer=world.act(request)
                assert answer['reading']==expected
                transcript.append((request,answer))
            assert world.cash==5192 and other.cash==5200
            before=world.state()
            try:world.act({'op':'observe','x':[0]})
            except ValueError:pass
            else:raise AssertionError('Invalid configuration accepted')
            assert world.state()==before
            for request,answer in transcript:assert other.act(request)==answer
            for arm in ('N0','M','F'):
                actual=initial(packet,arm).encode()
                assert actual==(ROOT/f'benchmark/prompts/neural-{family}-{arm}.txt').read_bytes()
            circuit=compile_interfaces(world.material,'selected' if family=='C' else 'base')
            assert certify(world.material,circuit)['all_targets_all_ambient_certified']
            final=manufacture(world.act,circuit)
            assert final['phase']=='survived' and final['installed']==8 and final['frames']==100000
            assert final['capital']-100000==5200-8-final['manufacturing_spend']>0
            failed=World(packet);failed.act({'op':'transfer'});failure=failed.act({'op':'commission'})
            assert failure['phase']=='dead' and failure['capital']==0
            rows.append({'family':family,'public_engineering_seed':101,'scalar_vector_agreement':True,
                         'observation_cost_and_replay':True,'invalid_action_no_charge':True,
                         'fresh_world_state_independent':True,'exact_prompts':3,
                         'author_reference_devices':8,'qualification_frames':100000,
                         'manufacturing_cost':final['manufacturing_spend'],
                         'incomplete_delivery_rejected':True})
    return {'schema':'portable-core-self-test-v1','passed':True,'synthetic_fixture':True,
            'model_calls':0,'formal_score_eligible':False,'host_isolation_qualified':False,
            'scope':'Public seed101 author-supplied structure; verifies core semantics and packaging, not model discovery or production isolation.',
            'elapsed_seconds':round(time.monotonic()-started,3),'families':rows}

def write_new(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['verify','self-test']);p.add_argument('--output');a=p.parse_args()
    try:r=verify() if a.command=='verify' else self_test()
    except Exception as e:r={'passed':False,'error':f'{type(e).__name__}: {e}','model_calls':0}
    if a.output:write_new(a.output,r)
    print(json.dumps(r,indent=2));return 0 if r['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
