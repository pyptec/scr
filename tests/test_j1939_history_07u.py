"""Synthetic provenance checks for hourmeter history."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from j1939.evidence_store import EvidenceStore
from j1939.history import detail


class HourmeterHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "engine.sqlite"
        EvidenceStore(self.db).migrate_evidence(create=True)
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,observed_from_utc,observed_until_utc,ended_at_utc,status,active,initial_rpm,final_rpm,quality) VALUES('s','g','e','2031-01-01T10:00:00Z','2031-01-01T11:00:00Z','2031-01-01T11:00:00Z','INDETERMINADA',0,1500,0,'INCOMPLETE')")
            c.commit()

    def event(self, ident, when, sample_time, value, kind='STATE_RECONCILED', **overrides):
        sample = dict(key='engine_total_hours', pgn=0xFEE5, spn=247, sourceAddress=234,
                      unit='h', available=True, quality='GOOD', confidence='CONFIRMED',
                      value=value, timestampUtc=sample_time)
        sample.update(overrides)
        snapshot = dict(kind='j1939_signal_snapshot_v2', evaluatedAtUtc=when,
                        maxSampleAgeSeconds=5, signals=[sample])
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,source_address,reason,evidence_quality,evidence_ref,recorded_at_utc) VALUES(?,?,?, ?,?,'RUNNING','STOPPED',234,'synthetic','GOOD',?,?)", (ident,'g','e',when,kind,json.dumps(snapshot),when))
            if kind == 'START':
                c.execute("UPDATE j1939_engine_sessions SET start_event_id=?, started_at_utc=? WHERE session_id='s'",(ident,when))
            if kind == 'STOP':
                c.execute("UPDATE j1939_engine_sessions SET stop_event_id=? WHERE session_id='s'",(ident,))
            c.commit()

    def test_prior_post_and_stop_are_distinct_and_verified(self):
        self.event('before','2031-01-01T10:00:00Z','2031-01-01T09:59:59Z',100)
        self.event('stop','2031-01-01T11:00:00Z','2031-01-01T10:59:59Z',101,'STOP')
        self.event('after','2031-01-01T11:00:03Z','2031-01-01T11:00:02Z',102)
        d=detail(self.db,'s'); h=d['hourmeter_observations']
        self.assertIsNone(h['start'])
        self.assertEqual((h['prior']['value'], h['stop']['value'], h['posterior']['value']), (100,101,102))
        self.assertEqual(h['delta'],2)
        self.assertEqual(d['initial_rpm'],1500)
        self.assertEqual(d['final_rpm'],0)
        self.assertIsNone(d['rpm_max'])
        self.assertIn('unconfirmed_start',d['warnings'])

    def test_wrong_ecu_stale_future_and_decreasing_are_excluded(self):
        self.event('bad_ecu','2031-01-01T10:00:00Z','2031-01-01T09:59:59Z',50,sourceAddress=235)
        self.event('stale','2031-01-01T10:00:00Z','2031-01-01T09:59:50Z',50)
        self.event('future','2031-01-01T10:00:00Z','2031-01-01T10:00:01Z',50)
        self.event('stop','2031-01-01T11:00:00Z','2031-01-01T10:59:59Z',101,'STOP')
        h=detail(self.db,'s')['hourmeter_observations']
        self.assertIsNone(h['prior']); self.assertIsNone(h['posterior']); self.assertIsNone(h['delta'])
        self.event('before','2031-01-01T10:00:00Z','2031-01-01T09:59:59Z',102)
        self.event('after','2031-01-01T11:00:02Z','2031-01-01T11:00:01Z',100)
        self.assertIsNone(detail(self.db,'s')['hourmeter_delta'])

    def test_start_association_requires_real_start_event(self):
        self.event('start','2031-01-01T10:00:00Z','2031-01-01T09:59:59Z',100,'START')
        h=detail(self.db,'s')['hourmeter_observations']
        self.assertEqual(h['start']['event_id'],'start')
        self.assertEqual(h['prior']['value'],100)
        self.assertIsNone(h['stop'])


if __name__ == '__main__':
    unittest.main()
