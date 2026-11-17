"""Testes da Etapa 3 (rodar:  python -m unittest discover -s tests -v   dentro de backend/previsao)."""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset import JANELA_MEDIA, eventos_para_dataset  # noqa: E402
from previsao import CAMINHO_MODELO_PADRAO, ModeloEspera  # noqa: E402
import simulador  # noqa: E402

C, K = "CHEGADA", "CONCLUSAO"


class TestDataset(unittest.TestCase):
    def test_mesma_semantica_do_firmware(self):
        # Mesmos números do teste do firmware (test_fila_core.cpp), em segundos em vez de milissegundos
        ev = [(C, 1), (C, 2), (C, 3), (K, 5), (K, 9), (K, 10), (C, 20), (K, 26)]
        l = eventos_para_dataset(ev, "TESTE")
        self.assertEqual([(x["espera_real_s"], x["atendimento_real_s"]) for x in l],
                         [(0, 4), (3, 4), (6, 1), (0, 6)])
        self.assertEqual([x["pessoas_a_frente"] for x in l], [0, 1, 2, 0])

    def test_conclusao_com_fila_vazia_e_ignorada(self):
        self.assertEqual(eventos_para_dataset([(K, 1), (K, 2)], "TESTE"), [])
        l = eventos_para_dataset([(K, 1), (C, 2), (K, 5)], "TESTE")
        self.assertEqual(len(l), 1)
        self.assertEqual(l[0]["atendimento_real_s"], 3)

    def test_media_recente_so_usa_o_passado(self):
        # a 1ª pessoa chega sem histórico; a 2ª chega depois de um atendimento de 4 s
        ev = [(C, 0), (K, 4), (C, 10), (K, 16)]
        l = eventos_para_dataset(ev, "TESTE")
        self.assertIsNone(l[0]["media_atendimento_recente_s"])
        self.assertEqual(l[1]["media_atendimento_recente_s"], 4)

    def test_janela_de_dez_atendimentos(self):
        ev, t = [], 0.0
        duracoes = [10] * 5 + [100] * JANELA_MEDIA            # 15 atendimentos
        for d in duracoes:
            ev += [(C, t), (K, t + d)]
            t += d + 1
        ev += [(C, t), (K, t + 7)]
        ultima = eventos_para_dataset(ev, "TESTE")[-1]
        self.assertAlmostEqual(ultima["media_atendimento_recente_s"], 100.0)   # só os 10 últimos (todos de 100 s)

    def test_origem_e_preservada(self):
        l = eventos_para_dataset([(C, 0), (K, 3)], "REAL")
        self.assertEqual(l[0]["origem"], "REAL")

    def test_tipo_desconhecido(self):
        with self.assertRaises(ValueError):
            eventos_para_dataset([("OUTRO", 0)], "TESTE")


