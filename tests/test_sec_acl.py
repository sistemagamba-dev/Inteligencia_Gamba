"""Compartilhamento amplo (anyone/domain/group) na entrada ou na raiz: deve aparecer no Adm.

Campos conforme o recurso permissions do Drive v3 (type, role, emailAddress, domain,
allowFileDiscovery, permissionDetails). Somente fakes; nenhuma chamada ao Google.
"""
import unittest
from unittest.mock import Mock

from acesso import AccessManager
from drive_adapter import GoogleDrive
from tests.test_acesso import FakeRegistry
from tests.test_drive_acl import BOT, FakeDrive, perm

ADMIN = 'chefe@example.org'


def anyone(pid, role='reader', discovery=False, inherited=None):
    p = {'id': pid, 'type': 'anyone', 'role': role, 'allowFileDiscovery': discovery}
    if inherited is not None:
        p['permissionDetails'] = [{'inherited': inherited, 'role': role}]
    return p


def domain(pid, name, role='writer', inherited=None):
    p = {'id': pid, 'type': 'domain', 'role': role, 'domain': name, 'allowFileDiscovery': True}
    if inherited is not None:
        p['permissionDetails'] = [{'inherited': inherited, 'role': role}]
    return p


class BroadSharingTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        session = Mock(); session.request.side_effect = self.fake
        self.drive = GoogleDrive(session, 'root', 'inbox', 'done', 'failed')
        self.registry = FakeRegistry([])
        self.access = AccessManager(self.registry, self.drive, admins=[ADMIN], protected=[BOT])
        self.fake.calls.clear()

    def tearDown(self):
        self.assertEqual([c for c in self.fake.writes() if not c[1].startswith('/inbox/permissions')], [])

    def amplos(self):
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        return status['amplos']

    def test_clean_acl_is_isolated(self):
        status = self.access.status(ADMIN)
        self.assertTrue(status['isolamento_ok'])
        self.assertEqual(status['amplos'], [])

    def test_anyone_reader_on_entrada(self):
        self.fake.entrada.append(anyone('a1', inherited=False))
        self.assertEqual(self.amplos(), [{'onde': 'entrada', 'tipo': 'anyone', 'papel': 'reader', 'alvo': ''}])

    def test_domain_writer_on_entrada(self):
        self.fake.entrada.append(domain('dm1', 'Exemplo.org', inherited=False))
        self.assertEqual(self.amplos(), [{'onde': 'entrada', 'tipo': 'domain', 'papel': 'writer',
                                          'alvo': 'exemplo.org'}])

    def test_group_on_entrada_is_broad_not_orphan(self):
        self.fake.entrada.append(perm('g1', 'Equipe@example.org', 'writer', 'group', inherited=False))
        status = self.access.status(ADMIN)
        self.assertFalse(status['isolamento_ok'])
        self.assertEqual(status['amplos'], [{'onde': 'entrada', 'tipo': 'group', 'papel': 'writer',
                                             'alvo': 'equipe@example.org'}])
        self.assertEqual(status['pendencias'], [])  # Grupo não ganha botão Revogar.

    def test_anyone_on_root_inherited_everywhere(self):
        self.fake.root_perms.append(anyone('a2'))
        self.fake.entrada.append(anyone('a2', inherited=True))
        self.assertEqual(self.amplos(), [{'onde': 'raiz', 'tipo': 'anyone', 'papel': 'reader', 'alvo': ''}])

    def test_unknown_type_and_user_without_email_are_not_isolated(self):
        self.fake.entrada.append({'id': 'u1', 'type': 'novo_tipo', 'role': 'reader'})
        self.fake.root_perms.append({'id': 'u2', 'type': 'user', 'role': 'reader'})
        self.assertEqual(sorted(a['onde'] for a in self.amplos()), ['entrada', 'raiz'])

    def test_unsafe_characters_never_reach_descriptor(self):
        self.fake.entrada.append(domain('dm2', '[x](javascript:alert) **y**'))
        [item] = self.amplos()
        self.assertRegex(item['alvo'], r'^[a-z0-9@._-]*$')

    def test_acl_read_error_never_claims_isolation(self):
        def broken(method, url, **kw):
            if url.endswith('/root/permissions'):
                raise ConnectionError('Drive indisponível')
            return original(method, url, **kw)
        original = self.fake.__call__
        self.drive.session.request.side_effect = broken
        with self.assertRaises(ConnectionError):
            self.access.status(ADMIN)

    def test_revoke_never_touches_group_domain_or_anyone(self):
        self.fake.entrada += [perm('g1', 'equipe@example.org', 'writer', 'group', inherited=False),
                              anyone('a1', inherited=False), domain('dm1', 'example.org', inherited=False)]
        self.assertFalse(self.drive.revoke_entrada('equipe@example.org'))
        self.access.revoke_orphan(ADMIN, 'equipe@example.org')  # Via Adm (antes: aparecia em Pendências).
        self.assertEqual([c for c in self.fake.writes() if c[0] == 'DELETE'], [])
        self.assertEqual({'g1', 'a1', 'dm1'} - {p['id'] for p in self.fake.entrada}, set())


class BroadSharingInterfaceTests(unittest.TestCase):
    """O Adm mostra aviso inequívoco e nunca diz que está tudo certo com ACL ampla."""

    def setUp(self):
        from tests.test_ui import GoogleAccessInterfaceTests
        case = GoogleAccessInterfaceTests('test_operator_works_without_adm')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case

    def test_warning_lists_broad_shares_and_no_ok_message(self):
        acl = self.case.acl
        acl.perms['anyone'] = {'id': 'a1', 'email': '', 'role': 'reader', 'type': 'anyone', 'inherited': False}
        acl.broad = [{'onde': 'entrada', 'tipo': 'anyone', 'papel': 'reader', 'alvo': ''},
                     {'onde': 'raiz', 'tipo': 'domain', 'papel': 'writer', 'alvo': 'example.org'},
                     {'onde': 'entrada', 'tipo': 'group', 'papel': 'writer', 'alvo': 'equipe@example.org'}]
        app = self.case.run_app(self.case.admin)
        errors = ' '.join(e.value for e in app.error)
        self.assertIn('Compartilhamento amplo na pasta de entrada', errors)
        self.assertIn('qualquer pessoa com o link', errors)
        self.assertIn('domínio example.org', errors)
        self.assertIn('grupo equipe@example.org', errors)
        self.assertIn('raiz', errors)
        self.assertIn('revise no Google Drive', errors)
        self.assertNotIn('compartilhamento disponível', self.case.texts(app))
        self.assertFalse([b for b in app.button if b.label == 'Revogar'])
        self.assertEqual(self.case.log, [])

    def test_clean_acl_keeps_previous_caption(self):
        app = self.case.run_app(self.case.admin)
        self.assertFalse(app.error)
        self.assertIn('compartilhamento disponível', self.case.texts(app))

    def test_stale_state_without_isolation_flag_is_not_ok(self):
        app = self.case.run_app(self.case.admin)
        app.session_state['adm'] = {'compartilhamento': True, 'usuarios': [], 'pendencias': []}
        app.run()
        self.assertNotIn('compartilhamento disponível', self.case.texts(app))
        self.assertTrue(app.error)


if __name__ == '__main__':
    unittest.main()
