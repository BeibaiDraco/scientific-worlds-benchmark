"""Trusted Linux worker parent and action-pipe relay; no world or packet access."""
import ctypes,errno,hashlib,io,json,math,os,resource,select,signal,socket,sys,threading,time,traceback
from pathlib import Path

DENIED = ('fork', 'vfork', 'unshare', 'setns', 'sched_setaffinity',
          'ptrace', 'process_vm_readv', 'process_vm_writev', 'process_madvise',
          'pidfd_getfd', 'pidfd_send_signal', 'tkill', 'mount', 'umount2', 'bpf',
          'perf_event_open', 'socket', 'socketpair', 'socketcall', 'connect',
          'io_uring_setup', 'io_uring_enter', 'io_uring_register',
          'execve', 'execveat', 'open_by_handle_at', 'kcmp')
SELF_SIGNALS = ('kill', 'tgkill', 'rt_sigqueueinfo', 'rt_tgsigqueueinfo')
REQUIRED_DENIED = {'fork', 'vfork', 'unshare', 'setns', 'sched_setaffinity',
    'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd',
    'pidfd_send_signal', 'tkill', 'socket', 'socketpair', 'connect',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register', 'execve', 'execveat'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def set_parent_protection():
    libc = ctypes.CDLL(None, use_errno=True)
    # Do not allow the same-UID child to open our /proc/PID/fd or memory.
    for option, value in ((4, 0), (38, 1)):  # DUMPABLE, NO_NEW_PRIVS
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'parent_prctl_failed')
    if libc.prctl(3, 0, 0, 0, 0) != 0 or libc.prctl(39, 0, 0, 0, 0) != 1:
        raise RuntimeError('parent_protection_not_set')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if any(int(status[name].strip(), 16) for name in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb')):
        raise RuntimeError('unexpected_namespace_capabilities')
    return {'dumpable': 0, 'no_new_privs': 1, 'capabilities_zero': True}


def load_child_filter():
    # Known installed ABI, already used by the first host probe. Avoid
    # find_library(), whose helper subprocesses are unnecessary here.
    lib = ctypes.CDLL('libseccomp.so.2')
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int

    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('seccomp_init_failed')
    try:
        for name in DENIED:
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number < 0 and name in REQUIRED_DENIED:
                raise RuntimeError('required_seccomp_syscall_unknown:' + name)
            if number >= 0 and lib.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, number, 0, None) != 0:
                raise RuntimeError('seccomp_rule_failed:' + name)
        # Allow signals to this worker's own process/thread group, never its
        # trusted parent or another namespace process. Legacy tkill is denied
        # because its lone TID argument cannot identify the thread group.
        compare = Compare(0, 1, os.getpid(), 0)  # SCMP_CMP_NE
        for name in SELF_SIGNALS:
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or lib.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, number, 1, ctypes.byref(compare)) != 0:
                raise RuntimeError('seccomp_self_signal_rule_failed:' + name)
        # Threads remain within the worker's wait4/CPU/RSS accounting unit.
        number = lib.seccomp_syscall_resolve_name(b'clone')
        compare = Compare(0, 7, 0x10000, 0)  # CLONE_THREAD absent
        if number < 0 or lib.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, number, 1, ctypes.byref(compare)) != 0:
            raise RuntimeError('seccomp_clone_rule_failed')
        number = lib.seccomp_syscall_resolve_name(b'clone3')
        if number >= 0 and lib.seccomp_rule_add_array(ctx, 0x50000 | errno.ENOSYS, number, 0, None) != 0:
            raise RuntimeError('seccomp_clone3_rule_failed')
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('seccomp_load_failed')
    finally:
        lib.seccomp_release(ctx)


def send(channel, row):
    channel.sendall((json.dumps(row, allow_nan=False, separators=(',', ':'))+'\n').encode())


END=object()


def io_deadline(deadline, monitor=None):
    # Once a worker is reaped, bound draining its already-issued action/reply.
    # Before that, the unchanged public wall/CPU/memory watchdog controls it.
    if monitor is not None and monitor.done.is_set():
        deadline=min(deadline,monitor.finished+15)
    if time.monotonic()>=deadline:raise TimeoutError('trusted_relay_deadline')
    return deadline


