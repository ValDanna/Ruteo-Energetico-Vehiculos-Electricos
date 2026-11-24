/* bogota.js — Carga los binarios de datos_bogota/ y datos_medellin/, dibuja la red y rutea.
   Lee y nada mas: no escribe ni modifica ningun entregable.

   Ruteo por energia con potenciales de Johnson derivados de la altura, como en
   Eisner, Funke y Storandt (2011) y el Dij-PH de Baum y otros (2013): con el
   potencial h(v) = c * z(v) los costos reducidos quedan no negativos y Dijkstra
   es exacto, sin Bellman-Ford. El intervalo valido de c se calcula aqui mismo y
   se muestra en la pagina.                                                     */

export let D = {};                         // la ciudad en uso: todo lo cargado queda aqui
const CIUDADES = {};                       // carpeta de datos -> lo cargado de esa ciudad
/* Cambia la ciudad en uso. Todo lo demas (rutas, perfil, geometria) trabaja sobre
   D, asi que basta con apuntar D a la otra ciudad. */
export function usar(base) { if (CIUDADES[base]) D = CIUDADES[base]; return D; }
export const cargada = base => CIUDADES[base] || null;
const M_ = n => n.toLocaleString("es-CO");
const F = (b, n, o) => new Float32Array(b, o, n);
const I = (b, n, o) => new Int32Array(b, o, n);

async function traer(ruta, como = "bin") {
  const r = await fetch(ruta, { cache: "no-cache" });   // datos recién empaquetados, no los de la caché
  if (!r.ok) throw new Error(`no pude leer ${ruta} (${r.status})`);
  return como === "bin" ? r.arrayBuffer() : r.json();
}

// --------------------------------------------------------------- carga inicial
export async function cargar(aviso = () => {}, base = "datos_bogota") {
  if (CIUDADES[base]) return usar(base);
  const C = { base };
  aviso("leyendo el escenario");
  C.meta = await traer(`${base}/meta.json`, "json");
  const N = C.meta.n_nodos, A = C.meta.n_aristas, G = C.meta.n_dibujo;

  aviso(`${M_(C.meta.n_nodos)} esquinas`);
  const nb = await traer(`${C.base}/nodos.bin`);
  C.lon = F(nb, N, 0); C.lat = F(nb, N, 4 * N); C.z = F(nb, N, 8 * N);

  aviso(`${M_(C.meta.n_aristas)} aristas`);
  const ab = await traer(`${C.base}/aristas.bin`);
  C.u = I(ab, A, 0); C.v = I(ab, A, 4 * A); C.gi = I(ab, A, 8 * A);
  C.largo = F(ab, A, 12 * A); C.pend = F(ab, A, 16 * A);
  C.rev = new Uint8Array(ab, 20 * A, A);

  aviso(`${M_(C.meta.n_dibujo)} calles`);
  const gb = await traer(`${C.base}/dibujo.bin`);
  C.off = I(gb, G + 1, 0);
  C.xy = F(gb, 2 * C.off[G], 4 * (G + 1));
  const at = await traer(`${C.base}/dibujo_attr.bin`);
  C.pendAbs = F(at, G, 0);
  C.nom = I(at, G, 4 * G);
  C.clase = new Uint8Array(at, 8 * G, G);
  C.loc = new Uint8Array(at, 9 * G, G);
  C.vocab = await traer(`${C.base}/vocab.json`, "json");
  C.estaciones = await traer(`${C.base}/estaciones.json`, "json");
  C.control = await traer(`${C.base}/control.json`, "json");

  aviso("armando el grafo");
  adyacencia(C);
  CIUDADES[base] = C;
  // la primera ciudad que se carga queda en uso; las siguientes no la desplazan
  if (!D.meta) D = C;
  return C;
}