class TestSimulador(unittest.TestCase):
    def test_deterministico(self):
        self.assertEqual(simulador.simular(dias=3, seed=1), simulador.simular(dias=3, seed=1))
        self.assertNotEqual(simulador.simular(dias=3, seed=1), simulador.simular(dias=3, seed=2))

    def test_dados_gerados_sao_identificados_como_simulados(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho, n = simulador.gerar_arquivos(pasta, seed=3, dias=4)
            with open(caminho, encoding="utf-8") as f:
                linhas = list(csv.DictReader(f))
            self.assertEqual(len(linhas), n)
            self.assertTrue(all(l["origem"] == "SIMULADO" for l in linhas))
            with open(os.path.join(pasta, "dados_simulados.meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
            self.assertIn("SIMULADOS", meta["AVISO"])

    def test_simulacao_respeita_fifo_e_nao_tem_esperas_negativas(self):
        l = eventos_para_dataset(simulador.simular(dias=5, seed=7), "SIMULADO")
        self.assertTrue(all(x["espera_real_s"] >= 0 and x["atendimento_real_s"] > 0 for x in l))
        self.assertTrue(all(x["pessoas_a_frente"] >= 0 for x in l))
        # quem chega e encontra a fila vazia nunca espera
        self.assertTrue(all(x["espera_real_s"] == 0 for x in l if x["pessoas_a_frente"] == 0))


class TestModeloEspera(unittest.TestCase):
    def setUp(self):
        self.m = ModeloEspera(["pessoas_a_frente", "media_atendimento_recente_s", "hora_do_dia"],
                              [300.0, 0.5, -20.0], -30.0, media_historica_s=228.0)

    def test_sem_ninguem_a_frente_a_espera_e_zero(self):
        e = self.m.estimar(0, 200.0, 11.0)
        self.assertEqual(e["convencional_s"], 0)
        self.assertEqual(e["ia_s"], 0)

    def test_convencional_e_pessoas_vezes_media(self):
        self.assertAlmostEqual(self.m.prever_convencional(5), 5 * 228.0)

    def test_ia_e_a_soma_ponderada(self):
        esperado = -30.0 + 300.0 * 4 + 0.5 * 200.0 - 20.0 * 11.0
        self.assertAlmostEqual(self.m.prever_ia(4, 200.0, 11.0), esperado)

    def test_previsao_nunca_negativa(self):
        m = ModeloEspera(["pessoas_a_frente"], [1.0], -1000.0, 228.0)
        self.assertEqual(m.prever_ia(1, 100.0, 9.0), 0.0)

    def test_sem_media_recente_usa_convencional(self):
        e = self.m.estimar(3, None, 10.0)
        self.assertTrue(e["ia_usou_fallback"])
        self.assertAlmostEqual(e["ia_s"], e["convencional_s"])

    def test_estimativa_cresce_com_a_fila(self):
        valores = [self.m.estimar(n, 200.0, 11.0)["ia_s"] for n in range(0, 10)]
        self.assertEqual(valores, sorted(valores))
        convs = [self.m.estimar(n, 200.0, 11.0)["convencional_s"] for n in range(0, 10)]
        self.assertEqual(convs, sorted(convs))

    def test_ida_e_volta_do_json(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "m.json")
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(self.m.para_dict(), f)
            m2 = ModeloEspera.carregar(caminho)
            self.assertAlmostEqual(m2.prever_ia(4, 200.0, 11.0), self.m.prever_ia(4, 200.0, 11.0))

    def test_atributo_desconhecido_e_tamanhos_diferentes(self):
        with self.assertRaises(ValueError):
            ModeloEspera(["xyz"], [1.0], 0.0, 100.0)
        with self.assertRaises(ValueError):
            ModeloEspera(["pessoas_a_frente"], [1.0, 2.0], 0.0, 100.0)


class TestTreino(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy  # noqa: F401
            import sklearn  # noqa: F401
            import pandas  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("numpy/pandas/scikit-learn não instalados")
        import treinar
        cls.treinar = treinar
        cls.pasta = tempfile.mkdtemp()
        caminho, _ = simulador.gerar_arquivos(cls.pasta, seed=11, dias=20)
        cls.saida, cls.modelo = treinar.comparar(caminho, pasta_saida=cls.pasta, grafico=False)
        cls.dados = treinar.carregar_dados(caminho)

    def test_divisao_cronologica_sem_vazamento(self):
        treino, teste, dias_tr, dias_te = self.treinar.dividir_cronologicamente(self.dados)
        self.assertLess(max(dias_tr), min(dias_te))
        self.assertEqual(len(set(treino["data"]) & set(teste["data"])), 0)

    def test_modelo_sem_sklearn_reproduz_o_sklearn(self):
        import numpy as np
        from sklearn.linear_model import LinearRegression
        rng = np.random.default_rng(0)
        X = rng.uniform(0, 10, (50, 3))
        y = X @ np.array([3.0, -1.0, 0.5]) + 2.0
        lr = LinearRegression().fit(X, y)
        m = ModeloEspera(["pessoas_a_frente", "media_atendimento_recente_s", "hora_do_dia"],
                         lr.coef_, lr.intercept_, 100.0)
        for linha in X[:10]:
            esperado = max(0.0, float(lr.predict([linha])[0]))
            self.assertAlmostEqual(m.prever_ia(linha[0], linha[1], linha[2]), esperado, places=6)

    def test_metricas_conhecidas(self):
        m = self.treinar.metricas([0, 10, 20], [0, 10, 20])
        self.assertEqual((m["MAE_s"], m["RMSE_s"], m["R2"]), (0, 0, 1))
        m = self.treinar.metricas([10, 10], [20, 0])
        self.assertAlmostEqual(m["MAE_s"], 10)
        self.assertAlmostEqual(m["RMSE_s"], 10)

    def test_artefatos_gravados_e_identificados(self):
        caminho = os.path.join(self.pasta, "modelo_regressao.json")
        self.assertTrue(os.path.exists(caminho))
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        self.assertIn("SIMULADOS", d["info"]["AVISO"].upper())
        self.assertEqual(d["info"]["origem_dos_dados"], ["SIMULADO"])

    def test_resultados_tem_as_tres_metricas_dos_dois_metodos(self):
        r = self.saida["resultados"][self.saida["modelo_escolhido"]]["so_com_fila_ge_1"]
        for metodo in ("convencional", "ia_regressao_linear"):
            for chave in ("MAE_s", "RMSE_s", "R2"):
                self.assertIn(chave, r[metodo])


class TestModeloEntregue(unittest.TestCase):
    def test_modelo_gravado_funciona(self):
        if not os.path.exists(CAMINHO_MODELO_PADRAO):
            self.skipTest("rode treinar.py antes")
        m = ModeloEspera.carregar()
        ia = [m.estimar(n, 230.0, 11.5)["ia_s"] for n in range(0, 12)]
        self.assertEqual(ia[0], 0)
        self.assertTrue(all(b >= a for a, b in zip(ia, ia[1:])))
        self.assertIn("SIMULADO", m.info["origem_dos_dados"])


if __name__ == "__main__":
    unittest.main()
