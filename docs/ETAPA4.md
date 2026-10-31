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
| `JANUS_ADMIN_EMAILS` | e-mails separados por vírgula | administradores do Adm; inválido = recusa |

## Comandos da equipe técnica

| Comando | Efeito |
|---|---|
| `python manage.py verificar-historico ARQUIVO.xlsx` | Somente leitura e local. Mostra só métricas agregadas: linhas, linhas com protocolo, únicos normalizados, excesso de duplicados, bytes JSON, maior célula, número de appends e se o envio cabe num append/nas células |
| `python manage.py import-history-sheets ARQUIVO.xlsx` | Importação única; recusa célula acima de 50 mil caracteres antes de abrir credenciais |
| `python manage.py backup-sheets DESTINO.xlsx` | Somente leitura do Google. Cria um arquivo **novo** (recusa se já existe) com a base lógica (`JANUS 2026`) e a cópia bruta `journal` (A:F). Se o diário estiver inconsistente, salva só a cópia bruta e avisa |

## Recuperação (procedimento manual comprovado)

Sem código novo de restauração: usa `backup-sheets` e `import-history-sheets`.
A aba `JANUS 2026` da cópia já está no formato aceito como histórico.

**Rotina:** `backup-sheets` antes do piloto, depois de cada lote aprovado (ou ao fim do dia) e
antes de qualquer intervenção. Guarde a cópia fora da conta dona e anote data e hora.

**Se a planilha de produção se perder, se corromper ou o diário ficar inconsistente:**
1. Parar o uso do app (não processar, não aprovar).
2. Criar, com a conta dona, uma planilha **nova** com aba `journal` vazia, dentro de `JANUS_PRODUCAO`,
   e compartilhá-la com a conta de serviço como Editor (gate humano).
3. Trocar `JANUS_SHEET_ID` nos segredos para a planilha nova (gate humano).
4. `python manage.py verificar-historico COPIA.xlsx` e depois `python manage.py import-history-sheets COPIA.xlsx`,
   usando a **cópia mais recente**: histórico, duplicatas históricas e registros já aprovados voltam
   idênticos (valores A:J e ordem). Repetir o comando não grava de novo.
5. Registros aprovados **depois** da cópia: devolver da pasta `processados` para `entrada` os PDFs
   movidos após a hora da cópia (na dúvida, todos) e clicar **Processar PDFs**. Os que já estão na
   cópia aparecem como duplicados e são ignorados; os perdidos voltam como novos para conferir e aprovar.
6. PDFs que estavam com arquivamento pendente no momento da cópia aparecem como duplicados e ficam
   na entrada: mover manualmente para `processados`.
7. `backup-sheets` da base recuperada e conferir o Excel exportado. Se a cópia bruta `journal` indicar
   inconsistência, preservar o arquivo e a planilha antiga para análise; nunca apagá-los.

Ensaio: `tests/test_recuperacao.py` (3 cenários) e lote em tamanho real com histórico sintético
de 3.271 linhas, 54 duplicatas e 40 registros: base recuperada idêntica, 1 append
(`docs/evidence/etapa4/recuperacao.txt`).

## Adm e acessos (`acesso.py`)

- **Quem entra** (modo google): administradores de `JANUS_ADMIN_EMAILS` (configuração; vazio = sem Adm;
  e-mail inválido recusa o início antes das credenciais), a lista fixa `JANUS_ALLOWED_EMAILS` (mantida
  por compatibilidade) ou quem está ativo na aba `usuarios` da planilha (`usuarios!A:F`; o `journal` não
  muda). O cadastro nunca concede papel de Adm. Falha de leitura nega o acesso.
- **Sessão aberta**: a autorização fica em cache por até 30 s (edições da tabela não gastam cota);
  Processar, Aprovar, Tentar arquivar, Preparar Excel e toda ação do Adm conferem de novo na hora. Sem
  acesso, a sessão é limpa e aparece "Seu acesso foi removido.".
- **Adm** (expansor discreto, só para administradores; cada clique confere de novo): estado do
  compartilhamento da pasta `entrada`, adicionar e-mail, lista de assessores com Remover, pendências com
  Revogar. Mudanças de permissão em sequência (um lock por processo).
- **Adicionar**: compartilha só a `entrada` (Editor) e depois registra no cadastro. Se compartilhar
  falhar, nada é liberado; se o registro falhar, a pasta fica compartilhada e aparece como pendência.
- **Remover**: bloqueia primeiro no cadastro e depois revoga a permissão direta na `entrada`. Se a
  revogação falhar, o app já está bloqueado e a permissão aparece em pendências para Revogar. Nunca
  informa "removido" com acesso restante. Administradores, proprietários da pasta, a conta de serviço e
  a lista fixa não podem ser alterados pelo Adm. Arquivos que o próprio assessor enviou podem continuar
  sendo dele no Drive: isso não é revogado aqui.
- **Cadastro**: vale o evento mais recente pelo instante gravado; Remover sempre grava um DEL, então um
  ADD que chegue atrasado não devolve o acesso. Linha estranha na aba `usuarios` bloqueia todos os
  assessores (falha fechada; administradores continuam entrando). Excel já preparado só é entregue após
  conferência atual.
- **Pré-requisitos (gates humanos)**: o proprietário cria a aba `usuarios` vazia na planilha de produção;
  mantém ligado “Editores podem alterar permissões e compartilhar” **somente** na pasta `entrada`
  (desligado na raiz, `processados`, `falhas` e planilha), senão a conta técnica não consegue compartilhar
  (o Adm mostra o aviso). Efeito colateral: assessores também podem recompartilhar a `entrada`; o Adm
  lista essas permissões em Pendências para Revogar. Comportamento real da API (endereço canônico do
  Gmail, atraso na listagem, herança no Meu Drive) só se confirma no teste real autorizado.

## Gates humanos (não executados aqui)

Planilha e pastas `JANUS_PRODUCAO*`, conta de serviço e permissões, segredos de produção,
login/allowlist, importação real do histórico, cópia antes do piloto, deploy e merge
dependem de aprovação humana pontual.

## Testes

116 testes OK: os 74 anteriores, 15 em `tests/test_etapa4.py`, 3 do ensaio de recuperação em `tests/test_recuperacao.py`,
17 em `tests/test_acesso.py` e 7 de acesso na interface em `tests/test_ui.py` (somente fakes).
