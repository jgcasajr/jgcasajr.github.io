"""Testes sem chamar a API: roteador e fluxo do grafo com um cliente falso.

Uso:  python -m pytest -q
"""

import asyncio
import json
from types import SimpleNamespace

import prompts
from grafo import MAX_CORRECOES, GrafoLeads, rotear


def triagem(**campos):
    base = {
        "tipo": "novo_lead", "segmento": "", "nome_ou_empresa": "", "cidade": "", "necessidade": "",
        "produto_indicado": "", "urgencia": "media", "pontuacao": 50, "motivos_para_humano": [],
        "justificativa": "",
    }
    return base | campos


# --- roteador -----------------------------------------------------------------

def test_spam_e_descartado():
    assert rotear(triagem(tipo="spam"))[0] == "descartar"


def test_cliente_com_problema_vai_para_suporte():
    assert rotear(triagem(tipo="cliente_suporte"))[0] == "suporte_humano"
    assert rotear(triagem(motivos_para_humano=["reclamacao"]))[0] == "suporte_humano"


def test_pedido_de_preco_vai_para_vendas():
    destino, motivo = rotear(triagem(motivos_para_humano=["preco_proposta"]))
    assert destino == "vendas_humano"
    assert "preco_proposta" in motivo


def test_lead_quente_vai_para_vendas():
    assert rotear(triagem(pontuacao=90))[0] == "vendas_humano"


def test_duvida_simples_fica_com_a_ia():
    assert rotear(triagem(pontuacao=60))[0] == "ia_continua"


# --- grafo com cliente falso ---------------------------------------------------

class ClienteFalso:
    """Imita client.beta.messages.create respondendo conforme o nó (pelo system prompt)."""

    def __init__(self, triagem, revisoes, recusar=()):
        self.triagem = triagem
        self.revisoes = list(revisoes)
        self.recusar = set(recusar)
        self.chamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        system = kw["system"][0]["text"]
        no = {prompts.TRIAGEM: "triagem", prompts.REDATOR: "redator",
              prompts.REVISOR: "revisor", prompts.PASSAGEM: "passagem"}[system]
        self.chamadas.append((no, kw))
        if no in self.recusar:
            return self._msg("", "refusal")
        texto = {
            "triagem": lambda: json.dumps(self.triagem),
            "redator": lambda: f"resposta {sum(1 for n, _ in self.chamadas if n == 'redator')}",
            "revisor": lambda: json.dumps(self.revisoes.pop(0)),
            "passagem": lambda: "- resumo",
        }[no]()
        return self._msg(texto, "end_turn")

    @staticmethod
    def _msg(texto, stop_reason):
        usage = SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0,
                                cache_read_input_tokens=100, output_tokens=5)
        return SimpleNamespace(stop_reason=stop_reason, usage=usage,
                               content=[SimpleNamespace(type="text", text=texto)])

    def nos(self):
        return [n for n, _ in self.chamadas]


CONVERSA = [{"autor": "cliente", "texto": "oi"}]
APROVADA = {"aprovada": True, "problemas": []}
REPROVADA = {"aprovada": False, "problemas": ["inventou preço"]}


def rodar(cliente):
    return asyncio.run(GrafoLeads(client=cliente).processar(CONVERSA))


def test_spam_nao_gera_resposta():
    cliente = ClienteFalso(triagem(tipo="spam"), [])
    r = rodar(cliente)
    assert r.destino == "descartar" and r.resposta is None
    assert cliente.nos() == ["triagem"]


def test_ia_continua_aprovada_envia_sem_passagem():
    cliente = ClienteFalso(triagem(pontuacao=60), [APROVADA])
    r = rodar(cliente)
    assert r.enviar_automaticamente and r.passagem is None
    assert cliente.nos() == ["triagem", "redator", "revisor"]


def test_reprovada_e_corrigida():
    cliente = ClienteFalso(triagem(pontuacao=60), [REPROVADA, APROVADA])
    r = rodar(cliente)
    assert r.resposta == "resposta 2" and r.resposta_aprovada
    assert cliente.nos() == ["triagem", "redator", "revisor", "redator", "revisor"]
    correcao = cliente.chamadas[3][1]["messages"][0]["content"]
    assert "inventou preço" in correcao and "resposta 1" in correcao


def test_reprovada_sempre_nao_envia_e_pede_humano():
    cliente = ClienteFalso(triagem(pontuacao=60), [REPROVADA] * (MAX_CORRECOES + 1))
    r = rodar(cliente)
    assert not r.enviar_automaticamente
    assert r.passagem == "- resumo"
    assert cliente.nos().count("revisor") == MAX_CORRECOES + 1


def test_vendas_recebe_passagem():
    cliente = ClienteFalso(triagem(motivos_para_humano=["preco_proposta"]), [APROVADA])
    r = rodar(cliente)
    assert r.destino == "vendas_humano" and r.enviar_automaticamente and r.passagem


def test_recusa_do_redator_vai_para_humano_sem_resposta():
    cliente = ClienteFalso(triagem(pontuacao=60), [], recusar={"redator"})
    r = rodar(cliente)
    assert r.destino == "vendas_humano" and r.resposta is None and r.passagem


def test_recusa_na_triagem_nao_perde_a_conversa():
    cliente = ClienteFalso(triagem(), [], recusar={"triagem"})
    r = rodar(cliente)
    assert r.destino == "vendas_humano"


def test_fallback_so_no_sonnet_e_system_com_cache():
    cliente = ClienteFalso(triagem(pontuacao=60), [APROVADA])
    rodar(cliente)
    for no, kw in cliente.chamadas:
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        if kw["model"] == "claude-sonnet-5-5":
            assert kw["fallbacks"] == "default"
        else:
            assert "fallbacks" not in kw
