# Etapa 1 — prova técnica de Protocolos JANUS

**Veredito: APROVADO COM RESSALVAS.** Núcleo de extração, mapeamento A:J,
compatibilidade com histórico, deduplicação e recuperação local validados.
Não representa protótipo fechado, implantação ou aceite da Etapa 2.

Execução em 30/10/2026, branch `etapa1/prova-tecnica`. Base original:
`a282d2da6910eb11df1967f2b36b541cd1686e20`.
Contrato operacional: `CONTRATO_ETAPA1_CODEX.md` do pacote privado fornecido
pelo responsável nesta conversa, autorizado como referência substituta enquanto
a Issue #1 permanece inacessível. Não é transcrição integral da Issue.
Issue canônica: https://github.com/sistemagamba-dev/Inteligencia_Gamba/issues/1.
Este relatório deve ser transposto à Issue quando houver acesso.

## Evidência e reprodução

Python 3.12.14, pypdf 6.10.0, openpyxl 3.1.5; Linux. Nenhuma dependência de IA,
OCR, serviço externo, Streamlit ou ReportLab para executar a prova.

```sh
cd /workspace/Inteligencia_Gamba
python3 -m venv /tmp/gamba-etapa1-venv
/tmp/gamba-etapa1-venv/bin/python -m pip install -r requirements.txt
/tmp/gamba-etapa1-venv/bin/python -m unittest discover -v
/tmp/gamba-etapa1-venv/bin/python benchmark.py
# Opcional: referências privadas fora do checkout; nunca enviar saídas com valores pessoais.
/tmp/gamba-etapa1-venv/bin/python validate_private.py /tmp/pacote-privado --report /tmp/evidencia.json
```

Os testes públicos são inteiramente sintéticos. O validador privado exige as seis
amostras e uma planilha, usa aliases em ordem alfabética dos caminhos locais e
só publica contagens e indicadores; datas divulgadas são exemplos sintéticos. Não incorpora o pacote real ao Git.
Instalação em venv limpo, testes, benchmark e validação privada foram executados
com os comandos acima; `pip check` também passou.
As evidências JSON em `docs/evidence/` foram geradas por execução real nesta
máquina; tempos variam conforme máquina/carga e não são SLA.
Revisão pré-publicação registrada em `docs/evidence/privacy-review.json`:
arquivos versionados, relatórios e logs conferidos contra valores privados das
referências. Datas individuais reais e identificadores reais foram removidos;
o único commit da prova foi substituído localmente antes do primeiro push, para
não publicar versões intermediárias com esses metadados. Somente exemplos
explicitamente sintéticos de datas são divulgados.

### Seis PDFs reais

| Alias | Tipo | Páginas | Resultado |
|---|---|---:|---|
| PDF-01 | Zeladoria | 2 | Campos extraídos |
| PDF-02 | Zeladoria | 2 | Campos extraídos |
| PDF-03 | Zeladoria | 2 | Campos extraídos |
| PDF-04 | Zeladoria | 2 | Já no histórico |
| PDF-05 | Eventos | 4 | Layout específico extraído |
| PDF-06 | Zeladoria | 2 | Campos extraídos |

Datas individuais reais são verificadas somente na memória do validador e não
integram os relatórios ou logs versionados. Exemplo **inteiramente sintético**,
sem correspondência com documento real: `2030-01-02T01:15:00Z` se converte em
`2030-01-01T22:15:00-03:00` em `America/Sao_Paulo` (virada do dia).

As 16 páginas têm texto selecionável. Não foi necessário OCR. Foram localizados
protocolo, serviço, responsável pelo preenchimento, enquadramento, endereço,
bairro e pedido, com CreationDate válido em todas as amostras. O JSON conta oito
campos presentes considerando também a constante SISTEMA. B fica em branco;
A só é calculada ao inserir. Nenhum aviso de ausência/ambiguidade nestes layouts.
Datas próximas da virada do dia e horário de verão foram testadas sinteticamente;
nenhuma das seis datas reais mudou de dia na conversão.