class SocketFrames:
    """No socket.makefile timeout state; partial frames survive slow durable go."""
    def __init__(self, channel):
        self.channel=channel;self.buffer=b'';channel.setblocking(False)

    def read(self, deadline, limit, monitor=None):
        while b'\n' not in self.buffer:
            io_deadline(deadline,monitor)
            if not select.select([self.channel],[],[],.05)[0]:continue
            try:part=self.channel.recv(65536)
            except BlockingIOError:continue
            if not part:
                if self.buffer:raise ValueError('incomplete_trusted_frame')
                return END
            self.buffer+=part
            if b'\n' not in self.buffer and len(self.buffer)>limit:raise ValueError('trusted_frame_too_large')
        raw,self.buffer=self.buffer.split(b'\n',1)
        if len(raw)>limit:raise ValueError('trusted_frame_too_large')
        def invalid(value):raise ValueError('nonfinite JSON constant')
        return json.loads(raw,parse_constant=invalid)

    def send(self, row, deadline, monitor=None):
        body=(json.dumps(row,allow_nan=False,separators=(',',':'))+'\n').encode()
        view=memoryview(body)
        while view:
            io_deadline(deadline,monitor)
            if not select.select([],[self.channel],[],.05)[1]:continue
            try:sent=self.channel.send(view)
            except BlockingIOError:continue
            if not sent:raise ConnectionError('trusted_socket_write_closed')
            view=view[sent:]


def host_disconnected(channel):
    if not select.select([channel],[],[],0)[0]:return False
    try:part=channel.recv(1,socket.MSG_PEEK)
    except BlockingIOError:return False
    if not part:return True
    raise RuntimeError('unexpected_host_data_while_worker_runs')


def pipe_readline(fd, buffer, deadline, channel, monitor, limit=8*1024**2):
    while b'\n' not in buffer:
        io_deadline(deadline,monitor)
        if host_disconnected(channel):raise ConnectionError('host_disconnected')
        if not select.select([fd],[],[],.05)[0]:continue
        try:part=os.read(fd,65536)
        except BlockingIOError:continue
        if not part:
            if buffer:raise ValueError('RPC message too long or incomplete')
            return END,b''
        buffer+=part
        if b'\n' not in buffer and len(buffer)>limit:raise ValueError('RPC message too long or incomplete')
    raw,buffer=buffer.split(b'\n',1)
    if len(raw)>limit:raise ValueError('RPC message too long or incomplete')
    def invalid(value):raise ValueError('nonfinite JSON constant')
    return json.loads(raw,parse_constant=invalid),buffer


def pipe_write(fd, body, deadline, channel, monitor):
    view=memoryview(body)
    while view:
        io_deadline(deadline,monitor)
        if host_disconnected(channel):raise ConnectionError('host_disconnected')
        if not select.select([],[fd],[],.05)[1]:continue
        try:sent=os.write(fd,view)
        except BlockingIOError:continue
        view=view[sent:]


def readiness(fd, deadline, channel, monitor):
    while True:
        io_deadline(deadline,monitor)
        if host_disconnected(channel):raise ConnectionError('host_disconnected')
        if select.select([fd],[],[],.05)[0]:return os.read(fd,2)==b'R'


def line(stream, limit):
    raw = stream.readline(limit+1)
    if not raw:
        return END
    if len(raw) > limit or not raw.endswith(b'\n'):
        raise ValueError('RPC message too long or incomplete')
    def invalid_constant(value):raise ValueError('nonfinite JSON constant')
    return json.loads(raw,parse_constant=invalid_constant)


def process_sample(pid):
    try:
        stat = Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()
        cpu = (int(stat[11])+int(stat[12])) / os.sysconf('SC_CLK_TCK')
        rss = 0
        for row in Path('/proc/%d/status' % pid).read_text().splitlines():
            if row.startswith('VmRSS:'):
                rss = int(row.split()[1])*1024
        return cpu, rss
    except OSError as exc:
        if exc.errno in (errno.ENOENT,errno.ESRCH):return None,0
        raise


