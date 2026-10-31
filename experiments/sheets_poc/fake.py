"""values.append INSERT_ROWS simulado: sem dedup/CAS/garantia exactly-once.

Aplicação ocorre ao chegar: pedidos retidos podem chegar em qualquer ordem e
até mais de uma vez. Leituras podem falhar ou devolver um snapshot antigo.
"""
from copy import deepcopy
from threading import Lock
import json


class SimulatedSheets:
    def __init__(self):
        self.rows=[]
        self.lock=Lock()
        self.failures=[]
        self.read_faults=[]
        self.deferred=[]
        self.commits=0
        self.append_calls=0
        self.max_bytes=0
        self.after_get=None

    def get(self):
        with self.lock:
            fault=self.read_faults.pop(0) if self.read_faults else None
            if fault=='fail':raise ConnectionError('Leitura indisponível')
            result=deepcopy(fault) if isinstance(fault,dict) else {'values':deepcopy(self.rows)}
            for row in result.get('values', []):
                while row and row[-1] == '':row.pop()
        if self.after_get:self.after_get()
        return result

    def _apply(self, body):
        # Modela append atômico de um pedido, não transação entre get e append.
        self.rows.extend(deepcopy(body['values']))
        self.commits+=1
        return {'updates':{'updatedRows':len(body['values'])}}

    def append(self, body, *, range, valueInputOption, insertDataOption):
        if (range,valueInputOption,insertDataOption) != ('journal!A:F','RAW','INSERT_ROWS'):
            raise ValueError('Somente append RAW INSERT_ROWS nesta prova')
        if any(len(row)!=6 for row in body['values']):raise ValueError('Linha inválida')
        with self.lock:
            self.append_calls+=1
            self.max_bytes=max(self.max_bytes,len(json.dumps(body,ensure_ascii=False).encode()))
            failure=self.failures.pop(0) if self.failures else None
            if failure=='before':raise TimeoutError('Não aplicado')
            if failure=='deferred':
                self.deferred.append(deepcopy(body))
                raise TimeoutError('Ainda em trânsito')
            result=self._apply(body)
            if failure=='after':raise TimeoutError('Aplicado; resposta perdida')
            return result

    def deliver_deferred(self, *, reverse=False, copies=1):
        with self.lock:
            pending=list(reversed(self.deferred)) if reverse else self.deferred
            for body in pending:
                for _ in range(copies):self._apply(body)
            self.deferred=[]
