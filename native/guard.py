"""Subprocess guard: terminate the entire job group when its parent pipe closes."""
import os
import select
import signal
import subprocess
import sys
import time

def main():
    # Runner creates this process in a new session; descendants share this group.
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    child=subprocess.Popen(sys.argv[1:],stdin=subprocess.DEVNULL)
    while child.poll() is None and not stopping:
        if select.select([sys.stdin.buffer],[],[],.1)[0] and not os.read(sys.stdin.fileno(),1):
            stopping=True
    if stopping:
        os.killpg(os.getpgrp(),signal.SIGTERM)
        try:child.wait(timeout=1.5)
        except subprocess.TimeoutExpired:os.killpg(os.getpgrp(),signal.SIGKILL)
    return child.wait()
if __name__=='__main__':raise SystemExit(main())
