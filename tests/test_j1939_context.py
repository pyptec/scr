import sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from j1939.evidence_store import EvidenceStore
from j1939.history import detail

class ContextTests(unittest.TestCase):
    def test_prior_context_requires_exact_reconciliation_and_time_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'test.sqlite'; EvidenceStore(path).migrate_evidence(create=True)
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,rpm,source_address,reason,evidence_quality,observed_at_utc,recorded_at_utc) VALUES('batch:2:reconciled','g','e','2031-04-12T13:52:47.431511Z','STATE_RECONCILED','UNKNOWN','RUNNING',1555,234,'synthetic','INCOMPLETE_HISTORY','2031-04-12T13:52:47.431144Z','2031-04-12T13:52:47.431511Z')""")
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,observed_from_utc,observed_until_utc,status,active,quality,verified_seconds) VALUES('batch:2:session','g','e','2031-04-12T13:52:47.431144Z','2031-04-12T14:25:30Z','INDETERMINADA',0,'INCOMPLETE',1234.567)""")
                gaps=[('context',None,'2031-04-12T13:51:32Z','2031-04-12T13:52:47.431511Z'),('linked','batch:2:session','2031-04-12T14:22:13Z','2031-04-12T14:23:38Z'),('old',None,'2031-04-12T12:00:00Z','2031-04-12T13:52:47.431511Z'),('mismatch',None,'2031-04-12T13:51:32Z','2031-04-12T13:52:47Z')]
                for id,sid,start,end in gaps:
                    c.execute('INSERT INTO j1939_observation_gaps(gap_id,gateway_id,equipment_id,session_id,started_at_utc,recovered_at_utc,reason) VALUES(?,?,?,?,?,?,?)',(id,'g','e',sid,start,end,'process_restart'))
                c.commit(); before=list(c.iterdump())
                x=detail(path,'batch:2:session')
                self.assertEqual([g['gap_id'] for g in x['observation_gaps']],['linked'])
                self.assertEqual([g['gap_id'] for g in x['prior_observation_context']],['context'])
                self.assertIsNone(x['prior_observation_context'][0]['session_id'])
                self.assertEqual(x['verified_seconds'],1234.567)
                self.assertIn('unlinked_prior_observation_context',x['warnings'])
                self.assertEqual(before,list(c.iterdump()))

if __name__ == '__main__': unittest.main()
