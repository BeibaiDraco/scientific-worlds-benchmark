"""Linux console adapter over unchanged neural physics, prompts and resources.

One instance belongs to one trusted OS supervisor. There is no provider launch.
"""
import errno,hashlib,json,math,os,select,shutil,signal,socket,struct,subprocess,tempfile,time
from pathlib import Path
from binding import HERE,digest,load_release,runtime_manifest
from interrupts import guarded


class MeterError(RuntimeError):pass


def process_identity(pid):
    try:fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()
    except OSError as exc:
        if exc.errno in (errno.ENOENT,errno.ESRCH):return None
        raise
    return {'start_ticks':int(fields[19]),'ppid':int(fields[1]),'state':fields[0]}


def cleanup_namespace(process,connection,listener,peer,grace=5):
    """Close IPC, allow trusted reap, then bounded kill and identity inspection.

    wait() on the bwrap leader alone does not prove a namespace peer is gone.
    Never signal a PID after its identity may have been recycled.
    """
    row={'grace_seconds':grace,'graceful_exit_attempted':False,'forced_namespace_kill':False,
         'peer_identity':peer,'peer_observations':[],'peer_identity_gone':peer is None}
    error=None
    if peer is not None:
        try:row['peer_before_close']=process_identity(peer['pid'])
        except Exception as exc:row['peer_before_close_error']=repr(exc)
    for channel in (connection,listener):
        if channel is None:continue
        try:channel.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        channel.close()
    if process is not None and process.poll() is None:
        row['graceful_exit_attempted']=True
        try:process.wait(timeout=grace)
        except BaseException as exc:
            row['graceful_exit_error']=type(exc).__name__
            if process.poll() is None:
                row['forced_namespace_kill']=True
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            try:process.wait(timeout=grace)
            except BaseException as exc:error='namespace_leader_not_reaped:'+type(exc).__name__
    row['namespace_leader_exit_code']=process.returncode if process is not None else None
    if peer is not None:
        end=time.monotonic()+grace;previous=None
        try:
            while True:
                observed=process_identity(peer['pid'])
                if observed!=previous or not row['peer_observations']:
                    if len(row['peer_observations'])<20:row['peer_observations'].append(observed)
                    previous=observed
                if observed is None or observed['start_ticks']!=peer['start_ticks']:
                    row['peer_identity_gone']=True;break
                if time.monotonic()>=end:
                    error=error or 'namespace_peer_identity_remaining';break
                time.sleep(.05)
        except BaseException as exc:error=error or 'namespace_peer_inspection_failed:'+type(exc).__name__
    return error,row


def accept_meter(listener,process,deadline):
    listener.setblocking(False)
    while time.monotonic()<deadline:
        if select.select([listener],[],[],.1)[0]:return listener.accept()[0]
        if process.poll() is not None:raise MeterError('meter_process_exited_before_connect')
    raise MeterError('campaign_deadline_before_meter_connect')


def send_frame(connection,body,deadline,process):
    connection.setblocking(False);view=memoryview(body)
    while view:
        if time.monotonic()>=deadline:raise MeterError('meter_send_deadline')
        if not select.select([],[connection],[],.1)[1]:
            if process.poll() is not None:raise MeterError('meter_process_exited_before_send')
            continue
        try:sent=connection.send(view)
        except BlockingIOError:continue
        if not sent:raise MeterError('meter_send_closed')
        view=view[sent:]


def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def append(path, value):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n')
        stream.flush();os.fsync(stream.fileno())


def descendant(pid, ancestor):
    seen=set()
    while pid>1 and pid not in seen:
        if pid==ancestor:return True
        seen.add(pid)
        try:pid=int(Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):return False
    return False


class Frames:
    def __init__(self, channel, process):
        self.channel,self.process=channel,process
        self.buffer=b''

    def read(self, deadline):
        while b'\n' not in self.buffer:
            if time.monotonic()>deadline:raise MeterError('meter_deadline_without_terminal')
            if not select.select([self.channel],[],[],.1)[0]:
                if self.process.poll() is not None:raise MeterError('meter_process_exited')
                continue
            try:part=self.channel.recv(65536)
            except BlockingIOError:continue
            if not part:raise MeterError('missing_meter_terminal')
            self.buffer+=part
            if len(self.buffer)>17*1024**2:raise MeterError('oversize_meter_frame')
        raw,self.buffer=self.buffer.split(b'\n',1)
        def reject(value):raise MeterError('nonfinite_meter_JSON')
        return json.loads(raw,parse_constant=reject)

    def eof(self):
        if self.buffer:raise MeterError('extra_meter_frame')
        self.channel.settimeout(5)
        if self.channel.recv(1):raise MeterError('extra_meter_frame')


