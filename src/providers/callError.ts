/**
 * Erro de chamada que PRESERVA o que o provider já informou (tokens, modelo) quando a resposta chegou mas
 * não pôde ser usada — ex.: truncada em max_tokens ou marcada como incompleta. O provider pode ter cobrado
 * esses tokens; descartar a contagem junto com o texto esconderia custo real.
 */

import type { TokenUsage } from "./types.js";

export type ProviderCallFailureKind = "truncated" | "incomplete";

export class ProviderCallError extends Error {
  constructor(
    readonly kind: ProviderCallFailureKind,
    message: string,
    readonly usage?: TokenUsage,
    readonly model?: string,
    /** Quantas requisições HTTP o provider fez nesta chamada (inclui adaptação de parâmetro). */
    readonly attempts?: number,
  ) {
    super(message);
    this.name = "ProviderCallError";
  }
}
