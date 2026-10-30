"""Prova de operador único, sem HTTP, credenciais ou integração ao app.

Escritas RAW em posições fixas: resposta perdida não autoriza novo append.
Coordinator deve ser único no processo Streamlit. Não é lock distribuído.
"""
from datetime import date
import hashlib
from io import BytesIO
import json
from threading import Lock

from openpyxl import Workbook
from janus import HEADERS, normalize, valid_protocol, read_history
from storage import dumps, loads


class Busy(Exception):
    pass


class Unconfirmed(Exception):
    pass


class Coordinator:
    def __init__(self):
        self.lock = Lock()
        self.pending = None


def read_snapshot(response):
    tabs = {v['range'].split('!')[0]: v.get('values', []) for v in response['valueRanges']}
    return {'history': [loads(r[0]) for r in tabs['historico']],
            'history_source': tabs['origem'][0][0] if tabs['origem'] else None,
            'records': tabs['novos'], 'receipts': {r[0]: r for r in tabs['lotes']},
            'receipt_rows': len(tabs['lotes']), 'archived': tabs['arquivados']}


class SheetsProof:
    def __init__(self, transport, coordinator):
        self.transport, self.coordinator = transport, coordinator

    def state(self):
        return read_snapshot(self.transport.get())

    def _write(self, data):
        body = {'valueInputOption': 'RAW', 'data': data}
        if any(len(str(v)) > 50000 for update in data for row in update['values'] for v in row):
            raise ValueError('Célula excede 50 mil caracteres')
        if len(json.dumps(body, ensure_ascii=False).encode()) > 2_000_000:
            raise ValueError('Requisição excede 2 MB nesta prova')
        return body

    def import_history(self, source):
        h = read_history(BytesIO(source))
        fingerprint = hashlib.sha256(source).hexdigest()
        with self.coordinator.lock:
            if self.coordinator.pending:
                raise Unconfirmed('Resolva a gravação anterior')
            state = self.state()
            if state['history_source']:
                if state['history_source'] != fingerprint:
                    raise ValueError('Não substituir histórico')
                return False
            if state['records']:
                raise ValueError('Importe o histórico primeiro')
            data = [{'range': 'origem!A1', 'values': [[fingerprint]]}]
            if h.rows:
                data.append({'range': 'historico!A1', 'values': [[dumps(r)] for r in h.rows]})
            self.transport.batch_update(self._write(data))
            return True

    def approve(self, batch_id, items, *, approved=False):
        if not approved:
            raise ValueError('Aprovação humana obrigatória')
        if not batch_id or not items:
            raise ValueError('Lote vazio/sem ID')
        for _, record, digest in items:
            if not valid_protocol(record.protocol) or len(digest) != 64:
                raise ValueError('Protocolo/hash inválido')
            if record.created:
                date.fromisoformat(record.created)
        fingerprint = hashlib.sha256(dumps([(f,r.row(0),d) for f,r,d in items]).encode()).hexdigest()
        if not self.coordinator.lock.acquire(blocking=False):
            raise Busy('Processamento em andamento')
        try:
            pending = self.coordinator.pending
            if pending:
                if pending['id'] != batch_id or pending['fingerprint'] != fingerprint:
                    raise Unconfirmed('Confirme o lote anterior antes de iniciar outro')
                plan = pending
            else:
                state = self.state()
                receipt = state['receipts'].get(batch_id)
                if receipt:
                    if receipt[1] != fingerprint:
                        raise ValueError('Lote reutilizado com conteúdo diferente')
                    return loads(receipt[2])
                known = {normalize(r[4]) for r in state['history'] if r[4]}
                known.update(r[2] for r in state['records'])
                bound = {r[1]:r[2] for r in state['records']}
                orders = [int(r[0]) for r in state['history']
                          if isinstance(r[0],(int,float)) and float(r[0]).is_integer()]
                order = max([0]+orders) + 1 + len(state['records'])
                result = {'inserted':0, 'ignored':0}
                rows = []
                for file_id, record, digest in items:
                    key = normalize(record.protocol)
                    if file_id in bound and bound[file_id] != key:
                        raise ValueError('Arquivo vinculado a outro protocolo')
                    if key in known:
                        result['ignored'] += 1
                        continue
                    # Colunas técnicas da prova; Excel mantém apenas A:J originais.
                    rows.append([dumps(record.row(order)),file_id,key,digest,batch_id])
                    known.add(key); bound[file_id]=key
                    order += 1; result['inserted'] += 1
                updates = [{'range': f"lotes!A{state['receipt_rows']+1}",
                            'values': [[batch_id,fingerprint,dumps(result)]]}]
                if rows:
                    updates.append({'range': f"novos!A{len(state['records'])+1}", 'values':rows})
                plan = {'id':batch_id,'fingerprint':fingerprint,'result':result,'body':self._write(updates)}
                # Preserva exatamente as posições/valores da tentativa incerta.
                self.coordinator.pending = plan
            try:
                self.transport.batch_update(plan['body'])
            except (TimeoutError, ConnectionError):
                try:
                    receipt = self.state()['receipts'].get(batch_id)
                except (TimeoutError, ConnectionError):
                    receipt = None
                if not receipt or receipt[1] != fingerprint:
                    raise Unconfirmed('Resultado incerto: repita somente este lote')
            self.coordinator.pending = None
            return plan['result']
        finally:
            self.coordinator.lock.release()

    def resume(self, drive):
        with self.coordinator.lock:
            if self.coordinator.pending:
                raise Unconfirmed('Confirme a gravação antes de arquivar')
            state = self.state()
            moved, failures, updates = 0, [], []
            for i, row in enumerate(state['records']):
                if i < len(state['archived']) and state['archived'][i] == ['1']:
                    continue
                if row[4] not in state['receipts']:
                    raise Unconfirmed('Registro sem recibo; não arquivar')
                try:
                    drive.archive(row[1],row[3])
                    updates.append({'range':f'arquivados!A{i+1}', 'values':[['1']]})
                    moved += 1
                except Exception:
                    failures.append(row[1])
            # Confirmação separada: replay tardio de dados não desfaz este estado.
            if updates:
                self.transport.batch_update(self._write(updates))
            return {'archived':moved,'failures':failures}

    def export(self, destination):
        state = self.state()
        book=Workbook(); sheet=book.active; sheet.title='JANUS 2026'
        sheet.append([]); sheet.append(HEADERS)
        for row in state['history'] + [loads(r[0]) for r in state['records']]:
            sheet.append(row)
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f': cell.data_type='s'
        book.save(destination); book.close()
