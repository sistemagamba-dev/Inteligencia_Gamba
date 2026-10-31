import unittest
from unittest.mock import Mock

from drive_adapter import GoogleDrive

API = GoogleDrive.API
FOLDER = 'application/vnd.google-apps.folder'
OWNER = 'dono@gmail.com'
BOT = 'robo@projeto.iam.gserviceaccount.com'


def perm(pid, email, role='writer', type='user', inherited=None):
    p = {'id': pid, 'emailAddress': email, 'role': role, 'type': type}
    if inherited is not None:
        p['permissionDetails'] = [{'inherited': inherited, 'role': role}]
    return p


class FakeDrive:
    """Sessão falsa roteada por método/URL; registra chamadas."""
    def __init__(self, entrada=(), can_share=True, page=None, hide_create=False, fail_delete=False):
        self.root_perms = [perm('o1', OWNER, 'owner'), perm('s1', BOT)]
        self.entrada = [perm('o1', OWNER, 'owner', inherited=True),
                        perm('s1', BOT, inherited=True)] + list(entrada)
        self.can_share, self.page, self.hide_create, self.fail_delete = can_share, page, hide_create, fail_delete
        self.calls, self.next_id = [], 100

    def resp(self, data=None, status=None):
        r = Mock(); r.json.return_value = data
        if status: r.raise_for_status.side_effect = OSError(status)
        return r

    def listing(self, items, params):
        if not self.page:
            return {'permissions': items}
        start = int(params.get('pageToken') or 0)
        data = {'permissions': items[start:start + self.page]}
        if start + self.page < len(items): data['nextPageToken'] = str(start + self.page)
        return data

    def __call__(self, method, url, timeout=None, params=None, json=None):
        params = params or {}
        path = url[len(API):]
        self.calls.append((method, path, params, json))
        if method == 'GET' and path in ('/root', '/inbox', '/done', '/failed'):
            fields = params['fields']
            if fields.startswith('capabilities'):
                return self.resp({'capabilities': {'canShare': self.can_share}})
            if fields.startswith('owners'):
                return self.resp({'owners': [{'emailAddress': OWNER.upper()}]})
            if path == '/root':
                return self.resp({'name': 'JANUS_TESTE x', 'mimeType': FOLDER})
            return self.resp({'parents': ['root'], 'mimeType': FOLDER})
        if method == 'GET' and path == '/root/permissions':
            return self.resp(self.listing(self.root_perms, params))
        if method == 'GET' and path == '/inbox/permissions':
            return self.resp(self.listing(self.entrada, params))
        if method == 'POST' and path == '/inbox/permissions':
            self.next_id += 1
            if not self.hide_create:
                self.entrada.append(perm(str(self.next_id), json['emailAddress'], json['role'], inherited=False))
            return self.resp({'id': str(self.next_id)})
        if method == 'DELETE' and path.startswith('/inbox/permissions/'):
            if self.fail_delete:
                return self.resp(status='403')
            pid = path.rsplit('/', 1)[1]
            self.entrada = [p for p in self.entrada if p['id'] != pid]
            return self.resp()
        raise AssertionError(f'chamada inesperada {method} {path}')

    def writes(self):
        return [c for c in self.calls if c[0] in ('POST', 'PATCH', 'PUT', 'DELETE')]


