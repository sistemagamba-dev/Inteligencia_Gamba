# Etapa 2 — protótipo JANUS

**Veredito: APROVADO COM RESSALVAS.** Fluxo funcional demonstrado no navegador
com armazenamento SQLite em disco e adaptador local de Drive. Adaptador Google
Drive v3 implementado e testado por contrato com respostas simuladas; integração
Google real, hospedagem e aceite humano permanecem pendentes. Não constitui
PROTÓTIPO FECHADO nem autorização para a Etapa 3.

Executado em 30/10/2026, conforme seção 10 da [Issue #1](https://github.com/sistemagamba-dev/Inteligencia_Gamba/issues/1).
Branch `etapa2/prototipo-janus`, criada diretamente sobre `84e41f28eeeff669e861577f88c842eac5119d19`
da `etapa1/prova-tecnica` / Draft PR #2. Main e Etapa 1 preservadas; sem merge,
publicação, credenciais novas, gastos ou acesso aos documentos reais nesta etapa.

## Uso pelo operador

1. Coloque os PDFs na pasta de entrada de teste indicada pela equipe técnica.
2. Abra o endereço da ferramenta e clique em **Processar PDFs**.
3. Confira e corrija a tabela. **Atenção** destaca em amarelo ausências e
   ambiguidades; use o link do PDF para consulta. Data: ano-mês-dia.
4. Clique em **Aprovar e registrar tudo**. Campos opcionais podem ficar vazios.
5. Confira o resumo e use **Preparar Excel da base → Baixar Excel (.xlsx)**.

Se houver arquivamento pendente, use **Tentar arquivar novamente**, sem aprovar
ou digitar os registros novamente. Duplicados e PDFs inválidos permanecem na
entrada, identificados no resumo, sem exclusão. A pasta falhas existe para uma
futura intervenção técnica; o protótipo mantém os erros na própria fila.

Na demonstração local, os PDFs são inventados; podem ser baixados em **Consultar
PDFs de demonstração**. O link direto ao documento pertence ao modo Google.

## Implementação e integridade

- Parser e testes da Etapa 1 reaproveitados. Pequena correção: CreationDate com
  tipo inesperado também produz ausência, sem invalidar o PDF inteiro.
- Uma página Streamlit: processar → tabela editável → aprovação → resumo/exportação.
  Direção visual sóbria, fundo branco, ação principal verde, texto escuro e aviso
  amarelo com descrição textual; tabela com rolagem horizontal. Sem dashboards.
- Histórico A:J importado uma vez em SQLite, com posição original e SHA-256 da
  fonte. Preserva valores, datas, ordem, linhas vazias e duplicatas históricas.
  Importação repetida idêntica não faz nada; outra fonte ou importação tardia é
  recusada. A fonte é lida, nunca sobrescrita. Exportação mantém o contrato da
  Etapa 1 (linha 2, aba JANUS 2026, valores A:J; não replica o livro completo).
- Prévia persistida separadamente em `batches`; não integra a base/exportação.
  Aprovação usa o lote salvo no servidor, valida o lote inteiro, compara hashes
  dos PDFs e grava dados, outbox e recibo numa transação `BEGIN IMMEDIATE`.
  Registra data/hora do lote e aprovação, IDs de arquivos e hashes para rastreio.
- Chaves normalizadas únicas apenas para novos registros; não sobrescreve o
  histórico. Duplicados encontrados ou criados por correção são ignorados,
  contados e preservados na entrada, sem arquivá-los como novos.
- Lock do kernel abrange processamento, aprovação, recuperação, exportação,
  importação e backup; tentativas sobrepostas recebem aviso para tentar depois.
  Não mantém lock durante a conferência humana. SQLite serializa as escritas.
- Outbox só arquiva após commit; falha de um PDF não impede outros. Retentativa
  confirma destino e conteúdo pelo ID/hash, inclusive após perda da confirmação
  da movimentação. Arquivos alterados ficam pendentes para intervenção.
- Banco é vinculado às pastas configuradas; troca acidental de Drive é recusada.
  Logs de parser que poderiam conter trechos do PDF são descartados; operador
  recebe mensagens claras. Não há CPF/RG/contato extraído para a base.

## Evidências realmente executadas

Ambiente Linux, Python 3.12.14; dependências diretas em `requirements.txt`.
`pip check`: **No broken requirements found**. `compileall` e `git diff --check`
sem erros. Todas as entradas novas destes ensaios são sintéticas.

| Ensaio | Resultado | Evidência |
|---|---|---|
| Regressão + persistência + adaptador + interface | **38 testes passaram** (22 existentes + 16 novos) | [tests.txt](evidence/etapa2/tests.txt) |
| Navegador Chromium real | 5 PDFs encontrados, 3 novos, 1 duplicado, 1 inválido; zero registros antes do clique de aprovação; 3 depois, com 3 PDFs arquivados | [browser.json](evidence/etapa2/browser.json) |
| Exportação baixada pelo navegador | 10 colunas A:J, 5 linhas de dados (2 históricas + 3 novas); recarga não reinsere | [captura após aprovação](evidence/etapa2/browser-approved.png) |
| Conferência visual | Tabela, avisos e ação de aprovação; ação de processar acessível também em viewport 390 px | [captura da prévia](evidence/etapa2/browser-preview.png) |
| Edição na interface | Evento de edição do `data_editor` no AppTest; valor corrigido persistido e exportação disponibilizada | `tests/test_ui.py` |
| Lote físico | 100 PDFs / 300 páginas / 50 de cada layout; 100 inseridos e arquivados; repetição encontra zero pendentes; Excel relido com 100 registros | [batch.json](evidence/etapa2/batch.json) |
| Recuperação e preservação | Reinício; falha após commit; perda da confirmação após mover; erro de um arquivo; PDF alterado; validação integral/sem inserção parcial | `tests/test_workflow.py` |
| Concorrência | Duas conexões; lock entre processos independentes; prévia obsoleta; nenhuma sobrescrita | `tests/test_workflow.py` |
| Backup/restauração | Snapshot consistente; restauração reabre histórico; cópia anterior preservada; backup inválido recusado | `tests/test_workflow.py` |
| Google Drive | Paginação, pais restritos, movimento/retentativa, hash e erro de permissão: **simulados**, sem chamada autenticada real | `GoogleContractTests` |

Lote medido: extração/prévia **0,097841 s**, commit/arquivamento local **0,005993 s**,
repetição **0,000177 s**. Não inclui rede Google, tempo humano ou garantia de desempenho.
A edição foi verificada pelo AppTest; o ensaio Chromium verifica os cliques,
registro, download, recarga e ausência de erros JavaScript. Nenhum ensaio substitui
um operador do gabinete na homologação.

## Reprodução pela equipe técnica

Os comandos abaixo são preparação técnica; assessores usam somente o navegador.
A aplicação fica em loopback por padrão, sem publicação externa.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python benchmark_stage2.py
# Use um diretório novo (não apague uma base para repetir demonstração):
.venv/bin/python manage.py demo .janus-data/demo
JANUS_MODE=local JANUS_DATA_DIR=.janus-data/demo .venv/bin/streamlit run app.py
```

Abra `http://127.0.0.1:8501` no mesmo ambiente. PDFs e banco permanecem no diretório
de dados ao reiniciar o processo. `/tmp` foi usado exclusivamente para ensaios
descartáveis desta execução. Não use disco temporário numa futura hospedagem.

Ensaio Chromium opcional: instale Playwright numa máquina de verificação com
Chromium em `/usr/bin/chromium`. Inicie o servidor com uma demonstração **nova**;
execute `python browser_check.py CAMINHO_DA_DEMO PASTA_DE_EVIDENCIAS`.
O navegador exige permissão de sockets locais. A verificação usou a URL de
loopback, sem publicar deploy. `JANUS_BROWSER_URL` permite mudar a porta.

### Google Drive de teste — preparação ainda pendente de gate

O ambiente desta execução reportou **zero secrets, runtime variables e identidades
externas provisionadas**. Não houve criação/alteração de credenciais ou permissões.
O conector de Drive do chat não fornece credenciais ADC ao aplicativo Python.
Não foi tentado consentimento/login interativo nem usado o Drive operacional.

Após autorização específica para credenciais/permissões, a equipe técnica deve:

- Provisionar uma identidade técnica restrita e compartilhar somente uma raiz de
  teste dedicada chamada `JANUS_TESTE...`, com três pastas filhas distintas.
  Conceder acesso a documentos também ao operador autorizado, sem links públicos.
- Configurar ADC fora do repositório (ex.: `GOOGLE_APPLICATION_CREDENTIALS` apontando
  para arquivo seguro já provisionado), `JANUS_MODE=google`, `JANUS_DATA_DIR` num
  volume persistente e IDs em `JANUS_TEST_ROOT`, `JANUS_ENTRADA`,
  `JANUS_PROCESSADOS`, `JANUS_FALHAS`.
- Importar **um histórico sintético de teste** antes do primeiro registro e
  carregar PDFs sintéticos. Executar a integração real após o gate e registrar
  evidências; não tomar testes simulados como comprovação de permissões/API.

O adaptador valida raiz/pastas e parent de cada arquivo, usa paginação,
`supportsAllDrives`, IDs estáveis e movimentação por `addParents/removeParents`.
Não cria permissões, não exclui PDFs. A barreira por nome de teste evita enganos;
a restrição efetiva depende das permissões da identidade. Não editar/substituir
PDFs durante a conferência/arquivamento; hashes detectam alterações nas leituras,
mas não há transação distribuída com edições externas ao Drive.

### Importação, backup e restauração

```sh
.venv/bin/python manage.py import-history DIRETORIO/janus.sqlite HISTORICO_TESTE.xlsx
.venv/bin/python manage.py backup DIRETORIO/janus.sqlite COPIA_NOVA.bak
# Com o aplicativo PARADO e usando uma cópia de teste:
.venv/bin/python manage.py restore DIRETORIO/janus.sqlite COPIA_NOVA.bak
```

Backup usa a API SQLite, não uma cópia de arquivo aberto. Não sobrescreve cópia
existente. Restauração valida integridade/tabelas, prepara outro arquivo e troca
atomicamente, preservando o banco anterior em `.before-restore-*.bak`. Precisa do
aplicativo parado; não há botão de restauração para o operador. Uma restauração
volta o banco no tempo, **não** desfaz movimentos do Drive: antes de retomar,
a equipe deve reconciliar PDFs/registros com o snapshot. Preservar também os
arquivos de teste; manter cópias de segurança fora do volume do aplicativo.

## Hospedagem persistente e limites

Caminho recomendado permanece **uma instância Python/Streamlit, um volume de disco
persistente local, acesso restrito por autenticação do provedor/proxy, backup externo**.
SQLite e flock exigem disco local do mesmo host; não usar réplicas, NFS ou disco
efêmero. Reinício do processo foi testado; sobrevivência a recriação do host só
pode ser comprovada no provedor selecionado. Nenhum provedor foi contratado.

O servidor de demonstração não implementa login próprio e escuta loopback.
Antes de qualquer exposição, escolher hospedagem com autenticação e TLS,
validar persistência/backup no host e obter os gates de custo/permissão/deploy.
Hospedagem gratuita com disco efêmero não atende ao contrato. A equipe técnica
faz toda a configuração; nenhum comando/credencial é exigido de assessores.

Ressalvas que impedem declarar o produto homologado:

1. Google real ainda não validado; falta identidade e estrutura de teste
   provisionadas sob o gate específico. A demonstração local é a alternativa
   isolada autorizada pela seção 10.
2. Sem URL hospedada/autenticada ou persistência comprovada após recriação de
   host; sem contratação ou publicação autorizada.
3. PDFs reais da Etapa 1 não foram reprocessados nesta etapa. Seis referências,
   outros layouts/OCR e operação leiga devem ser homologados após autorização
   da Etapa 3; não se presume cobertura além dos layouts testados.
4. Sem aceite humano ou revisão independente. Não foi avançado à Etapa 3.

A entrega é revisável em Draft PR. O gate **PROTÓTIPO FECHADO** permanece
exclusivamente na Etapa 3, mediante nova autorização e aceite humano explícito.
