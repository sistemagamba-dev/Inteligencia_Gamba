"""Modelo mínimo values.batchGet/batchUpdate. Sem CAS/chave única/lock remoto.

Simula falha antes da escrita, resposta perdida e pedido ainda em trânsito.
"""
from copy import deepcopy
from threading import Lock
import json
import re


class SimulatedSheets:
    def __init__(self):
        self.tabs={n:[] for n in ('historico','origem','novos','lotes','arquivados')}
        self.lock=Lock()
        self.failures=[]
        self.deferred=[]
        self.commits=0
        self.max_bytes=0
        self.after_get=None

    def get(self):
        with self.lock:
            result={'valueRanges':[{'range':name+'!A:Z','values':deepcopy(rows)}
                                   for name,rows in self.tabs.items()]}
        if self.after_get:self.after_get()
        return result

    def _apply(self, body):
        candidate=deepcopy(self.tabs)
        if body['valueInputOption'] != 'RAW':raise ValueError('Somente RAW')
        for update in body['data']:
            match=re.fullmatch(r'([a-z_]+)!A([1-9][0-9]*)', update['range'])
            if not match:raise ValueError('Range não modelado')
            rows=candidate[match[1]]; start=int(match[2])-1
            for i, values in enumerate(update['values'], start):
                while len(rows)<=i:rows.append([])
                # Atualiza apenas as células do pedido, sem append/replace global.
                while len(rows[i])<len(values):rows[i].append('')
                rows[i][:len(values)]=deepcopy(values)
        self.tabs=candidate
        self.commits+=1

    def batch_update(self, body):
        with self.lock:
            self.max_bytes=max(self.max_bytes,len(json.dumps(body,ensure_ascii=False).encode()))
            failure=self.failures.pop(0) if self.failures else None
            if failure=='before':raise TimeoutError('Não aplicado')
            if failure=='deferred':
                self.deferred.append(deepcopy(body))
                raise TimeoutError('Pedido ainda em trânsito')
            self._apply(body)
            if failure=='after':raise TimeoutError('Aplicado; resposta perdida')

    def deliver_deferred(self):
        with self.lock:
            for body in self.deferred:self._apply(body)
            self.deferred=[]
