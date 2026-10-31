"""Fluxo manual: prévia → aprovação → gravação confirmada → arquivamento recuperável.

Workflow usa o SQLite da Etapa 2; SheetsWorkflow usa o diário append-only aprovado.
"""
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import logging
from io import BytesIO
import uuid

from pypdf import PdfReader
from janus import Record, normalize, parse_text, valid_protocol
from storage import dumps, loads
from experiments.sheets_poc.store import Unconfirmed

# Bibliotecas de PDF podem registrar trechos do arquivo em warnings.
_pdf_log = logging.getLogger('pypdf')
_pdf_log.handlers = [logging.NullHandler()]
_pdf_log.propagate = False

EDITABLE = ('protocol', 'requester', 'created', 'category', 'address', 'description', 'neighborhood')
ARCHIVE_PENDING = 'Registrado; arquivamento pendente. Tente novamente.'


def read_record(data):
    reader = PdfReader(BytesIO(data))
    record = parse_text('\n'.join(p.extract_text() or '' for p in reader.pages),
                        (reader.metadata or {}).get('/CreationDate'))
    if not valid_protocol(record.protocol):
        raise ValueError('Sem protocolo confiável')
    return record


def preview(drive, known):
    """Lê a entrada sem gravar nada. known: protocolos normalizados já registrados."""
    files = drive.pending()
    rows, duplicates, failures, seen = [], [], [], set()
    for index, file in enumerate(files, 1):
        alias = f'PDF {index:03}'
        try:
            data = drive.read(file.id)
            record = read_record(data)
            key = normalize(record.protocol)
            if key in known or key in seen:
                duplicates.append({'alias': alias, 'url': file.url})
                continue
            seen.add(key)
            rows.append({'file_id': file.id, 'alias': alias, 'url': file.url,
                         'digest': hashlib.sha256(data).hexdigest(), 'record': asdict(record)})
        except Exception:
            failures.append({'alias': alias, 'url': file.url,
                'message': 'Não foi possível ler um protocolo confiável. Confira o PDF e tente novamente.'})
    return {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(), 'found': len(files),
            'rows': rows, 'duplicates': duplicates, 'failures': failures}


def edited(drive, source, edit, verify=True):
    record = Record(**source['record'])
    for field in EDITABLE:
        setattr(record, field, str(edit.get(field) or '').strip())
    if not valid_protocol(record.protocol):
        raise ValueError('Confira o número de protocolo destacado antes de aprovar.')
    if record.created:
        try:
            date.fromisoformat(record.created)
        except ValueError as exc:
            raise ValueError('Confira a data: use ano-mês-dia ou deixe em branco.') from exc
    if verify and hashlib.sha256(drive.read(source['file_id'])).hexdigest() != source['digest']:
        raise ValueError('Um PDF mudou após a conferência. Processe novamente.')
    return record


