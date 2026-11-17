"""Medições da Etapa 5 que NÃO dependem do ESP32: tamanho das mensagens, volume de dados e desempenho do backend.

  cd analise && python medir_rede_e_backend.py        (precisa de Flask: pip install -r ../backend/requirements.txt)

Os tempos do backend são medidos NESTE computador (não no ESP32, nem num servidor de produção).
"""
import json
import os
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "backend"))

import config  # noqa: E402
from app import criar_app  # noqa: E402
from banco import Banco  # noqa: E402
from estimador import carregar_modelo  # noqa: E402
from servico import ServicoFila  # noqa: E402

BASE = "teste/fila"
TOPICO = f"{config.TOPICO_BASE}/evento"


def evento(seq, tipo="CONCLUSAO", fila=3, atendidos=12, sessao="a1b2c3d4"):
    return {"sessao": sessao, "seq": seq, "tipo": tipo, "valido": tipo in ("CHEGADA", "CONCLUSAO"), "fila": fila,
            "atendidos": atendidos, "hora_s": 1794361680 + seq, "hora_real": True, "uptime_ms": 35236 + 1000 * seq,
            "espera_ms": 65000, "atendimento_ms": 215000, "media_ms": 220000}


def json_firmware(ev):
    """Mesmo formato (ordem e sem espaços) que o sketch.ino monta com snprintf."""
    return json.dumps(ev, separators=(",", ":"))


def main():
    # ---- 1) tamanho das mensagens MQTT
    tip = json_firmware(evento(17))
    pior = json_firmware(dict(evento(4294967295, "REJEITADA_VAZIA", fila=100, atendidos=4294967295, sessao="ffffffff"),
                              hora_s=4294967295, uptime_ms=4294967295, espera_ms=4294967295,
                              atendimento_ms=4294967295, media_ms=4294967295))
    topico = len(TOPICO.encode())
    print("== Mensagem MQTT (PUBLISH, QoS 0) ==")
    for nome, js in (("típica", tip), ("pior caso", pior)):
        carga = len(js.encode())
        resto = 2 + topico + carga                              # tamanho do tópico (2 B) + tópico + payload
        cab = 1 + (1 if resto < 128 else 2)                     # byte de controle + "remaining length" (1 ou 2 bytes)
        mqtt = cab + resto
        print(f"  {nome:<10} payload={carga} B | pacote MQTT={mqtt} B | com TCP/IP (+40 B)={mqtt + 40} B | cabe no buffer de 512 B: {mqtt <= 512}")

    # ---- 2) volume de dados do painel (polling)
    srv = ServicoFila(Banco(":memory:"), carregar_modelo(config.CAMINHO_MODELO), config.TOPICO_BASE)
    for i in range(1, 31):
        tipo = "CHEGADA" if i % 3 else "CONCLUSAO"
        srv.processar_mensagem(TOPICO, json_firmware(evento(i, tipo, fila=i % 6, atendidos=i // 3)).encode())
    cli = criar_app(srv).test_client()
    s = len(cli.get("/api/status").get_data())
    e15 = len(cli.get("/api/eventos?limite=15").get_data())
    print("\n== Painel (HTTP/JSON, sem compressão) ==")
    print(f"  /api/status = {s} B | /api/eventos?limite=15 = {e15} B | por ciclo = {s + e15} B")
    por_hora = (s + e15) * (3600 / 2)
    print(f"  a cada 2 s: {(s + e15) / 2 / 1024:.2f} KB/s por navegador aberto = {por_hora / 1e6:.1f} MB/hora")
    print(f"  só /api/status a cada 2 s: {s * 1800 / 1e6:.2f} MB/hora")

    # ---- 3) armazenamento e desempenho do backend (SQLite em arquivo, 1 commit por evento)
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "fila.db")
        banco = Banco(caminho)
        modelo = carregar_modelo(config.CAMINHO_MODELO)
        sv = ServicoFila(banco, modelo, config.TOPICO_BASE)
        N = 5000
        mensagens = [json_firmware(evento(i, "CHEGADA" if i % 2 else "CONCLUSAO", fila=i % 8, atendidos=i // 2)).encode()
                     for i in range(1, N + 1)]
        t0 = time.perf_counter()
        for m in mensagens:
            sv.processar_mensagem(TOPICO, m)
        dt = time.perf_counter() - t0
        banco._con.commit()
        tam = os.path.getsize(caminho)
        print("\n== Backend (neste computador) ==")
        print(f"  {N} eventos gravados em {dt:.2f} s = {1000 * dt / N:.3f} ms/evento ({N / dt:.0f} eventos/s), validando e com commit por evento")
        print(f"  arquivo SQLite: {tam} B para {N} eventos = {tam / N:.0f} B/evento (com índices)")
        t0 = time.perf_counter()
        for _ in range(200):
            sv.status()
        print(f"  status() (agrega contagens + calcula as duas estimativas): {1000 * (time.perf_counter() - t0) / 200:.3f} ms/chamada com {N} eventos no banco")
        por_dia = 190
        print(f"  uso típico (simulação da Etapa 3: ~{por_dia} eventos/dia): {por_dia * tam / N / 1024:.1f} KB/dia = {por_dia * tam / N * 365 / 1e6:.1f} MB/ano")


if __name__ == "__main__":
    main()
