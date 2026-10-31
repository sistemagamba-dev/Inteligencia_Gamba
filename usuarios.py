"""Cadastro append-only de assessores na aba usuarios!A:F da planilha operacional.

A aba usuarios deve ser criada pelo proprietário; sem ela a leitura falha e o
chamador deve recusar o acesso. Administradores vêm da configuração, não daqui.
Linhas: ADD|DEL, e-mail, por, instante UTC, permissão, ''. Vale o último evento.
"""
from datetime import datetime, timezone
import re

from experiments.sheets_poc.store import Unconfirmed

EMAIL = re.compile(r'[^@\s]+@[^@\s.]+(\.[^@\s.]+)+')


def normalize_email(value):
    email = str(value or '').strip().lower()
    if not EMAIL.fullmatch(email):
        raise ValueError('E-mail inválido')
    return email


def read_users(response):
    rows = [list(r) + [''] * (6-len(r)) for r in response.get('values', [])]
    if rows and str(rows[0][0]).strip().lower() == 'evento':
        rows = rows[1:]
    events = []
    for index, row in enumerate(rows):
        if len(row) != 6:
            raise ValueError('Linha de cadastro incompatível')
        if row[0] not in ('ADD', 'DEL'):
            raise ValueError('Evento desconhecido no cadastro')
        try:
            when = datetime.fromisoformat(row[3])
        except (TypeError, ValueError):
            raise ValueError('Instante inválido no cadastro') from None
        if when.tzinfo is None:
            raise ValueError('Instante inválido no cadastro')
        events.append((when, index, row[0], normalize_email(row[1]), row))
    # Vale o evento mais recente pelo instante gravado: um ADD que chega atrasado
    # (instante anterior) não desfaz um DEL posterior. Empate: ordem física.
    active, last = {}, {}
    for _, _, event, email, row in sorted(events, key=lambda e: (e[0], e[1])):
        last[email] = event
        if event == 'ADD':
            active[email] = {'desde':row[3], 'por':row[2], 'permissao':row[4]}
        else:
            active.pop(email, None)
    return {'ativos':active, 'removidos':{e for e, v in last.items() if v == 'DEL'}}


class UsersRegistry:
    RANGE = 'usuarios!A:F'

    def __init__(self, transport):
        self.transport = transport

    def state(self):
        return read_users(self.transport.get())

    def active(self):
        return set(self.state()['ativos'])

    def _write(self, event, email, by, permission_id, expected):
        row = [event, email, by, datetime.now(timezone.utc).isoformat(timespec='microseconds'), permission_id, '']
        try:
            self.transport.append({'values':[row]}, range=self.RANGE, valueInputOption='RAW',
                                  insertDataOption='INSERT_ROWS')
        except (TimeoutError, ConnectionError):
            pass
        if (email in self.active()) != expected:
            raise Unconfirmed('Cadastro não confirmado; tente novamente')
        return True

    def add(self, email, *, by, permission_id=''):
        email, by = normalize_email(email), normalize_email(by)
        if email in self.active():
            return False
        return self._write('ADD', email, by, str(permission_id or ''), True)

    def remove(self, email, *, by):
        """Garante um DEL como último evento, mesmo sem ADD visível (ADD ainda em trânsito).
        Retorna True se o e-mail estava ativo."""
        email, by = normalize_email(email), normalize_email(by)
        state = self.state()
        if email in state['removidos']:
            return False
        was_active = email in state['ativos']
        self._write('DEL', email, by, '', False)
        return was_active
