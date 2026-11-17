"""Armazenamento dos eventos em SQLite (o histórico completo fica aqui, não no ESP32)."""
import os
import sqlite3
import threading

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao         TEXT    NOT NULL,      -- identifica cada execução (boot) do firmware
    seq            INTEGER NOT NULL,      -- numeração do evento dentro da sessão (começa em 1)
    recebido_em    REAL    NOT NULL,      -- hora do servidor ao receber (epoch, s)
    tipo           TEXT    NOT NULL,
    valido         INTEGER NOT NULL,
    fila           INTEGER NOT NULL,
    atendidos      INTEGER NOT NULL,
    hora_s         INTEGER NOT NULL,      -- hora do ESP32 (NTP) ou segundos desde o boot
    hora_real      INTEGER NOT NULL,
    uptime_ms      INTEGER NOT NULL,
    espera_ms      INTEGER NOT NULL,
    atendimento_ms INTEGER NOT NULL,
    media_ms       INTEGER NOT NULL,
    UNIQUE (sessao, seq)                  -- a mesma mensagem recebida duas vezes não duplica
);
CREATE INDEX IF NOT EXISTS ix_eventos_id ON eventos (id DESC);
"""

COLUNAS = ["sessao", "seq", "tipo", "valido", "fila", "atendidos", "hora_s", "hora_real", "uptime_ms",
           "espera_ms", "atendimento_ms", "media_ms"]


class Banco:
    def __init__(self, caminho):
        if caminho != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
        self._con = sqlite3.connect(caminho, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if caminho != ":memory:":
                self._con.execute("PRAGMA journal_mode=WAL")
            self._con.executescript(ESQUEMA)
            self._con.commit()

    def inserir_evento(self, ev, recebido_em):
        """Devolve True se gravou, False se já existia (mesma sessão e seq)."""
        with self._lock:
            cur = self._con.execute(
                "INSERT OR IGNORE INTO eventos (sessao, seq, recebido_em, tipo, valido, fila, atendidos, hora_s, "
                "hora_real, uptime_ms, espera_ms, atendimento_ms, media_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev["sessao"], ev["seq"], recebido_em, ev["tipo"], int(ev["valido"]), ev["fila"], ev["atendidos"],
                 ev["hora_s"], int(ev["hora_real"]), ev["uptime_ms"], ev["espera_ms"], ev["atendimento_ms"],
                 ev["media_ms"]))
            self._con.commit()
            return cur.rowcount == 1

    @staticmethod
    def _linha(r):
        d = dict(r)
        d["valido"] = bool(d["valido"])
        d["hora_real"] = bool(d["hora_real"])
        return d

    def ultimo_evento(self):
        with self._lock:
            r = self._con.execute("SELECT * FROM eventos ORDER BY id DESC LIMIT 1").fetchone()
        return self._linha(r) if r else None

    def eventos_recentes(self, limite=20):
        with self._lock:
            rs = self._con.execute("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (int(limite),)).fetchall()
        return [self._linha(r) for r in rs]

    def todos_em_ordem(self):
        with self._lock:
            rs = self._con.execute("SELECT * FROM eventos ORDER BY id ASC").fetchall()
        return [self._linha(r) for r in rs]

    def contagens(self):
        with self._lock:
            r = self._con.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(tipo='CHEGADA'),0) AS chegadas, "
                "COALESCE(SUM(tipo='CONCLUSAO'),0) AS conclusoes, "
                "COALESCE(SUM(valido=0),0) AS rejeitadas FROM eventos").fetchone()
            lac = self._con.execute(
                "SELECT COALESCE(SUM(m - n),0) FROM (SELECT MAX(seq) AS m, COUNT(*) AS n FROM eventos GROUP BY sessao)"
            ).fetchone()[0]
        d = dict(r)
        d["lacunas"] = int(lac)   # eventos numerados pelo ESP32 que não chegaram aqui (seq começa em 1)
        return d

    def fechar(self):
        with self._lock:
            self._con.close()
