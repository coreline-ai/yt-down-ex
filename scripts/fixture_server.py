import json
import signal
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.fixtures import MediaServer
server=MediaServer(sys.argv[1])
print(json.dumps({'url':server.url}),flush=True)
signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
try:
    while True:signal.pause()
finally:server.close()
