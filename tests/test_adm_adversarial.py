"""Revisão independente da fronteira de acesso (Adm): testes adversariais só com fakes.

Nenhuma chamada ao Google; e-mails inventados. Testes marcados expectedFailure
documentam defeitos reais encontrados na revisão (ver comentário de cada um).
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from acesso import AccessManager, Refused, SHARE_FAILED
from drive_adapter import GoogleDrive
from experiments.sheets_poc.fake import SimulatedSheets
from tests.test_acesso import FakeAcl, FakeRegistry
from tests.test_drive_acl import BOT, OWNER, FakeDrive, perm
from usuarios import UsersRegistry

ADMIN = 'chefe@example.org'
OPER = 'assessor@example.org'
T = '2026-10-31T00:00:00+00:00'


def registry_with(rows):
    sheets = SimulatedSheets('usuarios!A:F')
    sheets.rows = [list(r) for r in rows]
    return sheets, UsersRegistry(sheets)


class RegistryTamperingTests(unittest.TestCase):
    """Linhas estranhas na aba usuarios: nunca autorizam por engano; na dúvida, ninguém do cadastro entra."""

    def manager(self, rows):
        _, registry = registry_with(rows)
        return AccessManager(registry, FakeAcl([]), admins=[ADMIN])

    def test_case_and_whitespace_variants_are_one_identity(self):
        access = self.manager([['ADD', ' Assessor@Example.ORG ', ADMIN, T, 'p1', ''],
                               ['DEL', 'assessor@example.org', ADMIN, T, '', '']])
        for login in (OPER, OPER.upper(), ' ' + OPER + '\n'):
            self.assertFalse(access.is_authorized(login))
        access = self.manager([['ADD', OPER, ADMIN, T, 'p1', ''],
                               ['DEL', ' ASSESSOR@example.org', ADMIN, T, '', '']])
        self.assertFalse(access.is_authorized(OPER))

    def test_interleaved_events_last_wins(self):
        rows = [['ADD', OPER, ADMIN, T, 'p1', ''], ['DEL', OPER, ADMIN, T, '', ''],
                ['ADD', OPER, ADMIN, T, 'p2', '']]
        self.assertTrue(self.manager(rows).is_authorized(OPER))
        self.assertFalse(self.manager(rows + [['DEL', OPER, ADMIN, T, '', '']]).is_authorized(OPER))
        self.assertFalse(self.manager([['DEL', OPER, ADMIN, T, '', '']]).is_authorized(OPER))

    def test_odd_rows_fail_closed_for_registry_users_only(self):
        good = ['ADD', OPER, ADMIN, T, 'p1', '']
        for bad in (['add', 'x@example.org', ADMIN, T, '', ''],      # caixa do evento
                    ['ADD ', 'x@example.org', ADMIN, T, '', ''],     # espaço no evento
                    ['ADMIN', 'x@example.org', ADMIN, T, '', ''],    # tentativa de papel
                    ['PROMOTE', OPER, ADMIN, T, '', ''],
                    [],                                              # linha em branco no meio
                    ['ADD', 'sem-arroba', ADMIN, T, '', ''],
                    ['ADD', 'x@example.org.', ADMIN, T, '', ''],     # ponto final
                    ['event', 'email', 'by', 'at', 'perm', '']):     # cabeçalho em inglês
            with self.subTest(bad=bad):
                access = self.manager([good, bad])
                self.assertFalse(access.is_authorized(OPER))
                self.assertTrue(access.is_authorized(ADMIN))  # Configuração não depende do cadastro.
                self.assertFalse(access.is_admin(OPER))

    def test_header_and_admin_role_column_never_promote(self):
        access = self.manager([['Evento', 'E-mail', 'Por', 'Quando', 'Permissão', ''],
                               ['ADD', OPER, ADMIN, T, 'p1', 'admin']])
        self.assertTrue(access.is_authorized(OPER))
        self.assertFalse(access.is_admin(OPER))
        with self.assertRaises(PermissionError):
            access.add(OPER, 'outro@example.org')
        with self.assertRaises(PermissionError):
            access.status(OPER)

    def test_unicode_lookalike_in_registry_does_not_match_real_login(self):
        access = self.manager([['ADD', 'аssessor@example.org', ADMIN, T, '', '']])  # 'а' cirílico
        self.assertFalse(access.is_authorized(OPER))
        self.assertFalse(access.is_authorized('аssessor@example.org'))

    def test_is_authorized_never_raises(self):
        for exc in (KeyError('x'), RuntimeError('x'), ValueError('x'), TypeError('x'), RecursionError()):
            with self.subTest(exc=exc):
                registry = Mock(); registry.active.side_effect = exc
                access = AccessManager(registry, FakeAcl([]), admins=[ADMIN])
                self.assertFalse(access.is_authorized(OPER))
        access = AccessManager(Mock(active=lambda: {OPER}), FakeAcl([]), admins=[ADMIN])
        for value in (None, 7, b'assessor@example.org', ['assessor@example.org'], '', ' '):
            self.assertFalse(access.is_authorized(value))
            self.assertFalse(access.is_admin(value))

    # Defeito (Médio): o append do ADD pode expirar e ser aplicado depois pelo Sheets.
    # usuarios.UsersRegistry.remove() só grava DEL se o e-mail estiver ativo naquele
    # instante; o Adm vê "Acesso removido" e, quando o ADD atrasado chega, o último
    # evento volta a ser ADD: o removido recupera o JANUS sem nenhuma ação.
    # Corrigido na integração (antes expectedFailure).
    def test_late_add_after_reported_removal_does_not_reauthorize(self):
        sheets, registry = registry_with([])
        log = []
        acl = FakeAcl(log, owners=[OWNER])
        access = AccessManager(registry, acl, admins=[ADMIN])
        sheets.failures = ['deferred']
        self.assertIn('não foi registrado', access.add(ADMIN, OPER)['mensagem'])
        self.assertIn('removido', access.remove(ADMIN, OPER)['mensagem'])
        sheets.deliver_deferred()
        self.assertFalse(access.is_authorized(OPER))


class AddRemoveNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.registry, self.acl = FakeRegistry(self.log), FakeAcl(self.log, owners=[OWNER])
        self.access = AccessManager(self.registry, self.acl, admins=[' Chefe@Example.org '],
                                    allowed=['legado@example.org'], protected=[BOT])

    def test_admin_or_system_never_added_as_operator(self):
        for email in (' CHEFE@EXAMPLE.ORG ', 'chefe@example.org\n', '\tChefe@example.org',
                      OWNER.upper(), ' ' + BOT.upper()):
            with self.subTest(email=email), self.assertRaises(Refused):
                self.access.add(ADMIN, email)
        for email in ('сhefe@example.org', 'chefe@example.org.', 'chefe@example.org\x00',
                      'chefe@example .org', 'chefe@@example.org', 'chefe'):
            with self.subTest(email=email), self.assertRaises(Refused):
                self.access.add(ADMIN, email)
        self.assertEqual(self.log, [])
        self.assertFalse(self.access.is_admin('сhefe@example.org'))

    def test_admin_check_uses_normalized_identity(self):
        self.assertTrue(self.access.is_admin(' CHEFE@example.org '))
        for email in ('chefe@example.org.', 'chefe+x@example.org', 'сhefe@example.org', 'c.hefe@example.org'):
            self.assertFalse(self.access.is_admin(email))
        with self.assertRaises(PermissionError):
            self.access.add('chefe+x@example.org', OPER)

    def test_remove_variant_spelling_blocks_same_user(self):
        self.access.add(ADMIN, OPER)
        result = self.access.remove(' CHEFE@example.org', ' ASSESSOR@Example.org ')
        self.assertTrue(result['app_bloqueado'] and result['pasta_revogada'])
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertNotIn(OPER, self.acl.perms)

    def test_remove_and_orphan_refuse_privileged_accounts(self):
        for email in (ADMIN, OWNER, BOT, 'legado@example.org'):
            for call in (self.access.remove, self.access.revoke_orphan):
                with self.subTest(email=email, call=call.__name__), self.assertRaises(Refused):
                    call(ADMIN, email.upper())
        self.registry.emails.add(OPER)
        with self.assertRaises(Refused):
            self.access.revoke_orphan(ADMIN, ' ' + OPER.upper())
        self.assertEqual(self.log, [])

    def test_remove_with_registry_failure_touches_nothing(self):
        self.access.add(ADMIN, OPER)
        del self.log[:]
        self.registry.fail = {'remove'}
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (False, False))
        self.assertEqual([e[0] for e in self.log], ['registry.remove'])
        self.assertIn(OPER, self.acl.perms)


class GoogleDriveBoundaryTests(unittest.TestCase):
    """AccessManager com o GoogleDrive real sobre uma sessão HTTP falsa."""

    def setUp(self):
        self.fake = FakeDrive()
        session = Mock(); session.request.side_effect = self.fake
        self.drive = GoogleDrive(session, 'root', 'inbox', 'done', 'failed')
        self.log = []
        self.registry = FakeRegistry(self.log)
        self.access = AccessManager(self.registry, self.drive, admins=[ADMIN], protected=[BOT])
        self.fake.calls.clear()

    def tearDown(self):
        for method, path, *_ in self.fake.writes():
            self.assertIn(method, ('POST', 'DELETE'))
            self.assertTrue(path.startswith('/inbox/permissions'), path)

    def test_full_cycle_writes_only_entrada_permissions(self):
        self.assertTrue(self.access.add(ADMIN, OPER)['app'])
        self.assertTrue(self.access.remove(ADMIN, OPER)['pasta_revogada'])
        self.fake.entrada.append(perm('z9', 'orfao@example.org', inherited=False))
        self.assertEqual(self.access.status(ADMIN)['pendencias'], ['orfao@example.org'])
        self.assertTrue(self.access.revoke_orphan(ADMIN, 'orfao@example.org')['pasta_revogada'])
        deleted = [c[1] for c in self.fake.writes() if c[0] == 'DELETE']
        self.assertNotIn('/inbox/permissions/o1', deleted)
        self.assertNotIn('/inbox/permissions/s1', deleted)
        self.assertEqual({p['id'] for p in self.fake.entrada}, {'o1', 's1'})

    def test_share_ok_registry_fail_then_retry_reuses_permission(self):
        self.registry.fail = {'add'}
        result = self.access.add(ADMIN, OPER)
        self.assertEqual((result['app'], result['pasta']), (False, True))
        self.assertFalse(self.access.is_authorized(OPER))
        self.registry.fail = set()
        self.assertTrue(self.access.add(ADMIN, OPER)['app'])
        self.assertEqual(len([c for c in self.fake.writes() if c[0] == 'POST']), 1)
        self.assertEqual(self.registry.log[-1][3], '101')

    def test_can_share_false_or_inherited_never_writes(self):
        self.fake.can_share = False
        self.assertFalse(self.access.add(ADMIN, OPER)['pasta'])
        self.fake.can_share = True
        self.fake.root_perms.append(perm('r7', OPER))
        self.fake.entrada.append(perm('r7', OPER))  # Herdado (My Drive: sem permissionDetails).
        self.assertFalse(self.access.add(ADMIN, OPER)['pasta'])
        self.assertEqual(self.fake.writes(), [])
        self.registry.emails.add(OPER)
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (True, False))
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertEqual(self.access.status(ADMIN)['pendencias'], [])  # Herdada não é "órfã" revogável.

    def test_drive_errors_never_authorize(self):
        self.fake.fail_delete = True
        self.registry.emails.add(OPER)
        self.fake.entrada.append(perm('d5', OPER, inherited=False))
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (True, False))
        self.assertIn('continua', result['mensagem'])
        self.assertFalse(self.access.is_authorized(OPER))

    # Defeito (Baixo/Médio): o POST foi aplicado, mas a confirmação por e-mail não
    # encontra a permissão (Google devolve o endereço canônico da conta, ex. com
    # pontos no Gmail, ou a listagem falha após o POST). O Adm vê "Nada foi
    # liberado" enquanto a pessoa já é editora de entrada (aparece só como pendência).
    # Corrigido na integração (antes expectedFailure).
    def test_share_applied_but_unconfirmed_is_not_reported_as_nothing_released(self):
        original = self.fake.__call__

        def canonical(method, url, **kw):
            if method == 'POST':
                kw['json'] = dict(kw['json'], emailAddress='as.sessor@example.org')
            return original(method, url, **kw)
        self.drive.session.request.side_effect = canonical
        result = self.access.add(ADMIN, 'assessor@example.org')
        self.assertTrue([p for p in self.fake.entrada if p['emailAddress'] == 'as.sessor@example.org'])
        self.assertFalse(self.access.is_authorized(OPER))  # Seguro no app...
        self.assertNotEqual(result['mensagem'], SHARE_FAILED)  # ...mas a mensagem é falsa.


class SessionInterfaceTests(unittest.TestCase):
    """AppTest em modo google com st.user simulado."""

    def setUp(self):
        from tests.test_ui import GoogleAccessInterfaceTests
        case = GoogleAccessInterfaceTests('test_operator_works_without_adm')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case
        self.registry, self.acl, self.log = case.registry, case.acl, case.log
        self.admin, self.oper = case.admin, case.oper

    def run_app(self, email):
        return self.case.run_app(email)

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def test_operator_cannot_reach_adm_by_session_state(self):
        app = self.run_app(self.oper)
        app.session_state['adm_email'] = 'intruso@example.org'
        app.session_state['adm_msg'] = (True, 'x')
        app.session_state['adm'] = {'compartilhamento': True, 'usuarios': [], 'pendencias': ['vitima@example.org']}
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.expander)
        self.assertFalse([b for b in app.button if b.label in ('Adicionar', 'Remover', 'Revogar', 'Atualizar lista')])
        self.assertEqual(self.log, [])
        self.assertTrue(self.registry.emails == {self.oper})

    def test_account_switch_rechecks_and_drops_state(self):
        app = self.run_app(self.admin)
        self.button(app, 'Processar PDFs').click().run()
        self.button(app, 'Preparar Excel da base').click().run()
        self.assertIn('export', app.session_state)
        self.case.user.email = 'estranho@example.org'  # Outra conta na mesma sessão.
        app.run()
        self.assertFalse(app.exception)
        self.assertIn('Acesso não autorizado', app.error[0].value)
        for key in ('batch', 'export', 'adm', 'auth'):
            self.assertNotIn(key, app.session_state)
        self.assertEqual([b.label for b in app.button], ['Sair'])

    def test_switch_between_authorized_accounts_reads_registry(self):
        app = self.run_app(self.oper)
        reads, active = [], self.registry.active
        self.registry.active = lambda: reads.append(1) or active()
        self.registry.emails.add('segundo@example.org')
        self.case.user.email = 'segundo@example.org'
        app.run()
        self.assertEqual(len(reads), 1)  # Cache de 30 s é por e-mail.

    def test_expired_cache_drops_prepared_export(self):
        app = self.run_app(self.oper)
        self.button(app, 'Preparar Excel da base').click().run()
        self.registry.emails.clear()
        app.session_state['auth'] = (self.oper, -1e9)  # Cache vencido.
        app.run()
        self.assertNotIn('export', app.session_state)
        self.assertIn('Acesso não autorizado', app.error[0].value)

    # Defeito (Médio): app.py:284-286 desenha "Baixar Excel" sem conferência atual.
    # Dentro da janela AUTH_TTL (30 s, app.py:20) um assessor já removido continua
    # baixando o Excel preparado (e vendo o lote/links), porque só os botões de ação
    # chamam guard(); o contrato exige autorização atual também para download.
    # Corrigido na integração (antes expectedFailure).
    def test_revoked_user_cannot_download_prepared_excel_within_ttl(self):
        app = self.run_app(self.oper)
        self.button(app, 'Preparar Excel da base').click().run()
        self.assertTrue(app.get('download_button'))
        self.registry.emails.clear()  # Removido por um Adm em outra sessão.
        app.run()
        self.assertFalse(app.get('download_button'))


class WiringTests(unittest.TestCase):
    def test_manage_backup_works_with_access_wiring(self):
        from manage import backup_sheets
        from tests.test_ui import InterfaceTests
        case = InterfaceTests('test_clicks_edit_approval_archive_and_export')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.flow.access = AccessManager(FakeRegistry([]), FakeAcl([]), admins=[ADMIN])
        with tempfile.TemporaryDirectory() as tmp:
            result = backup_sheets(Path(tmp) / 'copia.xlsx', lambda: case.flow)
            self.assertTrue(result['base_logica'])

    def test_local_mode_has_no_access_and_ignores_admin_config(self):
        import runtime
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'JANUS_MODE': 'local', 'JANUS_ADMIN_EMAILS': 'nao-e-email', 'JANUS_DATA_DIR': tmp}):
            try:
                flow = runtime.components()
            except ValueError:
                self.skipTest('modo local exige outra configuração')
            self.assertIsNone(flow.access)

    def test_google_config_errors_fail_before_credentials(self):
        import runtime
        base = {'JANUS_MODE': 'google', 'JANUS_ROOT': 'r', 'JANUS_SHEET_ID': 's', 'JANUS_ENTRADA': 'e',
                'JANUS_PROCESSADOS': 'p', 'JANUS_FALHAS': 'f'}
        for admins in ('a@b', 'chefe@example.org,,x', 'сhefe@example.org', 'chefe@example.org;x@y.org'):
            env = dict(base, JANUS_ADMIN_EMAILS=admins)
            with self.subTest(admins=admins), patch.dict(os.environ, env, clear=False), \
                    patch.dict('sys.modules', {'google.oauth2': None}):
                os.environ.pop('JANUS_GOOGLE_SA_JSON', None)
                with self.assertRaisesRegex(ValueError, 'JANUS_ADMIN_EMAILS'):
                    runtime.components()


if __name__ == '__main__':
    unittest.main()
