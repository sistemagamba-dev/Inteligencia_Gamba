"""Sheets v4 com a interface de SimulatedSheets. Somente values.get e values.append.

Mesmo contrato comprovado em prova/google-real (dbe31d6): RAW + INSERT_ROWS em journal!A:F.
"""
import re


class GoogleSheets:
    API = 'https://sheets.googleapis.com/v4/spreadsheets/'

    def __init__(self, session, spreadsheet):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', spreadsheet):
            raise ValueError('Planilha inválida')
        self.session, self.url = session, self.API + spreadsheet

    def get(self):
        response = self.session.get(self.url + '/values/journal!A:F', timeout=60)
        response.raise_for_status()
        return response.json()

    def append(self, body, *, range, valueInputOption, insertDataOption):
        if (range, valueInputOption, insertDataOption) != ('journal!A:F', 'RAW', 'INSERT_ROWS'):
            raise ValueError('Somente append RAW INSERT_ROWS')
        response = self.session.post(self.url + '/values/' + range + ':append', timeout=60, json=body,
                                     params={'valueInputOption': valueInputOption,
                                             'insertDataOption': insertDataOption})
        response.raise_for_status()
        return response.json()
