"""Sheets v4 com a interface de SimulatedSheets. Somente values.get e values.append.

Mesmo contrato comprovado em prova/google-real (dbe31d6): RAW + INSERT_ROWS em journal!A:F.
A aba usuarios!A:F (cadastro de assessores) usa o mesmo contrato, numa instância própria.
"""
import re


class GoogleSheets:
    API = 'https://sheets.googleapis.com/v4/spreadsheets/'
    RANGES = ('journal!A:F', 'usuarios!A:F')

    def __init__(self, session, spreadsheet, range_='journal!A:F'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', spreadsheet):
            raise ValueError('Planilha inválida')
        if range_ not in self.RANGES:
            raise ValueError('Intervalo inválido')
        self.session, self.url, self.range_ = session, self.API + spreadsheet, range_

    def get(self):
        response = self.session.get(self.url + '/values/' + self.range_, timeout=60)
        response.raise_for_status()
        return response.json()

    def append(self, body, *, range, valueInputOption, insertDataOption):
        if (range, valueInputOption, insertDataOption) != (self.range_, 'RAW', 'INSERT_ROWS'):
            raise ValueError('Somente append RAW INSERT_ROWS')
        response = self.session.post(self.url + '/values/' + range + ':append', timeout=60, json=body,
                                     params={'valueInputOption': valueInputOption,
                                             'insertDataOption': insertDataOption})
        response.raise_for_status()
        return response.json()
