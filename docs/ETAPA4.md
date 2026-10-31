# Etapa 4 — prontidão técnica (branch `etapa4/preparacao-operacional`)

Somente código e testes, sem uso real. Nenhuma chamada ao Google, credencial, deploy ou
dado real. A recusa continua sendo o padrão: sem `JANUS_AMBIENTE`, tudo funciona como na
Etapa 3 (homologação).

## O que mudou

- **Ambiente explícito** (`runtime.py`, `drive_adapter.py`). `JANUS_AMBIENTE` aceita
  `homologacao` (padrão) ou `producao`. Qualquer outro valor impede o início ("Ambiente
  desconhecido"). Cada ambiente aceita só a raiz do seu prefixo: `JANUS_TESTE*` em
  homologação, `JANUS_PRODUCAO*` em produção. Os prefixos são disjuntos. Produção exige
  `JANUS_MODE=google`. Ela também recusa a planilha e a pasta raiz de homologação já
  conhecidas, antes de ler qualquer credencial.
- **Tela** (`app.py`). A legenda mostra `AMBIENTE DE TESTE` ou `OPERAÇÃO`. Em produção não
  aparecem textos de demonstração, e o Excel baixado se chama `JANUS.xlsx`.
- **Histórico em partes** (`SheetsProof.import_history`). O formato do diário não mudou.
  Se o histórico cabe em 2 MB, o envio continua igual: um único append. Se não cabe, as
  linhas `H` vão em partes consecutivas abaixo de 2 MB e o manifesto `I` vai sozinho por
  último, depois de uma releitura que confere a sequência. Linhas `H` órfãs de uma
  tentativa interrompida são ignoradas pelo leitor, e repetir a importação com a mesma
  fonte resolve. A importação em partes é recusada se o diário já tiver qualquer linha que
  não seja `H`/`I`.
  **Pré-condição:** nenhuma outra escrita durante a importação, ou seja, antes da operação,
  com o app parado. Depois de uma interrupção, aguarde alguns minutos antes de repetir,
  para que pedidos ainda em trânsito se assentem. Se algum se intercalar mesmo assim, o
  leitor recusa o diário: a falha é segura, mas exige refazer a importação numa planilha
  nova.
- **Comandos** (`manage.py`), descritos na tabela abaixo.

## Variáveis

| Variável | Valores | Observação |
|---|---|---|
| `JANUS_AMBIENTE` | `homologacao` (padrão) \| `producao` | outro valor = recusa |
| `JANUS_MODE` | `local` (padrão) \| `google` | produção exige `google` |
| `JANUS_ROOT` / `JANUS_TEST_ROOT` | ID da pasta raiz | sinônimos; se ambos existirem e forem diferentes, recusa. Segredos atuais seguem válidos |
| `JANUS_ENTRADA`, `JANUS_PROCESSADOS`, `JANUS_FALHAS` | IDs | filhos diretos da raiz |
| `JANUS_SHEET_ID` | ID da planilha | em produção, diferente da homologação |
| `JANUS_ALLOWED_EMAILS`, `JANUS_GOOGLE_SA_JSON` | — | como na Etapa 3 |

## Comandos da equipe técnica

| Comando | Efeito |
|---|---|
| `python manage.py verificar-historico ARQUIVO.xlsx` | Somente leitura e local. Mostra só métricas agregadas: linhas, linhas com protocolo, únicos normalizados, excesso de duplicados, bytes JSON, maior célula, número de appends e se o envio cabe num append/nas células |
| `python manage.py import-history-sheets ARQUIVO.xlsx` | Importação única; recusa célula acima de 50 mil caracteres antes de abrir credenciais |
| `python manage.py backup-sheets DESTINO.xlsx` | Somente leitura do Google. Cria um arquivo **novo** (recusa se já existe) com a base lógica (`JANUS 2026`) e a cópia bruta `journal` (A:F). Se o diário estiver inconsistente, salva só a cópia bruta e avisa |

## Gates humanos (não executados aqui)

Planilha e pastas `JANUS_PRODUCAO*`, conta de serviço e permissões, segredos de produção,
login/allowlist, importação real do histórico, cópia antes do piloto, deploy e merge
dependem de aprovação humana pontual.

## Testes

89 testes OK: os 74 anteriores mais 15 novos em `tests/test_etapa4.py`.
