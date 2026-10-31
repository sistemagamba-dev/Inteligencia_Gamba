import unittest
from unittest.mock import Mock

from experiments.sheets_poc.fake import SimulatedSheets
from experiments.sheets_poc.store import SheetsProof, Unconfirmed
from sheets_adapter import GoogleSheets
from usuarios import UsersRegistry, normalize_email

ADMIN = 'admin@exemplo.org'


class UsersRegistryTests(unittest.TestCase):
    def setUp(self):
        self.sheet = SimulatedSheets(range_='usuarios!A:F')
        self.users = UsersRegistry(self.sheet)

    def test_add_remove_readd_cycle(self):
        self.assertEqual(self.users.active(), set())
        self.assertTrue(self.users.add('a@exemplo.org', by=ADMIN, permission_id='perm1'))
        self.assertEqual(self.users.active(), {'a@exemplo.org'})
        info = self.users.state()['ativos']['a@exemplo.org']
        self.assertEqual((info['por'], info['permissao']), (ADMIN, 'perm1'))
        self.assertTrue(info['desde'].endswith('+00:00'))
        self.assertTrue(self.users.remove('a@exemplo.org', by=ADMIN))
        state = self.users.state()
        self.assertEqual((state['ativos'], state['removidos']), ({}, {'a@exemplo.org'}))
        self.assertTrue(self.users.add('a@exemplo.org', by=ADMIN))
        state = self.users.state()
        self.assertEqual((set(state['ativos']), state['removidos']), ({'a@exemplo.org'}, set()))
        self.assertEqual([r[0] for r in self.sheet.rows], ['ADD', 'DEL', 'ADD'])
        self.assertTrue(all(len(r) == 6 for r in self.sheet.rows))

    def test_idempotent_add_and_remove(self):
        self.assertTrue(self.users.add('a@exemplo.org', by=ADMIN))
        self.assertFalse(self.users.add(' A@Exemplo.org ', by=ADMIN, permission_id='outra'))
        self.assertEqual(len(self.sheet.rows), 1)
        self.assertTrue(self.users.remove('a@exemplo.org', by=ADMIN))
        self.assertFalse(self.users.remove('a@exemplo.org', by=ADMIN))
        self.assertFalse(self.users.remove('nunca@exemplo.org', by=ADMIN))  # Grava DEL de bloqueio.
        self.assertEqual(len(self.sheet.rows), 3)
        self.assertFalse(self.users.remove('nunca@exemplo.org', by=ADMIN))
        self.assertEqual(len(self.sheet.rows), 3)

    def test_normalization_and_invalid_emails(self):
        self.assertEqual(normalize_email('  Fulano.Silva@Exemplo.ORG.br '), 'fulano.silva@exemplo.org.br')
        for value in ['', None, 'semarroba', 'a@b', 'a@@b.org', 'a b@c.org', 'a@b..org', 'a@.b.org',
                      'a@b.org.', '@b.org', 'a@b@c.org']:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'E-mail inválido'):
                normalize_email(value)
        self.users.add('B@Exemplo.org', by=' ADMIN@exemplo.org')
        self.assertEqual(self.sheet.rows[0][1:3], ['b@exemplo.org', ADMIN])
        with self.assertRaises(ValueError):
            self.users.add('invalido', by=ADMIN)
        with self.assertRaises(ValueError):
            self.users.add('c@exemplo.org', by='invalido')
        self.assertEqual(len(self.sheet.rows), 1)

    def test_lost_response_after_append_is_confirmed(self):
        self.sheet.failures = ['after']
        self.assertTrue(self.users.add('a@exemplo.org', by=ADMIN))
        self.assertEqual(len(self.sheet.rows), 1)
        self.sheet.failures = ['after']
        self.assertTrue(self.users.remove('a@exemplo.org', by=ADMIN))
        self.assertEqual(len(self.sheet.rows), 2)

    def test_timeout_before_apply_is_unconfirmed(self):
        self.sheet.failures = ['before']
        with self.assertRaisesRegex(Unconfirmed, 'Cadastro não confirmado'):
            self.users.add('a@exemplo.org', by=ADMIN)
        self.assertEqual((self.sheet.rows, self.users.active()), ([], set()))
        self.users.add('a@exemplo.org', by=ADMIN)
        self.sheet.failures = ['before']
        with self.assertRaises(Unconfirmed):
            self.users.remove('a@exemplo.org', by=ADMIN)
        self.assertEqual(self.users.active(), {'a@exemplo.org'})

    def test_unconfirmed_when_read_back_misses(self):
        self.sheet.read_faults = [None, {'values':[]}]
        with self.assertRaises(Unconfirmed):
            self.users.add('a@exemplo.org', by=ADMIN)

    def test_header_ignored_and_short_rows_padded(self):
        self.sheet.rows = [['evento', 'email', 'por', 'quando', 'permissao', 'obs'],
                           ['ADD', 'A@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00']]
        self.assertEqual(self.users.active(), {'a@exemplo.org'})
        self.assertEqual(self.users.state()['ativos']['a@exemplo.org']['permissao'], '')

    def test_unknown_event_or_bad_row_fails_closed(self):
        for rows in ([['XYZ', 'a@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00', '', '']],
                     [['ADD', 'a@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00', '', ''], ['evento', 'x', '', '', '', '']],
                     [['ADD', 'invalido', ADMIN, '2026-01-01T00:00:00+00:00', '', '']],
                     [['ADD', 'a@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00', '', '', 'extra']]):
            self.sheet.rows = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.users.active()
            with self.assertRaises(ValueError):
                self.users.add('b@exemplo.org', by=ADMIN)

    def test_missing_tab_propagates(self):
        transport = Mock()
        transport.get.side_effect = RuntimeError('400')
        users = UsersRegistry(transport)
        with self.assertRaises(RuntimeError):
            users.active()
        with self.assertRaises(RuntimeError):
            users.add('a@exemplo.org', by=ADMIN)
        transport.append.assert_not_called()

    def test_registry_never_writes_journal(self):
        journal = SimulatedSheets()
        SheetsProof(journal).state()
        with self.assertRaisesRegex(ValueError, 'Somente append'):
            UsersRegistry(journal).add('a@exemplo.org', by=ADMIN)
        self.assertEqual((journal.rows, journal.commits), ([], 0))
        self.users.add('a@exemplo.org', by=ADMIN)
        self.assertEqual(journal.rows, [])
        transport = Mock()
        transport.get.side_effect = [{'values':[]}, {'values':[['ADD', 'a@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00']]}]
        UsersRegistry(transport).add('a@exemplo.org', by=ADMIN)
        self.assertEqual(transport.append.call_args.kwargs,
                         {'range':'usuarios!A:F', 'valueInputOption':'RAW', 'insertDataOption':'INSERT_ROWS'})


