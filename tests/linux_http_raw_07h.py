"""POSIX HTTP RAW verification with only temporary synthetic data."""
import hashlib,json,sqlite3,tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from j1939.evidence_store import EvidenceStore
from j1939.service import start_local_api

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp); raw=root/'raw'; raw.mkdir(); db=root/'engine.sqlite'; EvidenceStore(db).migrate_evidence(create=True)
    name='j1939_auto_'+'a'*32+'_'+'b'*32+'.txt'; f=raw/name; f.write_bytes(b'synthetic')
    with sqlite3.connect(db) as c:
        c.execute('INSERT INTO j1939_evidence_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('seg','cap','batch','sid',str(f),None,None,1,'[]','[]',9,'INCOMPLETE','interruption',hashlib.sha256(b'synthetic').hexdigest(),'{}'))
    runtime=SimpleNamespace(engine_integration=SimpleNamespace(recorder=SimpleNamespace(store=SimpleNamespace(path=db)),evidence=SimpleNamespace(config=SimpleNamespace(directory=raw))))
    server,thread=start_local_api(runtime,'127.0.0.1',0)
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/j1939/engine/evidence/sid/seg/verify') as response: item=json.load(response)
        assert item['sha256_match'] is True and item['size_match'] is True and item['temporal_integrity']=='INCOMPLETE'
        assert 'file_path' not in item
        print('PASS: HTTP Linux SHA-256 correcto y estado INCOMPLETE preservado; datos sinteticos')
    finally:
        server.shutdown(); server.server_close(); thread.join()
