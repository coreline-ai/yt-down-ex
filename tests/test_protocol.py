import io
import json
import struct
import unittest
from native.protocol import read_message, write_message, MAX_MESSAGE
class Fragmented(io.BytesIO):
    def read(self,n=-1): return super().read(min(n,2))
class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_multiple(self):
        stream=io.BytesIO()
        for x in [{'text':'한글'}, {'b':2}]: write_message(stream,x)
        reader=Fragmented(stream.getvalue())
        self.assertEqual(read_message(reader),{'text':'한글'})
        self.assertEqual(read_message(reader),{'b':2})
        self.assertIsNone(read_message(reader))
    def test_invalid_frames(self):
        for data in [b'x',struct.pack('=I',MAX_MESSAGE+1),struct.pack('=I',2)+b'xx',struct.pack('=I',5)+b'a',struct.pack('=I',2)+b'[]']:
            with self.assertRaises(ValueError): read_message(io.BytesIO(data))
    def test_host_rejects_wrong_origin(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','native.host','chrome-extension://wrong/'],capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stdout,b'')

    def test_host_version_contract_and_unsupported_command_guidance(self):
        import subprocess,sys,tempfile,os
        from pathlib import Path
        identity=json.loads(Path('shared/extension-id.json').read_text())['id']
        with tempfile.TemporaryDirectory() as tmp:
            stream=io.BytesIO()
            write_message(stream,{'protocolVersion':1,'requestId':'hello','type':'hello','payload':{'extensionVersion':'0.2.0'}})
            write_message(stream,{'protocolVersion':1,'requestId':'unknown','type':'futureCommand','payload':{}})
            process=subprocess.run([sys.executable,'-m','native.host','chrome-extension://'+identity+'/'],input=stream.getvalue(),capture_output=True,timeout=10,env={**os.environ,'STASH_DATA_DIR':tmp})
            self.assertEqual(process.returncode,0)
            reader=io.BytesIO(process.stdout);replies={}
            while (reply:=read_message(reader)) is not None:replies[reply['requestId']]=reply
            self.assertEqual(replies['hello']['payload']['extensionVersion'],'0.2.0');self.assertEqual(replies['hello']['payload']['hostVersion'],'0.2.0')
            self.assertEqual(replies['unknown']['error']['code'],'UNSUPPORTED_COMMAND');self.assertIn('업데이트',replies['unknown']['error']['message'])
