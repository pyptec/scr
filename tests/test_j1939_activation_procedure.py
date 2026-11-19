"""Exercise the exact administrative Python blocks published in the runbook."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from j1939.engine_store import EngineStore
from j1939.integration import build_integration

ROOT=Path(__file__).resolve().parent.parent
DOC=ROOT/'docs/j1939/ACTIVACION_SAMEE100_ALKOSTO.md'


def published_python(marker):
    text=DOC.read_text(encoding='utf-8')
    block=text.split('<!-- '+marker+' -->',1)[1].split('```bash',1)[1].split('```',1)[0]
    code=block.split("<<'PY'",1)[1].rsplit('\nPY',1)[0]
    namespace={'__name__':'activation_procedure_test'}
    exec(compile(code,str(DOC)+':'+marker,'exec'),namespace)
    return namespace


class ActivationProcedureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.directory=self.root/'samee100-j1939'; self.directory.mkdir()
        self.database=self.directory/'engine.sqlite'
        self.admin=published_python('SQLITE_PREPARE_TESTABLE')
        self.addCleanup(self.temp.cleanup)

    def test_fresh_database_and_repeat_are_verified_without_second_write(self):
        self.admin['prepare'](self.database)
        before=self.database.read_bytes()
        self.admin['prepare'](self.database)
        self.assertEqual(before,self.database.read_bytes())
        self.assertEqual(self.admin['check'](self.database),2)

    def test_measurement_database_is_rejected_without_change(self):
        with closing(sqlite3.connect(self.database)) as c:
            c.execute('CREATE TABLE mediciones(value REAL)'); c.commit()
        before=self.database.read_bytes()
        with self.assertRaises(sqlite3.OperationalError): self.admin['prepare'](self.database)
        self.assertEqual(before,self.database.read_bytes())

    def test_forged_checksum_is_rejected_without_change(self):
        self.admin['prepare'](self.database)
        with closing(sqlite3.connect(self.database)) as c:
            c.execute("UPDATE j1939_schema_migrations SET checksum='forged' WHERE version=2"); c.commit()
        before=self.database.read_bytes()
        with self.assertRaises(RuntimeError): self.admin['prepare'](self.database)
        self.assertEqual(before,self.database.read_bytes())

    def test_real_schema_checked_beyond_migration_checksums(self):
        self.admin['prepare'](self.database)
        with closing(sqlite3.connect(self.database)) as c:
            c.execute('DROP INDEX idx_j1939_evidence_session_time'); c.commit()
        before=self.database.read_bytes()
        with self.assertRaises(RuntimeError): self.admin['prepare'](self.database)
        self.assertEqual(before,self.database.read_bytes())

    def test_empty_version_one_can_be_upgraded(self):
        EngineStore(self.database).migrate(create=True)
        self.admin['prepare'](self.database)
        self.assertEqual(self.admin['check'](self.database),2)

    def test_version_one_with_operational_data_is_not_migrated(self):
        store=EngineStore(self.database); store.migrate(create=True)
        store.begin_run('test-gateway','test-equipment','test-writer',datetime.now(timezone.utc))
        before=self.database.read_bytes()
        with self.assertRaises(RuntimeError): self.admin['prepare'](self.database)
        self.assertEqual(before,self.database.read_bytes())

    def test_unknown_empty_file_is_not_assumed_to_be_new_database(self):
        self.database.touch()
        with self.assertRaises(sqlite3.OperationalError): self.admin['prepare'](self.database)
        self.assertEqual(self.database.stat().st_size,0)

    def test_relative_or_unprepared_directory_rejected_without_creation(self):
        for p in (Path('samee100-j1939/engine.sqlite'),self.root/'missing/samee100-j1939/engine.sqlite'):
            with self.assertRaises(RuntimeError): self.admin['prepare'](p)
        self.assertFalse((self.root/'missing').exists())

    def test_reference_config_is_scoped_and_can_be_validated_without_workers(self):
        raw=json.loads((ROOT/'config/samee100_alkosto_j1939.reference.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['signal_sources'],{'engine_speed':234})
        self.assertEqual(raw['detector']['source_address'],234)
        self.assertNotIn('synthetic-',raw['gateway_id'])
        self.assertNotIn('synthetic-',raw['detector']['equipment_id'])
        self.assertFalse(raw['_activation_review']['identifiers_confirmed'])
        self.assertFalse(raw['_activation_review']['thresholds_calibrated'])
        self.assertFalse(raw['_activation_review']['field_rate_validated'])
        self.assertEqual(raw['evidence']['pre_seconds'],60)
        self.assertEqual(raw['evidence']['post_seconds'],60)
        self.assertFalse(raw['evidence']['retention_enabled'])
        self.admin['prepare'](self.database)
        raw['database']=str(self.database); raw['evidence']['directory']=str(self.root/'raw')
        cfg=self.root/'reference.json'; cfg.write_text(json.dumps(raw),encoding='utf-8')
        observer=build_integration(dict(engine_events_enabled=True,auto_evidence_enabled=True,engine_config=str(cfg)),start=False)
        self.assertIsNone(observer.recorder._thread)
        self.assertIsNone(observer.evidence._thread)
        self.assertFalse((self.root/'raw').exists())

    def test_rate_audit_uses_selected_pairs_and_counts_bad_or_unordered_rows(self):
        audit=published_python('RATE_AUDIT_TESTABLE')
        p=self.root/'archive.log'
        p.write_text('(1000.0) can0 0CF004EA#FFFFFF0000FFFFFF\n'
                     '(1000.5) can0 0CF004EA#FFFFFF0000FFFFFF\n'
                     '(1001.0) can0 0CF004EA#FFFFFF0000FFFFFF\n'
                     '(1001.1) can0 18FEEDEB#0000000000000000\n'
                     '(1000.25) can0 0CF004EA#FFFFFF0000FFFFFF\nmalformed\n',encoding='utf-8')
        r=audit['analyze'](p,'candump',{(0xF004,0xEA)})
        self.assertEqual(r['selectedFrames'],4)
        self.assertEqual(r['pairs']['F004/EA'],4)
        self.assertEqual(r['pairs']['FEED/EB'],1)
        self.assertEqual(r['invalid'],1)
        self.assertEqual(r['outOfOrder'],1)
        self.assertEqual(r['spanSeconds'],1)
        self.assertEqual(r['peakOneSecondUpperBound'],4)
        self.assertEqual(r['recommendedBuffer90sWith50PercentMargin'],540)

    def test_all_published_bash_blocks_parse_without_execution(self):
        git_bash=Path('C:/Program Files/Git/bin/bash.exe')
        bash=str(git_bash) if git_bash.is_file() else shutil.which('bash')
        if not bash: self.skipTest('Bash unavailable; no Linux operational validation')
        blocks=re.findall(r'```bash\n(.*?)```',DOC.read_text(encoding='utf-8'),re.S)
        self.assertGreater(len(blocks),10)
        for i,block in enumerate(blocks,1):
            result=subprocess.run([bash,'-n'],input=block,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,f'block {i}: {result.stderr}')


if __name__=='__main__':
    unittest.main()
