"""Grafo de atendimento de leads da Nexion AI Systems.

    mensagem → [triagem] → [roteador] ─ spam ─────────────→ descarta
                               ├─ suporte ─────────────→ resposta + passagem p/ suporte
                               ├─ vendas ──────────────→ resposta + passagem p/ vendas
                               └─ IA continua ─────────→ resposta
    resposta = [redator] → [revisor] → reprovada? → [redator corrige] ↺ (até MAX_CORRECOES)

Cada nó é UMA chamada à API, com só o contexto de que precisa.
O roteador é código: regras de negócio não dependem do modelo acertar.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import anthropic

import prompts

# Modelos por nó: barato onde a tarefa é simples, melhor onde o texto vai para o cliente.
MODELO_SIMPLES = os.environ.get("NEXION_MODELO_SIMPLES", "claude-haiku-5-5")  # triagem, passagem
MODELO_TEXTO = os.environ.get("NEXION_MODELO_TEXTO", "claude-sonnet-5-5")     # redator, revisor

MAX_CORRECOES = 2
PONTUACAO_QUENTE = 75  # a partir daqui o lead vai para vendas mesmo sem pedido específico

# Preço por milhão de tokens (US$): entrada, saída. Usado só para estimar custo.
PRECOS = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

DESTINOS_COM_HUMANO = {"vendas_humano", "suporte_humano"}

SCHEMA_TRIAGEM = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["novo_lead", "cliente_suporte", "spam"]},
        "segmento": {"type": "string"},
        "nome_ou_empresa": {"type": "string"},
        "cidade": {"type": "string"},
        "necessidade": {"type": "string"},
        "produto_indicado": {"type": "string"},
        "urgencia": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "pontuacao": {"type": "integer"},
        "motivos_para_humano": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "preco_proposta",
                    "contratacao",
                    "integracao_nao_listada",
                    "suporte_tecnico",
                    "reclamacao",
                ],
            },
        },
        "justificativa": {"type": "string"},
    },
    "required": [
        "tipo", "segmento", "nome_ou_empresa", "cidade", "necessidade", "produto_indicado",
        "urgencia", "pontuacao", "motivos_para_humano", "justificativa",
    ],
    "additionalProperties": False,
}

SCHEMA_REVISAO = {
    "type": "object",
    "properties": {
        "aprovada": {"type": "boolean"},
        "problemas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["aprovada", "problemas"],
    "additionalProperties": False,
}


class Recusa(Exception):
    """O modelo recusou a chamada (stop_reason == "refusal")."""


@dataclass
class Uso:
    """Tokens e custo estimado acumulados por modelo."""

    por_modelo: dict[str, dict[str, int]] = field(default_factory=dict)

    def somar(self, modelo: str, usage) -> None:
        d = self.por_modelo.setdefault(
            modelo, {"chamadas": 0, "entrada": 0, "cache_escrita": 0, "cache_leitura": 0, "saida": 0}
        )
        d["chamadas"] += 1
        d["entrada"] += usage.input_tokens or 0
        d["cache_escrita"] += usage.cache_creation_input_tokens or 0
        d["cache_leitura"] += usage.cache_read_input_tokens or 0
        d["saida"] += usage.output_tokens or 0

    def total_tokens(self) -> int:
        return sum(
            d["entrada"] + d["cache_escrita"] + d["cache_leitura"] + d["saida"]
            for d in self.por_modelo.values()
        )

    def custo_estimado(self) -> float:
        custo = 0.0
        for modelo, d in self.por_modelo.items():
            p_in, p_out = PRECOS.get(modelo, (0.0, 0.0))
            custo += (
                d["entrada"] * p_in
                + d["cache_escrita"] * p_in * 1.25
                + d["cache_leitura"] * p_in * 0.1
                + d["saida"] * p_out
            ) / 1_000_000
        return custo


@dataclass
class Resultado:
    triagem: dict
    destino: str
    motivo: str
    resposta: str | None = None
    resposta_aprovada: bool = False
    revisoes: list[dict] = field(default_factory=list)
    passagem: str | None = None

    @property
    def enviar_automaticamente(self) -> bool:
        """Só envia sem conferência humana se a resposta passou na revisão."""
        return self.resposta is not None and self.resposta_aprovada


def rotear(triagem: dict) -> tuple[str, str]:
    """Aresta condicional do grafo. Regras de negócio da Nexion — ajuste aqui."""
    if triagem["tipo"] == "spam":
        return "descartar", "spam"
    motivos = set(triagem["motivos_para_humano"])
    if triagem["tipo"] == "cliente_suporte" or motivos & {"suporte_tecnico", "reclamacao"}:
        return "suporte_humano", "cliente com problema"
    if motivos:
        return "vendas_humano", "pedido que a IA não resolve: " + ", ".join(sorted(motivos))
    if triagem["pontuacao"] >= PONTUACAO_QUENTE:
        return "vendas_humano", f"lead quente (pontuação {triagem['pontuacao']})"
    return "ia_continua", "a IA segue o atendimento"


def formatar_conversa(mensagens: list[dict]) -> str:
    """mensagens: [{"autor": "cliente" | "nexion", "texto": "..."}], em ordem."""
    nomes = {"cliente": "Cliente", "nexion": "Nexion"}
    return "\n".join(f"{nomes[m['autor']]}: {m['texto']}" for m in mensagens)


class GrafoLeads:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None, usar_fallback: bool = True):
        self.client = client or anthropic.AsyncAnthropic()
        # Fallback no servidor: se o Sonnet recusar, a API refaz a chamada noutro modelo.
        # Disponível só na API da Anthropic; desligue em Bedrock/Vertex/Foundry.
        self.usar_fallback = usar_fallback
        self.uso = Uso()

    async def _chamar(
        self, modelo: str, system: str, conteudo: str, *, schema: dict | None = None,
        effort: str = "low", max_tokens: int = 4000,
    ) -> str:
        extra = {}
        if self.usar_fallback and modelo == "claude-sonnet-5-5":
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        output_config: dict = {"effort": effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        resposta = await self.client.beta.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            # O system é fixo por nó: com cache, as próximas chamadas pagam ~10% dele.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": conteudo}],
            output_config=output_config,
            **extra,
        )
        self.uso.somar(modelo, resposta.usage)
        if resposta.stop_reason == "refusal":
            raise Recusa(f"{modelo} recusou a chamada")
        if resposta.stop_reason == "max_tokens":
            raise RuntimeError(f"{modelo} atingiu max_tokens={max_tokens}")
        return "".join(b.text for b in resposta.content if b.type == "text").strip()

    async def triar(self, conversa: str) -> dict:
        texto = await self._chamar(
            MODELO_SIMPLES, prompts.TRIAGEM, f"Conversa:\n{conversa}", schema=SCHEMA_TRIAGEM
        )
        triagem = json.loads(texto)
        triagem["pontuacao"] = max(0, min(100, triagem["pontuacao"]))
        return triagem

    async def redigir(self, conversa: str, destino: str, motivo: str, correcao: str = "") -> str:
        pedido = f"Conversa:\n{conversa}\n\nEncaminhamento decidido: {destino} ({motivo})."
        if correcao:
            pedido += f"\n\n{correcao}"
        return await self._chamar(MODELO_TEXTO, prompts.REDATOR, pedido)

    async def revisar(self, conversa: str, destino: str, motivo: str, resposta: str) -> dict:
        texto = await self._chamar(
            MODELO_TEXTO, prompts.REVISOR,
            f"Conversa:\n{conversa}\n\nEncaminhamento: {destino} ({motivo})\n\n"
            f'Mensagem proposta:\n"""{resposta}"""',
            schema=SCHEMA_REVISAO, effort="medium",
        )
        return json.loads(texto)

    async def resumir(self, conversa: str, triagem: dict, destino: str, motivo: str, resposta: str | None) -> str:
        return await self._chamar(
            MODELO_SIMPLES, prompts.PASSAGEM,
            f"Conversa:\n{conversa}\n\nTriagem: {json.dumps(triagem, ensure_ascii=False)}\n"
            f"Encaminhamento: {destino} ({motivo})\nResposta enviada pela IA: {resposta or '(nenhuma)'}",
        )

    async def processar(self, mensagens: list[dict]) -> Resultado:
        """Roda o grafo inteiro para uma conversa e devolve o que fazer com ela."""
        conversa = formatar_conversa(mensagens)
        try:
            triagem = await self.triar(conversa)
        except Recusa as erro:
            return Resultado(triagem={}, destino="vendas_humano", motivo=f"triagem não concluída: {erro}")
        destino, motivo = rotear(triagem)
        resultado = Resultado(triagem=triagem, destino=destino, motivo=motivo)
        if destino == "descartar":
            return resultado

        try:
            resposta = await self.redigir(conversa, destino, motivo)
            for tentativa in range(MAX_CORRECOES + 1):
                revisao = await self.revisar(conversa, destino, motivo, resposta)
                resultado.revisoes.append(revisao)
                if revisao["aprovada"]:
                    resultado.resposta_aprovada = True
                    break
                if tentativa == MAX_CORRECOES:
                    break
                problemas = "\n- ".join(revisao["problemas"])
                resposta = await self.redigir(
                    conversa, destino, motivo,
                    correcao=f'Versão anterior reprovada:\n"""{resposta}"""\n'
                             f"Problemas apontados:\n- {problemas}\nReescreva corrigindo todos.",
                )
            resultado.resposta = resposta
        except Recusa as erro:
            # Sem resposta automática: a conversa vai para uma pessoa.
            resultado.destino = "suporte_humano" if destino == "suporte_humano" else "vendas_humano"
            resultado.motivo = f"{motivo}; {erro}"

        # Resposta reprovada também precisa de uma pessoa olhando antes de enviar.
        if resultado.destino in DESTINOS_COM_HUMANO or not resultado.resposta_aprovada:
            try:
                resultado.passagem = await self.resumir(
                    conversa, triagem, resultado.destino, resultado.motivo, resultado.resposta
                )
            except Recusa:
                resultado.passagem = None  # a equipe lê a conversa direto
        return resultado