// Lista de adyacencia compacta (CSR): grado, luego desplazamientos acumulados.
function adyacencia(C) {
  const N = C.meta.n_nodos, A = C.meta.n_aristas;
  const ini = new Int32Array(N + 1);
  for (let e = 0; e < A; e++) ini[C.u[e] + 1]++;
  for (let i = 0; i < N; i++) ini[i + 1] += ini[i];
  const orden = new Int32Array(A), cursor = ini.slice(0, N);
  for (let e = 0; e < A; e++) orden[cursor[C.u[e]]++] = e;
  C.ini = ini; C.orden = orden;

  // y el grafo al reves, para calcular el costo de volver
  const iniR = new Int32Array(N + 1);
  for (let e = 0; e < A; e++) iniR[C.v[e] + 1]++;
  for (let i = 0; i < N; i++) iniR[i + 1] += iniR[i];
  const ordenR = new Int32Array(A), curR = iniR.slice(0, N);
  for (let e = 0; e < A; e++) ordenR[curR[C.v[e]]++] = e;
  C.iniR = iniR; C.ordenR = ordenR;
}

// ------------------------------------------------------------ pesos del carro
export async function cargarCarro(id, aviso = () => {}) {
  const C = D;                     // la ciudad en uso al pedirlo, aunque se cambie mientras llega
  if (C.carro && C.carro.id === id) return C.carro;
  aviso(`pesos de ${id}`);
  const A = C.meta.n_aristas;
  const b = await traer(`${C.base}/carros/${id}.bin`);
  const consumo = F(b, A, 0), peso = F(b, A, 4 * A);
  const ficha = C.meta.carros.find(c => c.id === id) || { id };
  C.carro = { id, consumo, peso, ficha, ...potencial(peso, C) };
  return C.carro;
}

/* El potencial de Johnson. Costo reducido de la arista e = (u,v):
      w'(e) = w(e) + c*z(u) - c*z(v) = w(e) - c*(z(v) - z(u))
   Para que nunca sea negativo hace falta  c <= w/dz  en las subidas  y
   c >= w/dz  en las bajadas. Esos dos limites se calculan en una pasada.      */
function potencial(w, D) {
  const A = D.meta.n_aristas;
  let alto = Infinity, bajo = -Infinity, sinAltura = 0;
  for (let e = 0; e < A; e++) {
    const dz = D.z[D.v[e]] - D.z[D.u[e]];
    if (Math.abs(dz) < 1e-6) { if (w[e] < 0) sinAltura++; continue; }
    const r = w[e] / dz;
    if (dz > 0) { if (r < alto) alto = r; } else if (r > bajo) bajo = r;
  }
  const sirve = bajo <= alto && sinAltura === 0;
  const c = sirve ? (Math.max(bajo, 0) + alto) / 2 : 0;
  return { c, cBajo: bajo, cAlto: alto, johnson: sirve && c > 0 };
}

// ------------------------------------------------------------------- Dijkstra
/* Monticulo binario sobre arreglos tipados: a esta escala es la diferencia
   entre responder al instante y colgar la pestana.                           */
class Monte {
  constructor(n) { this.k = new Float64Array(n + 1); this.v = new Int32Array(n + 1); this.n = 0; }
  push(k, v) {
    let i = ++this.n; this.k[i] = k; this.v[i] = v;
    while (i > 1) {
      const p = i >> 1; if (this.k[p] <= this.k[i]) break;
      [this.k[p], this.k[i]] = [this.k[i], this.k[p]];
      [this.v[p], this.v[i]] = [this.v[i], this.v[p]]; i = p;
    }
  }
  pop() {
    const kr = this.k[1], vr = this.v[1];
    this.k[1] = this.k[this.n]; this.v[1] = this.v[this.n--];
    let i = 1;
    for (;;) {
      let m = i; const l = i << 1, r = l + 1;
      if (l <= this.n && this.k[l] < this.k[m]) m = l;
      if (r <= this.n && this.k[r] < this.k[m]) m = r;
      if (m === i) break;
      [this.k[m], this.k[i]] = [this.k[i], this.k[m]];
      [this.v[m], this.v[i]] = [this.v[i], this.v[m]]; i = m;
    }
    return [kr, vr];
  }
}

