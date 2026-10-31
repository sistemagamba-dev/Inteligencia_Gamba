"""Adm e autorização com fakes: nenhuma chamada ao Google, e-mails inventados."""
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from acesso import AccessManager, Refused
from experiments.sheets_poc.store import Unconfirmed
import runtime

ADMIN, OPER, OWNER, SA = 'adm@example.org', 'assessor@example.org', 'dono@example.org', 'sa@proj.iam.gserviceaccount.com'


class FakeRegistry:
    """Mesma interface de usuarios.UsersRegistry."""
    def __init__(self, log, emails=()):
        self.log, self.emails, self.fail = log, set(emails), set()

    def active(self):
        if 'read' in self.fail:
            raise ConnectionError('Sheets indisponível')
        return set(self.emails)

    def state(self):
        return {'active': self.active()}

    def add(self, email, *, by, permission_id=''):
        self.log.append(('registry.add', email, by, permission_id))
        if 'add' in self.fail:
            raise Unconfirmed()
        new = email not in self.emails
        self.emails.add(email)
        return new

    def remove(self, email, *, by):
        self.log.append(('registry.remove', email, by))
        if 'remove' in self.fail:
            raise Unconfirmed()
        new = email in self.emails
        self.emails.discard(email)
        return new


class FakeAcl:
    """Mesma interface dos métodos de ACL de GoogleDrive para a pasta entrada."""
    def __init__(self, log, owners=(OWNER,), can_share=True):
        self.log, self.owners, self.can_share, self.fail = log, list(owners), can_share, set()
        self.perms = {o: {'id': 'p-' + o, 'email': o, 'role': 'owner', 'type': 'user', 'inherited': True}
                      for o in owners}
        self.broad = []  # Descritores de GoogleDrive.broad_sharing (anyone/domain/group na entrada ou raiz).

    def entrada_sharing(self):
        if 'sharing' in self.fail:
            raise ConnectionError('Drive indisponível')
        return {'can_share': self.can_share, 'owners': list(self.owners)}

    def entrada_permissions(self):
        if 'list' in self.fail:
            raise ConnectionError('Drive indisponível')
        return [dict(p) for p in self.perms.values()]

    def broad_sharing(self):
        if 'list' in self.fail:
            raise ConnectionError('Drive indisponível')
        return [dict(b) for b in self.broad]

    def share_entrada(self, email):
        self.log.append(('drive.share', email))
        if 'share' in self.fail:
            raise ValueError('Compartilhamento não confirmado')
        self.perms.setdefault(email, {'id': 'p-' + email, 'email': email, 'role': 'writer',
                                      'type': 'user', 'inherited': False})
        return self.perms[email]['id']

    def revoke_entrada(self, email):
        self.log.append(('drive.revoke', email))
        if 'revoke' in self.fail:
            raise ValueError('Revogação não confirmada')
        return self.perms.pop(email, None) is not None


class AccessManagerTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.registry, self.drive = FakeRegistry(self.log), FakeAcl(self.log)
        self.access = AccessManager(self.registry, self.drive, admins=[' Adm@Example.org '],
                                    allowed=['legado@example.org'], protected=[SA])

    def test_admin_add_success_and_idempotent(self):
        self.assertFalse(self.access.is_authorized(OPER))
        result = self.access.add(ADMIN, ' Assessor@Example.ORG ')
        self.assertEqual((result['email'], result['app'], result['pasta']), (OPER, True, True))
        self.assertTrue(self.access.is_authorized(OPER))
        self.assertFalse(self.access.is_admin(OPER))  # Cadastro nunca promove.
        self.assertEqual(self.log, [('drive.share', OPER), ('registry.add', OPER, ADMIN, 'p-' + OPER)])
        self.assertTrue(self.access.add(ADMIN, OPER)['app'])
        status = self.access.status(ADMIN)
        self.assertEqual(status, {'compartilhamento': True, 'pendencias': [], 'amplos': [], 'isolamento_ok': True,
                                  'usuarios': [{'email': OPER, 'app': True, 'pasta': 'ok'}]})

    def test_share_failure_authorizes_nothing(self):
        for fail in ('share', 'sharing'):
            with self.subTest(fail=fail):
                self.drive.fail = {fail}
                result = self.access.add(ADMIN, OPER)
                self.assertEqual((result['app'], result['pasta']), (False, False))
                # Falha antes da escrita: nada liberado; depois da tentativa: estado incerto, aponta Pendências.
                self.assertIn('Nada foi liberado' if fail == 'sharing' else 'confira as Pendências', result['mensagem'])
                self.assertFalse(self.access.is_authorized(OPER))
                self.assertNotIn('registry.add', [e[0] for e in self.log])

    def test_without_can_share_nothing_is_attempted(self):
        self.drive.can_share = False
        result = self.access.add(ADMIN, OPER)
        self.assertFalse(result['app'] or result['pasta'])
        self.assertEqual(self.log, [])
        self.assertFalse(self.access.status(ADMIN)['compartilhamento'])

    def test_registry_failure_after_share_is_pending(self):
        self.registry.fail = {'add'}
        result = self.access.add(ADMIN, OPER)
        self.assertEqual((result['app'], result['pasta']), (False, True))
        self.assertIn('não foi registrado', result['mensagem'])
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertEqual(self.access.status(ADMIN)['pendencias'], [OPER])
        self.assertTrue(self.access.revoke_orphan(ADMIN, OPER)['pasta_revogada'])
        self.assertEqual(self.access.status(ADMIN)['pendencias'], [])

    def test_remove_blocks_app_first_then_revokes(self):
        self.access.add(ADMIN, OPER)
        del self.log[:]
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (True, True))
        self.assertEqual(self.log, [('registry.remove', OPER, ADMIN), ('drive.revoke', OPER)])
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertNotIn(OPER, self.drive.perms)

    def test_registry_remove_failure_changes_nothing(self):
        self.access.add(ADMIN, OPER)
        self.registry.fail = {'remove'}
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (False, False))
        self.assertIn('nada mudou', result['mensagem'])
        self.assertNotIn(('drive.revoke', OPER), self.log)
        self.assertTrue(self.access.is_authorized(OPER))

    def test_revoke_failure_blocks_app_and_leaves_pending(self):
        self.access.add(ADMIN, OPER)
        self.drive.fail = {'revoke'}
        result = self.access.remove(ADMIN, OPER)
        self.assertEqual((result['app_bloqueado'], result['pasta_revogada']), (True, False))
        self.assertIn('permissão na pasta continua', result['mensagem'])
        self.assertNotIn('removido', result['mensagem'])
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertEqual(self.access.status(ADMIN)['pendencias'], [OPER])
        self.assertFalse(self.access.revoke_orphan(ADMIN, OPER)['pasta_revogada'])
        self.drive.fail = set()
        self.assertTrue(self.access.revoke_orphan(ADMIN, OPER)['pasta_revogada'])
        self.assertEqual(self.access.status(ADMIN)['pendencias'], [])

    def test_revoke_orphan_refuses_active_and_protected(self):
        self.access.add(ADMIN, OPER)
        with self.assertRaisesRegex(Refused, 'Remover'):
            self.access.revoke_orphan(ADMIN, OPER)
        for email in (OWNER, SA, ADMIN, 'legado@example.org'):
            with self.subTest(email=email), self.assertRaises(Refused):
                self.access.revoke_orphan(ADMIN, email)
        self.assertNotIn('drive.revoke', [e[0] for e in self.log])

    def test_operator_cannot_call_admin_functions(self):
        self.access.add(ADMIN, OPER)
        for call in (lambda: self.access.add(OPER, 'outro@example.org'), lambda: self.access.remove(OPER, OPER),
                     lambda: self.access.status(OPER), lambda: self.access.revoke_orphan(OPER, 'x@example.org'),
                     lambda: self.access.add(None, 'outro@example.org'), lambda: self.access.status('')):
            with self.assertRaises(PermissionError):
                call()
        self.assertEqual(len(self.log), 2)

    def test_admin_protected_and_owner_refused(self):
        for email in (ADMIN, 'ADM@example.org', OWNER, SA, 'invalido', ''):
            with self.subTest(email=email):
                with self.assertRaises(Refused):
                    self.access.add(ADMIN, email)
                with self.assertRaises(Refused):
                    self.access.remove(ADMIN, email)
        with self.assertRaises(Refused):
            self.access.remove(ADMIN, 'legado@example.org')  # Lista fixa: remover não bloquearia.
        self.assertEqual(self.log, [])

    def test_is_authorized_fails_closed(self):
        self.registry.emails = {OPER}
        self.assertTrue(self.access.is_authorized(' ASSESSOR@example.org'))
        self.assertTrue(self.access.is_authorized(ADMIN))
        self.assertTrue(self.access.is_authorized('legado@example.org'))
        for value in (None, '', '   ', 'sem-arroba', 42):
            self.assertFalse(self.access.is_authorized(value))
        self.registry.fail = {'read'}
        self.assertFalse(self.access.is_authorized(OPER))
        self.assertTrue(self.access.is_admin(ADMIN))  # Admin vem só da configuração.

    def test_status_reports_folder_state_and_raises_on_drive_error(self):
        self.registry.emails = {OPER, 'herdado@example.org'}
        self.drive.perms['herdado@example.org'] = {'id': 'h', 'email': 'herdado@example.org', 'role': 'writer',
                                                  'type': 'user', 'inherited': True}
        self.drive.perms['Solto@example.org'] = {'id': 's', 'email': 'Solto@example.org', 'role': 'reader',
                                                'type': 'user', 'inherited': False}
        self.drive.perms[SA] = {'id': 'sa', 'email': SA, 'role': 'writer', 'type': 'user', 'inherited': False}
        status = self.access.status(ADMIN)
        self.assertEqual({u['email']: u['pasta'] for u in status['usuarios']},
                         {OPER: 'ausente', 'herdado@example.org': 'herdada'})
        self.assertEqual(status['pendencias'], ['solto@example.org'])
        self.drive.fail = {'list'}
        with self.assertRaises(ConnectionError):
            self.access.status(ADMIN)

    def test_acl_changes_are_serialized(self):
        lock = threading.Lock()
        access = AccessManager(self.registry, self.drive, admins=[ADMIN], lock=lock)
        with lock:
            worker = threading.Thread(target=access.add, args=(ADMIN, OPER))
            worker.start()
            worker.join(0.2)
            self.assertTrue(worker.is_alive())
            self.assertEqual(self.log, [])
        worker.join(5)
        self.assertTrue(self.access.is_authorized(OPER))

    def test_invalid_admin_in_constructor_refused(self):
        with self.assertRaises(ValueError):
            AccessManager(self.registry, self.drive, admins=['nao-e-email'])


