"""Prova append-only: um operador, sem HTTP/credenciais ou alteração do app.

Cada grupo de registros termina com manifesto de contagem/hash. A base lógica
considera somente grupos confirmados e conserva o primeiro protocolo novo.
Nenhuma posição de escrita, reserva em memória, CAS ou aba versionada é usada.
"""
from datetime import date
import hashlib
from io import BytesIO
import json
import re
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
        self.lock = Lock() # Conforto contra clique duplo; não sustenta a integridade.


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


MAX_BYTES, MAX_CELL = 2_000_000, 50000


def measure(rows):
    """Bytes JSON do corpo do append e maior célula, sem expor valores."""
    return (len(json.dumps({'values':rows}, ensure_ascii=False).encode()),
            max((len(str(v)) for row in rows for v in row), default=0))


def history_plan(source, limit=MAX_BYTES):
    """Linhas H + manifesto I de import_history e os appends necessários.

    Cabendo no limite, um único append (H... + I). Senão, H em partes consecutivas
    abaixo do limite e o manifesto I sozinho por último; formato do diário inalterado.
    """
    h = read_history(BytesIO(source))
    digest = hashlib.sha256(source).hexdigest()
    events = [['H',digest,str(i),'',dumps(row),''] for i,row in enumerate(h.rows)]
    manifest = ['I',digest,fingerprint(events),str(len(events)),'','']
    if measure(events + [manifest])[0] <= limit:
        return h, digest, events, manifest, [events + [manifest]]
    chunks, size, overhead = [[]], 0, measure([])[0]
    for row in events:
        cost = len(json.dumps(row, ensure_ascii=False).encode()) + 2
        if chunks[-1] and overhead + size + cost > limit:
            chunks.append([]); size = 0
        chunks[-1].append(row); size += cost
    return h, digest, events, manifest, chunks + [[manifest]]


def read_snapshot(response):
    # values.get omite células vazias no fim de cada linha.
    rows = [list(r) + [''] * (6-len(r)) for r in response.get('values', [])]
    history, history_source, records, receipts, acknowledgements = [], None, {}, {}, set()
    for i, row in enumerate(rows):
        if len(row) != 6:
            raise ValueError('Linha de diário incompatível')
        kind = row[0]
        if kind in ('I', 'C'):
            count = int(row[3])
            block = rows[i-count:i] if count else []
            expected = 'H' if kind == 'I' else 'R'
            if count < 0 or len(block) != count or any(r[0] != expected or r[1] != row[1] for r in block):
                raise ValueError('Grupo incompleto: não exportar/arquivar')
            if fingerprint(block) != row[2]:
                raise ValueError('Hash do grupo divergente')
            if kind == 'I':
                source = row[1]
                if history_source and history_source != source:
                    raise ValueError('Históricos conflitantes: requer intervenção')
                history_source = source
                imported = [loads(r[4]) for r in block]
                if history and imported != history:
                    raise ValueError('Histórico divergente')
                history = imported
                continue
            if not history_source:
                raise ValueError('Histórico deve preceder registros novos')
            if row[1] in receipts and receipts[row[1]] != int(row[4]):
                raise ValueError('Manifestos conflitantes')
            receipts[row[1]] = int(row[4])
            historical_keys = {normalize(r[4]) for r in history if r[4]}
            for event in block:
                payload, source = loads(event[4]), loads(event[5])
                key = normalize(payload[4])
                if not valid_protocol(payload[4]) or key != event[2] or event[3] != 'JANUS:' + key:
                    raise ValueError('Identificador de registro divergente')
                if key not in historical_keys and key not in records:
                    records[key] = {'row': payload, 'record_id': event[3], 'batch_id':event[1],
                                    'file_id':source['file_id'], 'digest':source['digest']}
        elif kind == 'A':
            acknowledgements.add(tuple(row[1:4]))
        elif kind not in ('H', 'R'):
            raise ValueError('Evento desconhecido')
    return {'history':history, 'history_source':history_source, 'records':records,
            'receipts':receipts, 'archived':acknowledgements, 'physical_rows':len(rows)}


