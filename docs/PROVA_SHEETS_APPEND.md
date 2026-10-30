# Última prova Sheets — append-only, operador único

**Veredito: APROVADO no escopo desta prova simulada.** Nenhum cenário executado
perdeu/sobrescreveu registros, duplicou protocolos novos na visão lógica ou
arquivou PDF sem gravação confirmada. **Recomendação: seguir com Sheets usando
este modelo append-only; não retomar a escrita por posições fixas.** Isso não
significa migração realizada, integração Google comprovada ou PROTÓTIPO FECHADO.

Base: prova anterior `15c3b49aac3dbee1bbdf7dee8fb77b1fe2270488`, após leitura da
Issue #1. Branch isolada `prova/sheets-append-only`. A prova reaproveita os mesmos
arquivos experimentais, parser, serialização, leitor de histórico, fixtures e
adaptador LocalDrive. Streamlit, SQLite e código operacional não foram alterados.
Nenhuma dependência nova, conta, credencial, Google real, custo ou deploy.

## Alteração mínima de estratégia

A prova anterior escrevia em posições calculadas no cliente. Um pedido atrasado
podia ocupar a mesma posição de um lote posterior após reinício. Nesta versão,
**nenhum pedido informa a posição de escrita**: toda escrita usa o contrato
`values.append`, `valueInputOption=RAW`, `insertDataOption=INSERT_ROWS`, range
`journal!A:F`. O servidor simulado acrescenta ao final quando recebe o pedido.
Não há update, reserva de linha, CAS, lock distribuído ou versão de abas.

O diário possui seis colunas técnicas. Eventos:

- `H` + manifesto `I`: valores históricos e digest da fonte. Repetir uma importação
  não multiplica as linhas históricas na base lógica. As duplicatas que já existem
  **dentro da fonte** e suas posições permanecem integralmente preservadas.
- `R` + manifesto `C`: registros humanos aprovados e confirmação do lote. O ID do
  lote deriva do conteúdo aprovado/IDs/hashes dos PDFs, independentemente da
  ordenação dos itens; o ID de registro é `JANUS:` + protocolo normalizado.
  O manifesto verifica contagem/hash do grupo na releitura. Só um grupo completo
  e validado entra na base lógica ou pode gerar arquivamento.
- `A`: confirmação append-only de arquivamento por ID de registro, arquivo e hash.
  Chegadas tardias não apagam uma confirmação já existente.

A consulta conserva o **primeiro registro confirmado na ordem física do diário**
por protocolo normalizado, sem sobrescrever dados anteriores. Novas tentativas,
mesmo com linhas físicas repetidas, não criam novos registros lógicos. Registros
com o mesmo protocolo e campos diferentes também não sobrescrevem o primeiro;
ficam identificados como ignorados no resultado. PDFs dessas ocorrências
ignoradas não são arquivados como novos. Todos os dados físicos permanecem no
log para rastreio; nenhum evento é apagado para deduplicar.

O ID não é uma chave única fornecida pelo Sheets: a deduplicação é do leitor.
O lock local restante apenas evita clique duplo enquanto o processo está vivo.
Os ensaios de reinício descartam completamente esse objeto e toda memória do
cliente; a integridade não depende do lock nem de reservar a tentativa em RAM.

## Simulador adversarial e limites da modelagem

`fake.py` somente modela append de linhas, leituras e falhas. Não elimina pedidos
repetidos no servidor nem promete entrega exatamente uma vez. Permite:

- timeout antes de aplicar;
- aplicação com resposta perdida;
- retenção do pedido em trânsito, entrega fora da ordem de envio e repetição da
  entrega mais de uma vez;
- leitura indisponível ou snapshot antigo;
- omissão das células vazias finais na resposta, como ocorre em values.get.

O append de uma requisição é modelado como aplicado por inteiro ou não aplicado,
sem uma transação envolvendo leitura e escrita. Além disso, o leitor rejeita
manifestos corrompidos/incompletos e impede exportação/arquivamento nesses casos.
Isso não simula o Google inteiro, nem prova garantias de rede, privacidade,
permissões, cotas ou a semântica real do append sobre uma tabela configurada.

