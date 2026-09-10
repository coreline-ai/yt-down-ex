"""Chrome Native Messaging framing. stdout is reserved for protocol frames."""
import json
import struct
import threading
MAX_MESSAGE = 256 * 1024
_write_lock = threading.Lock()

def read_exact(stream, n):
    chunks = bytearray()
    while len(chunks) < n:
        part = stream.read(n - len(chunks))
        if not part:
            if not chunks:
                return None
            raise ValueError('Truncated message')
        chunks.extend(part)
    return bytes(chunks)

def read_message(stream):
    header = read_exact(stream, 4)
    if header is None:
        return None
    size = struct.unpack('=I', header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError('Invalid message length')
    data = read_exact(stream, size)
    if data is None:
        raise ValueError('Truncated message')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Object required')
    return result

def write_message(stream, message):
    data = json.dumps(message, ensure_ascii=False, allow_nan=False).encode()
    if len(data) > MAX_MESSAGE:
        raise ValueError('Message too large')
    with _write_lock:
        stream.write(struct.pack('=I', len(data)) + data)
        stream.flush()
