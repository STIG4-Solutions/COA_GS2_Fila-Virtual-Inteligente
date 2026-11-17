// Teste do painel (static/app.js) com um navegador simulado (jsdom). Opcional.
//   cd backend/tests && npm install jsdom && cd .. && node tests/painel.test.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { JSDOM } = require('jsdom');

const estatico = path.join(__dirname, '..', 'static');
const html = fs.readFileSync(path.join(estatico, 'index.html'), 'utf8').replace(/<script[^>]*><\/script>/g, '');
const appJs = fs.readFileSync(path.join(estatico, 'app.js'), 'utf8');

function novoPainel(respostas) {
  const dom = new JSDOM(html, { runScripts: 'outside-only' });
  const w = dom.window;
  w.__PAINEL_SEM_AUTOSTART__ = true;
  w.fetch = (url) => respostas(url);
  w.eval(appJs);
  return w;
}
const ok = (corpo) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(corpo) });

const status = (extra = {}) => Object.assign({
  fila: 3, atendidos: 12, rejeitadas: 2,
  espera_estimada: { pessoas_a_frente: 3, ia_s: 540, convencional_s: 683.4, ia_usou_fallback: false, media_atendimento_s: 215, media_historica_s: 227.8 },
  dispositivo: { status: 'online', ultimo_evento_ha_s: 12.4 },
  mqtt_conectado: true, eventos_total: 30, eventos_perdidos: 1, mensagens_invalidas: 0, origem_do_modelo: ['SIMULADO'],
}, extra);
const ev = (seq, tipo, fila, extra = {}) => Object.assign({
  sessao: 'a1b2c3d4', seq, tipo, valido: tipo === 'CHEGADA' || tipo === 'CONCLUSAO', fila, atendidos: 12,
  hora_s: 1794361680 + seq, hora_real: true, uptime_ms: 1000 * seq, espera_ms: 0, atendimento_ms: 0, media_ms: 0,
}, extra);
const rotas = (st, evs) => (url) => ok(url.startsWith('/api/status') ? st : evs);
const texto = (w, id) => w.document.getElementById(id).textContent;

(async () => {
  // 1) renderização normal
  let w = novoPainel(rotas(status(), [ev(5, 'CONCLUSAO', 3, { espera_ms: 65000, atendimento_ms: 215000 }), ev(4, 'CHEGADA', 4), ev(3, 'CHEGADA', 3), ev(2, 'REJEITADA_VAZIA', 0)]));
  await w.FilaPainel.atualizar();
  assert.strictEqual(texto(w, 'fila'), '3');
  assert.strictEqual(texto(w, 'espera-ia'), '9 min');
  assert.strictEqual(texto(w, 'espera-conv'), '11,4 min');
  assert.strictEqual(texto(w, 'atendidos'), '12');
  assert.strictEqual(texto(w, 'rejeitadas'), '2');
  assert.ok(texto(w, 'disp-status').includes('online'));
  assert.ok(texto(w, 'mqtt-status').includes('conectado'));
  assert.ok(texto(w, 'modelo').includes('SIMULADOS'));
  assert.strictEqual(texto(w, 'media-atendimento'), 'média recente: 3,6 min');
  assert.strictEqual(w.document.querySelectorAll('#eventos tr').length, 4);
  assert.ok(w.document.querySelector('#eventos tr td').textContent.length > 0);
  assert.ok(texto(w, 'eventos').includes('Recusada (fila vazia)'));
  assert.ok(texto(w, 'eventos').includes('1,1 min'));                    // espera da conclusão: 65 s
  assert.ok(w.document.querySelector('#grafico polyline'), 'gráfico desenhado');
  assert.strictEqual(w.document.getElementById('aviso-fallback').hidden, true);
  assert.ok(w.document.getElementById('conexao').className.includes('ok'));

  // 2) sem média recente: aviso de fallback
  w = novoPainel(rotas(status({ espera_estimada: { pessoas_a_frente: 3, ia_s: 683.4, convencional_s: 683.4, ia_usou_fallback: true, media_atendimento_s: null, media_historica_s: 227.8 } }), []));
  await w.FilaPainel.atualizar();
  assert.strictEqual(w.document.getElementById('aviso-fallback').hidden, false);
  assert.strictEqual(texto(w, 'media-atendimento'), 'média recente: –');
  assert.ok(texto(w, 'eventos').includes('Nenhum evento'));

  // 3) fila vazia e dispositivo offline
  w = novoPainel(rotas(status({ fila: 0, dispositivo: { status: 'offline', ultimo_evento_ha_s: 4000 }, mqtt_conectado: false,
    espera_estimada: { pessoas_a_frente: 0, ia_s: 0, convencional_s: 0, ia_usou_fallback: false, media_atendimento_s: 215, media_historica_s: 227.8 } }), []));
  await w.FilaPainel.atualizar();
  assert.strictEqual(texto(w, 'espera-ia'), 'Sem espera');
  assert.ok(texto(w, 'disp-status').includes('offline'));
  assert.ok(texto(w, 'mqtt-status').includes('desconectado'));
  assert.strictEqual(texto(w, 'disp-ultimo'), 'há 1,1 h');

  // 4) dados hostis entram como TEXTO, nunca como HTML
  w = novoPainel(rotas(status(), [ev(1, '<img src=x onerror=alert(1)>', 1, { valido: false })]));
  await w.FilaPainel.atualizar();
  assert.strictEqual(w.document.querySelectorAll('#eventos img').length, 0);
  assert.ok(texto(w, 'eventos').includes('<img'));

  // 5) falha de rede mostra aviso e recupera sozinho
  let falha = true;
  w = novoPainel((url) => falha ? Promise.reject(new Error('rede')) : ok(url.startsWith('/api/status') ? status() : []));
  await w.FilaPainel.atualizar();
  assert.ok(w.document.getElementById('conexao').className.includes('erro'));
  assert.ok(texto(w, 'conexao').includes('Sem conexão'));
  falha = false;
  await w.FilaPainel.atualizar();
  assert.ok(w.document.getElementById('conexao').className.includes('ok'));
  assert.strictEqual(texto(w, 'fila'), '3');

  // 6) resposta HTTP com erro também conta como falha
  w = novoPainel(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }));
  await w.FilaPainel.atualizar();
  assert.ok(w.document.getElementById('conexao').className.includes('erro'));

  // 7) formatadores
  const f = w.FilaPainel;
  assert.strictEqual(f.fmtEspera(0), 'Sem espera');
  assert.strictEqual(f.fmtEspera(30), 'menos de 1 min');
  assert.strictEqual(f.fmtEspera(150), '2,5 min');
  assert.strictEqual(f.fmtEspera(null), '–');
  assert.strictEqual(f.fmtDuracaoMs(4200), '4,2 s');
  assert.strictEqual(f.fmtDuracaoMs(0), '–');
  assert.strictEqual(f.fmtHa(5), 'há 5 s');
  assert.strictEqual(f.fmtHa(null), 'nenhum evento ainda');

  console.log('painel: todos os testes passaram');
})().catch((e) => { console.error('FALHOU:', e.message); process.exit(1); });
