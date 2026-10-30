# Inteligência Gambá

Ferramenta de inteligência operacional e automação para o Gabinete do Denis Gambá (Santo André, SP).

## MVP 01 — Protocolos JANUS

**Problema:** os assessores recebem PDFs gerados pelo JANUS e transcrevem manualmente os dados na planilha COLAB (cerca de 300 protocolos/mês, com picos no fim do mês).

**Objetivo:** um usuário sem conhecimento técnico deposita os PDFs no Google Drive, acessa uma interface simples, clica em **Processar PDFs**, confere e corrige **uma única tabela**, clica em **Aprovar e registrar tudo**, e os dados são registrados sem duplicações. Os arquivos processados são arquivados depois da confirmação de gravação, e a base pode ser exportada para Excel (.xlsx).

**Princípio:** fazer o mínimo necessário para eliminar a digitação manual com segurança. Nada de dashboards, automações extras ou arquitetura complexa antes da necessidade comprovada.

## Fonte canônica e materiais

- **Issue-mestra (leitura obrigatória):** [#1 — Etapa 0, MVP 01, etapas e rubricas](https://github.com/sistemagamba-dev/Inteligencia_Gamba/issues/1).
- **Drive autorizado:** [Inteligencia_Gamba](https://drive.google.com/drive/folders/12hFRwmYxrcpKa7X_NxHy3x0b3KpPhSWP), com 6 PDFs de referência e a planilha histórica (não usar como base operacional para testes destrutivos).
- **Código e decisões:** este repositório; referências de execução e aceites na Issue #1.

## Estado do projeto

- **Etapa 0:** descoberta funcional concluída.
- **Etapa 1:** prova técnica executada nesta branch, **APROVADA COM RESSALVAS**. Evidências, mapeamento, arquitetura e limites em [docs/ETAPA1.md](docs/ETAPA1.md). Contrato de autonomia e limites na seção 9 da Issue #1; pacote operacional fornecido pelo responsável usado durante o bloqueio de acesso.
- **Etapa 2:** protótipo funcional implementado nesta branch, **APROVADO COM RESSALVAS**. Uso, reprodução, evidências e pendências em [docs/ETAPA2.md](docs/ETAPA2.md). Integração Google real e hospedagem aguardam os gates específicos.
- **Etapa 3:** homologação, com rubrica de **PROTÓTIPO FECHADO** e aceite humano explícito.
- **Etapa 4:** ativação operacional, exige autorização específica.

## Bootstrap para executores e novos chats

1. **Leia integralmente a Issue #1** antes de propor mudanças; confira o estado atual do repositório e os arquivos referenciados no Drive.
2. **Não refaça o questionário** nem altere decisões aprovadas sem motivo material. Em caso de conflito, registre a divergência e consulte o responsável.
3. **Trabalhe dentro da etapa autorizada**; execute autonomamente escolhas técnicas reversíveis e testes. Peça decisão humana apenas para custos, credenciais/permissões, dados reais, mudanças de escopo, alteração da `main`, merge, produção e avanço de etapa.
4. **Proteja dados pessoais:** não suba PDFs reais, CPF, RG, contatos privados ou dados desnecessários ao repositório e logs; teste com cópias seguras ou amostras anonimizadas.
5. **Preserve integridade:** nunca sobrescreva o histórico sem autorização; o protocolo JANUS normalizado é a chave de deduplicação; salvar somente após aprovação humana, arquivar PDFs somente após persistência confirmada.
6. **Usuário final 100% leigo:** sem terminal, instalação de Python, VBA, configuração de tokens ou comandos. Interface via navegador e linguagem simples.
7. **Encerre cada etapa por evidência**, com veredito e gate humano previstos na Issue #1. Não avance automaticamente para a etapa seguinte.

> Este protótipo usa somente ambiente de teste. **Não representa PROTÓTIPO FECHADO, autorização da Etapa 3 ou liberação de produção.**