/* peso: funcion (arista) -> costo >= 0.  pot: funcion (nodo) -> potencial.
   Devuelve { costo, aristas, nodos } o null si no hay camino.                 */
export function dijkstra(o, d, peso, pot = null) {
  const N = D.meta.n_nodos;
  const dist = new Float64Array(N).fill(Infinity);
  const dePor = new Int32Array(N).fill(-1);
  const listo = new Uint8Array(N);
  const h = pot || (() => 0);
  const q = new Monte(Math.min(4 * N, 1 << 21));
  dist[o] = 0; q.push(0, o);
  let vistos = 0;
  while (q.n) {
    const [k, x] = q.pop();
    if (listo[x]) continue;
    listo[x] = 1; vistos++;
    if (x === d) break;
    for (let i = D.ini[x]; i < D.ini[x + 1]; i++) {
      const e = D.orden[i], y = D.v[e];
      if (listo[y]) continue;
      const nd = dist[x] + peso(e) + h(x) - h(y);
      if (nd < dist[y] - 1e-12) { dist[y] = nd; dePor[y] = e; q.push(nd, y); }
    }
  }
  if (!listo[d]) return null;
  const aristas = [], nodos = [d];
  for (let x = d; x !== o; x = D.u[dePor[x]]) { aristas.push(dePor[x]); nodos.push(D.u[dePor[x]]); }
  aristas.reverse(); nodos.reverse();
  // el potencial se cancela al final; se devuelve el costo real, no el reducido
  let costo = 0; for (const e of aristas) costo += peso(e);
  return { costo, aristas, nodos, vistos };
}

/* SPFA (Bellman-Ford con cola): respaldo cuando el potencial no sirve, porque
   con pesos negativos Dijkstra deja de ser exacto.                            */
export function spfa(o, d, peso) {
  const N = D.meta.n_nodos;
  const dist = new Float64Array(N).fill(Infinity);
  const dePor = new Int32Array(N).fill(-1);
  const enCola = new Uint8Array(N);
  const cola = [o]; dist[o] = 0; enCola[o] = 1;
  let pasos = 0, tope = 40 * N;
  while (cola.length && pasos++ < tope) {
    const x = cola.shift(); enCola[x] = 0;
    for (let i = D.ini[x]; i < D.ini[x + 1]; i++) {
      const e = D.orden[i], y = D.v[e], nd = dist[x] + peso(e);
      if (nd < dist[y] - 1e-12) {
        dist[y] = nd; dePor[y] = e;
        if (!enCola[y]) { enCola[y] = 1; cola.push(y); }
      }
    }
  }
  if (dist[d] === Infinity) return null;
  const aristas = [], nodos = [d];
  for (let x = d; x !== o; x = D.u[dePor[x]]) { aristas.push(dePor[x]); nodos.push(D.u[dePor[x]]); }
  aristas.reverse(); nodos.reverse();
  return { costo: dist[d], aristas, nodos, agotado: pasos >= tope };
}

// ------------------------------------------------------------------- consultas
export const porDistancia = (o, d) => dijkstra(o, d, e => D.largo[e]);

export function porEnergia(o, d) {
  const c = D.carro;
  const w = e => c.peso[e];
  if (c.johnson) {
    const h = x => c.c * D.z[x];
    const r = dijkstra(o, d, e => Math.max(w(e) + c.c * (D.z[D.u[e]] - D.z[D.v[e]]), 0), null);
    if (r) {                       // recalcular el costo real sobre el camino
      let costo = 0, energia = 0;
      for (const e of r.aristas) { costo += w(e); energia += c.consumo[e]; }
      return { ...r, costo, energia, metodo: "Dijkstra con potencial de altura" };
    }
    return null;
  }
  const r = spfa(o, d, w);
  if (!r) return null;
  let energia = 0; for (const e of r.aristas) energia += c.consumo[e];
  return { ...r, energia, metodo: "SPFA (el potencial no aplica)" };
}

