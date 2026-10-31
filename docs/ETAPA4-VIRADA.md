# Etapa 4 — Roteiro de virada (uma hospedagem Streamlit)

Decisão: reutilizar a hospedagem `protocolos-gamba-demo.streamlit.app`, preservando a homologação até a virada
autorizada (Issue #1, 6544225270). Modelo de acesso A. **H** = responsável (conta dona/admin); **T** = técnico.
Nada aqui é executado sem o gate indicado. Segredos nunca em GitHub, Issue, PR, chat ou log.

## Fatos que definem a sequência
- O Community Cloud **não troca branch** de um app: é preciso apagar e reimplantar. A documentação diz que o
  subdomínio “deve” ficar livre logo após apagar (não comprovável sem apagar) → registrar um redirect OAuth de reserva.
- Repositório público → o app reimplantado **provavelmente nasce público** e perde a lista de viewers.
- Com escopos básicos (openid/email/profile) a lista de usuários de teste do OAuth **não controla acesso**:
  quem controla é o cadastro `usuarios`, `JANUS_ADMIN_EMAILS` e, enquanto privado, os viewers do Streamlit.
- Sem `JANUS_AMBIENTE=producao` o código roda como homologação; sem `[auth]` mostra só “acesso não configurado”.
- A importação do histórico aceita repetição **só com o mesmo arquivo** (mesmo digest): guardar o export intacto.

## Sequência (cada linha: quem · ação · critério)
**0. Consolidação do código — gate “merge”**
1. H · Abrir **um** PR `etapa4/sec-revisao` → `producao` (contém #8–#10; #7 já está em `producao`).
   Conferir: head `3bf723fe1bece11fd0619838a88c6fff576710b6`, base `31f5859`, 16 commits, 21 arquivos,
   216 testes OK, ruleset `producao-protegida` ativo, diff sem segredo.
2. H · Merge com **“Create a merge commit”** (ou `gh api -X PUT .../pulls/<N>/merge -f merge_method=merge -f sha=3bf723f…`).
   Fechar #7–#10 como incorporados. **Não** fazer merge dos drafts nas bases atuais (chegaria a
   `etapa3/streamlit-sheets`, que alimenta a homologação). O merge não implanta nada (nenhum app acompanha `producao`).

**1. Preparação, sem tocar a homologação — gate “preparação”**
3. H · No cliente OAuth `JANUS Web` (janus-producao), manter `https://protocolos-gamba-demo.streamlit.app/oauth2callback`
   e **acrescentar a reserva** `https://janus-gamba-operacao.streamlit.app/oauth2callback` (horas antes; mudanças levam até horas).
4. H · Montar localmente o TOML de produção a partir de `docs/producao-secrets.template.toml`
   (`cookie_secret`: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`). Regras: todas as `JANUS_*`
   **antes** de `[auth]`; valores entre aspas; `JANUS_ADMIN_EMAILS` como **texto** com vírgulas (lista = sem admin,
   sem aviso); JSON da conta de serviço entre `'''`; `JANUS_ALLOWED_EMAILS = ""`.
5. H · Backups: cópia da planilha de homologação (“Fazer uma cópia”); Excel do app de homologação (Preparar/Baixar);
   **cópia dos Secrets da homologação** em cofre privado; anotar repo/branch/arquivo, subdomínio, versão do Python,
   estado privado e lista de viewers. Sem cópia dos Secrets não há volta → não seguir.

**2. Migração do histórico — gate “migração”** (app de produção ainda não no ar)
6. H · Congelar a digitação na COLAB no horário **T**; exportar `.xlsx` (só valores); T · `sha256sum` e guardar o arquivo
   intacto + cópia fora da conta dona.
7. H · Confirmar `journal` e `usuarios` **vazias** (sem cabeçalho) na `JANUS_PRODUCAO_BASE`.
8. T · `verificar-historico COLAB_T.xlsx` → ~3.271 linhas, ~3.106 únicos, 54 duplicatas (+ o que entrou até T),
   `appends: 1`, `celulas_ok: True`. Queda de linhas ou recusa → parar.
9. T · `import-history-sheets COLAB_T.xlsx` (uma vez; chave da conta de serviço **temporária**, por variável de
   ambiente, excluída no Cloud ao fim) → `backup-sheets BKP_POS_IMPORT.xlsx` + `verificar-historico` na cópia:
   métricas **idênticas**; repetir a importação → “Mesmo histórico já importado”.

**3. Troca da hospedagem — gate “virada”**
10. H · Apagar o app de homologação e, em seguida, **Create app**: repo `sistemagamba-dev/Inteligencia_Gamba`,
    branch `producao`, `app.py`, App URL `protocolos-gamba-demo` (recusado → `janus-gamba-operacao`), mesmo Python.
    Em *Advanced settings* colar **só** `JANUS_MODE = "google"` e `JANUS_AMBIENTE = "producao"`.
    Critério: a página abre só com “acesso não configurado” (sem credencial no ar enquanto possivelmente pública).
11. H · Settings → Sharing → **privado** (“Only specific people”); convidar os viewers.
12. H · Settings → Secrets: colar o TOML completo (`redirect_uri` igual à URL obtida) → Save → **Reboot**.

**4. Validação e piloto — gates “teste real” e “piloto”**
13. H · Login com conta autorizada → legenda **“OPERAÇÃO”** (não “AMBIENTE DE TESTE”, não demonstração);
    conta não autorizada → “Acesso não autorizado”; Adm só para admin; Adm sem aviso de compartilhamento amplo.
14. H · Preparar Excel → mesmo total do histórico do passo 9.
15. H · Piloto com 3–5 PDFs reais (1 já existente na COLAB): duplicado ignorado; novos com numeração seguinte;
    arquivados em `processados`; Excel confere com a COLAB. Teste de acesso: adicionar assessor aprovado (compartilha
    só `entrada`), remover (app bloqueado + pasta revogada ou pendência visível). Ao final `backup-sheets` fora da conta.

## Reversão
- **Importação falhou:** repetir com o **mesmo** arquivo; recusa por histórico → planilha nova em `JANUS_PRODUCAO`
  + trocar `JANUS_SHEET_ID`; nunca apagar a antiga, nunca reexportar a COLAB para repetir.
- **Problema após a virada:** parar o app (Settings), voltar à digitação manual; registros pós-T recuperados pelos PDFs
  (seção Recuperação de `docs/ETAPA4.md`, que restaura a base lógica, não o diário bruto).
- **Voltar à homologação:** apagar o app → Create app em `etapa3/streamlit-sheets` com só `JANUS_MODE` → privado +
  viewers → colar os Secrets guardados no passo 5 → Reboot. Dados de homologação intactos.

## Critérios de aprovação da virada
Passos 13–15 todos OK, sem aviso de ACL ampla, backup pós-piloto guardado fora da conta e aceite explícito do
responsável. Visibilidade pública continua sendo gate separado.
