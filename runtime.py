"""Configuração exclusiva da equipe técnica. Sem fluxo de login ou segredos na UI."""
import os
from pathlib import Path
from drive_adapter import LocalDrive, GoogleDrive
from storage import Store


def components():
    root = Path(os.environ.get('JANUS_DATA_DIR', '.janus-data/demo')).resolve()
    mode = os.environ.get('JANUS_MODE', 'local')
    if mode == 'local':
        drive = LocalDrive(root/'drive')
        binding = 'local:' + str(drive.root)
    elif mode == 'google':
        if 'JANUS_DATA_DIR' not in os.environ:
            raise ValueError('Configure um volume persistente para a base de teste')
        # Apenas credenciais previamente provisionadas; nunca inicia consentimento.
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive'])
        folders = [os.environ['JANUS_' + name] for name in ('TEST_ROOT', 'ENTRADA', 'PROCESSADOS', 'FALHAS')]
        drive = GoogleDrive(AuthorizedSession(credentials), *folders)
        binding = 'google:' + ':'.join(folders)
    else:
        raise ValueError('Modo desconhecido')
    store = Store(root/'janus.sqlite')
    with store.exclusive(), store.db:
        saved = store.db.execute("SELECT value FROM meta WHERE key='drive_binding'").fetchone()
        if saved and saved[0] != binding:
            raise ValueError('A base está vinculada a outra pasta')
        store.db.execute("INSERT OR IGNORE INTO meta VALUES ('drive_binding',?)", (binding,))
    return store, drive
