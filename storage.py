"""SQLite persistente, histórico imutável, outbox e cópia consistente."""
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import json
from io import BytesIO
from pathlib import Path
import sqlite3

from janus import History, TrialStore, read_history


def encode(value):
    if isinstance(value, datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, date):
        return {'__date__': value.isoformat()}
    raise TypeError('Tipo de célula não suportado')


def decode(value):
    if '__datetime__' in value:
        return datetime.fromisoformat(value['__datetime__'])
    if '__date__' in value:
        return date.fromisoformat(value['__date__'])
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=encode)


def loads(value):
    return json.loads(value, object_hook=decode)


class Busy(Exception):
    pass


class Store(TrialStore):
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(file_id TEXT PRIMARY KEY, key TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history(position INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                result TEXT);
        ''')
        self.reload_history()

    @contextmanager
    def exclusive(self):
        # Kernel libera o lock mesmo após encerramento abrupto do processo.
        with open(str(self.path) + '.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy('Há outro processamento em andamento. Tente novamente em instantes.') from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def reload_history(self):
        rows = [loads(p) for (p,) in self.db.execute('SELECT payload FROM history ORDER BY position')]
        from janus import normalize
        keys = {normalize(r[4]) for r in rows if r[4] is not None and str(r[4]).strip()}
        orders = [int(r[0]) for r in rows if isinstance(r[0], (int, float)) and float(r[0]).is_integer()]
        self.history = History(rows, keys, max([0] + orders) + 1,
                               sum(r[4] is not None and bool(str(r[4]).strip()) for r in rows))

    def import_history(self, source):
        data = Path(source).read_bytes()
        fingerprint = hashlib.sha256(data).hexdigest()
        history = read_history(BytesIO(data))
        with self.exclusive(), self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute("SELECT value FROM meta WHERE key='history_digest'").fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise ValueError('Histórico já importado; não é permitido substituí-lo')
                return False
            if self.db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
                raise ValueError('Importe o histórico antes do primeiro registro')
            self.db.executemany('INSERT INTO history VALUES (?,?)',
                                [(i, dumps(row)) for i, row in enumerate(history.rows, 3)])
            self.db.execute("INSERT INTO meta VALUES ('history_digest', ?)", (fingerprint,))
        self.reload_history()
        return True

    def contains(self, key):
        return key in self.history.keys or bool(self.db.execute(
            'SELECT 1 FROM records WHERE key=?', (key,)).fetchone())

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.path or destination.exists():
            raise ValueError('Escolha um novo arquivo para a cópia')
        with self.exclusive():
            target = sqlite3.connect(destination)
            try:
                self.db.backup(target)
                assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            finally:
                target.close()

    def export(self, destination):
        # TrialStore reaproveita o contrato A:J; histórico recarregado do disco.
        with self.exclusive():
            self.reload_history()
            super().export(destination)
