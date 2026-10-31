"""Configuração exclusiva da equipe técnica. Sem fluxo de login ou segredos na UI."""
import json
import os
from pathlib import Path
import tempfile

from drive_adapter import LocalDrive, GoogleDrive
from experiments.sheets_poc.store import SheetsProof
from workflow import SheetsWorkflow

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']


def mode():
    return os.environ.get('JANUS_MODE', 'local')


def components():
    if mode() == 'local':
        # Demonstração: Sheets simulado em memória e PDFs inventados numa pasta nova.
        from manage import demo_files
        from experiments.sheets_poc.fake import SimulatedSheets
        root = Path(os.environ.get('JANUS_DATA_DIR') or tempfile.mkdtemp(prefix='janus-demo-'))
        history = demo_files(root)
        proof = SheetsProof(SimulatedSheets())
        proof.import_history(history.read_bytes())
        return SheetsWorkflow(proof, LocalDrive(root/'drive'))
    if mode() == 'google':
        # Conta de serviço provisionada como segredo; nunca inicia consentimento.
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        from sheets_adapter import GoogleSheets
        info = json.loads(os.environ['JANUS_GOOGLE_SA_JSON'])
        session = AuthorizedSession(service_account.Credentials.from_service_account_info(info, scopes=SCOPES))
        folders = [os.environ['JANUS_' + name] for name in ('TEST_ROOT', 'ENTRADA', 'PROCESSADOS', 'FALHAS')]
        return SheetsWorkflow(SheetsProof(GoogleSheets(session, os.environ['JANUS_SHEET_ID'])),
                              GoogleDrive(session, *folders))
    raise ValueError('Modo desconhecido')


def allowed(email):
    """Modo google exige e-mail autorizado: o repositório é público e o app pode ficar público por engano."""
    if mode() != 'google':
        return True
    emails = {e.strip().lower() for e in os.environ.get('JANUS_ALLOWED_EMAILS', '').split(',') if e.strip()}
    return bool(email) and email.strip().lower() in emails
