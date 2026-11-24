/* viaje.js — "Planear viaje" dentro del explorador.
   Lee window.APP (mapa, datos, utilidades) que expone index.html.
   Calcula en el navegador y se verifica al arrancar contra los casos de control de Python. */
(() => {
  const G = 9.81, RHO_AIRE = 0.95;
  const COLOR_CORTA = '#ffb347', COLOR_EFIC = '#4ff0d0';
  const reducir = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function iniciar({ mapa, D }) {
    const V = D.viaje;
    if (!V) return;
    const T = D.tramos, N = D.nodos.length, M = T.length;

    // ---------- física (idéntica a consumo_sintetico.py) ----------
    const S = Float64Array.from(T, t => (t.s ?? 0) / 100);
    const L = Float64Array.from(T, t => t.L);
    const U = Int32Array.from(T, t => t.u), W = Int32Array.from(T, t => t.v);
    function energiaTramo(c, l, s, kmh) {
      const v = kmh / 3.6, th = Math.atan(s);
      const f = c.masa_kg * G * c.crr * Math.cos(th) + c.masa_kg * G * Math.sin(th) + 0.5 * RHO_AIRE * c.cd_a_m2 * v * v;
      const w = f * l;
      return (w >= 0 ? w / c.eficiencia_motor : w * c.eficiencia_regen) / 3.6e6;
    }
    const energias = V.carros.map(c => Float64Array.from(S, (s, i) => energiaTramo(c, L[i], s, V.velocidad_kmh)));

    // ---------- red en formato compacto (aristas que salen de cada esquina) ----------
    const inicio = new Int32Array(N + 1);
    U.forEach(u => inicio[u + 1]++);
    for (let i = 0; i < N; i++) inicio[i + 1] += inicio[i];
    const orden = new Int32Array(M), pos = inicio.slice(0, N);
    U.forEach((u, e) => { orden[pos[u]++] = e; });

    // Dijkstra con montículo (pesos no negativos: distancia)
    function dijkstra(o, peso) {
      const dist = new Float64Array(N).fill(Infinity), padre = new Int32Array(N).fill(-1), visto = new Uint8Array(N);
      const h = [[0, o]]; dist[o] = 0;
      const sube = i => { while (i > 0) { const p = (i - 1) >> 1; if (h[p][0] <= h[i][0]) break; [h[p], h[i]] = [h[i], h[p]]; i = p; } };
      const baja = i => { for (;;) { const a = 2 * i + 1, b = a + 1; let m = i;
        if (a < h.length && h[a][0] < h[m][0]) m = a; if (b < h.length && h[b][0] < h[m][0]) m = b;
        if (m === i) break; [h[m], h[i]] = [h[i], h[m]]; i = m; } };
      while (h.length) {
        const [d, u] = h[0]; const ult = h.pop(); if (h.length) { h[0] = ult; baja(0); }
        if (visto[u]) continue; visto[u] = 1;
        for (let k = inicio[u]; k < inicio[u + 1]; k++) {
          const e = orden[k], v = W[e], nd = d + peso[e];
          if (nd < dist[v]) { dist[v] = nd; padre[v] = e; h.push([nd, v]); sube(h.length - 1); }
        }
      }
      return { dist, padre };
    }
    // Bellman-Ford con cola (SPFA): admite energía negativa por regeneración
    function bellmanFord(o, peso) {
      const dist = new Float64Array(N).fill(Infinity), padre = new Int32Array(N).fill(-1);
      const enCola = new Uint8Array(N), veces = new Int32Array(N), cola = new Int32Array(N + 1);
      let ini = 0, fin = 0; dist[o] = 0; cola[fin++] = o; enCola[o] = 1;
      while (ini !== fin) {
        const u = cola[ini]; ini = (ini + 1) % (N + 1); enCola[u] = 0;
        for (let k = inicio[u]; k < inicio[u + 1]; k++) {
          const e = orden[k], v = W[e], nd = dist[u] + peso[e];
          if (nd < dist[v] - 1e-15) {
            dist[v] = nd; padre[v] = e;
            if (!enCola[v]) { if (++veces[v] > N) return null; cola[fin] = v; fin = (fin + 1) % (N + 1); enCola[v] = 1; }
          }
        }
      }
      return { dist, padre };
    }
    const camino = (padre, o, d) => { const r = []; let v = d; while (v !== o) { const e = padre[v]; if (e < 0) return null; r.push(e); v = U[e]; } return r.reverse(); };
    // ---------- recarga: grafo inverso y planificador (idéntico a planificador.py) ----------
    const inicioR = new Int32Array(N + 1);
    W.forEach(w => inicioR[w + 1]++);
    for (let i = 0; i < N; i++) inicioR[i + 1] += inicioR[i];
    const ordenR = new Int32Array(M), posR = inicioR.slice(0, N);
    W.forEach((w, e) => { ordenR[posR[w]++] = e; });
    // Bellman-Ford hacia el destino: dist[x] = menor energía de x hasta d
    function bellmanFordHacia(d, peso) {
      const dist = new Float64Array(N).fill(Infinity), padre = new Int32Array(N).fill(-1);
      const enCola = new Uint8Array(N), veces = new Int32Array(N), cola = new Int32Array(N + 1);
      let ini = 0, fin = 0; dist[d] = 0; cola[fin++] = d; enCola[d] = 1;
      while (ini !== fin) {
        const u = cola[ini]; ini = (ini + 1) % (N + 1); enCola[u] = 0;
        for (let k = inicioR[u]; k < inicioR[u + 1]; k++) {
          const e = ordenR[k], x = U[e], nd = dist[u] + peso[e];
          if (nd < dist[x] - 1e-15) {
            dist[x] = nd; padre[x] = e;
            if (!enCola[x]) { if (++veces[x] > N) return null; cola[fin] = x; fin = (fin + 1) % (N + 1); enCola[x] = 1; }
          }
        }
      }
      return { dist, padre };
    }
    const caminoHacia = (padre, o, d) => { const r = []; let v = o; while (v !== d) { const e = padre[v]; if (e < 0) return null; r.push(e); v = W[e]; } return r; };
    const resumen = (ruta, E) => { let a = 0, l = 0, p = 0; ruta.forEach(e => { a += E[e]; l += L[e]; p = Math.max(p, a); }); return { E: a, L: l, pico: p }; };

    const R = V.reglas || null;
    function planear(ci, o, d, soc, espera) {
      const c = V.carros[ci], E = energias[ci], cap = c.bateria_kwh, e0 = soc * cap, res = R.RESERVA_SOC * cap;
      const ida = bellmanFord(o, E), vuelta = bellmanFordHacia(d, E);
      if (!ida || !vuelta) return { error: true };
      const directa = resumen(camino(ida.padre, o, d), E);
      if (e0 - directa.pico >= res - 1e-12) return { parada: null, directa };
      let mejor = null;
      D.estaciones.forEach((s, k) => {
        if (s.kw == null || s.kw <= 0 || s.acc === 'PRIVADO' || s.nodo == null) return;
        if (!(s.con || []).some(t => c.conectores.includes(t.t))) return;
        const n = s.nodo;
        if (!isFinite(ida.dist[n]) || !isFinite(vuelta.dist[n])) return;
        const r1 = camino(ida.padre, o, n), r2 = caminoHacia(vuelta.padre, n, d);
        if (!r1 || !r2) return;
        const a = resumen(r1, E), b = resumen(r2, E);
        if (e0 - a.pico < res - 1e-12) return;
        const llegada = e0 - a.E, objetivo = res + Math.max(0, b.pico) + R.MARGEN_SOC * cap;
        if (objetivo > R.SOC_MAX_CARGA * cap + 1e-12) return;
        const carga = Math.max(0, objetivo - llegada);
        const dc = s.dc === true || s.kw > R.UMBRAL_DC_KW;
        const potencia = Math.min(s.kw, dc ? c.carga_dc_kw : c.carga_ac_kw);
        const tCarga = carga === 0 ? 0 : carga / (potencia * R.EFICIENCIA_CARGA) * 60;
        const tManejo = (a.L + b.L) / 1000 / V.velocidad_kmh * 60;
        const total = tManejo + tCarga + espera;
        if (!mejor || total < mejor.total_min - 1e-9)
          mejor = { estacion: k, total_min: total, carga_kwh: carga, t_carga_min: tCarga, t_manejo_min: tManejo,
                    potencia_kw: potencia, dc, r1, r2, llegada, objetivo, e0, cap };
      });
      return { parada: mejor, directa, imposible: !mejor };
    }

    // ---------- verificación contra Python ----------
    const idxCarro = Object.fromEntries(V.carros.map((c, i) => [c.nombre, i]));
    let fallas = 0, revisados = 0;
    V.control_tramos.forEach(ct => ct.idx.forEach((e, k) => {
      revisados++; if (Math.abs(energias[idxCarro[ct.carro]][e] - ct.kwh[k]) > 1e-12 + 1e-9 * Math.abs(ct.kwh[k])) fallas++;
    }));
    V.control_rutas.forEach(cr => {
      revisados++;
      const c = idxCarro[cr.carro];
      const dd = dijkstra(cr.origen, L).dist[cr.destino];
      const bf = bellmanFord(cr.origen, energias[c]);
      if (!bf || Math.abs(dd - cr.metros) > 1e-6 || Math.abs(bf.dist[cr.destino] - cr.kwh) > 1e-7) fallas++;
    });
    (V.control_recarga || []).forEach(cr => {
      revisados++;
      const r = planear(idxCarro[cr.carro], cr.origen, cr.destino, cr.soc, cr.espera);
      const k = r.parada ? r.parada.estacion : null;
      if (k !== cr.estacion) { fallas++; return; }
      if (k !== null && (Math.abs(r.parada.total_min - cr.total_min) > 1e-6 || Math.abs(r.parada.carga_kwh - cr.carga_kwh) > 1e-9)) fallas++;
    });
    const verificado = fallas === 0;

    // ---------- interfaz: pestañas dentro del panel ----------
    const estilo = document.createElement('style');
    estilo.textContent = `
      .pestanas { display: flex; gap: 4px; background: rgba(233,238,243,.06); border-radius: 12px; padding: 4px; margin: 4px 0 16px; }
      .pestanas button { flex: 1; font: inherit; font-size: .9rem; border: 0; border-radius: 9px; padding: 8px 0; cursor: pointer;
                         background: transparent; color: var(--tenue); transition: background .2s, color .2s; }
      .pestanas button[aria-selected="true"] { background: rgba(233,238,243,.12); color: var(--texto); }
      .pestanas button:focus-visible, .carro:focus-visible, .v-boton:focus-visible { outline: 2px solid var(--cian); outline-offset: 2px; }
      .carros { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
      .carro { font: inherit; text-align: left; cursor: pointer; border: 1px solid var(--borde); background: rgba(233,238,243,.03);
               color: var(--texto); border-radius: 12px; padding: 10px 9px 9px; transition: border-color .2s, background .2s; }
      .carro[aria-pressed="true"] { border-color: var(--cian); background: rgba(111,227,240,.08); }
      .carro svg { width: 100%; height: 22px; display: block; margin-bottom: 6px; }
      .carro b { display: block; font-size: .82rem; font-weight: 600; line-height: 1.15; }
      .carro span { display: block; color: var(--tenue); font-size: .74rem; margin-top: 3px; }
      .v-estado { margin: 14px 0 0; font-size: .92rem; color: #c3cfda; display: flex; gap: 10px; align-items: center; }
      .v-estado i { width: 9px; height: 9px; border-radius: 50%; background: var(--cian); box-shadow: 0 0 10px var(--cian); flex: none;
                    animation: latido 1.4s ease-in-out infinite; }
      @keyframes latido { 50% { opacity: .3; } }
      .v-res { margin-top: 14px; display: none; }
      .v-res.on { display: block; }
      .v-fila { display: grid; grid-template-columns: 12px 1fr auto auto; gap: 8px; align-items: center; font-size: .88rem; padding: 5px 0; }
      .v-fila .raya { height: 3px; border-radius: 2px; }
      .v-fila .num { color: #c3cfda; font-variant-numeric: tabular-nums; text-align: right; }
      .v-ahorro { display: flex; align-items: baseline; gap: 10px; margin: 10px 0 4px; }
      .v-ahorro b { font-family: 'Fraunces', Georgia, serif; font-size: 2.3rem; line-height: 1; color: var(--cian); white-space: nowrap; }
      .v-ahorro span { color: var(--tenue); font-size: .85rem; line-height: 1.3; }
      .bateria { margin-top: 12px; }
      .bateria .caja { height: 16px; background: rgba(233,238,243,.05); border-radius: 5px; border: 1px solid var(--borde); position: relative; overflow: hidden; }
      .bateria .nivel { position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg, #1f9e8a, #4ff0d0); width: 100%; }
      .bateria .et { display: flex; justify-content: space-between; font-size: .78rem; color: var(--tenue); margin-top: 5px; }
      .perfil { width: 100%; height: 70px; margin-top: 12px; display: block; }
      .comparar { margin-top: 12px; }
      .comparar .c { display: grid; grid-template-columns: 76px 1fr 52px; gap: 8px; align-items: center; font-size: .78rem; color: var(--tenue); padding: 3px 0; }
      .comparar .barra { height: 6px; border-radius: 3px; background: rgba(233,238,243,.08); position: relative; }
      .comparar .barra div { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: var(--cian); }
      .comparar .c.sel { color: var(--texto); }
      .v-pie { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; gap: 8px; }
      .v-boton { font: inherit; font-size: .85rem; color: var(--texto); background: transparent; border: 1px solid var(--borde);
                 border-radius: 10px; padding: 8px 12px; cursor: pointer; }
      .sello { font-size: .74rem; color: ${verificado ? '#7fe0b4' : '#ff8fa8'}; }
      .v-sint { margin-top: 12px; font-size: .76rem; color: #ffc2d7; background: rgba(255,47,122,.1);
                border: 1px solid rgba(255,47,122,.35); border-radius: 8px; padding: 6px 9px; line-height: 1.35; }
      .v-titulo { font-size: .8rem; color: var(--tenue); margin: 14px 0 2px; }
      .v-soc { margin-top: 14px; }
      .v-soc .fila { display: flex; justify-content: space-between; font-size: .88rem; }
      .v-soc b { font-variant-numeric: tabular-nums; }
      .v-soc input[type=range] { width: 100%; accent-color: #4ff0d0; margin: 6px 0 2px; }
      .v-soc .sub2 { display: flex; justify-content: space-between; align-items: center; font-size: .76rem; color: var(--tenue); }
      .v-soc select { font: inherit; font-size: .76rem; background: #13233a; color: var(--texto); border: 1px solid var(--borde); border-radius: 6px; padding: 2px 4px; }
      .v-recarga { margin-top: 14px; display: none; }
      .v-recarga.on { display: block; }
      .v-recarga h4 { margin: 0 0 4px; font-size: .95rem; font-weight: 600; }
      .v-recarga .quien { color: var(--tenue); font-size: .82rem; margin-bottom: 10px; }
      .v-linea { display: flex; height: 22px; border-radius: 6px; overflow: hidden; font-size: .7rem; }
      .v-linea div { display: flex; align-items: center; justify-content: center; white-space: nowrap; overflow: hidden; color: #06121c; font-weight: 600; min-width: 4px; }
      .linea-et { display: flex; justify-content: space-between; font-size: .76rem; color: var(--tenue); margin-top: 5px; }
      .reloj { font-family: 'Fraunces', Georgia, serif; font-size: 1.6rem; color: #ffe08a; line-height: 1; margin: 10px 0 2px; font-variant-numeric: tabular-nums; }
      .v-aviso { font-size: .82rem; color: #ff9f7a; margin-top: 10px; line-height: 1.4; }
      .bateria .nivel.baja { background: linear-gradient(90deg, #ff4d3d, #ff9a8a); }
      .bateria .et { gap: 10px; }
    `;
    document.head.appendChild(estilo);

    const mando = document.querySelector('.mando');
    const titulo = mando.querySelector('h2');
    const panelExplorar = document.createElement('div');
    [...mando.children].filter(n => n !== titulo).forEach(n => panelExplorar.appendChild(n));
    const pest = document.createElement('div');
    pest.className = 'pestanas'; pest.setAttribute('role', 'tablist');
    pest.innerHTML = '<button role="tab" aria-selected="true" data-p="explorar">Explorar</button><button role="tab" aria-selected="false" data-p="viaje">Planear viaje</button>';
    const panelViaje = document.createElement('div');
    panelViaje.hidden = true;

    const silueta = (masa) => {
      const k = (masa - 900) / 900;                     // más pesado, más alto y largo
      const largo = 70 + 22 * k, alto = 9 + 5 * k, x0 = (100 - largo) / 2;
      return `<svg viewBox="0 0 100 24" aria-hidden="true"><path d="M${x0} 18 q0 -${alto * .45} 8 -${alto * .55} l10 -${alto * .45} h${largo * .42} l12 ${alto * .45} q${largo * .12} 2 ${largo * .12} ${alto * .55} z"
        fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><circle cx="${x0 + largo * .22}" cy="19" r="3.2" fill="currentColor"/><circle cx="${x0 + largo * .78}" cy="19" r="3.2" fill="currentColor"/></svg>`;
    };
    panelViaje.innerHTML = `
      <div class="carros" role="group" aria-label="Elige un carro">
        ${V.carros.map((c, i) => `<button class="carro" data-i="${i}" aria-pressed="${i === 1}">${silueta(c.masa_kg)}
          <b>${c.nombre.replace(/\s*\(.*\)/, '')}</b><span>${c.bateria_kwh} kWh · ${c.masa_kg.toLocaleString('es-CO')} kg</span></button>`).join('')}
      </div>
      ${R ? `<div class="v-soc">
        <div class="fila"><span>Batería al salir</span><b id="v-soc-txt">100 %</b></div>
        <input type="range" id="v-soc" min="1" max="100" step="0.5" value="100" aria-label="Batería al salir">
        <div class="sub2"><span>Reserva ${Math.round(R.RESERVA_SOC * 100)} %</span>
          <label>Espera supuesta <select id="v-espera"><option value="0">0 min</option><option value="10">10 min</option><option value="20">20 min</option></select></label></div>
      </div>` : ''}
      <div class="v-estado" id="v-estado"><i></i><span>Toca la esquina de salida en el mapa</span></div>
      <div class="v-recarga" id="v-recarga"></div>
      <div class="v-res" id="v-res">
        <div class="v-ahorro"><b id="v-ahorro">0 %</b><span>menos batería tomando la ruta eficiente</span></div>
        <div class="v-fila"><span class="raya" style="background:${COLOR_CORTA}"></span><span>Más corta</span><span class="num" id="v-c-km"></span><span class="num" id="v-c-wh"></span></div>
        <div class="v-fila"><span class="raya" style="background:${COLOR_EFIC}"></span><span>Menor consumo</span><span class="num" id="v-e-km"></span><span class="num" id="v-e-wh"></span></div>
        <div class="bateria"><div class="caja"><div class="nivel" id="v-nivel"></div></div>
          <div class="et"><span id="v-bat-txt">Batería 100 %</span><span id="v-bat-regen"></span></div></div>
        <svg class="perfil" id="v-perfil" viewBox="0 0 300 70" preserveAspectRatio="none" aria-label="Perfil de altura"></svg>
        <div class="v-titulo">El mismo viaje con cada carro (ruta eficiente)</div>
        <div class="comparar" id="v-comparar"></div>
      </div>
      <div class="v-pie"><button class="v-boton" id="v-nuevo">Nuevo viaje</button>
        <span class="sello" title="${revisados} comparaciones con los cálculos de Python">${verificado ? '✓ Verificado contra Python' : '✗ No coincide con Python'}</span></div>
      ${V.sintetico ? '<div class="v-sint">Carros y consumo de prueba. Calles, pendientes y rutas por distancia son reales.</div>' : ''}`;
    mando.append(pest, panelExplorar, panelViaje);
    mando.insertBefore(pest, panelExplorar);

    const $ = id => document.getElementById(id);
    let carroSel = 1, origen = null, destino = null, animacion = null, socSalida = 1;
    const API = window.VIAJE = { activo: false, clic };

    pest.addEventListener('click', ev => {
      const b = ev.target.closest('button'); if (!b) return;
      [...pest.children].forEach(x => x.setAttribute('aria-selected', x === b));
      const viaje = b.dataset.p === 'viaje';
      panelExplorar.hidden = viaje; panelViaje.hidden = !viaje; API.activo = viaje;
      if (!viaje) limpiar();
    });
    panelViaje.querySelector('.carros').addEventListener('click', ev => {
      const b = ev.target.closest('.carro'); if (!b) return;
      carroSel = +b.dataset.i;
      panelViaje.querySelectorAll('.carro').forEach(x => x.setAttribute('aria-pressed', x === b));
      if (origen !== null && destino !== null) calcular();
    });
    $('v-nuevo').onclick = limpiar;
    if (R) {
      const actualizarSoc = () => { $('v-soc-txt').textContent = `${String(+$('v-soc').value).replace('.', ',')} %`; };
      $('v-soc').addEventListener('input', actualizarSoc);
      $('v-soc').addEventListener('change', () => { if (origen !== null && destino !== null) calcular(); });
      $('v-espera').addEventListener('change', () => { if (origen !== null && destino !== null) calcular(); });
    }

    // ---------- capas del viaje ----------
    const vacio = { type: 'FeatureCollection', features: [] };
    mapa.addSource('v-onda', { type: 'geojson', data: vacio });
    mapa.addSource('v-corta', { type: 'geojson', data: vacio, lineMetrics: true });
    mapa.addSource('v-efic', { type: 'geojson', data: vacio, lineMetrics: true });
    mapa.addSource('v-puntos', { type: 'geojson', data: vacio });
    mapa.addSource('v-carros', { type: 'geojson', data: vacio });
    mapa.addLayer({ id: 'v-onda', type: 'circle', source: 'v-onda',
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 2.2, 17, 7], 'circle-blur': .6,
               'circle-color': ['get', 'color'], 'circle-opacity': 0 } });
    const capaRuta = (id, color) => {
      mapa.addLayer({ id: id + '-halo', type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 8, 17, 22], 'line-blur': 8, 'line-opacity': 0 } });
      mapa.addLayer({ id, type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 3.5, 15, 6, 18, 12], 'line-gradient': color } });
    };
    capaRuta('v-corta', COLOR_CORTA); capaRuta('v-efic', COLOR_EFIC);
    mapa.addLayer({ id: 'v-carros-halo', type: 'circle', source: 'v-carros',
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 14, 17, 24], 'circle-color': ['get', 'color'],
               'circle-blur': .8, 'circle-opacity': .55 } });
    mapa.addLayer({ id: 'v-carros', type: 'circle', source: 'v-carros',
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 7, 17, 11], 'circle-color': '#ffffff',
               'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': 3.5 } });
    mapa.addSource('v-parada', { type: 'geojson', data: vacio });
    mapa.addLayer({ id: 'v-parada-halo', type: 'circle', source: 'v-parada',
      paint: { 'circle-radius': 22, 'circle-color': '#ffe08a', 'circle-blur': .9, 'circle-opacity': 0 } });
    mapa.addLayer({ id: 'v-parada', type: 'circle', source: 'v-parada',
      paint: { 'circle-radius': 11, 'circle-color': '#ffe08a', 'circle-stroke-color': '#0d1826', 'circle-stroke-width': 3 } });
    mapa.addLayer({ id: 'v-puntos', type: 'circle', source: 'v-puntos',
      paint: { 'circle-radius': 9, 'circle-color': '#0d1826', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 } });
    mapa.moveLayer('v-carros-halo'); mapa.moveLayer('v-carros');   // la bolita siempre encima de todo

        // Bolitas del recorrido como marcadores HTML: se mueven al instante, sin esperar
    // a que el mapa procese datos. Así nunca se desincronizan del reloj y la batería.
    const bolitas = [0, 1].map(() => {
      const el = document.createElement('div');
      el.style.cssText = 'width:16px;height:16px;border-radius:50%;background:#fff;border:3.5px solid #4ff0d0;' +
                         'box-shadow:0 0 14px 4px rgba(79,240,208,.55);pointer-events:none;display:none;';
      return { el, m: new maplibregl.Marker({ element: el }).setLngLat([0, 0]).addTo(mapa) };
    });
    function mover(i, p, color) {
      const b = bolitas[i];
      b.m.setLngLat(p);
      b.el.style.display = 'block';
      b.el.style.borderColor = color;
      b.el.style.boxShadow = `0 0 14px 4px ${color}8c`;
    }
    const ocultarCarros = () => bolitas.forEach(b => { b.el.style.display = 'none'; });
    const puntosGJ = () => ({ type: 'FeatureCollection', features: [origen, destino].filter(x => x !== null)
      .map(n => ({ type: 'Feature', geometry: { type: 'Point', coordinates: D.nodos[n].p } })) });

    // Esquina más cercana al clic. Para la llegada solo se aceptan esquinas alcanzables desde
    // la salida respetando los sentidos de circulación, así nunca queda un viaje imposible.
    let alcance = null;
    function esquinaCercana(e, valida = () => true) {
      let mejor = -1, md = Infinity;
      D.nodos.forEach((n, i) => { if (!valida(i)) return;
        const p = mapa.project(n.p), d = (p.x - e.point.x) ** 2 + (p.y - e.point.y) ** 2; if (d < md) { md = d; mejor = i; } });
      return md < 60 * 60 ? mejor : null;
    }

    function clic(e) {
      if (origen === null || destino !== null) {
        const n = esquinaCercana(e, i => inicio[i + 1] > inicio[i]); if (n === null) return;
        limpiar(); origen = n; alcance = dijkstra(origen, L).dist;
        estado('Ahora toca la esquina de llegada');
      } else {
        const n = esquinaCercana(e, i => i !== origen && isFinite(alcance[i]));
        if (n === null) { estado('Esa zona no se alcanza desde la salida. Toca otra esquina.'); return; }
        destino = n; calcular();
      }
      mapa.getSource('v-puntos').setData(puntosGJ());
    }
    function estado(txt, pulso = true) {
      $('v-estado').innerHTML = `${pulso ? '<i></i>' : ''}<span>${txt}</span>`;
    }
    function atenuarFondo(on) {
      if (!on) { if (window.APP.aplicarCapas) window.APP.aplicarCapas(); return; }
      const set = (c, p, v) => { if (mapa.getLayer(c)) { mapa.setPaintProperty(c, p + '-transition', { duration: 600 }); mapa.setPaintProperty(c, p, v); } };
      set('calles', 'line-opacity', 0.3); set('calles-brillo', 'line-opacity', 0.08);
      set('aristas', 'line-opacity', 0.12); set('nodos', 'circle-opacity', 0.25); set('nodos-brillo', 'circle-opacity', 0);
    }
    function limpiar() {
      ocultarCarros();
      cancelAnimationFrame(animacion); origen = destino = null; atenuarFondo(false);
      ['v-onda', 'v-corta', 'v-efic', 'v-puntos', 'v-carros', 'v-parada'].forEach(s => mapa.getSource(s).setData(vacio));
      $('v-res').classList.remove('on'); $('v-recarga').classList.remove('on'); estado('Toca la esquina de salida en el mapa');
    }

    // ---------- cálculo del viaje ----------
    function geometria(ruta, energia) {
      const coords = [], km = [], wh = [], z = [];
      let d = 0, en = 0, h = 0;
      ruta.forEach((e, j) => {
        const p = T[e].p;
        p.forEach((c, k) => {
          if (j > 0 && k === 0) return;
          if (coords.length) {
            const a = coords[coords.length - 1];
            d += Math.hypot((c[0] - a[0]) * 111320 * Math.cos(c[1] * Math.PI / 180), (c[1] - a[1]) * 110540);
          }
          const f = p.length > 1 ? k / (p.length - 1) : 1;
          coords.push(c); km.push(d); wh.push(en + f * energia[e] * 1000); z.push(h + f * S[e] * L[e]);
        });
        en += energia[e] * 1000; h += S[e] * L[e];
      });
      return { coords, km, wh, z, total_m: ruta.reduce((a, e) => a + L[e], 0), total_wh: en };
    }

    function calcular() {
      cancelAnimationFrame(animacion); atenuarFondo(true); ocultarCarros();
      const c = V.carros[carroSel], E = energias[carroSel];
      const dj = dijkstra(origen, L), bf = bellmanFord(origen, E);
      if (!bf) { estado('Se detectó un ciclo imposible de energía en la red.', false); return; }
      const rc = camino(dj.padre, origen, destino), re = camino(bf.padre, origen, destino);
      if (!rc || !re) { estado('No hay forma de llegar a esa esquina respetando los sentidos de las calles.', false); return; }
      const gc = geometria(rc, E), ge = geometria(re, E);
      // Verificación independiente: la ruta eficiente nunca gasta más que la corta.
      if (ge.total_wh > gc.total_wh + 1e-6) { estado('Error: la ruta eficiente gasta más que la corta.', false); return; }
      socSalida = R ? +$('v-soc').value / 100 : 1;
      $('v-recarga').classList.remove('on'); mapa.getSource('v-parada').setData(vacio);
      if (R) {
        const plan = planear(carroSel, origen, destino, socSalida, +$('v-espera').value);
        if (plan.parada) { viajeConParada(plan, c, E); return; }
        if (plan.imposible) {
          $('v-res').classList.remove('on');
          $('v-recarga').innerHTML = `<h4>No alcanza</h4><div class="v-aviso">Con ${(socSalida * 100).toFixed(1).replace('.', ',')} % de batería
            no se llega sin bajar de la reserva, y ninguna estación compatible y con potencia declarada permite completar el viaje.</div>`;
          $('v-recarga').classList.add('on');
          mapa.getSource('v-efic').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: ge.coords } });
          mapa.setPaintProperty('v-efic', 'line-gradient', '#ff6b5a');
          estado('Viaje imposible con esa batería', false);
          return;
        }
      }

      const ondaDe = (dist, color) => {
        const lim = dist[destino], lista = [];
        for (let i = 0; i < N; i++) if (dist[i] <= lim) lista.push(i);
        lista.sort((a, b) => dist[a] - dist[b]);
        return lista.map((i, k) => ({ type: 'Feature', properties: { r: k / Math.max(1, lista.length - 1), color },
                                      geometry: { type: 'Point', coordinates: D.nodos[i].p } }));
      };
      const ondaC = ondaDe(dj.dist, COLOR_CORTA), ondaE = ondaDe(bf.dist, COLOR_EFIC);

      // resultados
      const ahorro = gc.total_wh > 0 ? 100 * (gc.total_wh - ge.total_wh) / gc.total_wh : 0;
      $('v-ahorro').textContent = `${ahorro.toFixed(1).replace('.', ',')} %`;
      $('v-c-km').textContent = `${(gc.total_m / 1000).toFixed(2).replace('.', ',')} km`;
      $('v-e-km').textContent = `${(ge.total_m / 1000).toFixed(2).replace('.', ',')} km`;
      $('v-c-wh').textContent = `${Math.round(gc.total_wh)} Wh`;
      $('v-e-wh').textContent = `${Math.round(ge.total_wh)} Wh`;
      $('v-res').classList.add('on');

      // comparación entre carros (ruta eficiente de cada uno)
      const comp = V.carros.map((cc, i) => { const r = bellmanFord(origen, energias[i]); return r ? r.dist[destino] * 1000 : NaN; });
      const maxC = Math.max(...comp.filter(isFinite), 1);
      $('v-comparar').innerHTML = V.carros.map((cc, i) => `<div class="c${i === carroSel ? ' sel' : ''}">
        <span>${cc.nombre.replace(/\s*\(.*\)/, '')}</span><div class="barra"><div style="width:${Math.max(2, 100 * comp[i] / maxC)}%;${i === carroSel ? '' : 'opacity:.45'}"></div></div>
        <span style="text-align:right">${Math.round(comp[i])} Wh</span></div>`).join('');

      // perfil
      const zs = [...gc.z, ...ge.z], zmin = Math.min(...zs), zmax = Math.max(...zs, zmin + 1);
      const kmax = Math.max(gc.km.at(-1), ge.km.at(-1), 1);
      const trazo = g => g.km.map((k, i) => `${(300 * k / kmax).toFixed(1)},${(64 - 58 * (g.z[i] - zmin) / (zmax - zmin)).toFixed(1)}`).join(' ');
      $('v-perfil').innerHTML = `<polyline points="${trazo(gc)}" fill="none" stroke="${COLOR_CORTA}" stroke-width="1.6" vector-effect="non-scaling-stroke" opacity=".85"/>
        <polyline points="${trazo(ge)}" fill="none" stroke="${COLOR_EFIC}" stroke-width="2" vector-effect="non-scaling-stroke"/>
        <circle id="v-perfil-punto" r="3.5" fill="#fff" cx="0" cy="0"/>`;

      estado(`Buscando la ruta más corta… revisando ${ondaC.length.toLocaleString('es-CO')} esquinas`);
      mapa.getSource('v-corta').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: gc.coords } });
      mapa.getSource('v-efic').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: ge.coords } });
      mapa.getSource('v-puntos').setData(puntosGJ());

      // encuadre
      const todos = [...gc.coords, ...ge.coords];
      const b = todos.reduce((a, p) => [Math.min(a[0], p[0]), Math.min(a[1], p[1]), Math.max(a[2], p[0]), Math.max(a[3], p[1])], [180, 90, -180, -90]);
      mapa.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: { top: 80, bottom: 80, left: 400, right: 80 }, duration: reducir ? 0 : 900, pitch: 35 });

      animar(ondaC, ondaE, gc, ge, c);
    }

    // ---------- viaje con parada de recarga ----------
    function viajeConParada(plan, c, E) {
      const p = plan.parada, s = D.estaciones[p.estacion];
      const g1 = geometria(p.r1, E), g2 = geometria(p.r2, E);
      const coords = [...g1.coords, ...g2.coords.slice(1)];
      $('v-res').classList.remove('on');
      mapa.getSource('v-onda').setData(vacio);
      mapa.getSource('v-corta').setData(vacio);
      mapa.getSource('v-efic').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: coords } });
      mapa.getSource('v-parada').setData({ type: 'Feature', geometry: { type: 'Point', coordinates: D.nodos[s.nodo].p } });

      const t1 = g1.total_m / 1000 / V.velocidad_kmh * 60, t2 = g2.total_m / 1000 / V.velocidad_kmh * 60;
      const esp = +$('v-espera').value, tot = p.total_min;
      const pctDe = kwh => (100 * kwh / p.cap).toFixed(1).replace('.', ',');
      const ancho = x => `${Math.max(2, 100 * x / tot)}%`;
      const mm = x => x < 1 ? `${Math.round(x * 60)} s` : `${x.toFixed(1).replace('.', ',')} min`;
      $('v-recarga').innerHTML = `
        <h4>Hace falta recargar</h4>
        <div class="quien">Parada en <b>${s.n}</b>: ${Math.round(s.kw)} kW, carga a ${Math.round(p.potencia_kw)} kW (${p.dc ? 'DC' : 'AC'})</div>
        <div class="v-linea" role="img" aria-label="Línea de tiempo del viaje">
          <div style="width:${ancho(t1)};background:#4ff0d0">${t1 / tot > .18 ? mm(t1) : ''}</div>
          ${esp ? `<div style="width:${ancho(esp)};background:#93a3b5">${esp / tot > .18 ? esp + ' min' : ''}</div>` : ''}
          <div style="width:${ancho(p.t_carga_min)};background:#ffe08a">${p.t_carga_min / tot > .18 ? mm(p.t_carga_min) : ''}</div>
          <div style="width:${ancho(t2)};background:#4ff0d0">${t2 / tot > .18 ? mm(t2) : ''}</div>
        </div>
        <div class="linea-et"><span>Manejo · ${esp ? 'espera · ' : ''}carga · manejo</span><span>Total ${mm(tot)}</span></div>
        <div class="reloj" id="v-reloj">0 min 00 s</div>
        <div class="linea-et"><span id="v-reloj-txt">tiempo de viaje</span><span>carga ${p.carga_kwh.toFixed(2).replace('.', ',')} kWh</span></div>
        <div class="bateria"><div class="caja"><div class="nivel" id="v-nivel2"></div></div>
          <div class="et"><span id="v-bat2">Batería ${pctDe(p.e0)} %</span><span>llega con ${pctDe(p.llegada)} %, sale con ${pctDe(p.objetivo)} %</span></div></div>
        ${esp ? '<div class="v-aviso">La espera en la estación es un supuesto: no hay datos de ocupación.</div>' : ''}`;
      $('v-recarga').classList.add('on');

      const b = coords.reduce((a, q) => [Math.min(a[0], q[0]), Math.min(a[1], q[1]), Math.max(a[2], q[0]), Math.max(a[3], q[1])], [180, 90, -180, -90]);
      mapa.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: { top: 80, bottom: 80, left: 400, right: 80 }, duration: reducir ? 0 : 900, pitch: 35 });
      estado('Planeando con parada de recarga', false);

      // fases: dibujar · tramo 1 · carga · tramo 2
      const D1 = 1200, M1 = 3500 * Math.max(.35, g1.total_m / (g1.total_m + g2.total_m)) + 1500, C = reducir ? 0 : 3200, M2 = 5000 - M1 + 1500;
      const F = reducir ? [0, 0, 0, 0, 1] : [0, D1, D1 + M1, D1 + M1 + C, D1 + M1 + C + M2];
      const t0 = performance.now(), suave = x => x < .5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2;
      const avanza = (g, k) => { const d = k * g.km.at(-1); let i = 1; while (i < g.km.length - 1 && g.km[i] < d) i++;
        const a = i - 1, f = g.km[i] > g.km[a] ? Math.min(1, (d - g.km[a]) / (g.km[i] - g.km[a])) : 1;
        return { p: [g.coords[a][0] + f * (g.coords[i][0] - g.coords[a][0]), g.coords[a][1] + f * (g.coords[i][1] - g.coords[a][1])],
                 wh: g.wh[a] + f * (g.wh[i] - g.wh[a]) }; };
      const reloj = min => { const t = Math.round(min * 60); return `${Math.floor(t / 60)} min ${String(t % 60).padStart(2, '0')} s`; };
      const carro = (q, color = COLOR_EFIC) => { bolitas[0].el.style.display = 'none'; mover(1, q, color); };
      const bat = kwh => { const pct = 100 * kwh / p.cap; $('v-nivel2').style.width = `${Math.max(0, pct)}%`;
        $('v-nivel2').classList.toggle('baja', pct < 15); $('v-bat2').textContent = `Batería ${pct.toFixed(1).replace('.', ',')} %`; };

      const frame = ahora => {
        const t = ahora - t0, k = (a, b2) => Math.min(1, Math.max(0, (t - a) / Math.max(1, b2 - a)));
        mapa.setPaintProperty('v-efic', 'line-gradient', gradiente(COLOR_EFIC, suave(k(F[0], F[1]))));
        mapa.setPaintProperty('v-efic-halo', 'line-opacity', .35 * k(F[0], F[1]));
        const pulso = (Math.sin(ahora / 260) + 1) / 2;
        if (t < F[2]) {
          const q = avanza(g1, suave(k(F[1], F[2]))); carro(q.p); bat(p.e0 - q.wh / 1000);
          $('v-reloj').textContent = reloj(t1 * k(F[1], F[2])); $('v-reloj-txt').textContent = 'manejando hacia la estación';
          mapa.setPaintProperty('v-parada-halo', 'circle-opacity', .25 + .25 * pulso);
        } else if (t < F[3]) {
          const kc = k(F[2], F[3]); carro(D.nodos[s.nodo].p, '#ffe08a');
          bat(p.llegada + kc * p.carga_kwh);
          $('v-reloj').textContent = reloj(t1 + (esp + p.t_carga_min) * kc); $('v-reloj-txt').textContent = esp ? 'esperando y cargando' : 'cargando';
          mapa.setPaintProperty('v-parada-halo', 'circle-opacity', .45 + .45 * pulso);
          estado(`Cargando en ${s.n}`, true);
        } else {
          const q = avanza(g2, suave(k(F[3], F[4]))); carro(q.p); bat(p.objetivo - q.wh / 1000);
          $('v-reloj').textContent = reloj(t1 + esp + p.t_carga_min + t2 * k(F[3], F[4])); $('v-reloj-txt').textContent = 'manejando al destino';
          mapa.setPaintProperty('v-parada-halo', 'circle-opacity', .2);
        }
        if (t < F[4]) animacion = requestAnimationFrame(frame);
        else { $('v-reloj').textContent = reloj(tot); $('v-reloj-txt').textContent = 'tiempo total del viaje';
               estado(`Llegó con parada de ${mm(esp + p.t_carga_min)} en ${s.n}`, false); }
      };
      animacion = requestAnimationFrame(frame);
    }
    // ---------- animación ----------
    const oculto = 'rgba(0,0,0,0)';
    const gradiente = (color, k) => k >= 1 ? color : ['step', ['line-progress'], color, Math.max(1e-6, k), oculto];
    function animar(ondaC, ondaE, gc, ge, c) {
      const F = reducir ? [0, 0, 0, 0, 0, 1] : [0, 1500, 2300, 3800, 4600, 9800];   // fases (ms)
      const t0 = performance.now();
      const suave = x => x < .5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2;
      let fase = -1;
      const frame = ahora => {
        const t = ahora - t0, k = (a, b) => Math.min(1, Math.max(0, (t - a) / Math.max(1, b - a)));
        const nf = t < F[1] ? 0 : t < F[2] ? 1 : t < F[3] ? 2 : t < F[4] ? 3 : 4;
        if (nf !== fase) {
          fase = nf;
          if (fase === 0) mapa.getSource('v-onda').setData({ type: 'FeatureCollection', features: ondaC });
          if (fase === 2) { mapa.getSource('v-onda').setData({ type: 'FeatureCollection', features: ondaE });
            estado(`Energía necesaria para llegar a cada esquina… ${ondaE.length.toLocaleString('es-CO')} esquinas`); }
          if (fase === 4) estado('Recorriendo las dos rutas', false);
        }
        // ondas
        const ko = fase < 2 ? k(F[0], F[1]) : k(F[2], F[3]);
        const desvanece = fase === 1 || fase === 3 ? 1 - k(fase === 1 ? F[1] : F[3], fase === 1 ? F[2] : F[4]) * .7 : fase === 4 ? .3 * (1 - k(F[4], F[4] + 800)) : 1;
        mapa.setPaintProperty('v-onda', 'circle-opacity', ['*', desvanece, ['case', ['<=', ['get', 'r'], ko], 0.9, 0]]);
        // trazado de rutas
        const kc = k(F[1], F[2]), ke = k(F[3], F[4]);
        mapa.setPaintProperty('v-corta', 'line-gradient', gradiente(COLOR_CORTA, suave(kc)));
        mapa.setPaintProperty('v-efic', 'line-gradient', gradiente(COLOR_EFIC, suave(ke)));
        mapa.setPaintProperty('v-corta-halo', 'line-opacity', .25 * kc);
        mapa.setPaintProperty('v-efic-halo', 'line-opacity', .35 * ke);
        // viaje de los carros
        const kv = suave(k(F[4], F[5]));
        const avanza = g => { const d = kv * g.km.at(-1); let i = 1; while (i < g.km.length - 1 && g.km[i] < d) i++;
          const a = i - 1, f = g.km[i] > g.km[a] ? Math.min(1, (d - g.km[a]) / (g.km[i] - g.km[a])) : 1;
          return { p: [g.coords[a][0] + f * (g.coords[i][0] - g.coords[a][0]), g.coords[a][1] + f * (g.coords[i][1] - g.coords[a][1])],
                   wh: g.wh[a] + f * (g.wh[i] - g.wh[a]), z: g.z[a] + f * (g.z[i] - g.z[a]), km: d }; };
        if (fase === 4) {
          const ac = avanza(gc), ae = avanza(ge);
          mover(0, ac.p, COLOR_CORTA); mover(1, ae.p, COLOR_EFIC);
          const pct = Math.max(0, socSalida * 100 - ae.wh / (c.bateria_kwh * 1000) * 100);
          $('v-nivel').classList.toggle('baja', pct < 15);
          $('v-nivel').style.width = `${pct}%`;
          $('v-bat-txt').textContent = `Batería ${pct.toFixed(2).replace('.', ',')} %`;
          const recupera = ae.wh < (ge._maxwh = Math.max(ge._maxwh || 0, ae.wh)) - 0.05;
          $('v-bat-regen').textContent = recupera ? 'recuperando en bajada ↺' : `${Math.round(ae.wh)} Wh usados`;
          const zs = [...gc.z, ...ge.z], zmin = Math.min(...zs), zmax = Math.max(...zs, zmin + 1), kmax = Math.max(gc.km.at(-1), ge.km.at(-1), 1);
          const punto = $('v-perfil-punto');
          if (punto) { punto.setAttribute('cx', 300 * ae.km / kmax); punto.setAttribute('cy', 64 - 58 * (ae.z - zmin) / (zmax - zmin)); }
        }
        if (t < F[5]) animacion = requestAnimationFrame(frame);
        else estado(`Listo. Con ${V.carros[carroSel].nombre.replace(/\s*\(.*\)/, '')}, la ruta eficiente ahorra ${$('v-ahorro').textContent}.`, false);
      };
      animacion = requestAnimationFrame(frame);
    }
  }

  const arrancar = () => window.APP ? iniciar(window.APP) : window.addEventListener('app-listo', () => iniciar(window.APP), { once: true });
  arrancar();
})();