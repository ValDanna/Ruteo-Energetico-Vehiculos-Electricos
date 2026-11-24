"""
exportar_historia.py — Escribe datos_historia.js para la página historia/index.html.

Ejecutar desde F:\\Tesis\\App\\historia:
    python exportar_historia.py
Solo exporta lo que ya pasó las verificaciones de carga.py. No calcula nada nuevo.
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))          # para importar carga.py de App
import carga  # noqa: E402
import carga  # noqa: E402
import consumo_sintetico as consumo  # noqa: E402
import planificador  # noqa: E402
import networkx as nx

SALIDA = AQUI / "datos_historia.js"

def agregar_viaje(datos, velocidad_kmh=30, semilla=5):
    """Carros y casos de control para que la página verifique su cálculo contra Python."""
    tramos = datos["tramos"]
    # Se calcula con los MISMOS valores redondeados que recibe la página.
    s = np.array([0.0 if t["s"] is None else t["s"] / 100 for t in tramos])
    L = np.array([t["L"] for t in tramos])
    carros = [{"nombre": n, **p} for n, p in consumo.VEHICULOS.items()]

    rng = np.random.default_rng(semilla)
    muestra = rng.choice(len(tramos), size=min(60, len(tramos)), replace=False)
    control_tramos = [{"carro": n, "idx": muestra.tolist(),
                       "kwh": [float(x) for x in consumo.energia_tramo_kwh(p, L[muestra], s[muestra], velocidad_kmh)]}
                      for n, p in consumo.VEHICULOS.items()]

    G0 = nx.DiGraph()
    G0.add_edges_from((t["u"], t["v"]) for t in tramos)
    mayor = sorted(max(nx.strongly_connected_components(G0), key=len))
    pares = []
    while len(pares) < 3:
        a, b = (int(x) for x in rng.choice(mayor, 2, replace=False))
        pares.append((a, b))

    control_rutas = []
    for n, p in consumo.VEHICULOS.items():
        E = consumo.energia_tramo_kwh(p, L, s, velocidad_kmh)
        G = nx.MultiDiGraph()
        for i, t in enumerate(tramos):
            G.add_edge(t["u"], t["v"], key=i, L=float(L[i]), E=float(E[i]))
        peso = lambda attr: (lambda u, v, d: min(x[attr] for x in d.values()))
        for a, b in pares:
            control_rutas.append({"carro": n, "origen": a, "destino": b,
                                  "metros": float(nx.shortest_path_length(G, a, b, weight=peso("L"))),
                                  "kwh": float(nx.bellman_ford_path_length(G, a, b, weight=peso("E")))})

    datos["viaje"] = {"carros": carros, "velocidad_kmh": velocidad_kmh, "sintetico": bool(consumo.ES_SINTETICO),
                      "control_tramos": control_tramos, "control_rutas": control_rutas}
    print(f"  Viaje: {len(carros)} carros, {len(control_rutas)} rutas de control")
    return datos

# ---------- atributos de estaciones (A2, A3 y vocabulario de B4) ----------
def _es_nulo(v):
    if isinstance(v, str):
        return not v.strip()
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9_]+", " ", t).strip()


def _vocab(voc, grupo, valor):
    """Traduce con el vocabulario de B4. None si es centinela o no tiene equivalencia."""
    if _es_nulo(valor):
        return None
    crudo, n = str(valor).strip().lower(), _norm(valor)
    if n in voc["centinelas"] or crudo in voc["centinelas"]:
        return None
    return voc[grupo].get(crudo) or voc[grupo].get(n)


def _kw(texto):
    """'325 kW' -> 325 ; '22000 W' -> 22 ; '7,4 kW' -> 7.4 ; número sin unidad > 1000 se toma como W."""
    if _es_nulo(texto):
        return None
    vals = []
    for num, unidad in re.findall(r"(\d+(?:[.,]\d+)?)\s*(kw|w)?", str(texto).lower()):
        v = float(num.replace(",", "."))
        vals.append(v / 1000 if unidad == "w" or (not unidad and v > 1000) else v)
    return max(vals) if vals else None


def cargar_atributos(raiz):
    """Lee atributos crudos de A2 (OSM) y A3 (OCM) y el vocabulario de B4."""
    A2, A3 = raiz / "Bloque A/Entregable A2", raiz / "Bloque A/Entregable A3"
    voc = json.load(open(raiz / "Bloque B/Entregable B4/B4_vocabularios.json", encoding="utf-8"))
    osm, ocm, con = {}, [], []
    for ciudad in ("Bogota", "Medellin"):
        for f in json.load(open(A2 / f"A2_estaciones_OSM_{ciudad}.geojson", encoding="utf-8"))["features"]:
            osm[str(f["properties"]["osm_uid"])] = f["properties"]
        ocm.append(pd.read_csv(A3 / f"A3_OpenChargeMap_{ciudad}_estaciones.csv", encoding="utf-8-sig"))
        con.append(pd.read_csv(A3 / f"A3_OpenChargeMap_{ciudad}_conexiones.csv", encoding="utf-8-sig"))
    ocm = pd.concat(ocm).assign(ocm_id=lambda d: d["ocm_id"].astype("int64")).set_index("ocm_id")
    con = pd.concat(con).assign(ocm_id=lambda d: d["ocm_id"].astype("int64"))
    assert ocm.index.is_unique, "ocm_id repetido en A3"
    return voc, osm, ocm, con


def atributos_estacion(fila, voc, osm, ocm, con):
    """Atributos de ruteo de una estación, cada uno tomado de la fuente que eligió B4 (columnas origen_*)."""
    p = osm.get(str(fila["osm_uid"])) if not _es_nulo(fila.get("osm_uid")) else None
    o = ocm.loc[int(fila["ocm_id"])] if not _es_nulo(fila.get("ocm_id")) and int(fila["ocm_id"]) in ocm.index else None
    c = con[con["ocm_id"] == int(fila["ocm_id"])] if o is not None else con.iloc[0:0]
    fuente = lambda k: None if _es_nulo(fila.get(f"origen_{k}")) else str(fila[f"origen_{k}"])
    a = {}

    # potencia (kW máximo)
    f = fuente("potencia")
    if f == "OCM" and o is not None:
        a["kw"] = None if _es_nulo(o["potencia_kw_max"]) else float(o["potencia_kw_max"])
    elif f == "OSM" and p:
        salidas = [v for k, v in (p.get("sockets_json") or {}).items() if k.endswith(":output")]
        kws = [x for x in [_kw(p.get("potencia"))] + [_kw(s) for s in salidas] if x is not None]
        a["kw"] = max(kws) if kws else None
    else:
        a["kw"] = None
    a["kw_f"] = f if a["kw"] is not None else None

    # conectores (normalizados con B4) y cuántos de cada uno
    f, conect = fuente("conector"), {}
    if f == "OCM":
        for _, r in c.iterrows():
            k = _vocab(voc, "conector", r["conector"])
            if k:
                conect[k] = conect.get(k, 0) + (1 if _es_nulo(r["cantidad"]) else int(r["cantidad"]))
    elif f == "OSM" and p:
        for k, v in (p.get("sockets_json") or {}).items():
            partes = k.split(":")
            if len(partes) == 2:
                kk = _vocab(voc, "conector", partes[1])
                if kk:
                    try:
                        n = int(float(v))
                    except (TypeError, ValueError):
                        n = 1
                    conect[kk] = conect.get(kk, 0) + n
    a["con"] = [{"t": k, "n": n} for k, n in sorted(conect.items())]
    a["con_f"] = f if conect else None

    # acceso
    f = fuente("acceso")
    crudo = o["tipo_uso"] if f == "OCM" and o is not None else p.get("acceso") if f == "OSM" and p else None
    a["acc"], a["acc_f"] = _vocab(voc, "acceso", crudo), f
    if a["acc"] is None: a["acc_f"] = None

    # cobro (y tarifa declarada, sin inventar unidades)
    f = fuente("cobro")
    if f == "OCM" and o is not None:
        a["cob"] = _vocab(voc, "cobro", o["costo_uso"])
        if a["cob"] is None and not _es_nulo(o["costo_uso"]):
            try:
                a["cob"] = "COBRA" if float(o["costo_uso"]) > 0 else "GRATIS"
            except ValueError:
                pass
        a["tarifa"] = None if _es_nulo(o["costo_uso"]) else str(o["costo_uso"])
    elif f == "OSM" and p:
        a["cob"] = _vocab(voc, "cobro", p.get("cobro"))
        a["tarifa"] = (p.get("tags_json") or {}).get("charge")
    else:
        a["cob"], a["tarifa"] = None, None
    a["cob_f"] = f if a["cob"] else None

    # capacidad (puntos de carga)
    f = fuente("capacidad")
    crudo = o["n_puntos_declarados"] if f == "OCM" and o is not None else p.get("capacidad") if f == "OSM" and p else None
    try:
        a["cap"] = None if _es_nulo(crudo) else int(float(crudo))
    except ValueError:
        a["cap"] = None
    a["cap_f"] = f if a["cap"] is not None else None

    # operador
    f = fuente("operador")
    crudo = (o["operador"] if f == "OCM" and o is not None else
             (p.get("operador") or p.get("marca") or p.get("red")) if f == "OSM" and p else None)
    a["op"] = None if _es_nulo(crudo) or _norm(crudo) in voc["centinelas"] else str(crudo)
    a["op_f"] = f if a["op"] else None

    # vigencia y extras (solo informativos, no los decide B4)
    a["estado"] = None if o is None or _es_nulo(o["estado_operativo"]) else str(o["estado_operativo"])
    a["verif"] = None if o is None or _es_nulo(o["fecha_ultima_verificacion"]) else str(o["fecha_ultima_verificacion"])[:10]
    a["dc"] = None if o is None or _es_nulo(o["tiene_carga_dc"]) else str(o["tiene_carga_dc"]).strip().lower() == "true"
    a["horario"] = None if not p or _es_nulo(p.get("horario")) else str(p["horario"])
    a["osm_fecha"] = None if not p or _es_nulo(p.get("osm_timestamp")) else str(p["osm_timestamp"])[:10]
    return a

def agregar_recarga(datos, semilla=9):
    """Reglas de recarga y viajes de control con parada, para verificar la página."""
    V, tramos, est = datos["viaje"], datos["tramos"], datos["estaciones"]
    vel = V["velocidad_kmh"]
    s = np.array([0.0 if t["s"] is None else t["s"] / 100 for t in tramos])
    L = np.array([t["L"] for t in tramos])

    # esquina más cercana de cada estación (si no se calculó antes)
    P = np.array([n["p"] for n in datos["nodos"]])
    for q in est:
        if q.get("nodo") is None:
            dx = (P[:, 0] - q["p"][0]) * 111320 * np.cos(np.radians(q["p"][1]))
            dy = (P[:, 1] - q["p"][1]) * 110540
            d = np.hypot(dx, dy)
            q["nodo"], q["dm"] = int(d.argmin()), round(float(d.min()), 1)

    reglas = {k: getattr(consumo, k) for k in
              ("EFICIENCIA_CARGA", "SOC_MAX_CARGA", "RESERVA_SOC", "MARGEN_SOC", "UMBRAL_DC_KW")}
    rng = np.random.default_rng(semilla)
    G0 = nx.DiGraph(); G0.add_edges_from((t["u"], t["v"]) for t in tramos)
    mayor = sorted(max(nx.strongly_connected_components(G0), key=len))

    controles = []
    for nombre, par in consumo.VEHICULOS.items():
        E = consumo.energia_tramo_kwh(par, L, s, vel)
        G = nx.MultiDiGraph()
        for i, t in enumerate(tramos):
            G.add_edge(t["u"], t["v"], key=i, L=float(L[i]), E=float(E[i]))
        hechos, intentos = 0, 0
        while hechos < 3 and intentos < 60:
            intentos += 1
            a, b = (int(x) for x in rng.choice(mayor, 2, replace=False))
            base = planificador.planear(G, par, est, a, b, 1.0, 0, vel, consumo)
            if base["pico_directo"] <= 0:
                continue          # viaje en bajada: nunca necesita cargar
            soc = consumo.RESERVA_SOC + 0.4 * base["pico_directo"] / par["bateria_kwh"]
            r = planificador.planear(G, par, est, a, b, soc, 0, vel, consumo)
            p = r["parada"]
            controles.append({"carro": nombre, "origen": a, "destino": b, "soc": soc, "espera": 0,
                              "estacion": None if p is None else p["estacion"],
                              "total_min": None if p is None else p["total_min"],
                              "carga_kwh": None if p is None else p["carga_kwh"]})
            hechos += 1
    V["reglas"], V["control_recarga"] = reglas, controles
    print(f"  Recarga: {len(controles)} viajes de control, "
          f"{sum(c['estacion'] is not None for c in controles)} con parada posible")
    return datos

def r6(x):
    return round(float(x), 6)


def main():
    print("Cargando y verificando…")
    estaciones, p_est = carga.cargar_estaciones()
    seg, _, p_graf = carga.cargar_grafo()
    p_lim = carga.verificar_huella(carga.RUTAS["d1_limite"], carga.RUTAS["d1_huellas"])
    if not p_lim["pasa"]:
        raise carga.ErrorCarga(p_lim["detalle"])
    pruebas = p_est + p_graf + [p_lim]
    seg = seg.reset_index(drop=True)

    geo = seg.to_crs(carga.CRS_GEOGRAFICO)
    tramos, pos, vecinos = [], {}, defaultdict(set)
    for i, g in enumerate(geo.geometry):
        partes = g.geoms if g.geom_type == "MultiLineString" else [g]
        coords = [[r6(x), r6(y)] for p in partes for x, y in p.coords]
        s = seg.at[i, "pendiente_neta"]
        u, v = seg.at[i, "u"], seg.at[i, "v"]
        tramos.append({"p": coords, "s": None if pd.isna(s) else round(float(s) * 100, 2),
                       "c": bool(seg.at[i, "pendiente_confiable"]) and not pd.isna(s),
                       "e": bool(seg.at[i, "en_sector"]), "L": round(float(seg.at[i, "longitud_m"]), 1)})
        pos.setdefault(u, coords[0])
        pos.setdefault(v, coords[-1])
        vecinos[u].add(v)
        vecinos[v].add(u)
    nodos = [{"p": pos[n], "g": len(vecinos[n])} for n in pos]
    indice = {n: i for i, n in enumerate(pos)}     # posición de cada esquina en la lista de nodos
    for t, u, v in zip(tramos, seg["u"], seg["v"]):
        t["u"], t["v"] = indice[u], indice[v]
    # Verificación independiente: cada tramo empieza en su esquina u y termina en su esquina v.
    # Verificación independiente: cada tramo empieza en su esquina u y termina en su esquina v.
    # D1 forma las esquinas uniendo extremos en la misma celda de 2 m, así que un extremo puede
    # quedar hasta √2 ≈ 1,414 m de su esquina. Cualquier distancia mayor indica una unión mal hecha.
    TOLERANCIA_M = 1.415

    def metros(a, b):
        dx = (a[0] - b[0]) * 111320 * np.cos(np.radians(a[1]))
        dy = (a[1] - b[1]) * 110540
        return float(np.hypot(dx, dy))

    peor = max(max(metros(t["p"][0], nodos[t["u"]]["p"]), metros(t["p"][-1], nodos[t["v"]]["p"]))
               for t in tramos)
    print(f"  Distancia máxima extremo–esquina: {peor:.3f} m (tolerancia {TOLERANCIA_M} m)")
    assert peor <= TOLERANCIA_M, f"Un tramo está a {peor:.2f} m de su esquina: la unión no es confiable"
    lim = gpd.read_file(carga.RUTAS["d1_limite"], layer="limite").to_crs(carga.CRS_GEOGRAFICO)
    poligono = lim.geometry.union_all()
    mayor = max(lim.explode(index_parts=False).geometry, key=lambda g: g.area)
    limite = [[r6(x), r6(y)] for x, y in mayor.exterior.coords]

    est = estaciones[(~estaciones["es_secundario"]) & (estaciones["ciudad"] == "Bogota")]
    est = est[est.geometry.within(poligono)]
    voc_b4, osm_attr, ocm_attr, con_attr = cargar_atributos(carga.RAIZ)
    puntos = []
    for _, f in est.iterrows():
        nombre = f["nombre_osm"] if pd.notna(f.get("nombre_osm")) else f.get("nombre_ocm")
        cat = str(f["categoria"])
        puntos.append({"p": [r6(f["lon"]), r6(f["lat"])],
                       "n": "Estación sin nombre" if pd.isna(nombre) else str(nombre),
                       "g": "ambas" if cat.startswith(("C1", "C2")) else
                            "desacuerdo" if cat.startswith("C3") else "una",
                       **atributos_estacion(f, voc_b4, osm_attr, ocm_attr, con_attr)})
    print("  Atributos:", sum(q["kw"] is not None for q in puntos), "con potencia,",
          sum(bool(q["con"]) for q in puntos), "con conectores, de", len(puntos), "estaciones")

        # Enlace estación → esquina más cercana del grafo (necesario para la alcanzabilidad).
    P = np.array([n["p"] for n in nodos])
    for q in puntos:
        dx = (P[:, 0] - q["p"][0]) * 111320 * np.cos(np.radians(q["p"][1]))
        dy = (P[:, 1] - q["p"][1]) * 110540
        d = np.hypot(dx, dy)
        k = int(d.argmin())
        q["nodo"], q["dm"] = k, round(float(d[k]), 1)
    print("  Estaciones: metros a la esquina más cercana:", sorted(q["dm"] for q in puntos))
    datos = {"tramos": tramos, "nodos": nodos, "limite": limite, "estaciones": puntos,
             "sintetico": False,
             "pruebas": {"total": len(pruebas), "pasan": int(sum(p["pasa"] for p in pruebas))}}

    # Verificación independiente: los conteos exportados coinciden con el gpkg.
    assert len(tramos) == len(seg), "Se perdieron tramos al exportar"
    assert sum(t["e"] for t in tramos) == int(seg["en_sector"].sum()), "Conteo en sector no cuadra"
    assert len(nodos) == len(set(seg["u"]) | set(seg["v"])), "Conteo de nodos no cuadra"

    datos = agregar_viaje(datos)
    datos = agregar_recarga(datos)
    SALIDA.write_text("window.DATOS = " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + ";",
                      encoding="utf-8")
    print(f"Listo: {SALIDA.name}  ({SALIDA.stat().st_size / 1e6:.1f} MB)")
    print(f"  {len(tramos):,} tramos, {len(nodos):,} nodos, {len(puntos)} estaciones en Chapinero")


if __name__ == "__main__":
    main()