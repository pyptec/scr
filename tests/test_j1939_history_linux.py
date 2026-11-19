"""Synthetic POSIX-only security checks; never use operational RAW."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from j1939.evidence_store import EvidenceStore
from j1939.history import verify_registered_evidence

@unittest.skipUnless(hasattr(os, 'O_NOFOLLOW') and os.open in os.supports_dir_fd, 'secure POSIX open unavailable')
class RawLinuxTests(unittest.TestCase):
    def test_registered_evidence_security(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); raw=root/'raw'; raw.mkdir(); db=root/'db.sqlite'
            EvidenceStore(db).migrate_evidence(create=True)
            name='j1939_auto_'+'a'*32+'_'+'b'*32+'.txt'; target=raw/name
            target.write_bytes(b'test raw')
            digest=hashlib.sha256(b'test raw').hexdigest()
            with sqlite3.connect(db) as c:
                c.execute('INSERT INTO j1939_evidence_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('seg','cap','batch','session',str(target),None,None,1,'[]','[]',8,'INCOMPLETE','interruption',digest,'{}'))
            def verify(**kwargs): return verify_registered_evidence(db,'session','seg',raw,**kwargs)
            result=verify(); self.assertTrue(result['sha256_match']); self.assertTrue(result['size_match']); self.assertEqual(result['temporal_integrity'],'INCOMPLETE')
            with sqlite3.connect(db) as c: c.execute('UPDATE j1939_evidence_segments SET sha256=?,size_bytes=?',('0'*64,9))
            result=verify(); self.assertFalse(result['sha256_match']); self.assertFalse(result['size_match'])
            self.assertEqual(verify(max_bytes=1)['error'],'SIZE_LIMIT_EXCEEDED')
            with self.assertRaises(ValueError): verify_registered_evidence(db,'../session','seg',raw)
            self.assertIsNone(verify_registered_evidence(db,'session','missing',raw))
            target.unlink(); self.assertEqual(verify()['error'],'FILE_NOT_FOUND')
            outside=root/'outside'; outside.write_bytes(b'private'); target.symlink_to(outside)
            self.assertEqual(verify()['error'],'FILE_UNREADABLE')
            with sqlite3.connect(db) as c: c.execute('UPDATE j1939_evidence_segments SET file_path=?',(str(outside),))
            self.assertEqual(verify()['error'],'PATH_NOT_AUTHORIZED')
            with sqlite3.connect(db) as c: c.execute('UPDATE j1939_evidence_segments SET file_path=?',(str(raw/name),))
            with patch('os.read', side_effect=OSError('synthetic error')):
                target.unlink(); target.write_bytes(b'test raw')
                self.assertEqual(verify()['error'],'FILE_UNREADABLE')

if __name__ == '__main__': unittest.main()