def validate(row, binding, event=None):
    if not isinstance(row,dict) or any(row.get(k)!=v for k,v in binding.items()):
        raise MeterError('meter_binding_changed')
    if event is not None and row.get('event')!=event:raise MeterError('meter_event_changed')


def validate_terminal(row,binding):
    validate(row,binding,'terminal')
    if row.get('protection')!={'dumpable':0,'no_new_privs':1,'capabilities_zero':True}:
        raise MeterError('missing_meter_protection')
    for key in ('worker_cpu_seconds','worker_user_cpu_seconds','worker_system_cpu_seconds',
                'worker_wall_seconds','sampled_cpu_seconds'):
        if type(row.get(key)) not in (int,float) or not math.isfinite(row[key]) or row[key]<0:
            raise MeterError('invalid_meter_number:'+key)
    if abs(row['worker_cpu_seconds']-row['worker_user_cpu_seconds']-row['worker_system_cpu_seconds'])>1e-8:
        raise MeterError('inconsistent_meter_cpu')
    status=row.get('worker_wait_status')
    if type(status) is not int or status<0 or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
        raise MeterError('invalid_wait_status')
    if row.get('worker_exit_code')!=(os.WEXITSTATUS(status) if os.WIFEXITED(status) else None):
        raise MeterError('invalid_exit_code')
    if row.get('worker_signal')!=(os.WTERMSIG(status) if os.WIFSIGNALED(status) else None):
        raise MeterError('invalid_exit_signal')
    if type(row.get('requests')) is not int or row['requests']<0:raise MeterError('invalid_action_count')
    for key in ('peak_sampled_rss_bytes','os_maxrss_bytes'):
        if type(row.get(key)) is not int or row[key]<0:raise MeterError('invalid_rss')


