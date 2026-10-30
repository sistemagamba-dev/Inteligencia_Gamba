"""Somente dados inventados e backend em memória. Sem chamadas Google."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from time import perf_counter

from openpyxl import Workbook, load_workbook
from janus import HEADERS, extract
from drive_adapter import LocalDrive
from tests.fixtures import pdf, text
from experiments.sheets_poc.store import SheetsProof, Coordinator
from experiments.sheets_poc.fake import SimulatedSheets


def run():
    book=Workbook(); sheet=book.active; sheet.title='JANUS 2026'
    sheet.append([]); sheet.append(HEADERS)
    historical=[]
    for i in range(3160):
        row=[i+1,None,'Pessoa histórica sintética',None,f'C{i % 3106:018}',
             'JANUS','Categoria sintética','Rua de teste 1','Pedido inventado','Bairro de teste']
        historical.append(row); sheet.append(row)
    source=BytesIO(); book.save(source); book.close()
    remote=SimulatedSheets(); client=SheetsProof(remote,Coordinator())
    start=perf_counter()
    client.import_history(source.getvalue())
    with tempfile.TemporaryDirectory(prefix='janus-sheets-proof-') as tmp:
        drive=LocalDrive(Path(tmp)/'drive'); items=[]
        for i in range(100):
            protocol=f'C{0 if i == 0 else 10001 if i == 2 else 10000+i:018}'
            path=drive.root/'entrada'/f'{i:03}.pdf'
            pdf(path,text(protocol,events=bool(i%2)),pages=4 if i%2 else 2)
            items.append((path.name,extract(path),hashlib.sha256(path.read_bytes()).hexdigest()))
        ready=perf_counter()
        assert not client.state()['records']
        remote.failures=['after'] # Simula commit confirmado no servidor, resposta perdida.
        first=client.approve('synthetic-100',items,approved=True)
        committed=perf_counter()
        count_before=len(client.state()['records'])
        commits_before=remote.commits
        replay=SheetsProof(remote,Coordinator()).approve('synthetic-100',items,approved=True)
        assert replay == first
        assert remote.commits == commits_before
        count_after=len(client.state()['records'])
        archive=SheetsProof(remote,Coordinator()).resume(drive)
        assert first == {'inserted':98,'ignored':2}
        assert archive == {'archived':98,'failures':[]}
        output=BytesIO(); client.export(output); output.seek(0)
        exported=load_workbook(output,read_only=True)
        rows=list(exported.active.iter_rows(min_row=3,max_col=10,values_only=True))
        assert [list(r) for r in rows[:3160]] == historical
        assert len(rows) == 3258
        assert rows[3160][0] == 3161
        assert len(list((drive.root/'entrada').glob('*.pdf'))) == 2
        assert len(list((drive.root/'processados').glob('*.pdf'))) == 98
        exported.close()
        state=client.state()
        assert all(job == ['1'] for job in state['archived'])
        return {'backend':'Google Sheets simulado em memória; Google real não chamado',
                'base_commit':'e8e672b51d68d18b1156fa8d3a3639098ff41f9c',
                'synthetic_history':{'rows':3160,'unique_protocols':3106,'duplicate_excess':54},
                'synthetic_pdfs':100,'pages':300,'records_before_approval':0,'first':first,
                'additional_records_on_replay':count_after-count_before,'additional_commits_on_replay':0,
                'archive':archive,'preserved_pending_pdfs':2,'export_rows':len(rows),
                'history_values_unchanged':True,'batch_update_commits':remote.commits,
                'largest_serialized_request_bytes':remote.max_bytes,
                'seconds':{'history_import_pdf_generation_extraction':round(ready-start,6),
                           'approval_including_lost_response_recovery':round(committed-ready,6),
                           'total_including_export_archive':round(perf_counter()-start,6)},
                'known_failure':'cold restart during a request still in transit can overwrite a later batch; see negative control test'}


if __name__ == '__main__':
    print(json.dumps(run(),ensure_ascii=False,indent=2))
