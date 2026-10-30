"""Ensaio opcional com Chromium/Playwright; servidor local e demo NOVA já iniciados.
Uso: python browser_check.py /tmp/janus-browser-test docs/evidence/etapa2
Requer playwright e chromium, apenas na máquina de verificação.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
from playwright.sync_api import sync_playwright, expect
from openpyxl import load_workbook


def run(root, evidence):
    evidence.mkdir(parents=True, exist_ok=True)
    def count():
        with sqlite3.connect(root/'janus.sqlite') as db:
            return db.execute('SELECT count(*) FROM records').fetchone()[0]
    assert count() == 0, 'Use demonstração nova'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(os.environ.get('JANUS_BROWSER_URL','http://127.0.0.1:8501'))
        page.get_by_role('button',name='Processar PDFs',exact=True).click()
        expect(page.get_by_role('button',name='Aprovar e registrar tudo',exact=True)).to_be_visible()
        assert count() == 0
        expect(page.get_by_text('Novos para conferir: 3',exact=False)).to_be_visible()
        page.wait_for_timeout(800)  # Aguarda pintura dos canvas da tabela.
        page.screenshot(path=str(evidence/'browser-preview.png'),full_page=True)
        page.get_by_role('button',name='Aprovar e registrar tudo',exact=True).click()
        expect(page.get_by_text('3 novos registrados',exact=False)).to_be_visible()
        assert count() == 3
        page.get_by_role('button',name='Preparar Excel da base',exact=True).click()
        download_button = page.get_by_role('button',name='Baixar Excel (.xlsx)',exact=True)
        expect(download_button).to_be_visible()
        with page.expect_download() as download:
            download_button.click()
        path = root/'browser-export.xlsx'
        download.value.save_as(path)
        book = load_workbook(path,read_only=True)
        assert book['JANUS 2026'].max_column == 10
        assert book['JANUS 2026'].max_row == 7
        book.close()
        page.wait_for_timeout(400)
        page.screenshot(path=str(evidence/'browser-approved.png'),full_page=True)
        page.reload()
        page.get_by_role('button',name='Processar PDFs',exact=True).click()
        expect(page.get_by_text('Novos para conferir: 0',exact=False)).to_be_visible()
        assert count() == 3
        assert len(list((root/'drive'/'processados').glob('*.pdf'))) == 3
        assert len(list((root/'drive'/'entrada').glob('*.pdf'))) == 2
        assert not page.locator('[data-testid="stException"]').count()
        assert not errors
        # Viewport compacto: ações continuam acessíveis, tabela rola horizontalmente.
        page.set_viewport_size({'width':390,'height':844})
        expect(page.get_by_role('button',name='Processar PDFs',exact=True)).to_be_visible()
        browser.close()
    return {'environment':'Chromium headless / Streamlit local / PDFs sintéticos',
            'preview_before_approval_records':0,'after_approval_records':3,
            'historical_rows_preserved':2,'duplicates_ignored':1,'invalid_files_preserved':1,
            'archived_pdfs':3,'pending_pdfs':2,'xlsx_columns':10,'xlsx_data_rows':5,
            'browser_reload_no_new_records':True,'browser_errors':errors,
            'compact_viewport_action_visible':True,
            'google_drive_live':False,'human_acceptance':False}


if __name__ == '__main__':
    result = run(Path(sys.argv[1]),Path(sys.argv[2]))
    (Path(sys.argv[2])/'browser.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
