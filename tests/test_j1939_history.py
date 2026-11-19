from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from urllib.request import urlopen
from urllib.error import HTTPError
from j1939.service import start_local_api
from j1939.evidence_store import EvidenceStore
from j1939.history import detail, sessions, verify_evidence, verify_registered_evidence
import os
from j1939.state import SignalState
from j1939.models import DecodedSignal
from datetime import datetime, timezone, timedelta
import hashlib
import json


class HistoryTests(unittest.TestCase):
    def test_read_only_indeterminate_session_and_pagination(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "engine.sqlite"
            EvidenceStore(path).migrate_evidence(create=True)
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,
                    observed_from_utc,observed_until_utc,status,active,initial_hourmeter,final_hourmeter,
                    verified_seconds,quality) VALUES(?,?,?,?,?,'INDETERMINADA',0,712.25,712.80,1234.567,'INCOMPLETE')""",
                    ('synthetic:session','g','e','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z'))
                c.commit()
            with closing(sqlite3.connect(path)) as c:
                before = list(c.iterdump())
            item = detail(path, 'synthetic:session')
            self.assertIsNone(item['started_at_utc'])
            self.assertAlmostEqual(item['hourmeter_delta'], .55)
            self.assertIn('unconfirmed_start', item['warnings'])
            self.assertIn('raw_evidence_incomplete_or_missing', item['warnings'])
            self.assertEqual(len(sessions(path, 1, 0)), 1)
            self.assertEqual(sessions(path, 1, 1), [])
            self.assertIsNone(detail(path, 'missing'))
            with self.assertRaises(ValueError): sessions(path, 101, 0)
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(before, list(c.iterdump()))

    def test_http_queries_and_invalid_pagination(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "engine.sqlite"
            EvidenceStore(path).migrate_evidence(create=True)
            runtime = SimpleNamespace(engine_integration=SimpleNamespace(recorder=SimpleNamespace(store=SimpleNamespace(path=path), status=lambda: {})), state=SimpleNamespace(signals=lambda: []))
            server, thread = start_local_api(runtime, '127.0.0.1', 0)
            try:
                base = 'http://127.0.0.1:' + str(server.server_port)
                with urlopen(base + '/api/j1939/engine/sessions?limit=1') as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'"sessions": []', response.read())
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/api/j1939/engine/sessions?limit=101')
                self.assertEqual(error.exception.code, 400)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/api/j1939/engine/sessions/unknown')
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_event_snapshot_only_accepts_available_ea_temperature(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'engine.sqlite'
            EvidenceStore(path).migrate_evidence(create=True)
            samples = [dict(key='coolant_temperature', pgn=0xFEEE, sourceAddress=0xEA,
                            available=True, quality='GOOD', confidence='CONFIRMED', value=62, timestampUtc='2031-04-12T14:25:29Z')]
            ref = json.dumps(dict(kind='j1939_signal_snapshot_v1', signals=samples))
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,
                          previous_state,current_state,source_address,reason,evidence_quality,evidence_ref,recorded_at_utc)
                          VALUES('stop','g','e','2031-04-12T14:25:30Z','STOP','RUNNING','STOPPED',234,'test','GOOD',?,'2031-04-12T14:25:30Z')""", (ref,))
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,stop_event_id,
                    observed_from_utc,observed_until_utc,status,active,quality)
                    VALUES('s','g','e','stop','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z','INDETERMINADA',0,'INCOMPLETE')""")
                c.commit()
            item = detail(path, 's')
            self.assertEqual(item['coolant_last'], 62)
            self.assertIn('legacy_snapshot_freshness_limit_unknown', item['warnings'])
            self.assertIsNone(item['coolant_first'])
            self.assertIsNone(item['rpm_max'])
            self.assertIn('unconfirmed_start', item['warnings'])
            self.assertEqual(item['event_measurements']['STOP']['coolant_temperature']['timestampUtc'], '2031-04-12T14:25:29Z')

    def test_snapshot_after_stop_is_not_attributed_to_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'engine.sqlite'; EvidenceStore(path).migrate_evidence(create=True)
            snapshot = json.dumps({'kind':'j1939_signal_snapshot_v1', 'signals':[{'key':'coolant_temperature','pgn':0xFEEE,'sourceAddress':234,'available':True,'quality':'GOOD','confidence':'CONFIRMED','value':62,'timestampUtc':'2031-04-12T14:25:31Z'}]})
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,source_address,reason,evidence_quality,evidence_ref,recorded_at_utc) VALUES('stop','g','e','2031-04-12T14:25:30Z','STOP','RUNNING','STOPPED',234,'synthetic','GOOD',?,'2031-04-12T14:25:30Z')""", (snapshot,))
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,stop_event_id,observed_from_utc,observed_until_utc,status,active,quality) VALUES('s','g','e','stop','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z','INDETERMINADA',0,'INCOMPLETE')""")
                c.commit()
            self.assertIsNone(detail(path, 's')['coolant_last'])

    def test_unconfirmed_coolant_snapshot_is_not_associated(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite'; EvidenceStore(path).migrate_evidence(create=True)
            sample={'key':'coolant_temperature','pgn':0xFEEE,'sourceAddress':234,'available':True,'quality':'GOOD','confidence':'PROBABLE','value':62,'timestampUtc':'2031-04-12T14:25:29Z'}
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,source_address,reason,evidence_quality,evidence_ref,recorded_at_utc) VALUES('stop','g','e','2031-04-12T14:25:30Z','STOP','RUNNING','STOPPED',234,'synthetic','GOOD',?,'2031-04-12T14:25:30Z')""", (json.dumps({'kind':'j1939_signal_snapshot_v1','signals':[sample]}),))
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,stop_event_id,observed_from_utc,observed_until_utc,status,active,quality) VALUES('s','g','e','stop','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z','INDETERMINADA',0,'INCOMPLETE')"""); c.commit()
            self.assertIsNone(detail(path,'s')['coolant_last'])

    def test_snapshot_v2_checks_recorded_freshness_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite'; EvidenceStore(path).migrate_evidence(create=True)
            sample={'key':'coolant_temperature','pgn':0xFEEE,'sourceAddress':234,'available':True,'quality':'GOOD','confidence':'CONFIRMED','value':62,'timestampUtc':'2031-04-12T14:25:29Z'}
            snapshot={'kind':'j1939_signal_snapshot_v2','evaluatedAtUtc':'2031-04-12T14:25:30Z','maxSampleAgeSeconds':1,'signals':[sample]}
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,source_address,reason,evidence_quality,evidence_ref,recorded_at_utc) VALUES('stop','g','e','2031-04-12T14:25:30Z','STOP','RUNNING','STOPPED',234,'synthetic','GOOD',?,'2031-04-12T14:25:30Z')""",(json.dumps(snapshot),))
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,stop_event_id,observed_from_utc,observed_until_utc,status,active,quality) VALUES('s','g','e','stop','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z','INDETERMINADA',0,'INCOMPLETE')"""); c.commit()
                self.assertEqual(detail(path,'s')['coolant_last'],62)
                snapshot['maxSampleAgeSeconds']=0.5
                c.execute("UPDATE j1939_engine_events SET evidence_ref=? WHERE event_id='stop'",(json.dumps(snapshot),)); c.commit()
                self.assertIsNone(detail(path,'s')['coolant_last'])
                snapshot.pop('maxSampleAgeSeconds')
                c.execute("UPDATE j1939_engine_events SET evidence_ref=? WHERE event_id='stop'",(json.dumps(snapshot),)); c.commit()
                self.assertIsNone(detail(path,'s')['coolant_last'])

    def test_ecu_values_are_independent(self):
        state = SignalState(heartbeat_seconds=60)
        now = datetime(2026, 11, 19, tzinfo=timezone.utc)
        def signal(sa, value, stamp):
            return DecodedSignal('engine_speed', 'RPM', value, 1, 'rpm', 0xF004, sa, stamp, 'GOOD', 'CONFIRMED', {})
        state.update(signal(0xEA, 1800, now))
        state.update(signal(0xEB, 0, now + timedelta(seconds=1)))
        self.assertEqual(state.signals()[0]['sourceAddress'], 'EB')
        self.assertEqual(state.signals_by_source(0xEA)[0]['value'], 1800)
        state.update(signal(0xEA, 99, now - timedelta(seconds=1)))
        self.assertEqual(state.signals_by_source(0xEA)[0]['value'], 1800)

    def test_future_sample_cannot_poison_source_cache(self):
        state = SignalState()
        now = datetime(2026, 11, 19, tzinfo=timezone.utc)
        def make(value, timestamp):
            return DecodedSignal('engine_speed', 'RPM', value, 1, 'rpm', 0xF004, 0xEA, timestamp, 'GOOD', 'CONFIRMED', {})
        state.update(make(1800, now), received_at=now)
        state.update(make(3000, now + timedelta(days=1)), received_at=now)
        state.update(make(1850, now + timedelta(seconds=1)), received_at=now + timedelta(seconds=1))
        self.assertEqual(state.signals_by_source(0xEA)[0]['value'], 1850)

    def test_evidence_hash_and_temporal_status_are_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'raw.txt'
            file.write_bytes(b'synthetic raw')
            segment = dict(file_path=str(file), size_bytes=13, sha256=hashlib.sha256(b'synthetic raw').hexdigest(), integrity='INCOMPLETE', close_reason='interruption', manifest_json='{"warnings":["gap"]}')
            result = verify_evidence(segment)
            self.assertTrue(result['sha256_match'])
            self.assertTrue(result['size_match'])
            self.assertEqual(result['temporal_integrity'], 'INCOMPLETE')
            self.assertEqual(result['warnings'], ['gap'])
            segment['sha256'] = '0' * 64
            self.assertFalse(verify_evidence(segment)['sha256_match'])
            self.assertEqual(verify_evidence(segment, max_bytes=1)['error'], 'SIZE_LIMIT_EXCEEDED')
            file.unlink()
            self.assertEqual(verify_evidence(segment)['error'], 'FILE_NOT_FOUND')

    def test_registered_evidence_confines_paths_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); raw = root / 'raw'; raw.mkdir()
            path = root / 'engine.sqlite'; EvidenceStore(path).migrate_evidence(create=True)
            name = 'j1939_auto_' + 'a' * 32 + '_' + 'b' * 32 + '.txt'
            file = raw / name; file.write_bytes(b'synthetic')
            values = ('seg','capture','batch','sid',str(file),'2026-01-01Z','2026-01-01Z',1,'[]','[]',9,'INCOMPLETE','interruption',hashlib.sha256(b'synthetic').hexdigest(),'{}')
            with closing(sqlite3.connect(path)) as c:
                c.execute('INSERT INTO j1939_evidence_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values); c.commit()
            result = verify_registered_evidence(path, 'sid', 'seg', raw)
            if not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
                self.assertEqual(result['error'], 'SECURE_OPEN_UNSUPPORTED')
            else:
                self.assertTrue(result['sha256_match'])
                self.assertEqual(result['temporal_integrity'], 'INCOMPLETE')
                self.assertEqual(verify_registered_evidence(path, 'sid', 'seg', raw, max_bytes=1)['error'], 'SIZE_LIMIT_EXCEEDED')
                file.unlink()
                self.assertEqual(verify_registered_evidence(path, 'sid', 'seg', raw)['error'], 'FILE_NOT_FOUND')
            with closing(sqlite3.connect(path)) as c:
                c.execute('UPDATE j1939_evidence_segments SET file_path=?', (str(root / name),)); c.commit()
            self.assertEqual(verify_registered_evidence(path, 'sid', 'seg', raw)['error'], 'PATH_NOT_AUTHORIZED')
            with self.assertRaises(ValueError): verify_registered_evidence(path, '../sid', 'seg', raw)
            self.assertIsNone(verify_registered_evidence(path, 'sid', 'unknown', raw))
            runtime = SimpleNamespace(engine_integration=SimpleNamespace(recorder=SimpleNamespace(store=SimpleNamespace(path=path)), evidence=SimpleNamespace(config=SimpleNamespace(directory=raw))))
            server, thread = start_local_api(runtime, '127.0.0.1', 0)
            try:
                url = 'http://127.0.0.1:' + str(server.server_port) + '/api/j1939/engine/evidence/sid/seg/verify'
                with urlopen(url) as response:
                    payload = json.load(response)
                self.assertEqual(payload['error'], 'PATH_NOT_AUTHORIZED')
                self.assertNotIn('file_path', payload)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_synthetic_session_api(self):
        # Synthetic database: field observations are not attributed to event samples.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.sqlite'
            EvidenceStore(path).migrate_evidence(create=True)
            with closing(sqlite3.connect(path)) as c:
                c.execute("""INSERT INTO j1939_engine_events(event_id,gateway_id,equipment_id,timestamp_utc,event_type,previous_state,current_state,rpm,source_address,reason,evidence_quality,recorded_at_utc) VALUES('stop','g','e','2031-04-12T14:25:30Z','STOP','RUNNING','STOPPED',0,234,'synthetic','GOOD','2031-04-12T14:25:30Z')""")
                c.execute("""INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,stop_event_id,started_at_utc,ended_at_utc,observed_from_utc,observed_until_utc,status,active,initial_rpm,final_rpm,verified_seconds,quality) VALUES('synthetic-session','g','e','stop',NULL,'2031-04-12T14:25:30Z','2031-04-12T13:52:47Z','2031-04-12T14:25:30Z','INDETERMINADA',0,1555.125,0,1234.567,'INCOMPLETE')""")
                for i, (start, end) in enumerate((('2031-04-12T13:51:32Z','2031-04-12T13:52:47Z'), ('2031-04-12T14:22:13Z','2031-04-12T14:23:38Z'))):
                    c.execute("INSERT INTO j1939_observation_gaps(gap_id,gateway_id,equipment_id,session_id,started_at_utc,recovered_at_utc,reason) VALUES(?,?,?,?,?,?,?)", (f'gap{i}','g','e','synthetic-session',start,end,'process_restart'))
                for i, (frames, size, reason, warnings) in enumerate(((35377,2689423,'recovered_incomplete',['prebuffer_short','process_interruption','unconfirmed_start']), (3488,265998,'post_stop_elapsed',['prebuffer_short','unconfirmed_start']))):
                    c.execute('INSERT INTO j1939_evidence_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (f'seg{i}','synthetic-capture','batch','synthetic-session',f'synthetic-{i}.txt',None,None,frames,'[]','[]',size,'INCOMPLETE',reason,None,json.dumps({'warnings':warnings})))
                c.commit()
            runtime = SimpleNamespace(engine_integration=SimpleNamespace(recorder=SimpleNamespace(store=SimpleNamespace(path=path))))
            server, thread = start_local_api(runtime, '127.0.0.1', 0)
            try:
                with urlopen('http://127.0.0.1:' + str(server.server_port) + '/api/j1939/engine/sessions/synthetic-session') as response:
                    item = json.load(response)
            finally:
                server.shutdown(); server.server_close(); thread.join()
            self.assertEqual(item['status'], 'INDETERMINADA')
            self.assertIsNone(item['started_at_utc'])
            self.assertEqual(item['ended_at_utc'], '2031-04-12T14:25:30Z')
            self.assertAlmostEqual(item['verified_seconds'], 1234.567)
            self.assertEqual(len(item['observation_gaps']), 2)
            self.assertEqual(len(item['evidence']), 2)
            self.assertEqual(sum(e['frame_count'] for e in item['evidence']), 38865)
            self.assertTrue(all(e['integrity'] == 'INCOMPLETE' for e in item['evidence']))
            self.assertIn('process_interruption', json.loads(item['evidence'][0]['manifest_json'])['warnings'])
            self.assertIsNone(item['coolant_last'])
            self.assertIsNone(item['initial_hourmeter'])
            self.assertIsNone(item['final_hourmeter'])
            self.assertIsNone(item['hourmeter_delta'])

    def test_absent_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError): sessions(path)
            self.assertFalse(path.exists())

if __name__ == '__main__': unittest.main()
