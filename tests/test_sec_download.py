"""Revogação depois de o botão "Baixar Excel" já estar na tela (clique no botão desenhado, não rerun).

AppTest: executa o mesmo caminho do servidor no clique (MediaFileManager.execute_deferred).
Navegador (opcional): app.py real em `streamlit run` com fakes, clicado pelo Playwright;
roda só onde o pacote playwright existe, ex.: `<venv>/bin/python -m unittest tests.test_sec_download`.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

ROOT = Path(__file__).resolve().parent.parent
CHROMIUM = os.environ.get('JANUS_CHROMIUM', '/opt/pw-browsers/chromium-1243/chrome-linux64/chrome')


class DeferredDownloadTests(unittest.TestCase):
    """O Excel só sai do servidor no clique, após conferência atual do cadastro."""

    def setUp(self):
        from tests.test_ui import GoogleAccessInterfaceTests
        case = GoogleAccessInterfaceTests('test_operator_works_without_adm')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case, self.registry, self.oper = case, case.registry, case.oper
        # Como no servidor real: um único MediaFileManager vale para todos os reruns.
        self.manager = MediaFileManager(MemoryMediaFileStorage('/mock/media'))
        patcher = patch('streamlit.testing.v1.app_test.MediaFileManager', return_value=self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rendered(self):
        app = self.case.run_app(self.oper)
        self.case.button(app, 'Preparar Excel da base').click().run()
        [download] = app.get('download_button')
        self.assertEqual(download.proto.label, 'Baixar Excel (.xlsx)')
        return app, download.proto

    def click(self, proto):
        """O que o servidor faz quando o botão já desenhado é clicado (deferred_file_request)."""
        url = self.manager.execute_deferred(proto.deferred_file_id)
        return self.manager._storage.get_file(url.rsplit('/', 1)[1].split('.')[0]).content

    def test_no_bytes_published_when_rendered(self):
        _, proto = self.rendered()
        self.assertEqual(proto.url, '')  # Nenhuma URL /media com o Excel antes do clique.
        self.assertTrue(proto.deferred_file_id)

    def test_authorized_click_downloads_excel(self):
        _, proto = self.rendered()
        self.assertTrue(self.click(proto).startswith(b'PK'))

    def test_revoked_after_render_gets_no_bytes(self):
        app, proto = self.rendered()
        self.registry.emails.clear()  # Revogado por um Adm em outra sessão, botão ainda na tela.
        with self.assertRaisesRegex(Exception, 'Seu acesso foi removido'):
            self.click(proto)
        app.run()  # O rerun do clique mostra o bloqueio e apaga o Excel da sessão.
        self.assertIn('Seu acesso foi removido.', app.error[0].value)
        self.assertNotIn('export', app.session_state)
        with self.assertRaises(Exception):
            self.click(proto)  # Depois do rerun a função registrada nem existe mais.

    def test_unreadable_registry_at_click_gets_no_bytes(self):
        _, proto = self.rendered()
        self.registry.fail = {'read'}
        with self.assertRaisesRegex(Exception, 'Seu acesso foi removido'):
            self.click(proto)


HARNESS = '''
"""app.py real em modo google com login simulado e fakes; o cadastro é o arquivo REGISTRY."""
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, {root!r})
os.environ['JANUS_MODE'] = 'google'
import streamlit as st
import runtime, app
from acesso import AccessManager

REGISTRY = Path({registry!r})


class FileRegistry:
    def active(self):
        return set(REGISTRY.read_text().split())  # Leitura atual a cada chamada.


@st.cache_resource
def fake_flow():
    from drive_adapter import LocalDrive
    from experiments.sheets_poc.fake import SimulatedSheets
    from experiments.sheets_poc.store import SheetsProof
    from manage import demo_files
    from workflow import SheetsWorkflow
    root = Path({tmp!r})
    proof = SheetsProof(SimulatedSheets())
    proof.import_history(demo_files(root).read_bytes())
    flow = SheetsWorkflow(proof, LocalDrive(root/'drive'))
    flow.access = AccessManager(FileRegistry(), None, admins=['adm@example.org'])
    return flow


runtime.components = fake_flow
st.user = SimpleNamespace(is_logged_in=True, email='assessor@example.org')
app.main()
'''


def _playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return os.path.exists(CHROMIUM)
    except ImportError:
        return False


def run_experiment(tmp, revoke=True):
    """Desenha o botão, revoga fora da sessão e clica no botão já desenhado. Devolve o observado."""
    from playwright.sync_api import sync_playwright
    tmp = Path(tmp)
    registry = tmp/'usuarios.txt'
    registry.write_text('assessor@example.org\n')
    harness = tmp/'harness.py'
    harness.write_text(HARNESS.format(root=str(ROOT), registry=str(registry), tmp=str(tmp/'dados')))
    (tmp/'dados').mkdir()
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, '-m', 'streamlit', 'run', str(harness), '--server.address', '127.0.0.1',
         '--server.port', str(port), '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
        cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM)
            page = browser.new_page(accept_downloads=True)
            for _ in range(60):
                try:
                    page.goto(f'http://127.0.0.1:{port}/', timeout=2000)
                    break
                except Exception:
                    time.sleep(0.5)
            page.get_by_role('button', name='Preparar Excel da base').click(timeout=30000)
            baixar = page.get_by_role('button', name='Baixar Excel (.xlsx)')
            baixar.wait_for(timeout=30000)
            if revoke:
                registry.write_text('')  # Revogação fora da sessão; nenhum rerun acontece aqui.
            try:
                with page.expect_download(timeout=8000) as info:
                    baixar.click()
                out['download'] = Path(info.value.path()).read_bytes()
            except Exception as exc:
                out['download'] = None
                out['download_error'] = type(exc).__name__
            if revoke:
                page.get_by_text('Seu acesso foi removido.').wait_for(timeout=15000)
            out['blocked_after'] = page.get_by_text('Seu acesso foi removido.').count() > 0
            out['button_error'] = page.locator('.stDownloadButton').all_inner_texts()
            browser.close()
    finally:
        server.terminate()
        out['server_log'] = server.communicate(timeout=10)[0]
    return out


@unittest.skipUnless(_playwright(), 'playwright/chromium indisponível')
class BrowserRevocationTests(unittest.TestCase):
    def test_revoked_user_clicking_rendered_button_gets_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_experiment(tmp)
        self.assertTrue(out['blocked_after'])
        self.assertIsNone(out['download'] and f"Excel baixado por usuário revogado: {len(out['download'])} bytes")

    def test_authorized_user_still_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_experiment(tmp, revoke=False)
        self.assertFalse(out['blocked_after'])
        self.assertTrue(out['download'].startswith(b'PK'))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        result = run_experiment(tmp, revoke='--autorizado' not in sys.argv)
    log = result.pop('server_log')
    data = result.get('download')
    if data is not None:
        from io import BytesIO
        import openpyxl
        sheet = openpyxl.load_workbook(BytesIO(data)).active
        rows = [[v for v in r if v is not None] for r in sheet.iter_rows(values_only=True)]
        result['download'] = f'{len(data)} bytes; linhas: {[r[:2] for r in rows if r]}'
    print(result)
    print(textwrap.indent(log[-1500:], '  | '))
