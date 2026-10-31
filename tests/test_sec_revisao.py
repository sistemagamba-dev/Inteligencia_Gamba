"""Revisão independente das três correções de segurança do PR #9 (ACL ampla, download, inicialização).

Testes adversariais com fakes; nenhuma chamada ao Google, nenhuma credencial real.
Defeitos residuais reais ficam marcados com @unittest.expectedFailure e um comentário.
"""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

from acesso import AccessManager
from drive_adapter import GoogleDrive
from tests.test_acesso import FakeRegistry
from tests.test_drive_acl import BOT, FakeDrive, perm
from tests import test_sec_init as init

ADMIN = 'chefe@example.org'
OPER = 'assessor@example.org'


def anyone(pid, role='reader', inherited=None):
    p = {'id': pid, 'type': 'anyone', 'role': role}
    if inherited is not None:
        p['permissionDetails'] = [{'inherited': inherited, 'role': role}]
    return p


# ---------------------------------------------------------------- 1. ACL ampla

class AclAdversarialTests(unittest.TestCase):
    def build(self, **kw):
        self.fake = FakeDrive(**kw)
        session = Mock(); session.request.side_effect = self.fake
        self.drive = GoogleDrive(session, 'root', 'inbox', 'done', 'failed')
        self.registry = FakeRegistry([], {OPER})
        self.access = AccessManager(self.registry, self.drive, admins=[ADMIN], protected=[BOT])
        self.fake.calls.clear()

    def setUp(self):
        self.build()

    def deletes(self):
        return [c for c in self.fake.writes() if c[0] == 'DELETE']

    def test_broad_on_last_page_of_both_folders(self):
        self.build(page=1)  # Uma permissão por página: a ampla só aparece na última.
        self.fake.root_perms.append({'id': 'd1', 'type': 'domain', 'role': 'reader', 'domain': 'x.org'})
        self.fake.entrada.append(anyone('a1', inherited=False))
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        self.assertEqual(sorted((a['onde'], a['tipo']) for a in status['amplos']),
                         [('entrada', 'anyone'), ('raiz', 'domain')])
        self.assertTrue(any(c[2].get('pageToken') for c in self.fake.calls))

    def test_read_errors_raise_never_isolated(self):
        original = self.fake.__call__
        for target in ('/inbox/permissions', '/root/permissions'):
            for kind in ('exc', 'http'):
                with self.subTest(target=target, kind=kind):
                    def broken(method, url, **kw):
                        if url.endswith(target) and method == 'GET':
                            if kind == 'exc':
                                raise TimeoutError('lento')
                            return self.fake.resp(status='500')
                        return original(method, url, **kw)
                    self.drive.session.request.side_effect = broken
                    with self.assertRaises(Exception):
                        self.access.status(ADMIN)
                    with self.assertRaises(Exception):
                        self.drive.broad_sharing()

    def test_group_with_operator_email_is_broad_not_direct(self):
        # Grupo cujo endereço coincide com o e-mail de um assessor ativo: não conta como acesso direto.
        self.fake.entrada.append(perm('g1', OPER, 'writer', 'group', inherited=False))
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        self.assertEqual(status['amplos'], [{'onde': 'entrada', 'tipo': 'group', 'papel': 'writer', 'alvo': OPER}])
        self.assertEqual(status['usuarios'], [{'email': OPER, 'app': True, 'pasta': 'ausente'}])
        self.assertEqual(status['pendencias'], [])
        result = self.access.remove(ADMIN, OPER)  # Bloqueia no cadastro; grupo fica intacto.
        self.assertTrue(result['app_bloqueado'])
        self.assertEqual(self.deletes(), [])
        self.assertIn('g1', [p['id'] for p in self.fake.entrada])

    def test_remove_deletes_only_user_permission_when_broad_coexists(self):
        self.fake.entrada += [perm('u1', OPER, 'writer', inherited=False), anyone('a1', inherited=False),
                              perm('g1', 'equipe@example.org', 'writer', 'group', inherited=False)]
        self.access.remove(ADMIN, OPER)
        self.assertEqual([c[1] for c in self.deletes()], ['/inbox/permissions/u1'])
        status = self.access.status(ADMIN)  # Logo após remover, o Adm continua vendo a ACL ampla.
        self.assertFalse(status['isolamento_ok'])
        self.assertEqual({a['tipo'] for a in status['amplos']}, {'anyone', 'group'})

    def test_user_without_email_and_odd_types(self):
        self.fake.entrada += [{'id': 'u1', 'type': 'user', 'role': 'writer',
                               'permissionDetails': [{'inherited': False}]},
                              {'id': 'n1', 'role': 'reader'},  # Sem type.
                              {'id': 'x1', 'type': 'USER', 'role': 'reader', 'emailAddress': 'z@x.org'}]
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        self.assertEqual(sorted(a['tipo'] for a in status['amplos']), ['desconhecido', 'user', 'user'])
        self.assertEqual(status['pendencias'], [])  # Nada sem e-mail/tipo exato vira botão Revogar.

    def test_broad_inherited_from_root_in_my_drive(self):
        # Meu Drive: sem permissionDetails; o 'anyone' herdado aparece na entrada sem sinal de herança.
        self.fake.root_perms.append(anyone('a1'))
        self.fake.entrada.append(anyone('a1'))
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        self.assertIn('raiz', [a['onde'] for a in status['amplos']])

    # Corrigido na integração (antes expectedFailure).
    def test_group_inherited_from_root_listed_once(self):
        # DEFEITO (baixo, cosmético): broad_sharing passa a lista já normalizada (_entry, chave 'email')
        # para entrada_permissions, que procura 'emailAddress'; o conjunto on_root fica vazio e a
        # herança "presença na raiz" se perde. Um grupo da raiz herdado pela entrada (Meu Drive) é
        # listado duas vezes. Não leva a anúncio de isolamento (lista mais, nunca menos).
        self.fake.root_perms.append(perm('g1', 'equipe@example.org', 'reader', 'group'))
        self.fake.entrada.append(perm('g1', 'equipe@example.org', 'reader', 'group'))
        self.assertEqual([a['onde'] for a in self.drive.broad_sharing()], ['raiz'])

    def test_revoke_orphan_never_deletes_non_user(self):
        self.fake.entrada += [perm('g1', 'equipe@example.org', 'writer', 'group', inherited=False),
                              {'id': 'd1', 'type': 'domain', 'role': 'writer', 'domain': 'example.org'}]
        for target in ('equipe@example.org', 'example.org', ''):
            try:
                self.access.revoke_orphan(ADMIN, target)
            except ValueError:
                pass  # Domínio/vazio: recusado como e-mail inválido.
        self.assertEqual(self.deletes(), [])

    # Corrigido na integração (antes expectedFailure).
    def test_revoke_orphan_on_group_does_not_claim_success(self):
        # DEFEITO (baixo): revoke_orphan ignora o retorno de revoke_entrada (False = nada apagado) e
        # responde "Permissão na pasta revogada." enquanto a permissão do grupo continua. Pela UI o
        # grupo não aparece em Pendências, então só um pedido forjado/lista antiga chega aqui.
        self.fake.entrada.append(perm('g1', 'equipe@example.org', 'writer', 'group', inherited=False))
        result = self.access.revoke_orphan(ADMIN, 'equipe@example.org')
        self.assertFalse(result['pasta_revogada'])