class Monitor:
    def __init__(self, pid, config, started):
        self.pid,self.config,self.started=pid,config,started
        self.cpu,self.peak,self.reason=0.0,0,None
        self.status=self.usage=None
        self.error=None
        self.finished=None
        self.done=threading.Event()
        self.lock=threading.Lock()

    def stop(self, reason):
        with self.lock:
            if self.reason is None:self.reason=reason
        try:os.kill(self.pid,signal.SIGKILL)
        except ProcessLookupError:pass

    def sample(self):
        cpu,rss=process_sample(self.pid)
        if cpu is not None:self.cpu=max(self.cpu,cpu)
        self.peak=max(self.peak,rss)
        return self.cpu

    def watch(self):
        try:
            while True:
                pid,status,usage=os.wait4(self.pid,os.WNOHANG)
                if pid:
                    self.status,self.usage=status,usage
                    break
                self.sample()
                now=time.monotonic()
                if self.peak>self.config['memory_bytes']:self.stop('memory_limit')
                elif self.cpu>=self.config['remaining_cpu']:self.stop('cpu_limit')
                elif now>=self.config['campaign_deadline']:self.stop('campaign_wall')
                elif now-self.started>self.config['block_wall']:self.stop('block_wall')
                time.sleep(.05)
        except BaseException as exc:
            self.error=type(exc).__name__+':'+str(exc)[:200]
            self.stop('meter_error')
            try:
                _,self.status,self.usage=os.wait4(self.pid,0)
            except ChildProcessError:pass
        finally:self.finished=time.monotonic();self.done.set()


def worker(config, source, startup, meter, read_fd, write_fd, ready_fd):
    meter.close()
    output=os.open('/logs/stdout.txt',os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW)
    null=os.open('/dev/null',os.O_RDONLY)
    os.dup2(null,0);os.dup2(output,1);os.dup2(output,2)
    keep={0,1,2,read_fd,write_fd,ready_fd}
    for fd in os.listdir('/proc/self/fd'):
        if int(fd) not in keep:
            try:os.close(int(fd))
            except OSError as exc:
                if exc.errno!=errno.EBADF:raise
    os.sched_setaffinity(0,{config['core']})
    seconds=max(1,math.ceil(config['remaining_cpu']))
    resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds+1))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(config['file_bytes'],config['file_bytes']))
    os.environ.update(SCIPY_DIR=config['scientific_path'],CAMPAIGN_HISTORY='/history',
                      LAB_READ=str(read_fd),LAB_WRITE=str(write_fd))
    load_child_filter()
    tail="exec(compile(sys.stdin.read(), '<console>', 'exec'))"
    if startup.count(tail)!=1 or not startup.rstrip().endswith(tail):
        raise RuntimeError('unrecognized_frozen_console_start')
    namespace={'__name__':'__main__','__file__':'<console>'}
    # Identical frozen NumPy and act initialization, then a trusted readiness
    # byte is sent/closed before any participant code can execute.
    exec(compile(startup[:startup.index(tail)],'<console-start>','exec'),namespace,namespace)
    os.write(ready_fd,b'R');os.close(ready_fd)
    sys.stdin=io.StringIO(source)
    try:exec(compile(source,'<console>','exec'),namespace,namespace)
    except BaseException:
        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


