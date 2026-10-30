"""Adaptadores de teste. Nunca excluem arquivos ou alteram permissões."""
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

    Raiz deve começar por JANUS_TESTE; filhos devem estar diretamente nessa raiz.
    Isso é uma barreira contra enganos de configuração, não substitui permissões.
    """
    API = 'https://www.googleapis.com/drive/v3/files'

    def __init__(self, session, root, entrada, processados, falhas):
        self.session = session
        self.root, self.entrada, self.processados, self.falhas = root, entrada, processados, falhas
        if len({root, entrada, processados, falhas}) != 4:
            raise ValueError('Pastas devem ser diferentes')
        for value in (root, entrada, processados, falhas):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
                raise ValueError('Pasta inválida')
        parent = self._metadata(root)
        if not parent['name'].startswith('JANUS_TESTE') or parent.get('trashed'):
            raise ValueError('Use uma raiz de teste dedicada')
        if parent['mimeType'] != 'application/vnd.google-apps.folder':
            raise ValueError('Raiz inválida')
        for folder in (entrada, processados, falhas):
            meta = self._metadata(folder)
            if (meta.get('parents') != [root] or meta.get('trashed') or
                    meta['mimeType'] != 'application/vnd.google-apps.folder'):
                raise ValueError('Pasta fora da raiz de teste')

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
            raise ValueError('Arquivo fora das pastas de teste')
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