class AclInterfaceTests(unittest.TestCase):
    """O Adm nunca mostra o 'ok' sem isolamento confirmado."""

    def setUp(self):
        from tests.test_ui import GoogleAccessInterfaceTests
        case = GoogleAccessInterfaceTests('test_operator_works_without_adm')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case

    def render(self, status):
        app = self.case.run_app(self.case.admin)
        app.session_state['adm'] = status
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_inconsistent_or_missing_states_never_ok(self):
        broad = [{'onde': 'raiz', 'tipo': 'anyone', 'papel': 'reader', 'alvo': ''}]
        base = {'compartilhamento': True, 'usuarios': [], 'pendencias': []}
        for extra in ({'isolamento_ok': True, 'amplos': broad}, {'isolamento_ok': False, 'amplos': []},
                      {'isolamento_ok': 'sim', 'amplos': []}, {'isolamento_ok': True},
                      {'isolamento_ok': True, 'amplos': None}, {'amplos': []}):
            with self.subTest(extra=extra):
                app = self.render({**base, **extra})
                self.assertNotIn('compartilhamento disponível', self.case.texts(app))
                self.assertTrue(app.error)

    def test_error_state_shows_only_error(self):
        app = self.render({'erro': True})
        self.assertNotIn('compartilhamento disponível', self.case.texts(app))
        self.assertIn('Não foi possível consultar', app.error[0].value)

    def test_no_share_permission_plus_broad_shows_both(self):
        app = self.render({'compartilhamento': False, 'usuarios': [], 'pendencias': [], 'isolamento_ok': False,
                           'amplos': [{'onde': 'entrada', 'tipo': 'domain', 'papel': 'writer', 'alvo': 'x.org'}]})
        self.assertIn('domínio x.org', app.error[0].value)
        self.assertTrue(app.warning)

    def test_broad_warning_survives_remove_action(self):
        self.case.acl.broad = [{'onde': 'entrada', 'tipo': 'anyone', 'papel': 'writer', 'alvo': ''}]
        app = self.case.run_app(self.case.admin)
        self.case.button(app, 'Remover').click().run()
        self.assertFalse(app.exception)
        self.assertIn('qualquer pessoa com o link', ' '.join(e.value for e in app.error))
        self.assertNotIn('compartilhamento disponível', self.case.texts(app))


# ---------------------------------------------------------------- 2. Download no clique