class SheetsProof:
    def __init__(self, transport, coordinator=None):
        self.transport, self.coordinator = transport, coordinator or Coordinator()

    def state(self):
        return read_snapshot(self.transport.get())

    def _append(self, rows):
        size, cell = measure(rows)
        if cell > MAX_CELL:
            raise ValueError('Célula excede 50 mil caracteres')
        if size > MAX_BYTES:
            raise ValueError('Requisição excede 2 MB nesta prova')
        return self.transport.append({'values':rows}, range='journal!A:F', valueInputOption='RAW',
                                     insertDataOption='INSERT_ROWS')

    def import_history(self, source):
        _, digest, events, manifest, chunks = history_plan(source)
        with self.coordinator.lock:
            response = self.transport.get()
            state = read_snapshot(response)
            if state['history_source']:
                if state['history_source'] != digest:
                    raise ValueError('Não substituir histórico')
                return False
            if len(chunks) == 1:
                try:
                    self._append(chunks[0])
                except (TimeoutError, ConnectionError):
                    pass
            else:
                # Pré-condição: nenhuma outra escrita intercalada (antes da operação, um operador,
                # sob o lock). H órfãos de tentativa interrompida são ignorados pelo leitor.
                if any(row and row[0] not in ('H', 'I') for row in response.get('values', [])):
                    raise ValueError('Diário já tem registros: importação em partes recusada')
                try:
                    for chunk in chunks[:-1]:
                        self._append(chunk)
                except (TimeoutError, ConnectionError):
                    raise Unconfirmed('Importação interrompida; repetir a mesma fonte') from None
                tail = [list(r) + [''] * (6-len(r)) for r in self.transport.get().get('values', [])]
                if tail[-len(events):] != events:
                    raise Unconfirmed('Partes não confirmadas em sequência; repetir a mesma fonte')
                try:
                    self._append([manifest])
                except (TimeoutError, ConnectionError):
                    pass
            if self.state()['history_source'] != digest:
                raise Unconfirmed('Importação não confirmada; repetir a mesma fonte')
            return True

    def approve(self, items, *, approved=False):
        if not approved:
            raise ValueError('Aprovação humana obrigatória')
        if not items:
            raise ValueError('Lote vazio')
        seen_files = set()
        for file_id, record, digest in items:
            if not valid_protocol(record.protocol) or not re.fullmatch(r'[0-9a-f]{64}',digest):
                raise ValueError('Protocolo/hash inválido')
            if file_id in seen_files:
                raise ValueError('Arquivo repetido no lote')
            seen_files.add(file_id)
            if record.created:
                date.fromisoformat(record.created)
        # Identidade derivada dos dados aprovados, recuperável após perda de memória.
        signatures = [(f,r.row(0),d) for f,r,d in items]
        batch_id = fingerprint(sorted(signatures, key=lambda value: (value[0],dumps(value))))
        if not self.coordinator.lock.acquire(blocking=False):
            raise Busy('Processamento em andamento')
        try:
            state = self.state()
            if not state['history_source']:
                raise ValueError('Importe o histórico, mesmo vazio, antes de aprovar')
            if batch_id not in state['receipts']:
                known = {normalize(r[4]) for r in state['history'] if r[4]} | set(state['records'])
                bound = {r['file_id']:key for key,r in state['records'].items()}
                events = []
                for file_id, record, digest in items:
                    key = normalize(record.protocol)
                    if file_id in bound and bound[file_id] != key:
                        raise ValueError('Arquivo vinculado a outro protocolo')
                    if key in known:
                        continue
                    events.append(['R',batch_id,key,'JANUS:'+key,dumps(record.row(0)),
                                   dumps({'file_id':file_id,'digest':digest})])
                    known.add(key)
                commit = ['C',batch_id,fingerprint(events),str(len(events)),str(len(items)),'']
                try:
                    self._append(events + [commit])
                except (TimeoutError, ConnectionError):
                    pass
                state = self.state() # Resposta de escrita sozinha não determina vencedor lógico.
            if batch_id not in state['receipts']:
                raise Unconfirmed('Lote não confirmado; pode repetir sem reservar posições')
            inserted = sum(r['batch_id'] == batch_id for r in state['records'].values())
            return {'batch_id':batch_id, 'inserted':inserted,
                    'ignored':state['receipts'][batch_id]-inserted}
        finally:
            self.coordinator.lock.release()

    def resume(self, drive):
        with self.coordinator.lock:
            state = self.state()
            moved, failures, events = 0, [], []
            for record in state['records'].values():
                key = (record['record_id'],record['file_id'],record['digest'])
                if key in state['archived']:
                    continue
                try:
                    drive.archive(record['file_id'],record['digest'])
                    events.append(['A',*key,'',''])
                    moved += 1
                except Exception:
                    failures.append(record['file_id'])
            if events:
                try:
                    self._append(events)
                except (TimeoutError, ConnectionError):
                    pass
                confirmed = self.state()['archived']
                if any(tuple(r[1:4]) not in confirmed for r in events):
                    raise Unconfirmed('Movimento efetuado; confirmação pendente para retomada')
            return {'archived':moved, 'failures':failures}

    def export(self, destination):
        state = self.state()
        book=Workbook(); sheet=book.active; sheet.title='JANUS 2026'
        sheet.append([]); sheet.append(HEADERS)
        for row in state['history']:
            sheet.append(row)
        orders = [int(r[0]) for r in state['history']
                  if isinstance(r[0],(int,float)) and float(r[0]).is_integer()]
        start = max([0]+orders)+1
        for order, record in enumerate(state['records'].values(), start):
            row = record['row'].copy(); row[0] = order
            sheet.append(row)
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f': cell.data_type='s'
        book.save(destination); book.close()