class RuntimeAccessTests(unittest.TestCase):
    def env(self, **values):
        clean = {k: v for k, v in os.environ.items() if not k.startswith('JANUS_')}
        return patch.dict(os.environ, {**clean, 'JANUS_MODE': 'google', 'JANUS_SHEET_ID': 'planilha',
                                       'JANUS_ROOT': 'raiz', 'JANUS_ENTRADA': 'e', 'JANUS_PROCESSADOS': 'p',
                                       'JANUS_FALHAS': 'f', **values}, clear=True)

    def test_admin_config_is_normalized_and_invalid_fails_before_credentials(self):
        with self.env(JANUS_ADMIN_EMAILS=' Adm@Example.org , b@example.org,'):
            self.assertEqual(runtime.google_settings()['admins'], {ADMIN, 'b@example.org'})
        with self.env():
            self.assertEqual(runtime.google_settings()['admins'], frozenset())
        for value in ('nao-e-email', 'adm@example.org;b@example.org', 'a @example.org'):
            with self.subTest(value=value), self.env(JANUS_ADMIN_EMAILS=value):
                with self.assertRaisesRegex(ValueError, 'JANUS_ADMIN_EMAILS'):
                    runtime.components()  # Sem JANUS_GOOGLE_SA_JSON: KeyError se lesse credenciais.

    def test_google_access_wiring(self):
        created = {}
        class Sheets:
            def __init__(self, session, sheet, range_):
                created['sheets'] = (session, sheet, range_)
        class Registry(FakeRegistry):
            def __init__(self, transport):
                created['transport'] = transport
                super().__init__([], {OPER})
        fake_sheets = type('M', (), {'GoogleSheets': Sheets})
        fake_users = type('M', (), {'UsersRegistry': Registry})
        with self.env(JANUS_ADMIN_EMAILS=ADMIN, JANUS_ALLOWED_EMAILS='Legado@example.org'), \
                patch.dict('sys.modules', {'sheets_adapter': fake_sheets, 'usuarios': fake_users}):
            access = runtime.google_access('sessao', runtime.google_settings(), FakeAcl([]), SA)
        self.assertEqual(created['sheets'], ('sessao', 'planilha', 'usuarios!A:F'))
        self.assertTrue(access.is_admin(ADMIN) and access.is_authorized(OPER) and access.is_authorized('legado@example.org'))
        self.assertIn(SA, access.protected)

    def test_local_mode_has_no_access_manager(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {'JANUS_MODE': 'local', 'JANUS_AMBIENTE': 'homologacao', 'JANUS_DATA_DIR': tmp}):
            self.assertIsNone(runtime.components().access)


if __name__ == '__main__':
    unittest.main()
