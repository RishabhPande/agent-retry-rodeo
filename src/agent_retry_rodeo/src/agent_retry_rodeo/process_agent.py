"""JSON-lines bridge to an explicitly trusted external executable. Not a sandbox."""
from __future__ import annotations

import json
import math
import os
import selectors
import signal
import subprocess
import time

FRAME_LIMIT = 64_000
OUTPUT_LIMIT = 4_000_000


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('Duplicate protocol JSON key')
        out[key] = value
    return out


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite protocol number')
    return number


def _decode(line):
    try:
        obj = json.loads(line.decode('utf-8'), object_pairs_hook=_object,
                         parse_float=_finite_float,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite protocol number')))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid external-agent JSON frame') from exc
    if not isinstance(obj, dict):
        raise ValueError('External-agent frames must be objects')
    return obj


class ProcessAgent:
    """One fresh process per case; the parent owns the simulator and grading."""
    name = 'External command'
    kind = 'external command; model provenance not verified'

    def __init__(self, command, timeout=30.0):
        if not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError('Command must be a nonempty argument list')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Agent timeout must be positive and finite')
        if os.name != 'posix':
            raise ValueError('External command transport currently requires POSIX')
        self.command, self.timeout = list(command), timeout

    def run(self, call, goal):
        process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, bufsize=0)
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + self.timeout
        pending = bytearray((json.dumps({'type': 'start', 'protocol': 1, 'goal': goal}) + '\n').encode())
        buffer = bytearray()
        total = 0
        claim = None
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, 'input')
        selector.register(process.stdout, selectors.EVENT_READ, 'output')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('External agent exceeded its wall-clock deadline')
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream, role = key.fileobj, key.data
                    if role == 'input':
                        try:
                            n = os.write(stream.fileno(), pending)
                        except BrokenPipeError as exc:
                            raise ValueError('External agent closed its input') from exc
                        del pending[:n]
                        if not pending:
                            selector.unregister(stream)
                        continue
                    chunk = os.read(stream.fileno(), 8192)
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    total += len(chunk)
                    if total > OUTPUT_LIMIT:
                        raise ValueError('External agent exceeded its output budget')
                    if role == 'stderr':
                        continue  # Drain, but never copy arbitrary logs into public evidence.
                    buffer.extend(chunk)
                    while b'\n' in buffer:
                        line, _, tail = buffer.partition(b'\n')
                        buffer = bytearray(tail)
                        if len(line) > FRAME_LIMIT:
                            raise ValueError('External-agent frame exceeds 64 KB')
                        if claim is not None:
                            raise ValueError('External agent sent data after completion')
                        obj = _decode(line)
                        if obj.get('type') == 'done':
                            if set(obj) != {'type', 'claimed_complete'} or type(obj['claimed_complete']) is not bool:
                                raise ValueError('done requires only a boolean claimed_complete')
                            claim = obj['claimed_complete']
                        elif obj.get('type') == 'call':
                            if set(obj) != {'type', 'action', 'params'} or not isinstance(obj['action'], str) or not isinstance(obj['params'], dict):
                                raise ValueError('call requires action text and params object')
                            observation = call(obj['action'], **obj['params'])
                            pending.extend((json.dumps({'type': 'observation', 'ok': observation.ok,
                                                        'result': observation.result}, allow_nan=False) + '\n').encode())
                            if len(pending) > OUTPUT_LIMIT:
                                raise ValueError('External agent is not consuming observations')
                            if process.stdin not in selector.get_map():
                                selector.register(process.stdin, selectors.EVENT_WRITE, 'input')
                        else:
                            raise ValueError('Unknown external-agent frame type')
                    if len(buffer) > FRAME_LIMIT:
                        raise ValueError('External-agent frame exceeds 64 KB')
                # A successful done frame must be followed by a clean process exit.
                if process.poll() is not None and not any(k.data in ('output', 'stderr') for k in selector.get_map().values()):
                    break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('External agent exceeded its wall-clock deadline')
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError('External agent exceeded its wall-clock deadline') from exc
            if buffer:
                raise ValueError('External agent left an unterminated frame')
            if code != 0:
                raise ValueError(f'External agent exited with status {code}')
            if claim is None:
                raise ValueError('External agent exited without a completion frame')
            return claim
        finally:
            selector.close()
            # Kill the process group even when the direct child has already exited.
            # Descendants must not retain protocol pipes or outlive a completed case.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
