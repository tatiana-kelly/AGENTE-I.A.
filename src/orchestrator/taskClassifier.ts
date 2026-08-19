import type { ClassificationResult, EffectLevel, SkillCategory } from "./types.js";

interface ClassificationRule {
  id: string;
  pattern: RegExp;
  skills: SkillCategory[];
  requiresGoogleWorkspace?: boolean;
  requiresInvestigation?: boolean;
  requiresImplementation?: boolean;
  requiresDecision?: boolean;
}

/**
 * Deterministic, keyword-based classification (FASE 1 scope). Each rule maps
 * a language signal to skills + routing flags consumed by the Routing Engine.
 * Rules are intentionally simple and auditable — no LLM call in the classifier
 * itself, so routing decisions stay explainable and reproducible.
 */
const RULES: ClassificationRule[] = [
  {
    id: "investigation",
    pattern: /\b(investigu\w*|descobr\w*|descubr\w*|apur\w*|explor\w*|pesquis\w*|por qu[eê])\b/i,
    skills: ["research", "operational-analysis"],
    requiresInvestigation: true,
  },
  {
    id: "business-interpretation",
    pattern: /\b(o que (realmente )?(est[aá] |esta )?acontecendo|o que houve|o que aconteceu)\b/i,
    skills: ["business-analysis"],
    requiresInvestigation: true,
  },
  {
    id: "decision",
    pattern: /\b(decis[ãa]o|decidir?|estrat[ée]gic\w*|valide|validar|avaliar|criti\w*)\b/i,
    skills: ["business-analysis"],
    requiresDecision: true,
  },
  {
    id: "architecture",
    pattern: /\b(arquitetur\w*|desenh\w* (o|a|essa|esse) sistema)\b/i,
    skills: ["architecture"],
  },
  {
    id: "implementation",
    pattern: /\b(implement\w*|constru\w*|codifi\w*|program(e|ar|ando))\b/i,
    skills: ["programming"],
    requiresImplementation: true,
  },
  {
    id: "debugging",
    pattern: /\b(corrij\w*|corrigir|bug|debug\w*|erro no c[oó]digo|falha no c[oó]digo)\b/i,
    skills: ["debugging"],
    requiresImplementation: true,
  },
  {
    id: "google-workspace",
    pattern: /\b(planilha\w*|google sheets|gmail|google drive|google agenda|google calendar|workspace)\b/i,
    skills: ["data-analysis"],
    requiresGoogleWorkspace: true,
  },
  {
    id: "data-analysis",
    pattern: /\b(analis\w* os dados|indicador\w*|m[ée]tric\w*|kpi|dashboard)\b/i,
    skills: ["data-analysis"],
  },
  {
    id: "financial",
    pattern: /\b(custo\w*|financeir\w*|receita\w*|faturamento|margem)\b/i,
    skills: ["financial-analysis"],
  },
  {
    id: "presentation",
    pattern: /\b(apresenta[çc][ãa]o|slide\w*|deck)\b/i,
    skills: ["presentation"],
  },
  {
    id: "automation",
    pattern: /\b(automa[çc][ãa]o|automatiz\w*|agend\w* (uma )?tarefa)\b/i,
    skills: ["automation"],
  },
];

const EXTERNAL_ACTION_PATTERN =
  /\b(envi\w*|dispar\w*|public\w*|deploy\w*|execut\w* (o |a |um |uma )?(workflow|automa[çc][ãa]o)|agend\w* (o |a |um |uma )?(envio|reuni[ãa]o|evento)|fa[çc]a (o |um )?deploy)\b/i;

const WRITE_PATTERN =
  /\b(alter\w*|atualiz\w*|modifi\w*|edit\w*|remov\w*|apag\w*|delet\w*|exclu\w*|salv\w*|grav\w*|commit\w*|push\w*|merge\w*|instal\w*)\b/i;

const READ_PATTERN =
  /\b(analis\w*|investig\w*|descobr\w*|descubr\w*|apur\w*|explor\w*|pesquis\w*|avali\w*|revis\w*|expli\w*|compar\w*|resum\w*|diagnostic\w*|identifi\w*|liste|listar|mostre|mostrar|consulte|consultar|leia|ler)\b/i;

const IMPLEMENTATION_DISCUSSION_PATTERN =
  /\b(analis\w*|avali\w*|revis\w*|expli\w*)\s+(como|se|a forma de)\s+(implement\w*|constru\w*|codifi\w*|program\w*)\b/i;

function classifyEffect(task: string, matched: ClassificationRule[]): EffectLevel {
  if (EXTERNAL_ACTION_PATTERN.test(task)) {
    return "EXTERNAL_ACTION";
  }

  if (WRITE_PATTERN.test(task)) {
    return "WRITE";
  }

  const implementationSignal = matched.some((rule) => rule.requiresImplementation === true);
  if (implementationSignal && IMPLEMENTATION_DISCUSSION_PATTERN.test(task)) {
    return "READ";
  }

  if (implementationSignal) {
    return "WRITE";
  }

  if (READ_PATTERN.test(task)) {
    return "READ";
  }

  const readOnlySignal = matched.some(
    (rule) => rule.requiresInvestigation === true || rule.requiresDecision === true,
  );
  return readOnlySignal ? "READ" : "UNKNOWN";
}

export function classifyTask(task: string): ClassificationResult {
  const matched = RULES.filter((rule) => rule.pattern.test(task));
  const skills = Array.from(new Set(matched.flatMap((rule) => rule.skills)));
  const effectLevel = classifyEffect(task, matched);

  return {
    skills: skills.length > 0 ? skills : ["operational-analysis"],
    effectLevel,
    requiresGoogleWorkspace: matched.some((rule) => rule.requiresGoogleWorkspace === true),
    requiresInvestigation: matched.some((rule) => rule.requiresInvestigation === true),
    requiresImplementation:
      effectLevel !== "READ" && matched.some((rule) => rule.requiresImplementation === true),
    requiresDecision: matched.some((rule) => rule.requiresDecision === true),
    rationale:
      matched.length > 0
        ? `Regras acionadas: ${matched.map((rule) => rule.id).join(", ")}. Efeito: ${effectLevel}.`
        : `Nenhuma regra reconheceu sinais fortes; efeito tratado como ${effectLevel}.`,
  };
}
