# Atendimento de leads — Nexion AI Systems

Grafo que recebe uma conversa de WhatsApp, classifica o lead, decide o encaminhamento,
escreve a resposta, revisa essa resposta e, quando precisa, prepara um resumo para a equipe.

```
mensagem → [triagem] → [roteador] ─ spam ──────────→ descarta (sem resposta)
                            ├─ suporte_humano ───→ resposta + resumo p/ suporte
                            ├─ vendas_humano ────→ resposta + resumo p/ vendas
                            └─ ia_continua ──────→ resposta
resposta = [redator] → [revisor] → reprovada? → [redator corrige] ↺ (até 2 vezes)
```

| Nó | Como roda | Modelo |
|---|---|---|
| Triagem | 1 chamada, saída em JSON validado | Claude Haiku 5.5 |
| Roteador | código Python (`rotear` em `grafo.py`) | — |
| Redator | 1 chamada | Claude Sonnet 5.5 |
| Revisor | 1 chamada, saída em JSON validado | Claude Sonnet 5.5 |
| Passagem | 1 chamada | Claude Haiku 5.5 |

Cada chamada leva só o necessário: instruções do nó + fatos da empresa (em cache) + a conversa.
Um lead típico usa de 4 a 6 chamadas e alguns milhares de tokens. Rode `demo.py` para medir o custo real.

## Arquivos

- `prompts.py` — fatos oficiais da empresa e instruções de cada nó. **Atualize os fatos aqui** quando mudar produto ou serviço.
- `grafo.py` — os nós, o roteador e `GrafoLeads.processar()`.
- `demo.py` — roda 7 conversas fictícias e mostra resultado, tokens e custo estimado.
- `test_grafo.py` — testes que não chamam a API (roteador e fluxo completo com cliente falso).

## Como rodar

```bash
pip install -r requirements.txt
python -m pytest -q                           # testes, sem custo
ANTHROPIC_API_KEY=sk-ant-... python demo.py   # chama a API de verdade
```

Para trocar os modelos sem mexer no código: `NEXION_MODELO_SIMPLES` e `NEXION_MODELO_TEXTO`.

## Como ligar ao WhatsApp e ao CRM

`processar()` recebe a conversa e devolve um `Resultado`. Quem chama decide o que fazer com ele:

```python
grafo = GrafoLeads()

async def ao_receber_mensagem(conversa):         # chamado pelo webhook do WhatsApp
    r = await grafo.processar(conversa)           # [{"autor": "cliente"|"nexion", "texto": "..."}]
    registrar_no_crm(r.triagem, r.destino)        # NEXION CRM
    if r.enviar_automaticamente:
        enviar_whatsapp(r.resposta)
    if r.passagem:
        avisar_equipe(r.destino, r.passagem, rascunho=r.resposta)
```

`registrar_no_crm`, `enviar_whatsapp` e `avisar_equipe` dependem dos sistemas da Nexion
(WhatsApp Business API e NEXION CRM) e não estão implementadas aqui.

Uma resposta só sai automaticamente quando o revisor aprovou. Se ela continuar reprovada depois das correções,
vai como rascunho para uma pessoa revisar. Se algum modelo recusar a chamada, a conversa vai para uma pessoa.

## Onde ajustar as regras

Em `grafo.py`:
- `rotear()` — quem vai para vendas, suporte ou fica com a IA.
- `PONTUACAO_QUENTE` — a partir de que nota o lead vai direto para vendas.
- `MAX_CORRECOES` — quantas vezes o redator pode reescrever.

Depois de mudar uma regra, ajuste ou acrescente o teste correspondente em `test_grafo.py`.

## Observações

- Nas chamadas ao Sonnet, se o modelo recusar, a API refaz a chamada em outro modelo
  (`fallbacks: "default"`). Isso só existe na API da Anthropic. Em Bedrock, Vertex ou Foundry,
  crie o grafo com `GrafoLeads(usar_fallback=False)`.
- O custo mostrado pelo `demo.py` é uma estimativa com os preços de tabela em `PRECOS`.
- Antes de colocar em produção, rode com conversas reais (anonimizadas) e confira as respostas.