class DownloadAdversarialTests(unittest.TestCase):
    def setUp(self):
        from tests.test_ui import GoogleAccessInterfaceTests
        case = GoogleAccessInterfaceTests('test_operator_works_without_adm')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case, self.registry = case, case.registry
        self.manager = MediaFileManager(MemoryMediaFileStorage('/mock/media'))
        patcher = patch('streamlit.testing.v1.app_test.MediaFileManager', return_value=self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rendered(self, email):
        app = self.case.run_app(email)
        self.case.button(app, 'Preparar Excel da base').click().run()
        downloads = app.get('download_button')
        self.assertEqual([d.proto.label for d in downloads], ['Baixar Excel (.xlsx)'])
        self.assertEqual(downloads[0].proto.url, '')
        return app, downloads[0].proto

    def click(self, proto, thread=False):
        """Como _handle_deferred_file_request: em outra thread, sem contexto de script."""
        out = {}

        def run():
            try:
                url = self.manager.execute_deferred(proto.deferred_file_id)
                out['bytes'] = self.manager._storage.get_file(url.rsplit('/', 1)[1].split('.')[0]).content
            except Exception as exc:
                out['error'] = exc
        if thread:
            t = threading.Thread(target=run); t.start(); t.join(30)
        else:
            run()
        return out

    def test_two_sessions_each_closure_checks_its_own_user(self):
        # O AppTest descarta o registro diferido de uma sessão quando outra roda; por isso a função
        # registrada no clique é guardada logo após cada desenho e chamada como execute_deferred faria.
        other = 'outro@example.org'
        self.registry.emails.add(other)
        _, proto_a = self.rendered(self.case.oper)
        call_a = self.manager._deferred_callables[proto_a.deferred_file_id]['callable']
        _, proto_b = self.rendered(other)  # st.user global muda; o clique de A continua sendo de A.
        call_b = self.manager._deferred_callables[proto_b.deferred_file_id]['callable']
        self.assertNotEqual(proto_a.deferred_file_id, proto_b.deferred_file_id)

        def click(call):
            out = {}
            def run():
                try:
                    out['bytes'] = call()
                except Exception as exc:
                    out['error'] = exc
            t = threading.Thread(target=run); t.start(); t.join(30)  # Sem contexto de script.
            return out
        self.registry.emails.discard(self.case.oper)
        a, b = click(call_a), click(call_b)
        self.assertNotIn('bytes', a)
        self.assertIn('Seu acesso foi removido', str(a['error']))
        self.assertTrue(b['bytes'].startswith(b'PK'))
        self.registry.emails.add(self.case.oper)
        self.registry.emails.discard(other)
        self.assertTrue(click(call_a)['bytes'].startswith(b'PK'))
        self.assertNotIn('bytes', click(call_b))

    def test_registry_errors_at_click_deny(self):
        _, proto = self.rendered(self.case.oper)
        for error in (ValueError('Linha de cadastro incompatível'), KeyError('values'), RuntimeError('x')):
            with self.subTest(error=error):
                self.registry.active = Mock(side_effect=error)
                self.assertNotIn('bytes', self.click(proto, thread=True))

    def test_no_media_file_exists_before_click(self):
        self.rendered(self.case.oper)
        self.assertEqual(self.manager._storage._files_by_id, {})


# ---------------------------------------------------------------- 3. Ordem de inicialização

class InitOrderAdversarialTests(init.Base):
    def test_sequence_of_users_in_one_process(self):
        self.run_app('estranho@example.org')
        self.assertEqual(self.kinds(), ['usuarios'])
        self.run_app(init.OPER)  # Fluxo construído e em cache.
        self.assertIn('drive', self.kinds())
        del init.FakeSession.log[:]
        app = self.run_app('estranho@example.org')  # Fluxo em cache não dá autoridade a ninguém.
        self.assertEqual(self.kinds(), ['usuarios'])
        self.assertEqual([b.label for b in app.button], ['Sair'])
        self.assertEqual(len(init.FakeSession.created), 1)

    def test_logged_in_without_email_reads_nothing(self):
        app = self.run_app(None)
        self.assertIn('Acesso não autorizado', app.error[0].value)
        self.assertEqual(self.kinds(), [])

    def test_lazy_drive_failure_is_not_cached(self):
        with patch.dict(init.FOLDERS, {'raiz': 'Outra pasta'}):
            app = self.run_app(init.OPER)
        self.assertIn('indisponível', app.error[0].value)
        self.assertNotIn('journal', self.kinds())  # Falha no Drive antes do journal.
        app = self.run_app(init.OPER)
        self.assertFalse(app.error)
        self.assertIn('journal', self.kinds())
        self.assertEqual(len(init.FakeSession.created), 1)  # Credencial/cadastro reaproveitados.

    def test_registry_unreadable_then_readable(self):
        with patch.object(init.FakeSession, 'get', side_effect=OSError('x')):
            self.run_app(init.OPER)
        self.assertEqual(self.kinds(), [])
        self.run_app(init.OPER)
        self.assertEqual(self.kinds()[0], 'usuarios')
        self.assertIn('drive', self.kinds())

    def test_manage_backup_still_works(self):
        import manage
        import runtime
        with tempfile.TemporaryDirectory() as tmp:
            result = manage.backup_sheets(Path(tmp) / 'copia.xlsx', runtime.components)
            self.assertTrue((Path(tmp) / 'copia.xlsx').exists())
        self.assertEqual(result['linhas_journal'], 0)
        self.assertNotIn('usuarios', self.kinds())  # Ferramenta técnica: sem consulta de cadastro.


if __name__ == '__main__':
    unittest.main()
