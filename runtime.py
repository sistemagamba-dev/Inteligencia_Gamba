"""Configuração exclusiva da equipe técnica. Sem fluxo de login ou segredos na UI."""
import json
import os
from pathlib import Path
import tempfile

from acesso import AccessManager, normalize_email
from drive_adapter import LocalDrive, GoogleDrive
from experiments.sheets_poc.store import SheetsProof
from workflow import SheetsWorkflow

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
# Ambiente explícito; o padrão é homologação. Cada um aceita só a raiz do seu prefixo.
PREFIXES = {'homologacao': 'JANUS_TESTE', 'producao': 'JANUS_PRODUCAO'}
# Recursos de homologação já usados: produção nunca deve apontar para eles.
HOMOLOGACAO = {'sheet': '1MaEfmY-7vnrS2c201evYopfoyRUDRXkzHg5udIFtKoo',
               'root': '1z3FUCnOVMd4m0aSNE6cFBKrPDma0aQIw'}


def mode():
    return os.environ.get('JANUS_MODE', 'local')


def ambiente():
    value = os.environ.get('JANUS_AMBIENTE', 'homologacao')
    if value not in PREFIXES:
        raise ValueError('Ambiente desconhecido: use JANUS_AMBIENTE=homologacao ou producao')
    return value


def producao():
    return ambiente() == 'producao'


def google_settings():
    """Valida a configuração antes de qualquer credencial ou chamada ao Google."""
    env = ambiente()
    root, alias = os.environ.get('JANUS_TEST_ROOT'), os.environ.get('JANUS_ROOT')
    if root and alias and root != alias:
        raise ValueError('JANUS_ROOT e JANUS_TEST_ROOT divergentes')
    root = alias or root
    if not root:
        raise ValueError('Configure JANUS_ROOT')
    sheet = os.environ['JANUS_SHEET_ID']
    if env == 'producao' and (sheet == HOMOLOGACAO['sheet'] or root == HOMOLOGACAO['root']):
        raise ValueError('Produção não pode usar a planilha ou a pasta de homologação')
    folders = [root] + [os.environ['JANUS_' + name] for name in ('ENTRADA', 'PROCESSADOS', 'FALHAS')]
    return {'sheet': sheet, 'folders': folders, 'prefix': PREFIXES[env], 'admins': admins(),
            'allowed': _emails('JANUS_ALLOWED_EMAILS')}


def _emails(name):
    return {e.strip().lower() for e in os.environ.get(name, '').split(',') if e.strip()}


def admins():
    """JANUS_ADMIN_EMAILS: lista separada por vírgulas; vazia = nenhum Adm. Valor inválido recusa o início."""
    try:
        return frozenset(normalize_email(e) for e in _emails('JANUS_ADMIN_EMAILS'))
    except ValueError:
        raise ValueError('JANUS_ADMIN_EMAILS contém e-mail inválido') from None


def google_components(session, settings):
    from sheets_adapter import GoogleSheets
    return SheetsWorkflow(SheetsProof(GoogleSheets(session, settings['sheet'])),
                          GoogleDrive(session, *settings['folders'], prefix=settings['prefix']))


def google_access(session, settings, drive, service_email):
    # Cadastro na aba usuarios da mesma planilha; o journal não é tocado.
    from sheets_adapter import GoogleSheets
    from usuarios import UsersRegistry
    registry = UsersRegistry(GoogleSheets(session, settings['sheet'], range_='usuarios!A:F'))
    return AccessManager(registry, drive, admins=settings['admins'], allowed=settings['allowed'],
                         protected={service_email} if service_email else ())


def components():
    env = ambiente()
    if mode() == 'local':
        if env == 'producao':
            raise ValueError('Produção exige JANUS_MODE=google')
        # Demonstração: Sheets simulado em memória e PDFs inventados numa pasta nova.
        from manage import demo_files
        from experiments.sheets_poc.fake import SimulatedSheets
        root = Path(os.environ.get('JANUS_DATA_DIR') or tempfile.mkdtemp(prefix='janus-demo-'))
        history = demo_files(root)
        proof = SheetsProof(SimulatedSheets())
        proof.import_history(history.read_bytes())
        flow = SheetsWorkflow(proof, LocalDrive(root/'drive'))
        flow.access = None  # Demonstração: sem login nem Adm.
        return flow
    if mode() == 'google':
        settings = google_settings()
        # Conta de serviço provisionada como segredo; nunca inicia consentimento.
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        info = json.loads(os.environ['JANUS_GOOGLE_SA_JSON'])
        session = AuthorizedSession(service_account.Credentials.from_service_account_info(info, scopes=SCOPES))
        flow = google_components(session, settings)
        flow.access = google_access(session, settings, flow.drive, info.get('client_email', ''))
        return flow
    raise ValueError('Modo desconhecido')


def allowed(email):
    """Compatibilidade: o app em modo google usa flow.access (cadastro + Adm). Modo google exige e-mail autorizado: o repositório é público e o app pode ficar público por engano."""
    if mode() != 'google':
        return True
    return bool(email) and email.strip().lower() in _emails('JANUS_ALLOWED_EMAILS')
