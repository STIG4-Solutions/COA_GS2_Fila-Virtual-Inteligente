"""Testes das ferramentas (simulador do ESP32 e exportação do dataset real)."""
import csv
import os
import random
import sys
import tempfile
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(QUI)
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "ferramentas"))

import json  # noqa: E402

from banco import Banco  # noqa: E402
from exportar_dataset import exportar  # noqa: E402
from servico import validar_evento  # noqa: E402
from simulador_esp32 import ROTEIRO_DEMO, FilaSimulada  # noqa: E402


class TestSimuladorEsp32(unittest.TestCase):
    def test_todo_evento_simulado_passa_na_validacao_do_backend(self):
        f = FilaSimulada("a1b2c3d4")
        rng = random.Random(1)
        t = 0
        for a in ROTEIRO_DEMO * 3 + list("sss") + [rng.choice("cs") for _ in range(200)]:
            t += 90000
            validar_evento(json.dumps(f.evento(a, t, 1794361680 + t // 1000)))

    def test_regras_iguais_as_do_firmware(self):
        f = FilaSimulada("00000001")
        e1 = f.evento("c", 1000, 1)
        e2 = f.evento("c", 2000, 2)
        e3 = f.evento("c", 3000, 3)
        a = f.evento("s", 5000, 5)       # mesmos números de test_fila_core.cpp (ms)
        b = f.evento("s", 9000, 9)
        self.assertEqual((e3["fila"], a["fila"], b["fila"]), (3, 2, 1))
        self.assertEqual((a["espera_ms"], a["atendimento_ms"]), (0, 4000))
        self.assertEqual((b["espera_ms"], b["atendimento_ms"]), (3000, 4000))
        self.assertEqual(b["media_ms"], 4000)
        self.assertEqual([e1["seq"], e2["seq"], e3["seq"], a["seq"], b["seq"]], [1, 2, 3, 4, 5])

    def test_fila_vazia_e_fila_cheia(self):
        f = FilaSimulada("00000002")
        v = f.evento("s", 1000, 1)
        self.assertEqual((v["tipo"], v["valido"], v["fila"], v["atendidos"]), ("REJEITADA_VAZIA", False, 0, 0))
        for i in range(100):
            self.assertEqual(f.evento("c", 2000 + i, 2)["tipo"], "CHEGADA")
        self.assertEqual(f.evento("c", 9999, 3)["tipo"], "REJEITADA_CHEIA")

    def test_roteiro_demo_termina_com_recusa_de_fila_vazia(self):
        f = FilaSimulada("00000003")
        tipos = [f.evento(a, 1000 * (i + 1), i)["tipo"] for i, a in enumerate(ROTEIRO_DEMO)]
        self.assertIn("REJEITADA_VAZIA", tipos)


class TestExportarDataset(unittest.TestCase):
    def test_exporta_com_as_mesmas_regras_da_etapa_3(self):
        banco = Banco(":memory:")
        f = FilaSimulada("aaaa0001")
        base = 1794361680
        for i, a in enumerate("ccscsss"):                    # a última tentativa é recusada (fila vazia)
            ev = f.evento(a, (i + 1) * 60000, base + (i + 1) * 60)
            banco.inserir_evento(validar_evento(json.dumps(ev)), 0)
        # segunda sessão (ESP32 reiniciou): uma pessoa
        g = FilaSimulada("bbbb0002")
        for i, a in enumerate("cs"):
            banco.inserir_evento(validar_evento(json.dumps(g.evento(a, (i + 1) * 60000, base + 9000 + (i + 1) * 60))), 0)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "dados_reais.csv")
            n = exportar(banco, caminho)
            with open(caminho, encoding="utf-8") as fh:
                linhas = list(csv.DictReader(fh))
        self.assertEqual(n, len(linhas))
        self.assertEqual(n, 4)                                 # 3 atendidos na sessão 1 + 1 na sessão 2
        self.assertTrue(all(l["origem"] == "REAL" for l in linhas))
        self.assertEqual(linhas[0]["pessoas_a_frente"], "0")
        self.assertEqual(linhas[1]["pessoas_a_frente"], "1")
        self.assertEqual(float(linhas[0]["atendimento_real_s"]), 120.0)   # chegou em 60 s, concluiu em 180 s
        self.assertEqual(linhas[0]["media_atendimento_recente_s"], "")     # 1ª pessoa: sem histórico


if __name__ == "__main__":
    unittest.main()
