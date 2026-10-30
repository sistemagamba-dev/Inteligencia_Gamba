"""Fluxo manual: prévia durável → aprovação → commit → arquivamento recuperável."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import logging
from io import BytesIO
import uuid

from pypdf import PdfReader
from janus import Record, normalize, parse_text, valid_protocol
from storage import dumps, loads

# Bibliotecas de PDF podem registrar trechos do arquivo em warnings.
_pdf_log = logging.getLogger('pypdf')
_pdf_log.handlers = [logging.NullHandler()]
_pdf_log.propagate = False

EDITABLE = ('protocol', 'requester', 'created', 'category', 'address', 'description', 'neighborhood')


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
                failed.append({'file_id': file_id, 'message': 'Registrado; arquivamento pendente. Tente novamente.'})
        return {'archived': moved, 'archive_failures': failed}

    def resume(self):
        with self.store.exclusive():
            return self._resume()

    def process(self):
        with self.store.exclusive():
            self.store.reload_history()
            recovery = self._resume()
            files = self.drive.pending()
            rows, duplicates, failures, seen = [], [], [], set()
            for index, file in enumerate(files, 1):
                alias = f'PDF {index:03}'
                try:
                    data = self.drive.read(file.id)
                    reader = PdfReader(BytesIO(data))
                    record = parse_text('\n'.join(p.extract_text() or '' for p in reader.pages),
                                        (reader.metadata or {}).get('/CreationDate'))
                    if not valid_protocol(record.protocol):
                        raise ValueError('Sem protocolo confiável')
                    key = normalize(record.protocol)
                    if self.store.contains(key) or key in seen:
                        duplicates.append({'alias': alias, 'url': file.url})
                        continue
                    seen.add(key)
                    rows.append({'file_id': file.id, 'alias': alias, 'url': file.url,
                                 'digest': hashlib.sha256(data).hexdigest(), 'record': asdict(record)})
                except Exception:
                    failures.append({'alias': alias, 'url': file.url,
                        'message': 'Não foi possível ler um protocolo confiável. Confira o PDF e tente novamente.'})
            batch = {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(), 'found': len(files), 'rows': rows,
                     'duplicates': duplicates, 'failures': failures, 'recovery': recovery}
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
            records = []
            for source, edit in zip(batch['rows'], edits):
                record = Record(**source['record'])
                for field in EDITABLE:
                    setattr(record, field, str(edit.get(field) or '').strip())
                if not valid_protocol(record.protocol):
                    raise ValueError('Confira o número de protocolo destacado antes de aprovar.')
                if record.created:
                    from datetime import date
                    try:
                        date.fromisoformat(record.created)
                    except ValueError as exc:
                        raise ValueError('Confira a data: use ano-mês-dia ou deixe em branco.') from exc
                data = self.drive.read(source['file_id'])
                if hashlib.sha256(data).hexdigest() != source['digest']:
                    raise ValueError('Um PDF mudou após a conferência. Processe novamente.')
                records.append(record)
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
