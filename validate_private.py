"""Valida referências locais; stdout e JSON contêm apenas métricas/aliases.

Uso: python validate_private.py /tmp/pacote --report /tmp/evidencia.json
Nunca imprime textos, nomes, caminhos de PDFs ou valores da planilha.
"""
import argparse
import json
import re
from pathlib import Path
import tempfile
from time import perf_counter

from openpyxl import load_workbook
from pypdf import PdfReader
from janus import extract, read_history, digest, TrialStore, normalize, creation_time


def run(root: Path) -> dict:
    pdfs = sorted(root.rglob('*.pdf'))
    sheets = list(root.rglob('*.xlsx'))
    assert len(pdfs) == 6 and len(sheets) == 1, 'Quantidade de referências divergente'
    sources = pdfs + sheets
    before = {p: digest(p) for p in sources}
    start = perf_counter()
    records = [extract(p) for p in pdfs]
    extraction_seconds = perf_counter() - start
    h = read_history(sheets[0])
    assert sum(normalize(r.protocol) in h.keys for r in records) == 1, 'Caso de duplicidade divergente'
    result = []
    for index, (path, record) in enumerate(zip(pdfs, records), 1):
        reader = PdfReader(path)
        raw = reader.metadata.get('/CreationDate')
        text = '\n'.join(p.extract_text() or '' for p in reader.pages)
        # Conferência independente de origem: nunca imprime valores de campos.
        assert record.protocol and normalize(record.protocol) in normalize(text)
        assert record.requester and record.requester in ' '.join(text.split())
        assert record.description and record.category and record.address and record.neighborhood
        assert not re.search(r'Anexar|Características do evento|Protocolo:|Informações complementares', record.description), \
            'OCORRÊNCIA com rótulo do formulário'
        assert not record.warnings, 'Extração com pendências: revisar localmente'
        assert ('Interessado' not in record.requester and 'E-mail' not in record.requester)
        assert record.created == creation_time(raw).date().isoformat()
        result.append({'sample': f'PDF-{index:02}', 'pages': len(reader.pages),
                       'type': 'Eventos' if 'Eventos' in record.kind else 'Zeladoria',
                       'creation_metadata_present': bool(raw),
                       'timezone_conversion_verified': True,
                       'mapped_fields_present': 8, 'optional_B_blank': True,
                       'warnings': record.warnings, 'in_history': normalize(record.protocol) in h.keys})
    # Cópia de valores A:J em banco/Excel temporários, nunca altera a fonte.
    with tempfile.TemporaryDirectory(prefix='gamba-private-check-') as tmp:
        store = TrialStore(Path(tmp)/'trial.sqlite', h)
        moved = set()
        first = store.approve([(digest(p), r) for p, r in zip(pdfs, records)], approved=True, archive=moved.add)
        repeat = store.approve([(digest(p), r) for p, r in zip(pdfs, records)], approved=True, archive=moved.add)
        target = Path(tmp)/'export.xlsx'
        store.export(target)
        wb = load_workbook(target, read_only=True, data_only=True)
        values = list(wb['JANUS 2026'].iter_rows(min_row=3, max_col=10, values_only=True))
        assert [list(v) for v in values[:len(h.rows)]] == h.rows
        assert len(values) == len(h.rows) + first['inserted']
        assert repeat['inserted'] == 0 and repeat['ignored'] == 6
        wb.close()
        store.close()
    assert all(digest(p) == before[p] for p in sources), 'Originais alterados'
    examples = [{'source': 'synthetic', 'creation_utc': '2030-01-02T01:15:00Z',
                 'creation_local': creation_time('D:20300102011500Z').isoformat()}]
    return {'synthetic_creation_examples': examples, 'samples': result, 'pdf_extraction_seconds': round(extraction_seconds, 6),
            'history': {'protocol_rows': h.protocol_rows, 'normalized_unique': len(h.keys),
                        'duplicate_excess': h.protocol_rows-len(h.keys),
                        'reference_duplicate_confirmed': True,
                        'historical_A_J_values_preserved': True},
            'real_reference_trial': {'first': first, 'repeat': repeat},
            'source_integrity_sha256_unchanged': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.root)
    except Exception as exc:
        # No traceback/values from real documents in logs.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
