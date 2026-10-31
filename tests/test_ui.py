import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from drive_adapter import LocalDrive
from experiments.sheets_poc.fake import SimulatedSheets
from experiments.sheets_poc.store import SheetsProof
from manage import demo_files
import runtime
from workflow import SheetsWorkflow


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        st.cache_resource.clear()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        history = demo_files(root)
        self.remote = SimulatedSheets()
        self.proof = SheetsProof(self.remote)
        self.proof.import_history(history.read_bytes())
        self.drive = LocalDrive(root/'drive')
        self.flow = SheetsWorkflow(self.proof, self.drive)
        patcher = patch.object(runtime, 'components', return_value=self.flow)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(st.cache_resource.clear)

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def records(self):
        return self.proof.state()['records']

    def test_clicks_edit_approval_archive_and_export(self):
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.button(app, 'Processar PDFs').click().run()
        self.assertFalse(app.exception)
        batch = app.session_state['batch']
        self.assertEqual((batch['found'], len(batch['rows']), len(batch['duplicates']), len(batch['failures'])), (5,3,1,1))
        self.assertEqual(self.records(), {})
        before = self.remote.rows[:]
        app.session_state['table_' + batch['id']] = {'edited_rows':{0:{'Solicitante':'Pessoa corrigida na interface'}},
                                                     'added_rows':[], 'deleted_rows':[]}
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertFalse(app.exception)
        self.assertIn('3 novos registrados', app.success[0].value)
        self.assertIn('0 arquivamentos pendentes', app.success[0].value)
        self.assertNotEqual(self.remote.rows, before)
        rows = [r['row'] for r in self.records().values()]
        self.assertEqual(len(rows), 3)
        self.assertIn('Pessoa corrigida na interface', [r[2] for r in rows])
        self.assertEqual(len(list((self.drive.root/'processados').iterdir())), 3)
        self.assertEqual(sorted(p.name for p in (self.drive.root/'entrada').iterdir()),
                         ['04-duplicado.pdf', '05-invalido.pdf'])
        self.button(app, 'Preparar Excel da base').click().run()
        self.assertTrue(app.session_state['export'].startswith(b'PK'))
        # Novo processamento: nada novo; duplicado e inválido continuam na entrada.
        self.button(app, 'Processar PDFs').click().run()
        self.assertEqual(len(app.session_state['batch']['rows']), 0)
        self.assertEqual(len(self.records()), 3)

    def test_table_edits_do_not_read_sheets(self):
        calls = []
        original = self.remote.get
        self.remote.get = lambda: calls.append(1) or original()
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.button(app, 'Processar PDFs').click().run()
        batch = app.session_state['batch']
        count = len(calls)
        app.session_state['table_' + batch['id']] = {'edited_rows':{0:{'BAIRRO':'Bairro corrigido'}},
                                                     'added_rows':[], 'deleted_rows':[]}
        app.run().run()
        self.assertEqual(len(calls), count)

    def test_unconfirmed_write_is_retried_without_duplicates(self):
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.button(app, 'Processar PDFs').click().run()
        self.remote.failures.append('before')
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertFalse(app.exception)
        self.assertIn('Gravação não confirmada', app.warning[-1].value)
        self.assertEqual(self.records(), {})
        self.assertEqual(len(list((self.drive.root/'processados').iterdir())), 0)
        self.remote.failures.append('after') # Aplicado no servidor; resposta perdida.
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertFalse(app.exception)
        self.assertIn('3 novos registrados', app.success[0].value)
        self.assertEqual(len(self.records()), 3)

    def test_archive_failure_then_retry_button(self):
        archive = self.drive.archive
        failed = []
        def flaky(file_id, digest):
            if not failed:
                failed.append(file_id)
                raise ConnectionError('Drive indisponível')
            return archive(file_id, digest)
        self.drive.archive = flaky
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.button(app, 'Processar PDFs').click().run()
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertIn('1 arquivamentos pendentes', app.success[0].value)
        self.assertIn('aguardam arquivamento', app.warning[-1].value)
        self.assertTrue((self.drive.root/'entrada'/failed[0]).exists())
        self.button(app, 'Tentar arquivar novamente').click().run()
        self.assertFalse(app.exception)
        self.assertIn('Pendentes: 0', app.info[-1].value)
        self.assertEqual(len(list((self.drive.root/'processados').iterdir())), 3)

    def test_configuration_failure_is_plain_portuguese(self):
        with patch.object(runtime, 'components', side_effect=ValueError('Modo desconhecido')):
            app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertIn('equipe técnica', app.error[0].value)

    def test_google_mode_without_login_configuration_loads_nothing(self):
        with patch.dict(os.environ, {'JANUS_MODE':'google'}):
            app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertIn('não foi configurado', app.error[0].value)
        runtime.components.assert_not_called()

    def test_allowlist_only_in_google_mode(self):
        with patch.dict(os.environ, {'JANUS_MODE':'google', 'JANUS_ALLOWED_EMAILS':' Operador@Example.org '}):
            self.assertTrue(runtime.allowed('operador@example.org'))
            self.assertFalse(runtime.allowed('outra@example.org'))
            self.assertFalse(runtime.allowed(None))
        with patch.dict(os.environ, {'JANUS_MODE':'google', 'JANUS_ALLOWED_EMAILS':''}):
            self.assertFalse(runtime.allowed('operador@example.org'))
        with patch.dict(os.environ, {'JANUS_MODE':'local'}):
            self.assertTrue(runtime.allowed(None))