export const metros = r => r.aristas.reduce((s, e) => s + D.largo[e], 0);
export const energia = r => r.aristas.reduce((s, e) => s + D.carro.consumo[e], 0);

// --------------------------------------------------- esquina mas cercana, geo
const R = 6371000;
export function cercano(lng, lat) {
  let mejor = -1, md = Infinity;
  const cl = Math.cos(lat * Math.PI / 180);
  for (let i = 0; i < D.lon.length; i++) {
    const dx = (D.lon[i] - lng) * cl, dy = D.lat[i] - lat;
    const d = dx * dx + dy * dy;
    if (d < md) { md = d; mejor = i; }
  }
  return { nodo: mejor, m: Math.sqrt(md) * Math.PI / 180 * R };
}

// ------------------------------------------- geometria de un camino, en orden
export function trazo(aristas) {
  const pts = [];
  for (const e of aristas) {
    const g = D.gi[e], a = D.off[g], b = D.off[g + 1];
    const tramo = [];
    for (let i = a; i < b; i++) tramo.push([D.xy[2 * i], D.xy[2 * i + 1]]);
    if (D.rev[e]) tramo.reverse();
    if (pts.length) tramo.shift();
    pts.push(...tramo);
  }
  return pts;
}

// --------------------------------------------- perfil de altura de un camino
export function perfil(aristas, nodos) {
  const p = [[0, D.z[nodos[0]]]];
  let s = 0;
  for (let i = 0; i < aristas.length; i++) {
    s += D.largo[aristas[i]];
    p.push([s, D.z[nodos[i + 1]]]);
  }
  return p;
}

// ------------------------------------------------------- la red como GeoJSON
/* Una sola capa con todas las calles. Se construye una vez y se reutiliza:
   rearmarla en cada cuadro fue lo que colgaba la version anterior.            */
/* El grosor sale del NOMBRE de la clase, no de su numero: asi funciona con
   cualquier vocabulario que traiga el paquete, sin indices escritos a mano. */
const PESO = { motorway: 3, trunk: 3, primary: 2.2, secondary: 1.5,
               tertiary: 1.15, residential: .75, living_street: .6, service: .55 };
function pesoDe(nombre) {
  if (!nombre) return .7;
  const n = String(nombre).toLowerCase();
  for (const k in PESO) if (n.includes(k)) return PESO[k];
  return .7;
}

export function redGeoJSON() {
  const G = D.meta.n_dibujo, fs = new Array(G);
  const peso = (D.vocab.clase || []).map(pesoDe);
  for (let g = 0; g < G; g++) {
    const a = D.off[g], b = D.off[g + 1], co = new Array(b - a);
    for (let i = a; i < b; i++) co[i - a] = [D.xy[2 * i], D.xy[2 * i + 1]];
    fs[g] = { type: "Feature", id: g,
      geometry: { type: "LineString", coordinates: co },
      // x = longitud del primer punto: con eso el barrido de occidente a
      // oriente se hace con una expresion de pintura, sin rearmar la capa
      properties: { p: D.pendAbs[g], w: peso[D.clase[g]] ?? .7, x: D.xy[2 * a] } };
  }
  return { type: "FeatureCollection", features: fs };
}

/* Reparto de la pendiente en toda la red, para que la leyenda diga donde cae
   de verdad la ciudad y no solo que color le toca a cada numero. */
export function repartoPendiente(cortes) {
  const n = new Int32Array(cortes.length);
  for (let g = 0; g < D.pendAbs.length; g++) {
    const p = D.pendAbs[g];
    let k = cortes.length - 1;
    while (k > 0 && p < cortes[k]) k--;
    n[k]++;
  }
  return n;
}
