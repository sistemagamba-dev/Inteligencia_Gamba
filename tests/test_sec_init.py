"""Nenhum recurso privado antes da autorização (PR #9, ponto 3).

Modo google de ponta a ponta com runtime, GoogleDrive, GoogleSheets e UsersRegistry reais:
só a credencial e a sessão HTTP são falsas e registram cada chamada. Nenhum acesso ao Google.
"""
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
import runtime

ADMIN, OPER, SA = 'adm@example.org', 'op@example.org', 'sa@projeto.iam.gserviceaccount.com'
FOLDERS = {'raiz': 'JANUS_TESTE_SEC', 'inbox': None, 'done': None, 'failed': None}
ENV = {'JANUS_MODE': 'google', 'JANUS_SHEET_ID': 'planilha', 'JANUS_ROOT': 'raiz',
       'JANUS_ENTRADA': 'inbox', 'JANUS_PROCESSADOS': 'done', 'JANUS_FALHAS': 'failed',
       'JANUS_ADMIN_EMAILS': ADMIN, 'JANUS_GOOGLE_SA_JSON': json.dumps({'client_email': SA})}
METADATA = 'id,name,mimeType,parents,trashed'


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Substitui AuthorizedSession: responde como Drive v3 / Sheets v4 mínimos e registra tudo."""
    log, created = [], []

    def __init__(self, credentials):
        FakeSession.created.append(credentials)

    def _kind(self, url):
        if 'googleapis.com/drive' in url:
            return 'drive'
        return 'usuarios' if 'usuarios' in url else 'journal' if 'journal' in url else 'outro'

    def request(self, method, url, params=None, **kwargs):
        params = params or {}
        FakeSession.log.append((self._kind(url), method, url, params.get('fields', '')))
        path = url.split('/drive/v3/files')[-1].strip('/').split('/')
        if method == 'GET' and len(path) == 2 and path[1] == 'permissions':
            return Response({'permissions': []})
        if method == 'GET' and len(path) == 1 and path[0]:
            fields = params.get('fields')
            if fields == 'capabilities(canShare)':
                return Response({'capabilities': {'canShare': True}})
            if fields == 'owners(emailAddress)':
                return Response({'owners': [{'emailAddress': 'dono@example.org'}]})
            name = FOLDERS.get(path[0]) or path[0]
            return Response({'id': path[0], 'name': name, 'mimeType': 'application/vnd.google-apps.folder',
                             'parents': [] if path[0] == 'raiz' else ['raiz']})
        if method == 'GET':
            return Response({'files': []})  # Entrada vazia.
        raise AssertionError('Chamada inesperada: ' + method + ' ' + url)

    def get(self, url, **kwargs):
        kind = self._kind(url)
        FakeSession.log.append((kind, 'GET', url, ''))
        if kind == 'usuarios':
            return Response({'values': [['ADD', OPER, ADMIN, '2026-10-01T00:00:00+00:00', 'p1', '']]})
        return Response({'values': []})

    def post(self, url, **kwargs):
        raise AssertionError('Escrita inesperada: ' + url)


class Base(unittest.TestCase):
    def setUp(self):
        st.cache_resource.clear()
        FakeSession.log, FakeSession.created = [], []
        self.credentials = []
        clean = {k: v for k, v in os.environ.items() if not k.startswith('JANUS_')}
        self.user = SimpleNamespace(is_logged_in=True, email=OPER)
        for patcher in (
                patch.dict(os.environ, {**clean, **ENV}, clear=True),
                patch('google.auth.transport.requests.AuthorizedSession', FakeSession),
                patch('google.oauth2.service_account.Credentials.from_service_account_info',
                      side_effect=lambda info, scopes: self.credentials.append(info) or 'cred'),
                patch.object(st, 'user', self.user)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(st.cache_resource.clear)

    def kinds(self):
        return [entry[0] for entry in FakeSession.log]

    def drive_metadata(self, folder):
        return [e for e in FakeSession.log if e[0] == 'drive' and e[2].endswith('/' + folder) and e[3] == METADATA]

    def run_app(self, email, app=None):
        self.user.email = email
        app = (app or AppTest.from_file('app.py', default_timeout=30)).run()
        self.assertFalse(app.exception)
        return app


class AppInitTests(Base):
    def test_unauthorized_user_touches_only_registry(self):
        app = AppTest.from_file('app.py', default_timeout=30)
        for key, value in (('export', b'PK'), ('batch', {'id': 'x'}), ('adm', {}), ('auth', ('x', 0))):
            app.session_state[key] = value
        app = self.run_app('estranho@example.org', app)
        self.assertIn('Acesso não autorizado', app.error[0].value)
        self.assertEqual([b.label for b in app.button], ['Sair'])
        # Só a leitura do cadastro: nenhum metadado do Drive, nenhum journal, nenhuma ACL.
        self.assertEqual(self.kinds(), ['usuarios'])
        for key in ('export', 'batch', 'adm', 'auth'):
            self.assertNotIn(key, app.session_state)

    def test_unreadable_registry_denies_without_drive(self):
        with patch.object(FakeSession, 'get', side_effect=ConnectionError('fora do ar')):
            app = self.run_app(OPER)
        self.assertIn('Acesso não autorizado', app.error[0].value)
        self.assertEqual(self.kinds(), [])

    def test_anonymous_constructs_nothing(self):
        self.user.is_logged_in = False
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual((FakeSession.created, self.credentials, FakeSession.log), ([], [], []))
        self.assertNotIn('Sair', [b.label for b in app.button])

    def test_authorized_user_gets_workflow(self):
        app = self.run_app(OPER)
        kinds = self.kinds()
        self.assertEqual(kinds[0], 'usuarios')  # Autoriza primeiro...
        self.assertIn('drive', kinds)  # ...depois a raiz e as subpastas são conferidas.
        self.assertIn('journal', kinds)
        self.assertEqual(len(self.drive_metadata('raiz')), 1)
        self.assertEqual(len(FakeSession.created), 1)  # Uma credencial por processo.
        del FakeSession.log[:]
        next(b for b in app.button if b.label == 'Processar PDFs').click().run()
        self.assertFalse(app.exception)
        self.assertIn('A base ainda não foi preparada', app.error[0].value)  # Workflow real leu o journal.
        self.assertEqual(self.kinds()[0], 'usuarios')  # Ação sensível: conferência atual antes do journal.
        self.assertIn('journal', self.kinds())

    def test_admin_reuses_one_drive_for_workflow_and_adm(self):
        app = self.run_app(ADMIN)
        self.assertEqual([e.label for e in app.expander], ['Adm'])
        self.assertFalse(app.error)
        self.assertEqual(len(self.drive_metadata('raiz')), 1)
        self.assertTrue([e for e in FakeSession.log if e[2].endswith('/inbox/permissions')])

    def test_config_errors_fail_before_credentials(self):
        for values in ({'JANUS_ADMIN_EMAILS': 'nao-e-email'},
                       {'JANUS_AMBIENTE': 'producao', 'JANUS_SHEET_ID': runtime.HOMOLOGACAO['sheet']},
                       {'JANUS_AMBIENTE': 'producao', 'JANUS_ROOT': runtime.HOMOLOGACAO['root']},
                       {'JANUS_ROOT': ''}):
            with self.subTest(values=values), patch.dict(os.environ, values):
                st.cache_resource.clear()
                app = self.run_app(OPER)
                self.assertIn('equipe técnica', app.error[0].value)
                self.assertEqual((FakeSession.created, self.credentials, FakeSession.log), ([], [], []))


class RuntimeInitTests(Base):
    def test_access_components_drive_is_lazy(self):
        access = runtime.access_components()
        self.assertEqual(FakeSession.log, [])  # Credencial pronta, nenhuma chamada.
        self.assertTrue(access.is_authorized(ADMIN))  # Admin vem da configuração.
        self.assertEqual(FakeSession.log, [])
        self.assertTrue(access.is_authorized(OPER))
        self.assertEqual(self.kinds(), ['usuarios'])
        self.assertIn(SA, access.protected)
        access.status(ADMIN)  # Primeira ação do Adm: só agora o Drive é construído.
        self.assertEqual(len(self.drive_metadata('raiz')), 1)
        self.assertNotIn('journal', self.kinds())
        flow = runtime.components(access)  # Mesmo Drive, sem nova conferência.
        self.assertIs(flow.access, access)
        self.assertIs(flow.drive, access.drive.get())
        self.assertEqual(len(self.drive_metadata('raiz')), 1)
        self.assertEqual(len(FakeSession.created), 1)

    def test_manage_style_components_builds_everything(self):
        flow = runtime.components()  # Ferramentas técnicas (backup/import): sem login.
        self.assertTrue(flow.access.is_admin(ADMIN))
        self.assertIs(flow.drive, flow.access.drive.get())
        self.assertEqual(len(self.drive_metadata('raiz')), 1)
        self.assertEqual(flow.proof.state()['records'], {})

    def test_config_errors_before_credentials(self):
        with patch.dict(os.environ, {'JANUS_ADMIN_EMAILS': 'a@b'}):
            with self.assertRaisesRegex(ValueError, 'JANUS_ADMIN_EMAILS'):
                runtime.access_components()
        self.assertEqual((FakeSession.created, self.credentials), ([], []))

    def test_invalid_drive_config_surfaces_on_first_drive_use(self):
        with patch.dict(FOLDERS, {'raiz': 'Outra pasta'}):
            access = runtime.access_components()
            self.assertTrue(access.is_authorized(OPER))
            with self.assertRaisesRegex(ValueError, 'raiz de teste'):
                access.status(ADMIN)
            with self.assertRaisesRegex(ValueError, 'raiz de teste'):
                runtime.components(access)

    def test_local_mode_unchanged(self):
        with patch.dict(os.environ, {'JANUS_MODE': 'local'}):
            self.assertIsNone(runtime.access_components())


if __name__ == '__main__':
    unittest.main()
