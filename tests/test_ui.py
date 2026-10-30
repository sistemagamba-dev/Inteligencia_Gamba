import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from manage import demo
from storage import Store


class InterfaceTests(unittest.TestCase):
    def test_clicks_edit_approval_and_export(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'JANUS_MODE':'local','JANUS_DATA_DIR':tmp}):
            demo(Path(tmp))
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            batch = app.session_state['batch']
            store = Store(Path(tmp)/'janus.sqlite')
            self.assertEqual(store.db.execute('SELECT count(*) FROM records').fetchone()[0],0)
            # Simula evento do data_editor; backend recebe valor corrigido na mesma tabela.
            app.session_state['table_' + batch['id']] = {'edited_rows':{0:{'Solicitante':'Pessoa corrigida na interface'}},
                                                         'added_rows':[], 'deleted_rows':[]}
            next(b for b in app.button if b.label == 'Aprovar e registrar tudo').click().run()
            self.assertFalse(app.exception)
            self.assertIn('3 novos registrados',app.success[0].value)
            self.assertIn('Pessoa corrigida na interface',store.db.execute('SELECT payload FROM records ORDER BY rowid').fetchone()[0])
            next(b for b in app.button if b.label == 'Preparar Excel da base').click().run()
            self.assertTrue(app.session_state['export'].startswith(b'PK'))
            self.assertEqual(store.db.execute('SELECT count(*) FROM records').fetchone()[0],3)
            store.close()

    def test_configuration_failure_is_plain_portuguese(self):
        with patch.dict(os.environ, {'JANUS_MODE':'invalid'}):
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertIn('equipe técnica',app.error[0].value)