### Mapeamento A:J

| Coluna | Regra comprovada |
|---|---|
| A ordem | Maior inteiro numérico histórico + 1, somente novos registros; sequência serializada na transação |
| B PREENCHIDO EM | Em branco para novos, sem correspondência comprovada |
| C Solicitante | Responsável pelo preenchimento; nunca Interessado(a) nem responsável pelo evento |
| D Data do Envio | CreationDate interno convertido por zoneinfo; salva data ISO local, não data de upload |
| E PROTOCOLO | Formato legível do cabeçalho; C + 18 dígitos após normalização para estas amostras |
| F SISTEMA | Constante JANUS |
| G ENQUADRAMENTO | Zeladoria: valor após Enquadramento:. Eventos: valor do campo repetido no bloco Enquadramento |
| H ENDEREÇO | Primeiro componente do endereço, preservando número e intervalo/lado da via de Eventos |
| I OCORRÊNCIA | Zeladoria: Descrição sintética do pedido. Eventos: Descrição objetiva do pedido, até Informações complementares |
| J BAIRRO | Segundo componente separado por vírgula, com estrutura municipal reconhecida; caso ambíguo fica vazio e sinalizado |

Endereço completo permanece em `Record.full_address` para revisão, inclusive cidade,
UF e CEP. `Local: -` nunca substitui endereço. Categoria de Eventos não é inferida
do nome ou do tipo do evento. O campo foi encontrado e extraído explicitamente.
Não há resumo por IA nem invenção de conteúdo. Ausência de opcionais produz
avisos; protocolo inválido/conflitante impede aprovação do lote no simulador.
Formato desconhecido é sinalizado: estes dois layouts não comprovam cobertura
de todos os futuros tipos JANUS. Novos layouts exigem revisão antes de inserção.
CreationDate ausente, malformado, parcial ou sem fuso explícito fica vazio com
aviso; não se presume fuso nem se usa a data do arquivo ou do upload.

### Histórico e segurança dos originais

Leitura `read_only=True` da aba JANUS 2026; cabeçalhos A:J conferidos na linha 2.
3.160 linhas com protocolo, 3.106 normalizados únicos, 54 excedentes repetidos.
O caso de duplicidade indicado no contrato foi confirmado (PDF-04), sem publicar o identificador real.
Na cópia temporária de teste: cinco novos, um ignorado; na repetição: zero novos,
seis ignorados. Comparação célula a célula dos valores históricos A:J na exportação
confirmou preservação inclusive de duplicatas e linhas vazias.

Os sete originais extraídos foram comparados por SHA-256 antes/depois: idênticos.
O ZIP original só foi aberto em leitura. Banco e exportações com dados reais
foram criados em TemporaryDirectory e removidos ao encerrar a validação;
arquivamento real não ocorreu (callback simulado em memória). Nenhuma chamada de
escrita ao Drive/Sheets ou à planilha fonte. Não se publica nome de pessoa,
contato, descrição de pedido ou conteúdo do pacote nas evidências.

**Limite da exportação:** preserva valores A:J, não o livro completo, suas outras
abas, colunas K:AB, macros, fórmulas ou formatação. O arquivo original continua
intacto. Qualquer migração definitiva precisa preservar o original como backup
e revisar fórmulas/colunas adicionais antes de operar. Strings iniciadas por `=`
são exportadas como texto literal para evitar execução de fórmulas novas.

### Testes e lote

22 testes unittest passaram: ambos os layouts e PDF gerado de ponta a ponta;
origem do solicitante; limites do pedido sem anexos; data ausente/inválida/sem
offset; offsets positivos/negativos, virada de dia e horário de verão; endereço
ambíguo; opcionais; protocolo conflitante; histórico em leitura; cabeçalhos
inválidos; aprovação obrigatória; lote inválido bloqueado integralmente;
duplicatas históricas/intralote/repetição; rollback sem arquivamento; commit antes
de arquivar; retomada após reabrir banco; movimento efetuado com confirmação
perdida; duas conexões sequenciais sem sobrescrita; exportação/ordem/texto literal.
O teste de duas conexões não é um ensaio de carga concorrente.

