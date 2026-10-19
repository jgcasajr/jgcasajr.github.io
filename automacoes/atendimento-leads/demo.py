"""Roda o grafo com 6 conversas simuladas e mostra o resultado e o custo.

Uso:  ANTHROPIC_API_KEY=... python demo.py
"""

import asyncio
import json

from grafo import GrafoLeads

# Conversas fictícias, escolhidas para testar casos difíceis.
CONVERSAS = {
    "L1 clínica quer testar já": [
        {"autor": "cliente", "texto": "Oi, boa tarde! Tenho uma clínica odontológica com 3 dentistas aqui em Pelotas"},
        {"autor": "cliente", "texto": "vi o OdontoNexion, como funciona o teste? quero começar essa semana ainda, nossa agenda é toda no papel"},
    ],
    "L2 pedido de preço": [
        {"autor": "cliente", "texto": "quanto custa o crm de vcs?"},
        {"autor": "cliente", "texto": "tenho uma imobiliária pequena, 4 corretores"},
    ],
    "L3 produto não lançado": [
        {"autor": "cliente", "texto": "Bom dia. Tenho duas óticas em Rio Grande e vi que vocês têm sistema pra ótica. Já posso contratar? Preciso trocar o sistema até o fim do mês."},
    ],
    "L4 integração não anunciada": [
        {"autor": "cliente", "texto": "Imobiliária Horizonte aqui. A IA de vocês puxa os leads do ZAP Imóveis e do VivaReal automaticamente?"},
        {"autor": "cliente", "texto": "recebemos uns 200 contatos por mês e metade se perde"},
    ],
    "L5 cliente com problema": [
        {"autor": "cliente", "texto": "Sou cliente do StudioNexion e o sistema não está mandando as confirmações de aula desde ontem!!"},
        {"autor": "cliente", "texto": "meus alunos estão reclamando, preciso de solução urgente"},
    ],
    "L6 spam": [
        {"autor": "cliente", "texto": "ganhe R$5.000 por semana trabalhando de casa, clique aqui bit.ly/xxxx"},
    ],
    "L7 dúvida simples": [
        {"autor": "cliente", "texto": "Oi! O StudioNexion serve para estúdio de yoga? Tenho um pequeno em Porto Alegre."},
    ],
}


async def main() -> None:
    grafo = GrafoLeads()
    nomes = list(CONVERSAS)
    resultados = await asyncio.gather(*(grafo.processar(CONVERSAS[n]) for n in nomes))

    for nome, r in zip(nomes, resultados):
        print(f"\n=== {nome}")
        print(f"tipo: {r.triagem.get('tipo')} · pontuação: {r.triagem.get('pontuacao')} · destino: {r.destino} ({r.motivo})")
        print(f"revisões: {len(r.revisoes)} · aprovada: {r.resposta_aprovada} · enviar automaticamente: {r.enviar_automaticamente}")
        if r.resposta:
            print(f"resposta:\n{r.resposta}")
        if r.passagem:
            print(f"passagem para a equipe:\n{r.passagem}")

    print("\n=== uso")
    print(json.dumps(grafo.uso.por_modelo, indent=2))
    print(f"tokens no total: {grafo.uso.total_tokens():,}")
    print(f"custo estimado: US$ {grafo.uso.custo_estimado():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
