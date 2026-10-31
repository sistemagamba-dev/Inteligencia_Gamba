import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

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


class GoogleAccessInterfaceTests(unittest.TestCase):
    """Modo google com login simulado (st.user) e Adm sobre fakes; nenhuma chamada ao Google."""
    def setUp(self):
        from acesso import AccessManager
        from tests.test_acesso import ADMIN, OPER, FakeAcl, FakeRegistry
        self.admin, self.oper = ADMIN, OPER
        InterfaceTests.setUp(self)
        self.log = []
        self.registry, self.acl = FakeRegistry(self.log, {OPER}), FakeAcl(self.log)
        self.acl.share_entrada(OPER)
        del self.log[:]
        self.flow.access = AccessManager(self.registry, self.acl, admins=[ADMIN])
        self.user = SimpleNamespace(is_logged_in=True, email=OPER)
        for patcher in (patch.object(st, 'user', self.user), patch.dict(os.environ, {'JANUS_MODE': 'google'})):
            patcher.start()
            self.addCleanup(patcher.stop)

    button, records = InterfaceTests.button, InterfaceTests.records

    def run_app(self, email):
        self.user.email = email
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        return app

    def texts(self, app):
        return ' '.join(e.value for e in (*app.markdown, *app.caption, *app.info, *app.warning,
                                           *app.error, *app.success))

    def test_operator_works_without_adm(self):
        app = self.run_app(self.oper)
        self.assertFalse([e for e in app.expander if e.label == 'Adm'])
        self.assertNotIn(self.admin, self.texts(app))
        self.button(app, 'Processar PDFs').click().run()
        self.assertEqual(len(app.session_state['batch']['rows']), 3)
        reads, active = [], self.registry.active
        self.registry.active = lambda: reads.append(1) or active()
        app.run().run()  # Edições da tabela: autorização em cache por até 30 s.
        self.assertEqual(reads, [])
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertEqual(len(reads), 1)  # Ação sensível: leitura atual.
        self.assertIn('3 novos registrados', app.success[0].value)

    def test_unauthorized_or_unreadable_registry_loads_nothing(self):
        for email, fail in (('outra@example.org', set()), (None, set()), (self.oper, {'read'})):
            with self.subTest(email=email, fail=fail):
                self.registry.fail = fail
                app = self.run_app(email)
                self.assertIn('Acesso não autorizado', app.error[0].value)
                self.assertEqual([b.label for b in app.button], ['Sair'])
                self.assertFalse(app.expander)

    def test_session_blocked_after_removal(self):
        app = self.run_app(self.oper)
        self.button(app, 'Processar PDFs').click().run()
        self.registry.emails.clear()  # Removido por um Adm em outra sessão.
        self.button(app, 'Aprovar e registrar tudo').click().run()
        self.assertFalse(app.exception)
        self.assertIn('Seu acesso foi removido.', app.error[0].value)
        self.assertEqual(self.records(), {})
        self.assertNotIn('batch', app.session_state)
        for label in ('Processar PDFs', 'Preparar Excel da base'):
            self.registry.emails.add(self.oper)
            app = self.run_app(self.oper)
            self.registry.emails.clear()
            self.button(app, label).click().run()
            self.assertIn('Seu acesso foi removido.', app.error[0].value)
            self.assertNotIn('export', app.session_state)

    def adm_add(self, app, email):
        next(t for t in app.text_input if t.label == 'E-mail Google do assessor').input(email)
        self.button(app, 'Adicionar').click().run()
        self.assertFalse(app.exception)
        return app

    def test_admin_adds_and_removes(self):
        app = self.run_app(self.admin)
        self.assertEqual([e.label for e in app.expander], ['Adm'])
        app = self.adm_add(app, 'Novo@Example.org')
        self.assertIn('Acesso liberado', app.success[0].value)
        self.assertTrue(self.flow.access.is_authorized('novo@example.org'))
        self.assertIn('novo@example.org · JANUS: liberado · Pasta: compartilhada', self.texts(app))
        del self.log[:]
        next(b for b in app.button if b.key == 'remover_novo@example.org').click().run()
        self.assertIn('Acesso removido', app.success[0].value)
        self.assertEqual([e[0] for e in self.log], ['registry.remove', 'drive.revoke'])
        self.assertFalse(self.flow.access.is_authorized('novo@example.org'))

    def test_admin_partial_failures_show_pending(self):
        app = self.run_app(self.admin)
        self.acl.fail = {'share'}
        app = self.adm_add(app, 'falha@example.org')
        self.assertIn('não foi liberado', app.warning[0].value)
        self.assertFalse(self.flow.access.is_authorized('falha@example.org'))
        self.acl.fail, self.registry.fail = set(), {'add'}
        app = self.adm_add(app, 'falha@example.org')
        self.assertIn('não foi registrado', app.warning[0].value)
        self.assertFalse(self.flow.access.is_authorized('falha@example.org'))
        self.assertIn('Pendências na pasta de entrada', self.texts(app))
        self.registry.fail = set()
        next(b for b in app.button if b.key == 'revogar_falha@example.org').click().run()
        self.assertIn('Permissão na pasta revogada', app.success[0].value)
        self.assertNotIn('Pendências', self.texts(app))
        self.acl.fail = {'revoke'}
        next(b for b in app.button if b.key == 'remover_' + self.oper).click().run()
        self.assertIn('permissão na pasta continua', app.warning[0].value)
        self.assertFalse(self.flow.access.is_authorized(self.oper))
        self.assertTrue(next(b for b in app.button if b.key == 'revogar_' + self.oper))

    def test_admin_refusals_and_handlers_recheck(self):
        app = self.run_app(self.admin)
        app = self.adm_add(app, self.admin)
        self.assertIn('Administradores', app.warning[0].value)
        app = self.adm_add(app, 'dono@example.org')
        self.assertIn('conta é do sistema', app.warning[0].value)
        self.assertEqual(self.log, [])
        # Ocultar não basta: o clique confere de novo (Adm visível ao desenhar, retirado ao clicar).
        self.flow.access.is_admin = Mock(side_effect=[True, False])
        app = self.adm_add(app, 'outro@example.org')
        self.assertIn('Seu acesso foi removido.', app.error[0].value)
        self.assertEqual(self.log, [])
        self.flow.access.is_admin = lambda email: False  # Sem Adm na configuração: menu some.
        app = self.run_app(self.admin)
        self.assertFalse(app.expander)
        with self.assertRaises(PermissionError):
            self.flow.access.status(self.admin)

    def test_drive_status_error_is_plain(self):
        self.acl.fail = {'list'}
        app = self.run_app(self.admin)
        self.assertIn('Não foi possível consultar', app.error[0].value)
        self.acl.can_share, self.acl.fail = False, set()
        self.button(app, 'Atualizar lista').click().run()
        self.assertIn('conta técnica não tem permissão', app.warning[0].value)