class Console:
    def __init__(self, packet, output, work, arm, deadline, history_dir, *,
                 release, commitment, runtime, core):
        self.release=Path(release).resolve();self.mods=load_release(self.release)
        self.mods['integrity'].verify_packet(packet,commitment)
        self.runtime_path=Path(runtime).resolve()
        self.runtime,self.runtime_sha256=runtime_manifest(runtime)
        if not sys_platform_linux():raise RuntimeError('Linux host required for Console')
        if type(core) is not int or core not in os.sched_getaffinity(0):raise RuntimeError('core_not_allocated')
        self.core=core
        self.out,self.work,self.history_dir=map(lambda p:Path(p).resolve(),(output,work,history_dir))
        if any(a==b or a.is_relative_to(b) or b.is_relative_to(a) for a,b in
               ((self.out,self.work),(self.out,self.history_dir),(self.work,self.history_dir))):
            raise ValueError('records_workspace_history_must_be_disjoint')
        if any(p.is_symlink() or not p.is_dir() for p in (Path(output),Path(work),Path(history_dir))):
            raise ValueError('explicit_existing_private_directories_required')
        self.deadline=deadline
        self.contract=self.mods['resources'].CONTRACT
        self.turn=0;self.turn_limit=self.contract['turns'];self.cpu=0.;self.tokens=0
        self.live_calls=0;self.worker_wall_s=0.;self.action_wall_s=0.
        self.accounting_complete=True
        self.w=self.mods['world'].World(packet)
        self.arm=arm
        prompts=self.mods['prompts']
        if arm not in prompts.ARMS:raise ValueError('unsupported_information_condition')
        for name in ('RULES.md','task.json'):
            shutil.copyfile(prompts.ASSETS/name,self.work/name)
        disclosed={}
        for name,content in prompts.disclosures(packet,arm).items():
            (self.work/name).write_bytes(content);(self.out/('provided_'+name)).write_bytes(content)
            disclosed[name]=hashlib.sha256(content).hexdigest()
        write(self.out/'provided_hashes.json',disclosed)
        self.initial_prompt=prompts.initial(packet,arm)
        (self.out/'initial_prompt.txt').write_text(self.initial_prompt)

    def budget(self):
        return dict(wall_seconds_remaining=max(0.,self.deadline-time.monotonic()),
            worker_cpu_seconds_remaining=max(0.,self.contract['worker_cpu_seconds']-self.cpu) if self.accounting_complete else None,
            known_generated_tokens_remaining=max(0,self.contract['generated_tokens']-self.tokens),
            model_turns_remaining=max(0,self.turn_limit-self.turn),capital=self.w.cash)

    def state(self):
        state=self.w.state();state.pop('grade')
        return dict(**state,cpu_s=self.cpu,generated_tokens=self.tokens,
            referee_verification_cpu_s=self.w.verification_cpu_s,research_budget=self.budget())

    def prompt(self,history):
        context=self.mods['context']
        return context.build(self.initial_prompt,history,context.safe_notes(self.work),self.budget())

    def bill(self,cpu=0.,tokens=0):
        if not self.accounting_complete:raise MeterError('prior_CPU_is_unknown')
        if type(cpu) not in (int,float) or not math.isfinite(cpu) or cpu<0 or type(tokens) is not int or tokens<0:
            raise ValueError('invalid_charge')
        self.cpu+=cpu;self.tokens+=tokens
        if self.cpu>self.contract['worker_cpu_seconds'] or self.tokens>self.contract['generated_tokens']:
            raise OverflowError('research allowance exceeded')

    def action(self,request):
        if not self.accounting_complete:raise MeterError('prior_CPU_is_unknown')
        if time.monotonic()>=self.deadline:raise ValueError('campaign wall budget exhausted')
        accepted=self.budget();started=time.monotonic()
        # Journal before an irreversible physical mutation. Replay consumes only
        # committed physical.jsonl; interrupted intent remains operationally open.
        append(self.out/'physical_intents.jsonl',dict(request=request,accepted_budget=accepted))
        try:result=self.w.act(request)
        except (ValueError,TypeError,KeyError,IndexError):
            raise ValueError('invalid physical action') from None
        append(self.out/'physical.jsonl',dict(request=request,result=result,accepted_budget=accepted))
        self.action_wall_s+=time.monotonic()-started
        visible=dict(result);visible.pop('grade',None)
        return dict(visible,research_budget=self.budget())

    @guarded
    def run(self,code,turn):
        if not self.accounting_complete:raise MeterError('prior_CPU_is_unknown')
        if type(turn) is not int or not 1<=turn<=self.turn_limit:raise ValueError('invalid_turn')
        remaining=max(0.,self.contract['worker_cpu_seconds']-self.cpu)
        if remaining<=0 or self.tokens>=self.contract['generated_tokens'] or time.monotonic()>=self.deadline:
            raise OverflowError('no_worker_budget_remains')
        self.turn=turn
        directory=self.out/('linux_%06d'%turn);directory.mkdir(mode=0o700)
        base=self.out/('console_%06d'%turn)
        base.with_suffix('.py').write_text(code)
        base.with_suffix('.txt').touch(exist_ok=False)
        source=directory/'SOURCE.py';source.write_text(code)
        startup=self.release/'b720/console_start.py'
        config=dict(source_sha256=digest(source),startup_sha256=digest(startup),
            core=self.core,remaining_cpu=remaining,campaign_deadline=self.deadline,
            block_wall=remaining+90,memory_bytes=self.contract['rss_bytes'],
            file_bytes=self.contract['file_bytes'],scientific_path='/scientific')
        write(directory/'CONTROL.json',config)
        binding=dict(schema='b720-linux-meter-v1',source_sha256=digest(source),config_sha256=digest(directory/'CONTROL.json'))
        sources={p.name:digest(p) for p in (HERE/'meter.py',HERE/'console.py',HERE/'binding.py',HERE/'interrupts.py',HERE/'DEPENDENCIES.json')}
        write(directory/'CLAIM.json',dict(binding=binding,sources=sources,runtime_sha256=self.runtime_sha256,
              cpu_accounting_complete=False,prior_cpu=self.cpu,prior_tokens=self.tokens))
        listener=connection=process=None;charged=0.;cpu_exhausted=False;terminal=None
        events=0;started=time.monotonic();failure=None;cleanup_error=None;terminal_verified=False;peer_identity=None
        handshake={'phase':'not_connected','authorization_deadline':self.deadline}
        def meter(value):
            nonlocal charged,cpu_exhausted
            if type(value) not in (float,int) or not math.isfinite(value) or value<0:raise MeterError('invalid_live_CPU')
            if value>charged:
                delta=value-charged;charged=value
                try:self.bill(cpu=delta)
                except OverflowError:cpu_exhausted=True
        try:
            with tempfile.TemporaryDirectory(prefix='sw-view-') as temporary:
                view=Path(temporary)
                aliases={'work':self.work,'history':self.history_dir,'source':source,
                    'config':directory/'CONTROL.json','startup':startup,'bootstrap':HERE/'meter.py',
                    'python':Path(self.runtime['python']),'base':Path(self.runtime['base_prefix']),
                    'scientific':Path(self.runtime['scientific_path']),'stdout':base.with_suffix('.txt')}
                for name,target in aliases.items():os.symlink(target,view/name)
                (view/'meter').mkdir()
                listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                listener.bind(str(view/'meter/receipt.sock'));listener.listen(1)
                command=build_command(view,self.runtime)
                write(directory/'COMMAND.json',dict(argv=command,env={},opaque_host_mount_aliases=True))
                with (directory/'bootstrap.txt').open('wb') as log:
                    process=subprocess.Popen(command,env={},stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                    connection=accept_meter(listener,process,self.deadline)
                    handshake.update(phase='connected',connected_elapsed=time.monotonic()-started)
                    pid,uid,gid=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
                    if uid!=os.getuid() or not descendant(pid,process.pid):raise MeterError('untrusted_meter_peer')
                    identity=process_identity(pid)
                    if identity is None:raise MeterError('authenticated_meter_peer_already_exited')
                    peer_identity=dict(pid=pid,start_ticks=identity['start_ticks'])
                    write(directory/'PEER.json',dict(host_pid=pid,uid=uid,gid=gid,process_identity=identity))
                    frames=Frames(connection,process)
                    hello=frames.read(self.deadline);validate(hello,binding,'hello')
                    if hello.get('protection')!={'dumpable':0,'no_new_privs':1,'capabilities_zero':True}:raise MeterError('unprotected_meter')
                    handshake.update(phase='hello_received',hello_received_elapsed=time.monotonic()-started)
                    append(directory/'METER.jsonl',hello)
                    handshake.update(phase='hello_durable',hello_durable_elapsed=time.monotonic()-started)
                    send_frame(connection,b'{"go":true}\n',self.deadline,process)
                    handshake.update(phase='go_sent',go_sent_elapsed=time.monotonic()-started)
                    while True:
                        row=frames.read(self.deadline+20)
                        validate(row,binding);append(directory/'METER.jsonl',row)
                        if row.get('event')=='terminal':terminal=row;break
                        if row.get('event')!='action' or row.get('sequence')!=events+1:raise MeterError('unexpected_action_sequence')
                        events+=1;meter(row['sampled_worker_cpu_seconds'])
                        if cpu_exhausted or self.cpu>=self.contract['worker_cpu_seconds']:
                            reply={'error':'research allowance exceeded'}
                        else:
                            try:reply={'value':self.action(row['request'])}
                            except (ValueError,KeyError,TypeError,IndexError) as exc:reply={'error':str(exc)[:400]}
                        self.live_calls+=1
                        append(self.out/'actions.jsonl',dict(request=row['request'],state=self.state(),error=reply.get('error')))
                        send_frame(connection,(json.dumps({'sequence':events,'reply':reply},allow_nan=False)+'\n').encode(),self.deadline+15,process)
                    validate_terminal(terminal,binding)
                    if terminal['requests']!=events:raise MeterError('action_count_mismatch')
                    if terminal['worker_cpu_seconds']+0.02<charged:raise MeterError('live_CPU_exceeds_terminal')
                    # Linux jiffy samples are a floor; numerical noise must not
                    # silently refund any already accepted live charge.
                    meter(terminal['worker_cpu_seconds'])
                    if charged>terminal['worker_cpu_seconds']:
                        # Reconcile a conservative live jiffy estimate to the
                        # authoritative terminal wait4 total, never to zero.
                        self.cpu-=charged-terminal['worker_cpu_seconds']
                        charged=terminal['worker_cpu_seconds']
                    frames.eof();process.wait(timeout=5)
                    if any(digest(HERE/name)!=value for name,value in sources.items()):raise MeterError('adapter_source_changed')
                    if digest(self.runtime_path)!=self.runtime_sha256:raise MeterError('runtime_manifest_changed')
                    load_release(self.release)
                    terminal_verified=True
                    budget_stop=terminal.get('stop_reason') in ('cpu_limit','memory_limit','campaign_wall','block_wall') or terminal.get('worker_signal')==signal.SIGXCPU
                    if process.returncode!=0 or (terminal['startup_ok'] is not True and not budget_stop):raise MeterError('trusted_worker_setup_failed')
                    if terminal.get('relay_error'):raise MeterError('trusted_relay_failed:'+terminal['relay_error'])
        except BaseException as exc:
            failure=dict(type=type(exc).__name__,message=str(exc)[:600]);self.accounting_complete=terminal_verified
        finally:
            cleanup_error,cleanup=cleanup_namespace(process,connection,listener,peer_identity)
            if cleanup_error:self.accounting_complete=False
            elapsed=time.monotonic()-started;self.worker_wall_s+=elapsed
            with base.with_suffix('.txt').open('rb') as stream:
                size=stream.seek(0,2);stream.seek(max(0,size-12000));visible=stream.read().decode(errors='replace')
            reason=terminal.get('stop_reason') if terminal else None
            memory=reason=='memory_limit'
            if memory:visible+='\nWorker stopped at the declared memory limit. Saved files and physical campaign persist.\n'
            result=dict(exit_code=(terminal['worker_exit_code'] if terminal and terminal['worker_exit_code'] is not None else -terminal['worker_signal'] if terminal else None),
                timed_out=reason=='block_wall',public_wall_exhausted=time.monotonic()>=self.deadline,
                cpu_exhausted=cpu_exhausted or reason=='cpu_limit' or self.cpu>=self.contract['worker_cpu_seconds'],
                protocol_error=terminal.get('protocol_error') if terminal else None,memory_exceeded=memory,
                peak_sampled_rss=terminal.get('peak_sampled_rss_bytes',0) if terminal else None,
                file_limit_bytes=self.contract['file_bytes'],stdout=visible,cpu_s=charged,
                cpu_accounting_complete=self.accounting_complete,ledger=self.state(),
                failure=failure,cleanup_error=cleanup_error,namespace_cleanup=cleanup,meter_terminal=terminal,
                wall_seconds=elapsed,handshake=handshake,scope='Linux scientific console; provider/campaign launch handled separately')
            write(directory/'RESULT.json',result)
            write(self.out/('receipt_%06d.json'%turn),result)
        if not self.accounting_complete:raise MeterError('unresolved_worker_meter; see preserved receipt')
        if failure:raise MeterError('trusted_worker_failure_with_verified_CPU; see preserved receipt')
        return result


def sys_platform_linux():
    import sys
    return sys.platform.startswith('linux')


def build_command(view,runtime):
    base=runtime['base_prefix']
    command=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session',
        '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--symlink','usr/bin','/bin',
        '--proc','/proc','--dev','/dev','--tmpfs','/tmp']
    for name,destination,mode in [('work','/work','--bind'),('history','/history','--ro-bind'),
        ('source','/trusted/SOURCE.py','--ro-bind'),('config','/trusted/CONTROL.json','--ro-bind'),
        ('startup','/trusted/console_start.py','--ro-bind'),('bootstrap','/trusted/meter.py','--ro-bind'),
        ('python','/runtime/python','--ro-bind'),('base',base,'--ro-bind'),
        ('scientific','/scientific','--ro-bind'),('stdout','/logs/stdout.txt','--bind'),
        ('meter','/meter','--ro-bind')]:command.extend([mode,str(view/name),destination])
    command.extend(['--chdir','/work'])
    for key,value in {'PATH':'/usr/bin:/bin','HOME':'/work','TMPDIR':'/work','LANG':'C.UTF-8',
        'LD_LIBRARY_PATH':base+'/lib','VECLIB_MAXIMUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
        'OMP_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'}.items():command.extend(['--setenv',key,value])
    command.extend(['/runtime/python','-I','-S','-B','/trusted/meter.py'])
    return command
