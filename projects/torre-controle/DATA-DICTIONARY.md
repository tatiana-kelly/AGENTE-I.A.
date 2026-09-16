# Torre de Controle — Dicionário mínimo

## Metas (src/lib/metas.ts, por dia útil)
Faturamento R$ 700.000 · Custo total R$ 400.000 · % Custo 57,14%.
Transferências R$ 136.250 · Coletas R$ 63.500 · Entregas Filiais R$ 116.000 ·
Entregas Parceiros R$ 80.000.

## Capacidades de veículo (snapshot/config_operacional.py — REFERÊNCIA operacional, não contratual)
VUC 3.500 · TOCO 6.500 · TRUCK 12.000 · TRUCK 3/4 4.000 · BITRUCK 18.000 ·
CARRETA 27.000 · BITREM 27.000 (kg).

## Alertas de custo por CT-e (referência de alerta, não meta corporativa)
BHE/DIE/VGE R$ 22,00 · demais bases R$ 25,00 (default).

## Lane e diagnóstico
lane = origem (hub) → destino. tipo_rota: FIXA | COMPARTILHADA | EVENTUAL | INDEFINIDA.
Prioridade da ação: P1 imediata · P2 prioritária · P3 monitorar · P4 sem ação.
Rota sem peso/capacidade recebe "DADO INSUFICIENTE", nunca uma recomendação.

## Custo × Performance (classificar_custo_perf)
A = custo subiu E performance caiu (prioridade operacional) · B = custo subiu, performance
estável (investigar diluição/volume) · C = ambos subiram (verificar retorno) · D =
performance caiu sem aumento de custo (investigar execução).

## Coleta Parceiros
R$ 249,36/dia útil — referência FIXA, sem granularidade real. Não tratar como medição.
