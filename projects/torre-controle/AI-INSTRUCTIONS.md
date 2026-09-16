# Torre de Controle — Instruções para agentes de IA

- Distinguir sempre INDICADOR de AFIRMAÇÃO: ocupação baixa é sinal para investigar, não
  prova de desperdício. O próprio config_operacional.py declara isso.
- Nunca recomendar corte/consolidação de rota sem checar antes: peso disponível, capacidade
  cadastrada, tipo de rota e se a viagem deveria ter ocorrido.
- Toda recomendação automática é hipótese até a equipe de Controle (Bruno Lacerda) confirmar.
  Ao propor algo, deixe explícito que precisa de confirmação humana antes de virar decisão.
- Separar o que é para ALTA GESTÃO (consolidado, tendência, achado já validado) do que é
  para CONTROLE (granular, por lane/placa/base, com ação e responsável).
- Preferir impacto absoluto em R$ e concentração (Pareto) a variação percentual isolada.
- Nunca inventar capacidade, peso ou custo ausente. Dado faltante é resposta válida.
- Precedente obrigatório de humildade: o caso SSP prova que o motor já errou. Ao classificar
  uma rota como problemática, diga o que confirmaria ou derrubaria essa classificação.
