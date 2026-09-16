# Torre de Controle — Regras de negócio inegociáveis

## Peso e ocupação (docs/regras-negocio/TRANSFERENCIA_OCUPACAO.md)
1. PESO NUNCA É ZERO. Ausência de dado = `null` + status INDISPONIVEL. Zero significaria
   "a rota transportou 0 kg" (grave); null significa "não conseguimos determinar".
2. Peso vem só de F_CUSTO_TRANSF, com dedup obrigatório MAX(PESO_CTRC) por ctrc.
3. `viagens = DISTINCTCOUNT(manifesto)`. NUNCA usar quantidade de CT-e como denominador.
4. ocupacao_pct = peso_medio_viagem / capacidade. Só é calculada com peso != null E
   capacidade > 0; caso contrário NAO_CALCULAVEL.
5. Faixas: >=85% saudável · 60-84,99% ociosidade moderada · <60% crítica. São INDICADOR,
   não afirmação de desperdício.
6. Capacidade cadastrada como 0 (ex. cavalo mecânico) = CADASTRO_INCONSISTENTE. NUNCA
   substituir por capacidade default inventada.
7. NUNCA chamar uma rota de ociosa quando o peso está ausente.
8. Se <80% das rotas tiverem peso, o diagnóstico é PARCIAL e a publicação é bloqueada.
9. Caso SSP: histórico de custo alto com CTes/viagens zerados — NÃO classificar
   automaticamente como rota deficitária; precedente documentado de erro do motor.

## OS Avulsas (docs/regras-negocio/OS_AVULSAS.md)
10. O CUSTO SEGUE O VEÍCULO: OS avulsa se vincula à jornada (Manifesto + Placa), nunca à
    data em que foi lançada.
11. As medidas dos BIs de Transferência, Coleta e Entrega JÁ INCLUEM as OS. Não somar de
    novo ao custo consolidado — expor separado apenas para rastreabilidade.

## Governança Alta Gestão × Controle (aprovada 17/08/2026)
12. Recomendação automática do motor (P1-P4, "onde agir", economia estimada) nasce
    PENDENTE e só aparece para a equipe de Controle. Nunca sobe como fato para a diretoria
    sem confirmação humana.
13. Rejeição vira registro de exceção append-only (autor + data + motivo) — é esse
    histórico que vira backlog de revisão de config_operacional.py. Correção NUNCA
    sobrescreve o config automaticamente.
14. Sem revisão em 48h úteis: estado "vencido, aguardando revisão", sempre visível como
    tal. Nunca escalado em silêncio nem descartado.
15. O detalhamento bruto nunca é removido da diretoria — deixa de ser o padrão, mas
    continua acessível (auditoria, decisão urgente).
