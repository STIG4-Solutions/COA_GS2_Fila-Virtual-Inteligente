/* Painel da Fila Virtual — consulta /api/status e /api/eventos a cada 2 s (polling).
   Todo texto vindo do servidor entra por textContent (nunca innerHTML). */
(function () {
  'use strict';

  var INTERVALO_MS = 2000;
  var nf1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
  var NOMES_TIPO = {
    CHEGADA: 'Chegada',
    CONCLUSAO: 'Conclusão',
    REJEITADA_VAZIA: 'Recusada (fila vazia)',
    REJEITADA_CHEIA: 'Recusada (fila cheia)'
  };

  function $(id) { return document.getElementById(id); }

  function fmtEspera(s) {
    if (s === null || s === undefined) return '–';
    if (s <= 0) return 'Sem espera';
    if (s < 60) return 'menos de 1 min';
    return nf1.format(s / 60) + ' min';
  }

  function fmtDuracaoMs(ms) {
    if (!ms) return '–';
    var s = ms / 1000;
    return s >= 60 ? nf1.format(s / 60) + ' min' : nf1.format(s) + ' s';
  }

  function fmtHa(s) {
    if (s === null || s === undefined) return 'nenhum evento ainda';
    if (s < 60) return 'há ' + Math.round(s) + ' s';
    if (s < 3600) return 'há ' + Math.round(s / 60) + ' min';
    return 'há ' + nf1.format(s / 3600) + ' h';
  }

  function fmtHoraEvento(ev) {
    if (ev.hora_real) return new Date(ev.hora_s * 1000).toLocaleTimeString('pt-BR');
    var s = ev.hora_s;
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return 'T+' + p(Math.floor(s / 3600)) + ':' + p(Math.floor(s / 60) % 60) + ':' + p(s % 60);
  }

  function definirTag(el, texto, classe) {
    el.textContent = '';
    var t = document.createElement('span');
    t.className = 'tag ' + classe;
    t.textContent = texto;
    el.appendChild(t);
  }

  function marcarConexao(ok) {
    var el = $('conexao');
    if (ok) {
      el.textContent = 'Atualizando automaticamente';
      el.className = 'pill ok';
    } else {
      el.textContent = 'Sem conexão com o servidor — tentando de novo';
      el.className = 'pill erro';
    }
  }

  function desenharGrafico(eventos) {
    var svg = $('grafico');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var legenda = $('grafico-legenda');
    var pontos = eventos.slice().reverse().map(function (e) { return e.fila; });   // do mais antigo ao mais novo
    if (pontos.length < 2) {
      legenda.textContent = 'Aguardando eventos…';
      return;
    }
    var ns = 'http://www.w3.org/2000/svg';
    var L = 320, A = 110, mx = 26, mt = 10, mb = 14;
    var maximo = Math.max(1, Math.max.apply(null, pontos));
    var x = function (i) { return mx + (i * (L - mx - 8)) / (pontos.length - 1); };
    var y = function (v) { return A - mb - (v * (A - mb - mt)) / maximo; };

    var eixo = document.createElementNS(ns, 'line');
    eixo.setAttribute('class', 'eixo');
    eixo.setAttribute('x1', mx); eixo.setAttribute('x2', L - 8);
    eixo.setAttribute('y1', y(0)); eixo.setAttribute('y2', y(0));
    svg.appendChild(eixo);

    [0, maximo].forEach(function (v) {
      var t = document.createElementNS(ns, 'text');
      t.setAttribute('x', 2); t.setAttribute('y', y(v) + 3);
      t.textContent = String(v);
      svg.appendChild(t);
    });

    var linha = document.createElementNS(ns, 'polyline');
    linha.setAttribute('class', 'linha');
    linha.setAttribute('points', pontos.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join(' '));
    svg.appendChild(linha);

    var ult = document.createElementNS(ns, 'circle');
    ult.setAttribute('class', 'ponto');
    ult.setAttribute('cx', x(pontos.length - 1)); ult.setAttribute('cy', y(pontos[pontos.length - 1])); ult.setAttribute('r', 4);
    svg.appendChild(ult);

    legenda.textContent = 'Últimos ' + pontos.length + ' eventos · fila atual: ' + pontos[pontos.length - 1];
  }

  function desenharTabela(eventos) {
    var corpo = $('eventos');
    corpo.textContent = '';
    if (!eventos.length) {
      var tr0 = document.createElement('tr');
      var td0 = document.createElement('td');
      td0.colSpan = 6;
      td0.textContent = 'Nenhum evento recebido ainda.';
      tr0.appendChild(td0);
      corpo.appendChild(tr0);
      return;
    }
    eventos.forEach(function (e) {
      var tr = document.createElement('tr');
      var celulas = [
        fmtHoraEvento(e),
        NOMES_TIPO[e.tipo] || e.tipo,
        String(e.fila),
        String(e.atendidos),
        e.tipo === 'CONCLUSAO' ? fmtDuracaoMs(e.espera_ms) : '–',
        e.tipo === 'CONCLUSAO' ? fmtDuracaoMs(e.atendimento_ms) : '–'
      ];
      celulas.forEach(function (c, i) {
        var td = document.createElement('td');
        if (i === 1) {
          var tag = document.createElement('span');
          tag.className = 'tag ' + (e.valido ? 'ok' : 'erro');
          tag.textContent = c;
          td.appendChild(tag);
        } else {
          td.textContent = c;
        }
        tr.appendChild(td);
      });
      corpo.appendChild(tr);
    });
  }

  function render(status, eventos) {
    var est = status.espera_estimada;
    $('fila').textContent = String(status.fila);
    $('espera-ia').textContent = fmtEspera(est.ia_s);
    $('espera-conv').textContent = fmtEspera(est.convencional_s);
    $('aviso-fallback').hidden = !est.ia_usou_fallback;
    $('atendidos').textContent = String(status.atendidos);
    $('rejeitadas').textContent = String(status.rejeitadas);
    $('media-atendimento').textContent = 'média recente: ' +
      (est.media_atendimento_s === null ? '–' : fmtDuracaoMs(est.media_atendimento_s * 1000));

    var d = status.dispositivo;
    if (d.status === 'online') definirTag($('disp-status'), '● online', 'ok');
    else if (d.status === 'offline') definirTag($('disp-status'), '○ offline', 'erro');
    else definirTag($('disp-status'), '? sem informação', 'neutro');
    $('disp-ultimo').textContent = fmtHa(d.ultimo_evento_ha_s);
    if (status.mqtt_conectado) definirTag($('mqtt-status'), '● conectado', 'ok');
    else definirTag($('mqtt-status'), '○ desconectado', 'alerta');
    $('ev-total').textContent = String(status.eventos_total);
    $('ev-perdidos').textContent = String(status.eventos_perdidos);
    $('msg-invalidas').textContent = String(status.mensagens_invalidas);
    $('modelo').textContent = (status.origem_do_modelo || []).indexOf('SIMULADO') >= 0
      ? 'treinado com dados SIMULADOS' : 'treinado com ' + (status.origem_do_modelo || []).join(', ');

    desenharTabela(eventos);
    desenharGrafico(eventos);
  }

  function atualizar() {
    return Promise.all([
      fetch('/api/status', { cache: 'no-store' }),
      fetch('/api/eventos?limite=15', { cache: 'no-store' })
    ]).then(function (rs) {
      if (!rs[0].ok || !rs[1].ok) throw new Error('HTTP ' + rs[0].status + '/' + rs[1].status);
      return Promise.all([rs[0].json(), rs[1].json()]);
    }).then(function (dados) {
      render(dados[0], dados[1]);
      marcarConexao(true);
    }).catch(function () {
      marcarConexao(false);
    });
  }

  function iniciar() {
    (function ciclo() {
      atualizar().then(function () { setTimeout(ciclo, INTERVALO_MS); });
    })();
  }

  window.FilaPainel = { atualizar: atualizar, render: render, fmtEspera: fmtEspera, fmtDuracaoMs: fmtDuracaoMs, fmtHa: fmtHa };
  if (!window.__PAINEL_SEM_AUTOSTART__) iniciar();
})();
