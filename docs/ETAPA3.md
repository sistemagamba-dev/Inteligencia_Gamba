# Etapa 3 — integração Streamlit + Google Sheets append-only

**Veredito: APROVADO COM RESSALVAS.** O protótipo da Etapa 2 passa a gravar no diário
append-only aprovado (`1e94527`), com o contrato real comprovado em `prova/google-real`
(`dbe31d6`). Validado com Google **simulado** e PDFs sintéticos. Nenhuma chamada real,
credencial, deploy ou URL nesta execução. Não constitui PROTÓTIPO FECHADO.

Branch `etapa3/streamlit-sheets`, criada sobre `dbe31d6` (que contém, em linha, a Etapa 2
`e8e672b` e as provas). Main e PRs anteriores intocados. O workflow de disparo único da
prova real foi removido desta branch.

## O que mudou (mínimo)

- `workflow.py`: `SheetsWorkflow` usa o mesmo fluxo da tela sobre `SheetsProof`. A prévia
  fica na sessão e nada é gravado antes da aprovação. Os PDFs são relidos e conferidos por
  hash. A aprovação grava o lote e só arquiva o que o diário confirmou. A retomada de
  arquivamento lê as confirmações `A` do diário. A leitura do PDF e a validação das
  edições viraram funções compartilhadas com o `Workflow` SQLite, que continua testado.
- `sheets_adapter.py`: transporte Sheets v4 (apenas `values.get` e `values.append` com
  `RAW` + `INSERT_ROWS` em `journal!A:F`), igual ao da prova real.
- `runtime.py`: modo `local` (padrão) com Sheets simulado em memória, Drive local e PDFs
  e histórico inventados. Modo `google` com conta de serviço lida de segredo, Sheets e
  Drive v3.
- `app.py`: mesma tela. Sem diário técnico visível. Aviso claro quando a gravação não é
  confirmada ("clique novamente; nada será duplicado"). A contagem de pendências fica na
  sessão, para que as edições na tabela não consumam cota do Sheets.
- **Acesso:** no modo `google` a tela não carrega nada sem login Google do próprio
  Streamlit (`st.login`, `[auth]` nos segredos) **e** e-mail presente em
  `JANUS_ALLOWED_EMAILS`. Na ausência de qualquer um, a tela recusa. O motivo é que o
  repositório é público e o app pode ficar público por engano. Desde o Streamlit 1.42,
  `st.user.email` só existe com `[auth]` configurado.
- `manage.py import-history-sheets ARQUIVO`: importação única do histórico no diário
  (equipe técnica). `demo_files` reaproveita os PDFs sintéticos da Etapa 2.
- `.streamlit/config.toml` sem `server.address` fixo, para compatibilidade com o
  Community Cloud. Localmente, use `--server.address 127.0.0.1`.
- `requirements.txt`: `Authlib==1.6.12`, exigido por `st.login`.

## Evidências executadas (31/10/2026)

| Ensaio | Resultado | Evidência |
|---|---|---|
| Suíte completa | **72 testes OK**: 59 anteriores, com os 2 de interface reescritos para o Sheets, e 15 novos | [tests.txt](evidence/etapa3/tests.txt) |
| Venv limpo só com `requirements.txt` | `pip check`: no broken requirements; 72 OK | — |
| Navegador (Chromium, Streamlit local, Sheets simulado) | 5 PDFs: 3 novos, 1 duplicado, 1 inválido. 0 registros antes de aprovar, 3 depois. 3 arquivados, 2 preservados na entrada. Excel com 10 colunas e 5 linhas (2 históricas + 3). Recarga sem reinserção. Sem erros JS | [browser.json](evidence/etapa3/browser.json), [prévia](evidence/etapa3/browser-preview.png), [após aprovar](evidence/etapa3/browser-approved.png) |
| Falhas simuladas | Timeout antes do envio e resposta perdida após o append; repetição sem duplicar; falha de arquivamento com retomada após reinício; PDF alterado; duplicado criado por edição fica na entrada; base sem histórico recusada | `tests/test_sheets_workflow.py`, `tests/test_ui.py` |
| Acesso | Modo `google` sem `[auth]` não carrega componentes; lista de e-mails normalizada e vazia = recusa | `tests/test_ui.py` |

## Publicação futura (aguarda autorização e confirmação de privacidade)

1. **Nova chave.** A anterior foi revogada. Gere uma nova chave JSON para `janus-teste` e
   guarde-a só nos segredos do app.
2. **Login Google.** No projeto `janus-homologacao` (sem faturamento), crie uma tela de
   consentimento "Externo" em modo de teste, com o operador como usuário de teste. Depois
   crie um cliente OAuth "Aplicativo da Web" com o redirecionamento
   `https://<app>.streamlit.app/oauth2callback`.
3. **Community Cloud.** Escolha app privado, branch aprovada, arquivo `app.py` e
   Python 3.12. Adicione como *viewer* apenas o e-mail do operador. **Confirme que o app
   está privado antes de inserir os segredos.**
4. **Segredos** (Settings → Secrets). As chaves na raiz viram variáveis de ambiente:

```toml
JANUS_MODE = "google"
JANUS_SHEET_ID = "<planilha>"
JANUS_TEST_ROOT = "<pasta JANUS_TESTE_...>"
JANUS_ENTRADA = "<entrada>"
JANUS_PROCESSADOS = "<processados>"
JANUS_FALHAS = "<falhas>"
JANUS_ALLOWED_EMAILS = "<e-mail do operador>"
JANUS_GOOGLE_SA_JSON = '''<conteúdo do JSON da conta de serviço>'''

[auth]
redirect_uri = "https://<app>.streamlit.app/oauth2callback"
cookie_secret = "<texto aleatório longo>"
client_id = "<cliente OAuth>"
client_secret = "<segredo OAuth>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

5. **Base.** Com uma planilha nova, rode uma única vez
   `JANUS_MODE=google ... python manage.py import-history-sheets historico.xlsx`. A
   planilha de homologação já contém o histórico sintético da prova real.

## Ressalvas

- Validação desta execução somente com Google simulado. O contrato real foi comprovado
  em `dbe31d6`, mas o app integrado ainda não falou com as APIs reais.
- `GoogleDrive` aceita apenas raiz `JANUS_TESTE*`, uma barreira deliberada. O uso com
  dados reais exige outra raiz e novo gate.
- `SheetsProof` continua em `experiments/sheets_poc/`. Ele foi reaproveitado sem mudança.
  Promovê-lo a módulo próprio é uma limpeza para depois.
- O SQLite (`Workflow`, `Store`, backup/restauração) não é mais usado pela tela, mas foi
  mantido com seus testes. Removê-lo depende de decisão.
- Importação de histórico grande: um único append limitado a 2 MB nesta prova.
- Privacidade do app e login: depende da configuração do Community Cloud e do OAuth,
  ainda não executados.
- Um operador; o lock é por processo. Mais de uma instância não é suportado.
