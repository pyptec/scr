"""Abrupt termination of a synthetic recorder process, no CAN or real service."""
import sqlite3, subprocess, sys, tempfile, unittest
from contextlib import closing
from pathlib import Path
from j1939.evidence_store import EvidenceStore
from j1939.engine_recorder import EngineRecorder, RecorderConfig
from j1939.engine_detector import RpmSample
from tests.test_j1939_engine_detector import FakeClock, synthetic_config

CHILD = r"""
import os,sys
from pathlib import Path
from j1939.evidence_store import EvidenceStore
from j1939.engine_recorder import EngineRecorder, RecorderConfig
from j1939.engine_detector import RpmSample
from tests.test_j1939_engine_detector import FakeClock, synthetic_config
clock=FakeClock(); store=EvidenceStore(Path(sys.argv[1])); rec=EngineRecorder(RecorderConfig('g',synthetic_config(),enabled=True),clock,store)
def feed(value):
    clock.advance(1); rec.offer(RpmSample(clock.utcnow(),value,234,'synthetic-generator'))
    while rec.drain_once(): pass
for value in [0,0,0,1800,1800,1800,1950]: feed(value)
rec.flush()
while rec.drain_once(): pass
feed(2500)
os._exit(0)
"""

class AbruptRecorderTests(unittest.TestCase):
    def test_recorder_process_restart_preserves_only_committed_peak(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.sqlite'; store=EvidenceStore(path); store.migrate_evidence(create=True); store.migrate_summary()
            result=subprocess.run([sys.executable,'-B','-c',CHILD,str(path)],timeout=20)
            self.assertEqual(result.returncode,0)
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute('SELECT rpm_max FROM j1939_session_summary').fetchone()[0],1950)
            clock=FakeClock(); clock.advance(20); recorder=EngineRecorder(RecorderConfig('g',synthetic_config(),enabled=True),clock,store)
            for value in (1800,1800,1800):
                clock.advance(1); recorder.offer(RpmSample(clock.utcnow(),value,234,'synthetic-generator'))
                while recorder.drain_once(): pass
            recorder.flush()
            while recorder.drain_once(): pass
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute('SELECT rpm_max FROM j1939_session_summary').fetchone()[0],1950)
                self.assertEqual(c.execute('SELECT count(*) FROM j1939_engine_sessions').fetchone()[0],1)
                self.assertEqual(c.execute("SELECT count(*) FROM j1939_engine_events WHERE event_type='START'").fetchone()[0],1)
                self.assertEqual(c.execute("SELECT count(*) FROM j1939_engine_events WHERE event_type='STOP'").fetchone()[0],0)
                self.assertEqual(c.execute("SELECT count(*) FROM j1939_observation_gaps WHERE reason='process_restart'").fetchone()[0],1)

if __name__ == '__main__': unittest.main()