class Workflow:
    def __init__(self, store, drive):
        self.store, self.drive = store, drive

    def _resume(self):
        failed, moved = [], 0
        pending = self.store.db.execute('SELECT file_id,digest FROM outbox WHERE archived=0').fetchall()
        for file_id, fingerprint in pending:
            try:
                self.drive.archive(file_id, fingerprint)
                with self.store.db:
                    self.store.db.execute('UPDATE outbox SET archived=1 WHERE file_id=?', (file_id,))
                moved += 1
            except Exception:
                failed.append({'file_id': file_id, 'message': ARCHIVE_PENDING})
        return {'archived': moved, 'archive_failures': failed}

    def resume(self):
        with self.store.exclusive():
            return self._resume()

    def process(self):
        with self.store.exclusive():
            self.store.reload_history()
            recovery = self._resume()
            batch = {**preview(self.drive, _Known(self.store)), 'recovery': recovery}
            with self.store.db:
                self.store.db.execute('INSERT INTO batches(id,payload) VALUES (?,?)',
                                      (batch['id'], dumps(batch)))
            return batch

    def approve(self, batch_id, edits, *, approved=False, after_commit=None):
        if not approved:
            raise ValueError('Aprovação humana obrigatória')
        with self.store.exclusive():
            saved = self.store.db.execute('SELECT payload,result FROM batches WHERE id=?', (batch_id,)).fetchone()
            if not saved:
                raise ValueError('Lote não encontrado. Processe novamente.')
            if saved[1]:
                return {**loads(saved[1]), **self._resume()}
            batch = loads(saved[0])
            if len(edits) != len(batch['rows']):
                raise ValueError('A tabela mudou. Processe novamente.')
            records = [edited(self.drive, source, edit) for source, edit in zip(batch['rows'], edits)]
            self.store.reload_history()
            inserted = ignored = 0
            with self.store.db:
                self.store.db.execute('BEGIN IMMEDIATE')
                for source, record in zip(batch['rows'], records):
                    key = normalize(record.protocol)
                    if self.store.contains(key):
                        ignored += 1
                        continue  # Não arquivar arquivo rejeitado por duplicidade.
                    order = self.store.history.next_order + self.store.db.execute('SELECT count(*) FROM records').fetchone()[0]
                    self.store.db.execute('INSERT INTO records VALUES (?,?)', (key, dumps(record.row(order))))
                    self.store.db.execute('INSERT INTO outbox(file_id,key,digest) VALUES (?,?,?)',
                                          (source['file_id'], key, source['digest']))
                    inserted += 1
                result = {'approved_at': datetime.now(timezone.utc).isoformat(),
                          'found': batch['found'], 'inserted': inserted,
                          'ignored': len(batch['duplicates']) + ignored, 'failures': len(batch['failures'])}
                self.store.db.execute('UPDATE batches SET result=? WHERE id=?', (dumps(result), batch_id))
            if after_commit:
                after_commit()
            return {**result, **self._resume()}


class _Known:
    """Consulta de duplicidade do SQLite com a interface de um conjunto."""
    def __init__(self, store):
        self.store = store

    def __contains__(self, key):
        return self.store.contains(key)


class SheetsWorkflow:
    """Mesmo fluxo sobre SheetsProof (diário append-only). A prévia fica na sessão;
    nada é gravado antes da aprovação e nenhum PDF é arquivado sem gravação confirmada."""
    def __init__(self, proof, drive):
        self.proof, self.drive = proof, drive

    def pending_archives(self):
        state = self.proof.state()
        return [r for r in state['records'].values()
                if (r['record_id'], r['file_id'], r['digest']) not in state['archived']]

    def resume(self):
        before = len(self.pending_archives())
        try:
            self.proof.resume(self.drive)
        except Unconfirmed:
            pass  # Releitura abaixo decide o que continua pendente.
        pending = self.pending_archives()
        return {'archived': before - len(pending),
                'archive_failures': [{'file_id': r['file_id'], 'message': ARCHIVE_PENDING} for r in pending]}

    def process(self):
        recovery = self.resume()
        state = self.proof.state()
        if not state['history_source']:
            raise ValueError('A base ainda não foi preparada pela equipe técnica.')
        known = {normalize(r[4]) for r in state['history'] if r[4]} | set(state['records'])
        return {**preview(self.drive, known), 'recovery': recovery}

    def approve(self, batch, edits, *, approved=False):
        if not approved:
            raise ValueError('Aprovação humana obrigatória')
        if len(edits) != len(batch['rows']):
            raise ValueError('A tabela mudou. Processe novamente.')
        # PDF já registrado pode estar arquivado; a repetição é reconhecida pelo ID do lote.
        registered = {(r['file_id'], r['digest']) for r in self.proof.state()['records'].values()}
        items = [(source['file_id'], edited(self.drive, source, edit,
                                            (source['file_id'], source['digest']) not in registered), source['digest'])
                 for source, edit in zip(batch['rows'], edits)]
        result = self.proof.approve(items, approved=True)
        return {'approved_at': datetime.now(timezone.utc).isoformat(), 'found': batch['found'],
                'inserted': result['inserted'], 'ignored': len(batch['duplicates']) + result['ignored'],
                'failures': len(batch['failures']), **self.resume()}

    def export(self, destination):
        self.proof.export(destination)