def main():
    raw=Path('/trusted/CONTROL.json').read_bytes();config=json.loads(raw)
    source=Path('/trusted/SOURCE.py').read_bytes()
    startup=Path('/trusted/console_start.py').read_bytes()
    if sha(source)!=config['source_sha256'] or sha(startup)!=config['startup_sha256']:
        raise RuntimeError('trusted_input_changed')
    protection=set_parent_protection()
    meter=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    meter.settimeout(max(.001,min(60,config['campaign_deadline']-time.monotonic())))
    meter.connect('/meter/receipt.sock')
    binding={'schema':'b720-linux-meter-v1','config_sha256':sha(raw),'source_sha256':sha(source)}
    wire=SocketFrames(meter)
    # The host durably journals hello before granting execution. A fixed10s
    # socket timeout raced GPFS fsync. Both sides now share the public deadline;
    # no worker exists and no participant CPU can be consumed before valid go.
    wire.send(dict(binding,event='hello',protection=protection,namespace_pid=os.getpid()),config['campaign_deadline'])
    if wire.read(config['campaign_deadline'],128)!={'go':True}:
        raise RuntimeError('missing_host_authorization')
    request_read,request_write=os.pipe();response_read,response_write=os.pipe()
    ready_read,ready_write=os.pipe()
    started=time.monotonic();pid=os.fork()
    if pid==0:
        try:worker(config,source.decode(),startup.decode(),meter,response_read,request_write,ready_write)
        except BaseException:
            traceback.print_exc();os._exit(125)
    os.close(response_read);os.close(request_write);os.close(ready_write)
    for fd in (request_read,response_write,ready_read):os.set_blocking(fd,False)
    monitor=Monitor(pid,config,started)
    thread=threading.Thread(target=monitor.watch,daemon=True);thread.start()
    protocol_error=None;relay_error=None;startup_ok=False;requests=0;buffer=b''
    try:
        startup_ok=readiness(ready_read,config['campaign_deadline']+15,meter,monitor)
        if startup_ok:
            while True:
                try:request,buffer=pipe_readline(request_read,buffer,config['campaign_deadline']+15,meter,monitor)
                except (ValueError,RecursionError) as exc:
                    protocol_error=str(exc)[:400];monitor.stop('participant_rpc_error');break
                if request is END:break
                requests+=1
                wire.send(dict(binding,event='action',request=request,sequence=requests,
                    sampled_worker_cpu_seconds=monitor.sample()),config['campaign_deadline']+15,monitor)
                reply=wire.read(config['campaign_deadline']+15,8*1024**2,monitor)
                if not isinstance(reply,dict) or set(reply)!={'sequence','reply'} or reply['sequence']!=requests:
                    raise RuntimeError('invalid_trusted_action_reply')
                try:pipe_write(response_write,(json.dumps(reply['reply'],allow_nan=False)+'\n').encode(),config['campaign_deadline']+15,meter,monitor)
                except BrokenPipeError:break
    except BaseException as exc:
        relay_error=type(exc).__name__+':'+str(exc)[:400]
        monitor.stop('trusted_relay_error')
    finally:
        for fd in (request_read,response_write,ready_read):
            try:os.close(fd)
            except OSError:pass
        if not monitor.done.wait(1):monitor.stop('participant_closed_rpc')
        thread.join(timeout=5)
        # Never invent a wait4 total after a killed/unreaped meter. A missing or
        # unusable terminal remains operationally unknown at the host.
        if monitor.error or monitor.usage is None or not monitor.done.is_set():
            meter.close()
            raise RuntimeError('meter_unresolved:'+str(monitor.error))
        usage=monitor.usage;status=monitor.status
        terminal=dict(binding,event='terminal',protection=protection,
            startup_ok=startup_ok,requests=requests,protocol_error=protocol_error,
            worker_cpu_seconds=usage.ru_utime+usage.ru_stime,
            worker_user_cpu_seconds=usage.ru_utime,worker_system_cpu_seconds=usage.ru_stime,
            worker_wait_status=status,
            worker_exit_code=os.WEXITSTATUS(status) if os.WIFEXITED(status) else None,
            worker_signal=os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
            peak_sampled_rss_bytes=monitor.peak,os_maxrss_bytes=usage.ru_maxrss*1024,
            sampled_cpu_seconds=monitor.cpu,worker_wall_seconds=time.monotonic()-started,
            stop_reason=monitor.reason,worker_namespace_pid=pid)
        if relay_error:terminal['relay_error']=relay_error
        try:wire.send(terminal,time.monotonic()+15)
        finally:meter.close()


if __name__=='__main__':main()