Referências do contrato a conferir em futura integração autorizada:
[values.append](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append)
e [atomicidade/limites das requisições](https://developers.google.com/workspace/sheets/api/limits).
Nenhuma chamada a essas APIs foi feita nesta execução.

## Evidências executadas

[Suíte completa](evidence/sheets-append/tests.txt): **59 testes aprovados**
(40 do protótipo + 19 desta prova), em 0,787 s. Não há controle negativo que aceite
perda de dados como resultado esperado na suíte atual. A falha do commit anterior
foi convertida em teste que exige a preservação dos dois lotes.

Os testes incluem todos os casos pedidos: clique duplo, reprocessamento,
normalização, timeout antes/depois de gravar, reinício completo com pedido em
trânsito, lote posterior confirmado primeiro, lotes parcialmente sobrepostos,
entrega repetida, leitura antiga/falha, histórico e exportação, confirmação de
arquivo perdida e proibição de arquivar enquanto a gravação não está confirmada.
Um teste percorre **as seis permutações de chegada de três lotes retidos**, com
entregas duplicadas, reinícios e um quarto lote já confirmado.

[Ensaio maior](evidence/sheets-append/benchmark.json):

| Medida | Resultado observado |
|---|---|
| Histórico inteiramente sintético | 3.160 linhas / 3.106 protocolos distintos / 54 repetições originais |
| PDFs físicos gerados e extraídos | 100 PDFs / 300 páginas / 50 de cada layout |
| Antes da aprovação | 0 registros novos lógicos |
| Segundo lote confirmado primeiro | 50 novos |
| Primeiro lote, retido e depois entregue duas vezes | 48 novos + 2 duplicados ignorados |
| Eventos físicos de registros novos | 146 |
| Base lógica nova | 98 protocolos únicos; 48 repetições físicas consolidadas |
| Repetição do primeiro lote após reinício | 0 registros e 0 appends adicionais |
| Reprocessamento dos 100 PDFs | 0 novos / 100 ignorados |
| Arquivamento confirmado | 98 PDFs; 2 duplicados preservados na entrada |
| Excel relido | 3.258 linhas de dados; histórico idêntico; primeira ordem nova 3.161 |
| Prefixo já confirmado do diário | Inalterado após a chegada tardia |
| Chamadas append / entregas aplicadas | 5 / 6 (inclui a entrega adicional simulada) |
| Maior corpo append serializado | 857.474 bytes (importação histórica) |

Tempos locais: importação/geração/extração **0,301228 s**; aprovações adversariais e
reconciliação **0,096660 s**; total, incluindo arquivamento/exportação, **0,845159 s**.
Não incluem latência Google, quotas, servidor Cloud ou tempo de conferência humana.

Reprodução, com as dependências já existentes:

```sh
/tmp/janus-venv/bin/python -m unittest discover -v
/tmp/janus-venv/bin/python -m experiments.sheets_poc.benchmark
```

Somente o experimento usa esse armazenamento. Os testes do aplicativo original
continuam verificando a implementação SQLite. Não houve migração de tela,
workflow ou importação de acervo real.

## Riscos ainda não comprovados no Google real

1. Range da tabela append, autorização e respostas reais de get/append precisam
   de uma integração futura controlada. O transporte HTTP não foi implementado.
2. A planilha física é **um diário técnico**, com repetições possíveis. Toda leitura
   funcional/exportação deve passar pela projeção lógica; usar o export nativo
   desse diário como base de protocolos exibiria eventos/repetições. Isso deve
   continuar invisível para o assessor na futura integração.
3. Leitura do diário inteiro e crescimento das linhas físicas precisam de medição
   com retenção real. A prova limita célula a 50 mil caracteres e corpo a 2 MB
   por escolha conservadora, sem fracionar um grupo confirmado. Não há promessa
   de capacidade gratuita ilimitada ou SLA.
4. Sem edição manual, ordenação ou exclusão de linhas no diário: a estratégia
   requer uma tabela sob controle do aplicativo. Não foi testada proteção de
   ranges, identidade técnica ou privacidade do Community Cloud.
5. IDs/hash/dados do lote aprovado precisam ser reproduzidos pela futura interface.
   A projeção deve ser usada em todos os caminhos; não basta trocar uma conexão.
6. Acesso privado, backups externos, cotas e bloqueio de cobranças ainda exigem os
   gates e validações já documentados. A prova usa R$ 0 e nenhum serviço remoto;
   não comprova, sozinha, a operação definitiva gratuita.

**Próximo passo recomendado:** manter o candidato append-only e encerrar as
alternativas com posições fixas. Apresentar esta evidência para decisão humana
sobre a próxima validação de integração, sem executá-la nesta autorização.
