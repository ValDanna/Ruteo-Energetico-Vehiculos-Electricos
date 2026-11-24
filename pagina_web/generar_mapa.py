"""
generar_mapa.py — Genera web/chapinero.html (mapa 3D animado, autónomo).

Ejecutar desde F:\\Tesis\\App:
    python generar_mapa.py
Luego abrir web\\chapinero.html con doble clic.

Python hace todo lo que importa: carga, 16 verificaciones y cálculo de rutas.
El HTML solo DIBUJA lo que Python ya verificó; no calcula nada.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd

import carga
import consumo_sintetico as consumo

SALIDA = Path(__file__).resolve().parent / "web" / "chapinero.html"
PLANTILLA = Path(__file__).resolve().parent / "plantilla_mapa.html"

CARRO = "Carro prueba B (compacto)"
VELOCIDAD_KMH = 30
N_RUTAS = 4
SEMILLA = 11

# Cómo se asigna pendiente a los tramos SOLO para calcular el consumo de las rutas.
#   "estimada": usa pendiente_neta en todos los tramos (alturas coherentes entre sí).
#   "confiable_o_plano": tramos no confiables como planos. Puede crear ciclos
#   imposibles que "generan" energía y dejar sin rutas; se deja para diagnóstico.
MODO_PENDIENTE_RUTAS = "estimada"


def coords(g):
    partes = g.geoms if g.geom_type == "MultiLineString" else [g]
    return [[round(x, 6), round(y, 6)] for p in partes for x, y in p.coords]


def main():
    print("Cargando y verificando…")
    estaciones, p_est = carga.cargar_estaciones()
    seg, _, p_graf = carga.cargar_grafo()
    p_lim = carga.verificar_huella(carga.RUTAS["d1_limite"], carga.RUTAS["d1_huellas"])
    if not p_lim["pasa"]:
        raise carga.ErrorCarga(p_lim["detalle"])
    pruebas = p_est + p_graf + [p_lim]
    seg = seg.reset_index(drop=True)

    # --- tramos ------------------------------------------------------------
    geo = seg.to_crs(carga.CRS_GEOGRAFICO)
    nombre = seg["name"] if "name" in seg.columns else pd.Series("", index=seg.index)
    tramos = []
    for i, g in enumerate(geo.geometry):
        p = seg.at[i, "pendiente_neta"]
        conf = bool(seg.at[i, "pendiente_confiable"]) and not pd.isna(p)
        tramos.append({
            "p": coords(g),
            "s": None if pd.isna(p) else round(float(p) * 100, 2),
            "c": conf,
            "e": bool(seg.at[i, "en_sector"]),
            "n": str(nombre.iat[i]) if pd.notna(nombre.iat[i]) and str(nombre.iat[i]) else "Calle sin nombre",
            "l": round(float(seg.at[i, "longitud_m"]), 1),
        })

    # --- límite ------------------------------------------------------------
    lim = gpd.read_file(carga.RUTAS["d1_limite"], layer="limite").to_crs(carga.CRS_GEOGRAFICO)
    poligono = lim.geometry.union_all()
    limite = [[[round(x, 6), round(y, 6)] for x, y in g.exterior.coords]
              for g in lim.explode(index_parts=False).geometry]

    # --- estaciones de Bogotá ----------------------------------------------
    est = estaciones[(~estaciones["es_secundario"]) & (estaciones["ciudad"] == "Bogota")].copy()
    est["dentro"] = est.geometry.within(poligono)
    est = est[est["dentro"]]          # solo las estaciones dentro de Chapinero
    puntos = []
    for _, f in est.iterrows():
        nombre_est = f.get("nombre_osm")
        if pd.isna(nombre_est):
            nombre_est = f.get("nombre_ocm")
        cat = str(f["categoria"])
        grupo = ("ambas" if cat.startswith(("C1", "C2")) else
                 "desacuerdo" if cat.startswith("C3") else "una")
        puntos.append({"pos": [round(f["lon"], 6), round(f["lat"], 6)],
                       "n": "Estación sin nombre" if pd.isna(nombre_est) else str(nombre_est),
                       "cat": cat, "g": grupo, "dentro": bool(f["dentro"])})

    # --- rutas de ejemplo --------------------------------------------------
    print("Calculando rutas de ejemplo…")
    carro = consumo.VEHICULOS[CARRO]
    if MODO_PENDIENTE_RUTAS == "estimada":
        pend = seg["pendiente_neta"].fillna(0.0).to_numpy()
    else:
        pend = np.where(seg["pendiente_confiable"], seg["pendiente_neta"].fillna(0.0), 0.0)
    energia = consumo.energia_tramo_kwh(carro, seg["longitud_m"].to_numpy(), pend, VELOCIDAD_KMH)
    G = nx.MultiDiGraph()
    for i, (u, v) in enumerate(zip(seg["u"], seg["v"])):
        G.add_edge(u, v, key=i, L=float(seg.at[i, "longitud_m"]), E=float(energia[i]))

    pos = {}
    for i, (u, v) in enumerate(zip(seg["u"], seg["v"])):
        pts = tramos[i]["p"]
        pos.setdefault(u, pts[0])
        pos.setdefault(v, pts[-1])

    mayor = max(nx.strongly_connected_components(G), key=len)
    nodos = sorted(mayor & (set(seg.loc[seg["en_sector"], "u"]) | set(seg.loc[seg["en_sector"], "v"])), key=str)

    def peso(a):
        return lambda u, v, d: min(x[a] for x in d.values())

    def trazar(camino, a):
        pts, dist, t, energia_total = [], 0.0, [], 0.0
        for u, v in zip(camino[:-1], camino[1:]):
            k, x = min(G[u][v].items(), key=lambda kx: kx[1][a])
            linea = tramos[k]["p"]
            for j, c in enumerate(linea):
                if pts and j == 0:
                    continue
                if pts:
                    dx = (c[0] - pts[-1][0]) * 111320 * np.cos(np.radians(c[1]))
                    dy = (c[1] - pts[-1][1]) * 110540
                    dist += float(np.hypot(dx, dy))
                pts.append(c)
                t.append(round(dist, 1))
            energia_total += x["E"]
        return pts, t, energia_total

    rng = np.random.default_rng(SEMILLA)
    rutas, intentos, razones = [], 0, Counter()
    while len(rutas) < N_RUTAS and intentos < 400:
        intentos += 1
        a, b = (nodos[i] for i in rng.choice(len(nodos), 2, replace=False))
        dx = (pos[a][0] - pos[b][0]) * 111320 * np.cos(np.radians(pos[a][1]))
        dy = (pos[a][1] - pos[b][1]) * 110540
        if not 1200 < np.hypot(dx, dy) < 3500:
            razones["distancia fuera de 1,2 a 3,5 km"] += 1
            continue
        corta = nx.shortest_path(G, a, b, weight=peso("L"))
        try:
            efic = nx.bellman_ford_path(G, a, b, weight=peso("E"))
        except nx.NetworkXUnbounded:
            razones["ciclo que genera energía"] += 1
            continue
        if corta == efic:
            razones["las dos rutas son iguales"] += 1
            continue
        pc, tc, ec = trazar(corta, "L")
        pe, te, ee = trazar(efic, "E")
        if ec - ee < max(2.0e-3, 0.03 * abs(ec)):   # exige al menos 2 Wh y 3 % de diferencia
            razones["diferencia de energía < 3 % o < 2 Wh"] += 1
            continue
        assert ee <= ec + 1e-9 and tc[-1] <= te[-1] * 1.01, "Ruteo incoherente"
        rutas.append({"corta": {"p": pc, "t": tc, "km": round(tc[-1] / 1000, 2), "wh": round(ec * 1000)},
                      "efic": {"p": pe, "t": te, "km": round(te[-1] / 1000, 2), "wh": round(ee * 1000)}})
    print(f"  Modo de pendiente para rutas: {MODO_PENDIENTE_RUTAS}")
    print(f"  {len(rutas)} rutas de ejemplo ({intentos} pares probados)")
    for razon, n in razones.most_common():
        print(f"    descartados por {razon}: {n}")
    if not rutas:
        print("  AVISO: ningún par con rutas distintas; el mapa se genera sin recorrido animado.")

    datos = {
        "tramos": tramos, "limite": limite, "estaciones": puntos, "rutas": rutas,
        "carro": CARRO, "velocidad": VELOCIDAD_KMH, "modo_pendiente": MODO_PENDIENTE_RUTAS,
        "pruebas": {"total": len(pruebas), "pasan": sum(p["pasa"] for p in pruebas)},
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "conteos": {
            "tramos_sector": sum(t["e"] for t in tramos),
            "confiables_sector": sum(t["e"] and t["c"] for t in tramos),
            "est_chapinero": len(puntos),
            "est_ambas": sum(p["g"] == "ambas" for p in puntos),
            "est_desacuerdo": sum(p["g"] == "desacuerdo" for p in puntos),
            "est_una": sum(p["g"] == "una" for p in puntos),
        },
    }

    html = PLANTILLA.read_text(encoding="utf-8").replace(
        "__DATOS__", json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")
    print(f"Listo: {SALIDA}  ({SALIDA.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