class DriveAclTests(unittest.TestCase):
    def drive(self, **kw):
        self.fake = FakeDrive(**kw)
        session = Mock(); session.request.side_effect = self.fake
        drive = GoogleDrive(session, 'root', 'inbox', 'done', 'failed')
        self.fake.calls.clear()
        return drive

    def tearDown(self):
        for method, path, *_ in getattr(self, 'fake', FakeDrive()).writes():
            self.assertTrue(path.startswith('/inbox/permissions'), path)

    def test_sharing_and_permissions(self):
        d = self.drive(entrada=[perm('d1', 'Op@Gmail.com', inherited=False), perm('a1', None, 'reader', 'anyone')])
        self.assertEqual(d.entrada_sharing(), {'can_share': True, 'owners': [OWNER]})
        perms = {p['id']: p for p in d.entrada_permissions()}
        self.assertEqual(perms['d1'], {'id': 'd1', 'email': 'op@gmail.com', 'role': 'writer',
                                       'type': 'user', 'inherited': False, 'domain': '', 'discovery': False})
        self.assertTrue(perms['o1']['inherited']); self.assertEqual(perms['a1']['email'], '')

    def test_inherited_by_root_without_details(self):
        d = self.drive()
        self.fake.entrada[1].pop('permissionDetails')
        self.assertTrue([p for p in d.entrada_permissions() if p['id'] == 's1'][0]['inherited'])

    def test_share_creates_once_on_entrada(self):
        d = self.drive()
        pid = d.share_entrada(' Op@Gmail.com ')
        self.assertEqual(pid, '101')
        [(method, path, params, body)] = self.fake.writes()
        self.assertEqual((method, path), ('POST', '/inbox/permissions'))
        self.assertEqual(body, {'type': 'user', 'role': 'writer', 'emailAddress': 'op@gmail.com'})
        self.assertEqual(params['sendNotificationEmail'], 'true')
        self.assertEqual(params['fields'], 'id')

    def test_share_idempotent(self):
        d = self.drive(entrada=[perm('d1', 'op@gmail.com', inherited=False)])
        self.assertEqual(d.share_entrada('OP@gmail.com'), 'd1')
        self.assertEqual(self.fake.writes(), [])

    def test_share_refused_without_can_share(self):
        d = self.drive(can_share=False)
        with self.assertRaisesRegex(ValueError, 'sem permissão para compartilhar'):
            d.share_entrada('op@gmail.com')
        self.assertEqual(self.fake.writes(), [])

    def test_share_not_confirmed(self):
        d = self.drive(hide_create=True)
        with self.assertRaisesRegex(ValueError, 'Compartilhamento não confirmado'):
            d.share_entrada('op@gmail.com')
        self.assertEqual(len(self.fake.writes()), 1)

    def test_owner_bot_and_invalid_email_refused(self):
        d = self.drive()
        for email in (OWNER.upper(), 'sem-arroba', 'a@b', 'a b@c.com', ''):
            with self.assertRaises(ValueError): d.share_entrada(email)
            with self.assertRaises(ValueError): d.revoke_entrada(email)
        with self.assertRaisesRegex(ValueError, 'herdado'): d.share_entrada(BOT)
        with self.assertRaisesRegex(ValueError, 'herdado'): d.revoke_entrada(BOT)
        self.assertEqual(self.fake.writes(), [])

    def test_revoke_only_direct_of_email(self):
        d = self.drive(entrada=[perm('d1', 'op@gmail.com', inherited=False),
                                perm('d2', 'OP@gmail.com', 'reader'),
                                perm('x1', 'outro@gmail.com', inherited=False)])
        self.assertTrue(d.revoke_entrada('op@gmail.com'))
        self.assertEqual(sorted(c[1] for c in self.fake.writes()),
                         ['/inbox/permissions/d1', '/inbox/permissions/d2'])
        self.assertEqual({p['id'] for p in self.fake.entrada}, {'o1', 's1', 'x1'})
        self.assertEqual(self.fake.calls[-1][1], '/inbox/permissions')

    def test_revoke_absent(self):
        d = self.drive(entrada=[perm('x1', 'outro@gmail.com')])
        self.assertFalse(d.revoke_entrada('op@gmail.com'))
        self.assertEqual(self.fake.writes(), [])

    def test_revoke_inherited_remains_after_direct_deleted(self):
        d = self.drive(entrada=[perm('d1', 'op@gmail.com', inherited=False),
                                perm('h1', 'op@gmail.com', 'reader', inherited=True)])
        with self.assertRaisesRegex(ValueError, 'Acesso herdado da raiz'):
            d.revoke_entrada('op@gmail.com')
        self.assertEqual([c[1] for c in self.fake.writes()], ['/inbox/permissions/d1'])

    def test_revoke_delete_error_propagates(self):
        d = self.drive(entrada=[perm('d1', 'op@gmail.com')], fail_delete=True)
        with self.assertRaises(OSError): d.revoke_entrada('op@gmail.com')

    def test_pagination(self):
        extra = [perm(f'p{i}', f'u{i}@gmail.com') for i in range(5)]
        d = self.drive(entrada=extra + [perm('d1', 'op@gmail.com')], page=2)
        self.assertEqual(len(d.entrada_permissions()), 8)
        tokens = [c[2]['pageToken'] for c in self.fake.calls if c[1] == '/inbox/permissions']
        self.assertEqual(tokens, [None, '2', '4', '6'])
        self.assertEqual(d.share_entrada('op@gmail.com'), 'd1')
        self.assertTrue(d.revoke_entrada('op@gmail.com'))
        self.assertEqual([c[1] for c in self.fake.writes()], ['/inbox/permissions/d1'])


if __name__ == '__main__':
    unittest.main()