class GoogleSheetsRangeTests(unittest.TestCase):
    BASE = 'https://sheets.googleapis.com/v4/spreadsheets/abc/values/'

    def test_default_is_journal(self):
        session = Mock()
        sheets = GoogleSheets(session, 'abc')
        self.assertEqual(sheets.range_, 'journal!A:F')
        sheets.get()
        session.get.assert_called_once_with(self.BASE + 'journal!A:F', timeout=60)
        with self.assertRaises(ValueError):
            sheets.append({'values':[]}, range='usuarios!A:F', valueInputOption='RAW', insertDataOption='INSERT_ROWS')
        session.post.assert_not_called()

    def test_usuarios_range(self):
        session = Mock()
        sheets = GoogleSheets(session, 'abc', 'usuarios!A:F')
        sheets.get()
        session.get.assert_called_once_with(self.BASE + 'usuarios!A:F', timeout=60)
        body = {'values':[['ADD', 'a@exemplo.org', ADMIN, '2026-01-01T00:00:00+00:00', '', '']]}
        sheets.append(body, range='usuarios!A:F', valueInputOption='RAW', insertDataOption='INSERT_ROWS')
        session.post.assert_called_once_with(self.BASE + 'usuarios!A:F:append', timeout=60, json=body,
                                             params={'valueInputOption':'RAW', 'insertDataOption':'INSERT_ROWS'})
        for args in (('journal!A:F', 'RAW', 'INSERT_ROWS'), ('usuarios!A:F', 'USER_ENTERED', 'INSERT_ROWS'),
                     ('usuarios!A:F', 'RAW', 'OVERWRITE')):
            with self.assertRaises(ValueError):
                sheets.append(body, range=args[0], valueInputOption=args[1], insertDataOption=args[2])
        self.assertEqual(session.post.call_count, 1)

    def test_invalid_range(self):
        for range_ in ('usuarios!A:Z', 'outra!A:F', 'Sheet1', ''):
            with self.subTest(range_=range_), self.assertRaisesRegex(ValueError, 'Intervalo inválido'):
                GoogleSheets(Mock(), 'abc', range_)


if __name__ == '__main__':
    unittest.main()