Lote sintético real: **100 PDFs, 300 páginas**, 50 de cada layout, geração e
extração física via pypdf. Primeira passagem: 100 inseridos; repetição: 0 inseridos,
100 ignorados; 100 operações únicas simuladas de arquivo; Excel relido com 100
linhas. Tempos originais em `docs/evidence/synthetic-batch.json`.
Rede, download/upload, consentimento humano e autenticação não estão incluídos.

## Arquitetura recomendada única

**Python + Streamlit + Google Drive + SQLite em volume persistente**, uma instância
do aplicativo, acesso autenticado e restrito ao gabinete; exportação `.xlsx`.
Interface futura apenas no navegador: processar por clique, uma tabela editável,
aprovar o lote uma vez, arquivar após commit. Operador não configura terminal ou
tokens. A implementação da interface e dos adaptadores é Etapa 2, não foi feita.

| Candidato avaliado | Decisão e motivo |
|---|---|
| Python + Streamlit + Drive + Sheets (prioritário no contrato) | Extração Python comprovada. Sheets facilita inspeção compartilhada, mas não oferece a mesma transação local entre chave única e outbox; prevenção de corridas, diário de lote e reconciliação exigiriam mecanismos extras. Acesso/autenticação Sheets não testados. Não escolhido como base primária. |
| Python + Streamlit + Drive + SQLite persistente | Escolhido. Parser selecionável sem IA/OCR, unicidade e commit/outbox testáveis, exportação Excel comprovada. Menos mecanismos para este volume; exige uma instância, disco persistente e backup/restauração. |
| Apps Script + Sheets + Drive | Boa identidade Google e hospedagem integrada, mas leitura de PDF tende a exigir conversão/OCR ou serviço adicional. Quotas, duração e locks precisam de prova própria. Menos reaproveitamento do parser validado; não demonstrado que seja mais simples para estes PDFs. |

Google Drive fica como entrada e arquivo, não como banco. O histórico deve ser
importado uma vez em tabela que permita duplicatas; novos registros têm chave
normalizada única. Nesta prova `History` mantém os valores importados em memória
e SQLite persiste apenas novos registros/outbox; migração persistente do histórico,
backup e autenticação ainda precisam ser implementados e testados na Etapa 2.

Transação de aprovação: valida todo o lote; ignora chaves existentes sem atualizar;
grava novos registros e outbox no mesmo commit; só então chama arquivamento.
Falha após commit deixa pendência; repetir não reinserta. Falha depois de mover
e antes de confirmar exige adaptador idempotente que consulte o destino pelo ID
estável do Drive. O simulador usa set em memória para provar esse contrato; não
comprova comportamento da API real. ID sintético no benchmark e digest dos PDFs
na validação privada identificam arquivos; na integração futura usar ID do Drive.

## Ressalvas e próximo gate

- Sem prova de autenticação Google, permissões de pastas, movimentação via API,
  sessão web, persistência de hospedagem ou restauração de backup. Nenhum deploy.
- Não se presume plano gratuito: escolher hospedagem com disco persistente e
  aprovar qualquer custo antes de contratar. SQLite em disco efêmero ou múltiplas
  réplicas não é configuração aceitável para esta recomendação.
- Não se afirma cobertura de documentos escaneados, todos os tipos de JANUS ou
  layouts além das seis referências. Eles devem aparecer para revisão, não ser
  inventados. Não há saneamento do histórico.
- Issue e Drive continuam canônicos; usar o pacote fornecido não demonstra que
  seus acessos online tenham sido corrigidos. Nenhum segredo foi solicitado.

**STOP:** Etapa 1 encerrada com ressalvas não críticas para esta prova.
Próximo gate: autorização humana explícita para a Etapa 2, com base e pasta de
teste, escolha de hospedagem sem custo não autorizado e concessões de acesso
necessárias. Não houve merge, alteração de main ou avanço de etapa.
