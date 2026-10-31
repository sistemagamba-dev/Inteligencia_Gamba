"""Adaptadores de Drive. Nunca excluem arquivos; permissões só na pasta de entrada."""
from dataclasses import dataclass
from pathlib import Path
import re
import hashlib


@dataclass(frozen=True)
class DriveFile:
    id: str
    url: str


class LocalDrive:
    """Substituto isolado da API, somente para demonstração sintética local."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        for name in ('entrada', 'processados', 'falhas'):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def _path(self, folder, file_id):
        if Path(file_id).name != file_id or file_id in ('', '.', '..'):
            raise ValueError('Arquivo inválido')
        path = self.root / folder / file_id
        if path.is_symlink():
            raise ValueError('Arquivo inválido')
        return path

    def pending(self):
        return [DriveFile(p.name, '') for p in sorted((self.root/'entrada').glob('*.pdf'))]

    def read(self, file_id):
        return self._path('entrada', file_id).read_bytes()

    def archive(self, file_id, expected_digest):
        source = self._path('entrada', file_id)
        target = self._path('processados', file_id)
        existing = source if source.exists() else target
        if hashlib.sha256(existing.read_bytes()).hexdigest() != expected_digest:
            raise ValueError('Arquivo mudou após aprovação')
        if target.exists():
            if source.exists():
                raise ValueError('Destino ocupado; arquivo preservado')
            return  # Confirmação perdida depois de mover.
        source.rename(target)


class GoogleDrive:
    """Drive v3 com identidade configurada pela equipe técnica, fora da interface.

    Raiz deve começar pelo prefixo do ambiente (JANUS_TESTE em homologação,
    JANUS_PRODUCAO em produção); filhos devem estar diretamente nessa raiz.
    Isso é uma barreira contra enganos de configuração, não substitui permissões.
    """
    API = 'https://www.googleapis.com/drive/v3/files'
    EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
    PREFIXES = {'JANUS_TESTE': 'Use uma raiz de teste dedicada',
                'JANUS_PRODUCAO': 'Use a raiz de produção dedicada'}

    def __init__(self, session, root, entrada, processados, falhas, prefix='JANUS_TESTE'):
        if prefix not in self.PREFIXES:
            raise ValueError('Prefixo de raiz desconhecido')
        self.session = session
        self.root, self.entrada, self.processados, self.falhas = root, entrada, processados, falhas
        if len({root, entrada, processados, falhas}) != 4:
            raise ValueError('Pastas devem ser diferentes')
        for value in (root, entrada, processados, falhas):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
                raise ValueError('Pasta inválida')
        parent = self._metadata(root)
        # Prefixos disjuntos: raiz de teste nunca serve à produção e vice-versa.
        if (not parent['name'].startswith(prefix) or parent.get('trashed') or
                any(parent['name'].startswith(p) for p in self.PREFIXES if p != prefix)):
            raise ValueError(self.PREFIXES[prefix])
        if parent['mimeType'] != 'application/vnd.google-apps.folder':
            raise ValueError('Raiz inválida')
        for folder in (entrada, processados, falhas):
            meta = self._metadata(folder)
            if (meta.get('parents') != [root] or meta.get('trashed') or
                    meta['mimeType'] != 'application/vnd.google-apps.folder'):
                raise ValueError('Pasta fora da raiz')

    def _request(self, method, suffix='', **kwargs):
        response = self.session.request(method, self.API + suffix, timeout=60, **kwargs)
        response.raise_for_status()
        return response

    def _metadata(self, file_id):
        return self._request('GET', '/' + file_id, params={
            'fields': 'id,name,mimeType,parents,trashed', 'supportsAllDrives': 'true'}).json()

    def pending(self):
        files, token = [], None
        while True:
            data = self._request('GET', params={
                'q': f"'{self.entrada}' in parents and trashed = false and mimeType = 'application/pdf'",
                'fields': 'nextPageToken,files(id)', 'pageSize': 100,
                'pageToken': token, 'supportsAllDrives': 'true',
                'includeItemsFromAllDrives': 'true'}).json()
            files.extend(DriveFile(f['id'], f"https://drive.google.com/file/d/{f['id']}/view")
                         for f in data.get('files', []))
            token = data.get('nextPageToken')
            if not token:
                return files

    def read(self, file_id):
        meta = self._metadata(file_id)
        if (meta.get('trashed') or meta.get('parents') != [self.entrada] or
                meta['mimeType'] != 'application/pdf'):
            raise ValueError('Arquivo fora da entrada')
        return self._request('GET', '/' + file_id, params={
            'alt': 'media', 'supportsAllDrives': 'true'}).content

    def archive(self, file_id, expected_digest):
        meta = self._metadata(file_id)
        if meta.get('trashed'):
            raise ValueError('Arquivo indisponível')
        if meta.get('parents') not in ([self.entrada], [self.processados]):
            raise ValueError('Arquivo fora das pastas')
        content = self._request('GET', '/' + file_id, params={
            'alt': 'media', 'supportsAllDrives': 'true'}).content
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError('Arquivo mudou após aprovação')
        if meta.get('parents') == [self.processados]:
            return
        if meta.get('parents') != [self.entrada]:
            raise ValueError('Arquivo fora da entrada')
        self._request('PATCH', '/' + file_id, params={
            'addParents': self.processados, 'removeParents': self.entrada,
            'fields': 'id,parents', 'supportsAllDrives': 'true'}, json={})
        if self._metadata(file_id).get('parents') != [self.processados]:
            raise ValueError('Arquivamento não confirmado')

    # ACL: toda escrita de permissão vai para self.entrada; a raiz só é lida.
    def _permissions(self, file_id, fields):
        items, token = [], None
        while True:
            data = self._request('GET', f'/{file_id}/permissions', params={
                'fields': f'nextPageToken,permissions({fields})', 'pageSize': 100,
                'pageToken': token, 'supportsAllDrives': 'true'}).json()
            items.extend(data.get('permissions', []))
            token = data.get('nextPageToken')
            if not token:
                return items

    def _email(self, email):
        email = str(email or '').strip().lower()
        if not self.EMAIL.fullmatch(email):
            raise ValueError('E-mail inválido')
        return email

    def entrada_sharing(self):
        caps = self._request('GET', '/' + self.entrada, params={
            'fields': 'capabilities(canShare)', 'supportsAllDrives': 'true'}).json()
        root = self._request('GET', '/' + self.root, params={
            'fields': 'owners(emailAddress)', 'supportsAllDrives': 'true'}).json()
        return {'can_share': (caps.get('capabilities') or {}).get('canShare') is True,
                'owners': [o['emailAddress'].lower() for o in root.get('owners', [])
                           if o.get('emailAddress')]}

    PERM_FIELDS = 'id,emailAddress,role,type,domain,allowFileDiscovery,permissionDetails'

    def _entry(self, p, inherited):
        return {'id': p['id'], 'email': (p.get('emailAddress') or '').lower(), 'role': p.get('role'),
                'type': p.get('type'), 'inherited': inherited,
                'domain': (p.get('domain') or '').lower(), 'discovery': p.get('allowFileDiscovery') is True}

    def entrada_permissions(self, root=None):
        if root is None:
            root = self._permissions(self.root, 'id,emailAddress')
        on_root = {(p.get('emailAddress') or '').lower() for p in root} - {''}
        result = []
        for p in self._permissions(self.entrada, self.PERM_FIELDS):
            email = (p.get('emailAddress') or '').lower()
            # Conservador: qualquer sinal de herança (detalhe ou presença na raiz) conta.
            inherited = (any(d.get('inherited') for d in p.get('permissionDetails') or []) or
                         email in on_root)
            result.append(self._entry(p, inherited))
        return result

    @staticmethod
    def _safe(value):
        return re.sub(r'[^a-z0-9@._-]', '', str(value or '').lower())[:254]

    def broad_sharing(self):
        """Só leitura: permissões que não são de uma pessoa (anyone, domain, group, tipo
        desconhecido ou usuário sem e-mail) na entrada e na raiz (herdadas por tudo nela).
        Erro de leitura propaga: nunca se conclui isolamento sem ler as duas pastas."""
        root = [self._entry(p, False) for p in self._permissions(self.root, self.PERM_FIELDS)]
        found, seen = [], set()
        for where, perms in (('raiz', root), ('entrada', self.entrada_permissions(root))):
            for p in perms:
                if p['type'] == 'user' and p['email']:
                    continue
                item = {'onde': where, 'tipo': self._safe(p['type']) or 'desconhecido',
                        'papel': self._safe(p['role']),
                        'alvo': self._safe(p['domain'] if p['type'] == 'domain' else p['email'])}
                key = (item['tipo'], item['papel'], item['alvo'])
                if where == 'entrada' and p['inherited'] and key in seen:
                    continue  # Já listada na raiz, de onde vem.
                seen.add(key)
                found.append(item)
        return found

    def _guard(self, email):
        email = self._email(email)
        sharing = self.entrada_sharing()
        if email in sharing['owners']:
            raise ValueError('Conta proprietária não pode ser alterada')
        return email, sharing

    def _direct(self, email, perms):
        # Só permissão de pessoa: grupo/domínio/anyone nunca são alterados pelo JANUS.
        return [p for p in perms if p['email'] == email and p['type'] == 'user'
                and not p['inherited'] and p['role'] != 'owner']

    def share_entrada(self, email):
        email, sharing = self._guard(email)
        if not sharing['can_share']:
            raise ValueError('Conta técnica sem permissão para compartilhar a pasta de entrada')
        perms = self.entrada_permissions()
        if any(p['email'] == email and p['inherited'] for p in perms):
            raise ValueError('Acesso herdado da raiz; revisar manualmente')
        writer = lambda ps: [p for p in self._direct(email, ps)
                             if p['role'] == 'writer' and p['type'] == 'user']
        if found := writer(perms):
            return found[0]['id']
        created = self._request('POST', f'/{self.entrada}/permissions', params={
            'sendNotificationEmail': 'true', 'fields': 'id', 'supportsAllDrives': 'true'},
            json={'type': 'user', 'role': 'writer', 'emailAddress': email}).json()
        found = writer(self.entrada_permissions())
        if not found:
            raise ValueError('Compartilhamento não confirmado')
        ids = [p['id'] for p in found]
        return created.get('id') if created.get('id') in ids else ids[0]

    def revoke_entrada(self, email):
        email, _ = self._guard(email)
        targets = self._direct(email, self.entrada_permissions())
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', p['id']) for p in targets):
            raise ValueError('Permissão inválida')
        for p in targets:
            self._request('DELETE', f"/{self.entrada}/permissions/{p['id']}",
                          params={'supportsAllDrives': 'true'})
        after = [p for p in self.entrada_permissions() if p['email'] == email]
        if self._direct(email, after):
            raise ValueError('Revogação não confirmada')
        if any(p['inherited'] for p in after):
            raise ValueError('Acesso herdado da raiz; revisar manualmente')
        return bool(targets)
