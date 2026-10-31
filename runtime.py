"""Configuração exclusiva da equipe técnica. Sem fluxo de login ou segredos na UI."""
import json
import os
from pathlib import Path
import tempfile

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
    return {'sheet': sheet, 'folders': folders, 'prefix': PREFIXES[env]}


def google_components(session, settings):
    from sheets_adapter import GoogleSheets
    return SheetsWorkflow(SheetsProof(GoogleSheets(session, settings['sheet'])),
                          GoogleDrive(session, *settings['folders'], prefix=settings['prefix']))


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
        return SheetsWorkflow(proof, LocalDrive(root/'drive'))
    if mode() == 'google':
        settings = google_settings()
        # Conta de serviço provisionada como segredo; nunca inicia consentimento.
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        info = json.loads(os.environ['JANUS_GOOGLE_SA_JSON'])
        session = AuthorizedSession(service_account.Credentials.from_service_account_info(info, scopes=SCOPES))
        return google_components(session, settings)
    raise ValueError('Modo desconhecido')


def allowed(email):
    """Modo google exige e-mail autorizado: o repositório é público e o app pode ficar público por engano."""
    if mode() != 'google':
        return True
    emails = {e.strip().lower() for e in os.environ.get('JANUS_ALLOWED_EMAILS', '').split(',') if e.strip()}
    return bool(email) and email.strip().lower() in emails
