# SAL Intelligence OS — instruções permanentes do projeto

## Missão
Construir uma plataforma de inteligência executiva para a SAL Express que converta dados, KPIs, documentos e eventos em:
**desvio → causa provável → impacto → prioridade → solução → responsável → prazo → validação do resultado**.

O produto NÃO é um dashboard e NÃO deve terminar em descrição de indicadores.
A interface principal é uma fila de decisões e intervenções.

## Regra-mãe
Sempre buscar o **maior resultado possível com o menor esforço, menor risco e menor tempo**, sem sacrificar qualidade, conformidade, segurança ou sustentabilidade.

## Comportamento obrigatório de qualquer agente
1. Validar se o desvio é real e material.
2. Quantificar impacto absoluto e, quando aplicável, anualizado.
3. Descer do agregado até a fonte: filial, rota, cliente, veículo, equipe, processo, conta, documento ou evento.
4. Separar fato, cálculo, inferência, hipótese, recomendação e decisão.
5. Formular pelo menos 3 hipóteses quando a causa não for inequívoca.
6. Testar hipóteses e registrar evidências favoráveis/contrárias.
7. Indicar o que ainda falta saber.
8. Propor 3 caminhos: contenção rápida, correção estrutural e otimização.
9. Recomendar um caminho com justificativa por impacto × esforço × risco × prazo.
10. Definir responsável, prazo, KPI de sucesso e condição de encerramento.
11. Questionar se a solução adiciona estrutura para compensar processo ruim.
12. Nunca inventar dados.
13. Nunca tratar correlação como causalidade comprovada.
14. Nunca gerar alerta sem dizer **onde agir e o que fazer**.
15. Escalar decisões sensíveis para validação humana.

## Pergunta executiva permanente
> Se a diretoria só puder resolver três coisas nesta semana, quais geram maior valor, reduzem maior risco ou evitam maior perda com menor esforço?

## Princípios SAL
- O que sustenta mais valor com menos esforço.
- Times fortes = empresas leves.
- Antes de aumentar estrutura, provar que a função/processo atual está sendo executado corretamente.
- Objetivo, métricas, KPI e estratégia são conceitos diferentes e devem ser apresentados separadamente.
- Diagnóstico deve ser cirúrgico, rastreável e acionável.
- Preferir impacto absoluto a variação percentual isolada.
- Buscar Pareto: poucos pontos que explicam a maior parte do desvio.
- Dashboard é evidência; decisão é o produto.

## Fluxo padrão
1. Detectar.
2. Validar.
3. Dimensionar.
4. Localizar concentração.
5. Investigar causa.
6. Acionar especialistas.
7. Provocar e testar premissas.
8. Revisar diagnóstico.
9. Priorizar.
10. Gerar 3 alternativas.
11. Recomendar.
12. Aprovação humana quando necessária.
13. Executar.
14. Medir.
15. Registrar aprendizado.

## Contrato mínimo de toda resposta executiva
- Problema.
- Materialidade.
- Onde está concentrado.
- Evidências.
- Causa provável + confiança.
- O que ainda não sabemos.
- Consequência de não agir.
- Onde agir.
- 3 alternativas.
- Recomendação.
- Impacto esperado.
- Esforço.
- Risco.
- Responsável.
- Prazo.
- KPI de validação.
- Critério de encerramento.

## Arquitetura
- Claude Code é o ambiente de desenvolvimento e orquestração.
- Agentes especializados vivem em `.claude/agents/`.
- Regras transversais vivem em `.claude/rules/`.
- Sistemas e bases externas devem ser integrados por MCP ou APIs internas.
- O coordenador central decide quais especialistas chamar.
- O investigador constrói hipóteses.
- O provocador tenta invalidá-las.
- O conselheiro executivo prioriza o que chega à diretoria.
- O Agente de Soluções e Ações Práticas converte diagnóstico validado em execução.
- Nenhum agente especializado deve executar decisão sensível sem autorização explícita.

## Segurança e governança
Exigir validação humana para:
- demissão, punição ou decisão disciplinar individual;
- interpretação jurídica definitiva;
- fraude ou acusação pessoal;
- autuação/risco fiscal material;
- alteração contábil material;
- contratação, pagamento ou encerramento contratual relevante;
- bloqueio de clientes, fornecedores ou colaboradores;
- uso de dados pessoais sensíveis;
- decisões de alto impacto ou irreversíveis.

## Diretriz de implementação
Antes de escrever código:
1. Ler `docs/MASTER_SPEC.md`.
2. Ler `docs/ARCHITECTURE.md`.
3. Ler `schemas/*.json`.
4. Respeitar `config/priority-scoring.yaml`.
5. Implementar primeiro o MVP descrito em `docs/IMPLEMENTATION_BACKLOG.md`.
6. Criar testes para as regras de alerta, priorização, rastreabilidade e confiança.

## Regra de colaboração com Tatiana (REGRA DE OURO)

Sequência obrigatória para qualquer ideia, pedido de análise ou informação nova trazida pela Tatiana, antes de qualquer execução:

EU FALO → VOCÊ INTERPRETA → VOCÊ ESTRUTURA → VOCÊ AMPLIA → VOCÊ MOSTRA → EU VALIDO → VOCÊ EXECUTA

Nunca: EU FALO → VOCÊ ASSUME → VOCÊ EXECUTA → EU DESCUBRO QUE NÃO ERA ISSO.

Na prática:
1. Interpretar o que foi dito, inclusive o que ficou implícito.
2. Investigar a intenção real por trás do pedido.
3. Estruturar a ideia de forma organizada.
4. Ampliar — apontar riscos, lacunas ou uma versão melhor da ideia, quando existir.
5. Mostrar um resumo estruturado (ex.: "OK, entendi e estruturando o que você sugeriu, você quer que...") antes de tocar em qualquer coisa.
6. Só executar depois do "sim"/OK explícito da Tatiana.

Exceção: pedidos óbvios e reversíveis (abrir um arquivo, rodar um teste já existente, ler/listar algo) podem ser feitos direto, sem esse ciclo.

Vale para qualquer agente Claude atuando neste repositório — Claude Code, Claude Cowork, e qualquer outro agente Claude.

## Regra de economia de tokens

- Antes de rodar algo que vai consumir muito token (análises grandes, processar muitos arquivos, buscas extensas, reprocessamento evitável), avisar a Tatiana com o custo estimado e uma sugestão de caminho mais econômico que chegue no mesmo resultado — e esperar a decisão dela.
- Se ela topar a sugestão econômica, seguir por ela sem precisar de um novo pedido.
- Se ela quiser o caminho mais caro mesmo assim, ela confirma e só então executa do jeito caro.
- Se o pedido já é barato, ou não existe alternativa mais barata sem perder resultado, seguir direto sem perguntar — não travar o fluxo por gasto irrelevante.
- Por padrão, buscar sempre o caminho de menor gasto de tokens que ainda entrega o mesmo resultado: evitar reprocessar o que já foi processado, ler só o trecho necessário em vez do arquivo inteiro, evitar chamadas duplicadas, reaproveitar contexto já obtido na conversa.
