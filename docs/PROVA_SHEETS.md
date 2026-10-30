# Prova Sheets — operador único, Google simulado

**Veredito: REPROVADO para substituir o SQLite neste estado.** O fluxo simples
funciona nos ensaios usuais, mas a recuperação não é segura em um cenário de
reinício completo com pedido antigo ainda em trânsito. Não foi feita migração,
integração Google, alteração do Streamlit/Drive existente ou publicação.

Issue #1 e PR #3 conferidos. Base: `e8e672b51d68d18b1156fa8d3a3639098ff41f9c`.
Branch isolada: `prova/sheets-simulado`. O ajuste de escopo desta execução fixa
**um único operador autorizado**. Não há requisito de concorrência entre usuários.
A proposta inicial de trocar abas/versionar snapshots foi retirada antes do
commit. A prova final usa somente consulta, escrita em posições fixas e recibos.

## Código isolado e funcionamento

- `experiments/sheets_poc/store.py`: consulta protocolos normalizados históricos e
  novos; ignora duplicados; recebe aprovação explícita; grava novos dados e
  recibo do lote em uma única chamada `values.batchUpdate`, usando `RAW`.
- Um bloqueio em memória evita clique duplo no mesmo processo. Um lote com
  resultado incerto impede outro lote enquanto o processo mantém essa memória.
  A repetição usa **os mesmos dados e posições**, sem repetir um append cego.
- Recibos confirmados no Sheets simulado permitem reconhecer o lote após recriar
  o cliente. Dados incluem ID/hash do PDF. O arquivamento só usa registros com
  recibo confirmado; a confirmação de arquivamento fica em células separadas,
  para não ser desfeita por uma repetição tardia dos dados do lote.
- Histórico sintético é importado uma vez, preservando valores A:J, duplicatas,
  linhas vazias, datas e ordem. Não há escrita na fonte. Exportação Excel segue
  a aba JANUS 2026/cabeçalhos na linha 2 e trata fórmulas novas como texto literal.
- `fake.py` modela apenas leitura dos ranges e escrita atômica em ranges fixos.
  **Não inventa CAS, chave única, lock remoto ou controle de versão no Sheets.**
  O lock interno do simulador representa uma requisição atômica, não a sequência
  de consultar e gravar. Não há código HTTP, ADC ou credenciais.
- Reutiliza `Record`, normalização, parser, leitor do histórico, serialização de
  datas e o adaptador `LocalDrive` existentes. A interface do transporte é só um
  contrato local; não existe adaptador para acessar o Google real nesta entrega.
- Os dados técnicos usam JSON por registro nos ranges simulados; isso não é uma
  migração da aplicação nem uma planilha final para uso manual do operador.

## Evidências executadas

[Log da suíte](evidence/sheets-poc/tests.txt): **52 testes passaram**, sendo 40
existentes e 12 da prova simplificada. Comando:

```sh
/tmp/janus-venv/bin/python -m unittest discover -v
/tmp/janus-venv/bin/python -m experiments.sheets_poc.benchmark
```

Os 12 testes cobrem: aprovação obrigatória e validação integral; clique duplo;
reprocessamento e duplicatas no lote; timeout antes de aplicar; timeout depois
de aplicar; pedido atrasado depois da repetição; controle negativo de reinício
com pedido em trânsito; rejeição atômica; histórico/exportação; reutilização de
ID de lote/arquivo; importação tardia/célula grande; recuperação do arquivamento.

**Atenção:** o teste com nome `test_negative_control_cold_restart_can_overwrite_unconfirmed_reservation`
passa porque **reproduz e confirma uma falha conhecida**, não porque o algoritmo
seja seguro nesse cenário. A aprovação da suíte inteira não aprova a migração.

[Lote executado](evidence/sheets-poc/benchmark.json):

| Verificação | Resultado |
|---|---|
| Histórico totalmente inventado | 3.160 linhas, 3.106 protocolos distintos, 54 repetições preservadas |
| PDFs gerados e extraídos fisicamente | 100 PDFs / 300 páginas, ambos os layouts |
| Registros antes da aprovação | 0 novos |
| Aprovação com resposta perdida simulada | 98 novos, 2 duplicados ignorados |
| Repetição do mesmo lote confirmado | 0 registros e 0 commits adicionais |
| Arquivamento confirmado | 98 PDFs; 2 duplicados preservados na entrada |
| Excel relido | 3.258 registros, valores históricos idênticos, sequência nova começa em 3.161 |
| Escritas aplicadas | 3: importação, lote+recibo e confirmação do arquivamento |
| Maior requisição serializada | 577.355 bytes |

Tempos desta execução: preparação/importação/geração/extração **0,252592 s**;
aprovação com recuperação de resposta perdida **0,024202 s**; total incluindo
arquivamento/exportação **0,607475 s**. Backend local em memória; tempos não
representam latência, cotas ou disponibilidade do Google.

Não foram executados: Google real, hospedagem Community Cloud, autenticação,
permissões, cotas remotas, persistência do servidor Google ou demonstração da
interface com Sheets. Os testes da aplicação original continuam usando SQLite.

## Risco reproduzido que impede aprovar a substituição simples

Ocorre **mesmo com um operador**, sem duas pessoas aprovando ao mesmo tempo:

1. Lote A envia escrita para a próxima linha livre. A chamada dá timeout, mas o
   pedido ainda está em trânsito e não aparece na releitura.
2. O aplicativo reinicia completamente, perdendo a memória do pedido incerto.
3. O operador inicia lote B. A planilha ainda parece vazia: B usa a mesma linha
   e confirma a gravação.
4. O pedido antigo de A chega depois e sobrescreve o registro/recibo confirmado
   de B. O teste verifica a perda do protocolo B.

Sem reinício, a repetição de A usa posições preservadas e ocupa essas linhas
antes de liberar B; a chegada tardia de A não apaga B. O problema é a perda da
reserva em memória enquanto ainda existe uma escrita externa possível.

Esse resultado demonstra uma falha sob o modelo de transporte adotado; não é
um incidente observado na API Google. Não temos uma garantia remota que exclua
esse ordenamento após a morte do cliente. Uma releitura vazia, sozinha, não é
prova de que o pedido antigo nunca será aplicado.

## Limite e próxima decisão

O fluxo simples serve como ensaio funcional, mas **não está aprovado como banco
permanente com recuperação equivalente à implementação atual**. Não se recomenda
aceitar perda de registros para conservar a simplicidade. Também não se afirma
que qualquer solução com Sheets seja impossível.

Conforme a instrução do responsável, o risco foi explicado durante a execução
antes de acrescentar complexidade. A prova para aqui: não foi implementado outro
mecanismo. Se houver continuação autorizada, avaliar somente a menor garantia
**durável de lote pendente/posições reservadas**, que sobreviva à perda do processo,
ou uma garantia remota equivalente. Sem múltiplos usuários, versionamento de
abas ou migração integral. Ainda seria uma prova simulada, não uma autorização
para Google real.

Limites adicionais da prova: até 50 mil caracteres por célula e teto conservador
próprio de 2 MB por escrita; o teto não é apresentado como limite rígido do
Google. Backups/credenciais/privacidade/cobrança não foram reimplementados nem
validados. Nenhum custo, recurso Google, dado real, main ou merge foi usado.
