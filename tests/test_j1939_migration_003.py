"""Synthetic migration/abrupt SQLite recovery tests; no operational data."""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from j1939.evidence_store import EvidenceStore
from j1939.history import detail, sessions

class Migration003Tests(unittest.TestCase):
    def test_additive_idempotent_and_abrupt_uncommitted_write(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'engine.sqlite'; store=EvidenceStore(path); store.migrate_evidence(create=True)
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,source_address,reason,evidence_quality,recorded_at_utc) VALUES('start','g','e','2026-11-19T10:00:00Z','START','STOPPED','RUNNING',234,'synthetic','GOOD','2026-11-19T10:00:00Z')""")
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,start_event_id,started_at_utc,observed_from_utc,observed_until_utc,status,active,quality) VALUES('s','g','e','start','2026-11-19T10:00:00Z','2026-11-19T10:00:00Z','2026-11-19T10:00:00Z','ABIERTA',1,'CONFIRMED')""")
                c.commit()
                before_event=c.execute('SELECT * FROM j1939_engine_events').fetchall(); before_session=c.execute('SELECT * FROM j1939_engine_sessions').fetchall()
            self.assertIsNone(detail(path,'s')['rpm_max'])
            self.assertEqual(len(sessions(path)),1)
            store.migrate_summary(); store.migrate_summary()
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(before_event,c.execute('SELECT * FROM j1939_engine_events').fetchall())
                self.assertEqual(before_session,c.execute('SELECT * FROM j1939_engine_sessions').fetchall())
                self.assertEqual(c.execute('SELECT COUNT(*) FROM j1939_schema_migrations WHERE version=3').fetchone()[0],1)
                c.execute('INSERT INTO j1939_session_summary VALUES(?,?,?,?)',('s',1800,234,0xF004)); c.commit()
            script = "import os,sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute('BEGIN IMMEDIATE');c.execute('UPDATE j1939_session_summary SET rpm_max=2000');os._exit(0)"
            child=subprocess.run([sys.executable,'-B','-c',script,str(path)],check=False,timeout=10)
            self.assertEqual(child.returncode,0)
            self.assertEqual(detail(path,'s')['rpm_max'],1800)
            self.assertEqual(sessions(path)[0]['rpm_max'],1800)
            self.assertIn('rpm_max_persisted_samples_only',detail(path,'s')['warnings'])

if __name__ == '__main__': unittest.main()
