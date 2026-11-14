"""Future local subprocess runner. Never cancels remote kernel work."""
import codecs
import os
import selectors
import signal
import subprocess
import time
from safe_diagnostics import redact, SafeLineStream


def run(args, timeout, log):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, start_new_session=True, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    captured = []
    def emit(text):
        captured.append(text)
        log(text)
    safe_stream = SafeLineStream(emit)
    safe_args = [redact(arg) for arg in args]
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while selector.get_map() or proc.poll() is None:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                safe_stream.feed('', final=True)
                raise subprocess.TimeoutExpired(safe_args, timeout, output=''.join(captured))
            for key, _ in selector.select(0.1 if remaining is None else min(0.1, remaining)):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    text = decoder.decode(b'', final=True)
                else:
                    text = decoder.decode(data)
                if text:
                    safe_stream.feed(text)
        code = proc.wait()
        safe_stream.feed('', final=True)
        output = ''.join(captured)
        if code:
            raise subprocess.CalledProcessError(code, safe_args, output=output)
        return output
    except BaseException:
        # Only this runner's newly created LOCAL process group. A Colab remote
        # kernel may continue: caller must retain session/output recovery state.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    finally:
        selector.close()
        proc.stdout.close()
