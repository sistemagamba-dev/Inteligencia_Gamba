"""Prova simples de operador único; controles negativos são identificados."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook
from janus import HEADERS, Record, extract
from drive_adapter import LocalDrive
from tests.fixtures import text, pdf
from experiments.sheets_poc.fake import SimulatedSheets
from experiments.sheets_poc.store import SheetsProof, Coordinator, Busy, Unconfirmed


def history_bytes(changed=False):
    book=Workbook(); sheet=book.active; sheet.title='JANUS 2026'
    sheet.append([]); sheet.append(HEADERS)
    for order in (10,20):
        sheet.append([order,datetime(2026,1,2),'Outra pessoa inventada' if changed else 'Pessoa histórica inventada',
                      None,'C000000000000000009','JANUS',None,None,None,None])
    sheet.append([None]*10)
    stream=BytesIO(); book.save(stream); book.close()
    return stream.getvalue()


class SheetsProofTests(unittest.TestCase):
    def setUp(self):
        self.remote=SimulatedSheets(); self.coordinator=Coordinator()
        self.store=SheetsProof(self.remote,self.coordinator)
        self.item=('file1',Record(protocol='C000000000000000001',requester='Pessoa inventada'),hashlib.sha256(b'pdf1').hexdigest())

    def test_approval_and_invalid_batch_do_not_write(self):
        with self.assertRaises(ValueError):self.store.approve('batch',[self.item])
        with self.assertRaises(ValueError):
            self.store.approve('batch',[self.item,('bad',Record(protocol='?'),'a'*64)],approved=True)
        self.assertEqual(self.remote.commits,0)

    def test_double_click_is_blocked_in_same_process(self):
        entered=threading.Event(); release=threading.Event()
        def hook():
            entered.set()
            if not release.wait(5):raise TimeoutError('Teste travado')
        self.remote.after_get=hook
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.store.approve,'batch',[self.item],approved=True)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(Busy):
                    SheetsProof(self.remote,self.coordinator).approve('batch',[self.item],approved=True)
            finally:
                self.remote.after_get=None; release.set()
            self.assertEqual(future.result()['inserted'],1)
        self.assertEqual(len(self.store.state()['records']),1)

    def test_reprocessing_and_intralot_duplicates_are_ignored(self):
        duplicate=('file2',replace(self.item[1],protocol='c-0000.0000.0000.0000/01'),self.item[2])
        self.assertEqual(self.store.approve('one',[self.item,duplicate],approved=True),{'inserted':1,'ignored':1})
        self.assertEqual(self.store.approve('two',[self.item],approved=True),{'inserted':0,'ignored':1})
        self.assertEqual(len(self.store.state()['records']),1)

    def test_timeout_before_commit_repeats_fixed_positions(self):
        self.remote.failures=['before']
        with self.assertRaises(Unconfirmed):self.store.approve('batch',[self.item],approved=True)
        self.assertEqual(self.remote.commits,0)
        with self.assertRaises(Unconfirmed):self.store.approve('other',[self.item],approved=True)
        self.assertEqual(self.store.approve('batch',[self.item],approved=True)['inserted'],1)
        self.assertEqual(len(self.store.state()['records']),1)

    def test_timeout_after_commit_is_reconciled(self):
        self.remote.failures=['after']
        self.assertEqual(self.store.approve('batch',[self.item],approved=True)['inserted'],1)
        commits=self.remote.commits
        self.assertEqual(SheetsProof(self.remote,Coordinator()).approve('batch',[self.item],approved=True)['inserted'],1)
        self.assertEqual(self.remote.commits,commits)
        self.assertEqual(len(self.store.state()['records']),1)

    def test_late_request_after_retry_does_not_overwrite_next_batch(self):
        self.remote.failures=['deferred']
        with self.assertRaises(Unconfirmed):self.store.approve('one',[self.item],approved=True)
        self.store.approve('one',[self.item],approved=True)
        second=('file2',replace(self.item[1],protocol='C000000000000000002'),self.item[2])
        self.store.approve('two',[second],approved=True)
        self.remote.deliver_deferred()
        self.assertEqual(len(self.store.state()['records']),2)
        self.assertEqual(set(self.store.state()['receipts']),{'one','two'})

    def test_negative_control_cold_restart_can_overwrite_unconfirmed_reservation(self):
        # Achado, não propriedade de sucesso: nenhuma reserva durável foi confirmada.
        self.remote.failures=['deferred']
        with self.assertRaises(Unconfirmed):self.store.approve('one',[self.item],approved=True)
        fresh=SheetsProof(self.remote,Coordinator()) # Perde memória de pedido em trânsito.
        second=('file2',replace(self.item[1],protocol='C000000000000000002'),self.item[2])
        fresh.approve('two',[second],approved=True)
        self.assertEqual(fresh.state()['records'][0][2],'C000000000000000002')
        self.remote.deliver_deferred()
        # Pedido antigo ocupa a mesma posição e elimina o registro confirmado do lote two.
        self.assertEqual(fresh.state()['records'][0][2],self.item[1].protocol)
        self.assertNotIn('two',fresh.state()['receipts'])
        self.assertEqual(len(fresh.state()['records']),1)

    def test_invalid_subrequest_is_atomic(self):
        before=self.remote.get()
        with self.assertRaises(ValueError):
            self.remote.batch_update({'valueInputOption':'RAW','data':[
                {'range':'origem!A1','values':[['should-not-persist']]},
                {'range':'invalid-range','values':[['bad']]}]})
        self.assertEqual(self.remote.get(),before)

    def test_history_duplicates_blank_dates_and_export_are_preserved(self):
        source=history_bytes(); digest=hashlib.sha256(source).hexdigest()
        self.assertTrue(self.store.import_history(source)); self.assertFalse(self.store.import_history(source))
        old=self.store.state()['history']
        duplicate=('historical',Record(protocol='c-0000.0000.0000.0000/09'),'a'*64)
        item=(self.item[0],replace(self.item[1],requester='=1+1'),self.item[2])
        self.assertEqual(self.store.approve('batch',[item,duplicate],approved=True),{'inserted':1,'ignored':1})
        with self.assertRaises(ValueError):self.store.import_history(history_bytes(True))
        self.assertEqual(self.store.state()['history'],old)
        output=BytesIO(); self.store.export(output); output.seek(0)
        book=load_workbook(output); sheet=book['JANUS 2026']
        self.assertEqual(tuple(c.value for c in sheet[2]),HEADERS)
        self.assertEqual([list(r) for r in sheet.iter_rows(min_row=3,max_row=5,values_only=True)],old)
        self.assertEqual(sheet.cell(6,1).value,21)
        self.assertEqual(sheet.cell(6,3).value,'=1+1'); self.assertEqual(sheet.cell(6,3).data_type,'s')
        self.assertIsNone(sheet.cell(6,4).value)
        book.close(); self.assertEqual(hashlib.sha256(source).hexdigest(),digest)

    def test_batch_reuse_and_file_rebinding_are_rejected(self):
        self.store.approve('batch',[self.item],approved=True)
        changed=(self.item[0],replace(self.item[1],protocol='C000000000000000002'),self.item[2])
        with self.assertRaises(ValueError):self.store.approve('batch',[changed],approved=True)
        with self.assertRaises(ValueError):self.store.approve('other',[changed],approved=True)

    def test_late_import_and_large_cell_are_rejected(self):
        big=(self.item[0],replace(self.item[1],description='x'*50001),self.item[2])
        with self.assertRaises(ValueError):self.store.approve('big',[big],approved=True)
        self.assertEqual(self.remote.commits,0)
        self.store.approve('batch',[self.item],approved=True)
        with self.assertRaises(ValueError):self.store.import_history(history_bytes())

    def test_existing_drive_archives_only_confirmed_data_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive=LocalDrive(Path(tmp)/'drive')
            path=drive.root/'entrada'/'file1.pdf'; pdf(path,text('C000000000000000001'))
            data=drive.read('file1.pdf')
            item=('file1.pdf',extract(path),hashlib.sha256(data).hexdigest())
            self.assertEqual(self.store.resume(drive)['archived'],0)
            self.remote.failures=['before']
            with self.assertRaises(Unconfirmed):self.store.approve('batch',[item],approved=True)
            with self.assertRaises(Unconfirmed):self.store.resume(drive)
            self.store.approve('batch',[item],approved=True)
            archive=drive.archive
            def lost(file_id,digest):
                archive(file_id,digest); raise TimeoutError('Movido; confirmação perdida')
            drive.archive=lost
            self.assertEqual(self.store.resume(drive)['failures'],['file1.pdf'])
            drive.archive=archive
            self.remote.failures=['after']
            with self.assertRaises(TimeoutError):self.store.resume(drive)
            self.assertEqual(SheetsProof(self.remote,Coordinator()).resume(drive)['archived'],0)
            self.assertEqual((drive.root/'processados'/'file1.pdf').read_bytes(),data)
            self.assertEqual(len(self.store.state()['records']),1)
