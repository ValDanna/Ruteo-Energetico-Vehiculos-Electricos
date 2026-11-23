"""
Amplia la revision visual a la franja de pendientes extremas con otro intervalo de porcentaje de pendiente.

La revision de los 52 casos cubrio los tramos con |neta| entre 67,4 y 105,3 %.
El 72 % de las filas extremas (1.902 de 2.641) esta entre 35 y 50 %. Este script toma una muestra aleatoria simple de
tramos fisicos de esa franja, con semilla fija para que sea reproducible, y
prepara los mismos enlaces y columnas de la revision anterior.

Dos modos:
  python auxiliares/aux_muestra_extremas_35_50.py            genera la muestra
  python auxiliares/aux_muestra_extremas_35_50.py --resumen  resume la muestra ya anotada

En el modo --resumen calcula la proporcion de cada categoria con su intervalo
de confianza del 95 %, que es lo que se reporta en el documento.

Sale: datos_salida/auxiliares/muestra_extremas_35_50.csv (UTF-8 con BOM)
      Anotar se_ve con: Calle_normal / Calle_abierta / No_se_ve / Escalera
"""
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX

N = 50
SEMILLA = 42
LIMITE_INFERIOR, LIMITE_SUPERIOR = 35.0, 50.0
ARCHIVO = CARPETA_AUX / "muestra_extremas_35_50.csv"
CATEGORIAS = ["No_se_ve", "Calle_normal", "Calle_abierta", "Escalera"]


def wilson(k, n, z=1.96):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return 100 * (centro - margen), 100 * (centro + margen)


def generar():
    if ARCHIVO.exists():
        sys.exit(f"Ya existe {ARCHIVO.name}; no se sobrescribe para no perder anotaciones. Borrelo a mano si quiere regenerarlo.")
    df = pd.read_csv(C.ARCHIVO_PENDIENTES)
    ext = df[df["pendiente_extrema"].astype(str).eq("True")].copy()
    ext["tramo_fisico"] = ext["segmento_id"].str.rsplit("_", n=1).str[0]
    ext["magnitud"] = ext["pendiente_neta_pct"].abs()
    # Un tramo fisico entra con su sentido de mayor |neta|; la franja se decide con ese valor.
    tramos = ext.sort_values("magnitud", ascending=False).drop_duplicates("tramo_fisico")
    franja = tramos[(tramos["magnitud"] > LIMITE_INFERIOR) & (tramos["magnitud"] <= LIMITE_SUPERIOR)]
    filas_franja = ext[(ext["magnitud"] > LIMITE_INFERIOR) & (ext["magnitud"] <= LIMITE_SUPERIOR)]
    print(f"Franja de {LIMITE_INFERIOR:.0f} a {LIMITE_SUPERIOR:.0f} %: {len(filas_franja):,} filas de {len(ext):,} "
          f"({100 * len(filas_franja) / len(ext):.1f} %), {len(franja):,} tramos fisicos")
    muestra = franja.sample(n=min(N, len(franja)), random_state=SEMILLA).sort_values("magnitud", ascending=False)

    seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS).to_crs(C.CRS_CONSULTA).set_index("segmento_id")
    extra = [c for c in seg.columns if c.lower() in ("localidad", "mvitcla", "clase_vial", "civ", "nombre", "mvinombre")]
    filas = []
    for i, (_, f) in enumerate(muestra.iterrows(), 1):
        g = seg.loc[f["segmento_id"]]
        enlaces = {}
        for nombre, frac in (("inicio", 0.0), ("centro", 0.5), ("fin", 1.0)):
            p = g.geometry.interpolate(frac, normalized=True)
            enlaces[f"url_{nombre}"] = f"https://www.google.com/maps?q={p.y:.6f},{p.x:.6f}"
        filas.append({"caso": i, "segmento_id": f["segmento_id"], **{c: g.get(c) for c in extra},
                      "longitud_m": round(float(g["longitud_m"]), 1),
                      "pendiente_neta_pct": round(f["pendiente_neta_pct"], 1),
                      "pendiente_acumulada_pct": round(f["pendiente_acumulada_pct"], 1),
                      "n_puntos_muestreados": f["n_puntos_muestreados"], **enlaces,
                      "se_ve": "", "observacion": ""})
    salida = pd.DataFrame(filas)
    salida.to_csv(ARCHIVO, index=False, encoding="utf-8-sig")
    print(f"{len(salida)} casos (semilla {SEMILLA}), |neta| de {salida['pendiente_neta_pct'].abs().min()} "
          f"a {salida['pendiente_neta_pct'].abs().max()} %. Guardado: {ARCHIVO.name}")


def resumir():
    # Excel en  punto y coma y a veces sin UTF-8: se aceptan ambos.
    try:
        m = pd.read_csv(ARCHIVO, sep=None, engine="python", encoding="utf-8-sig")
    except UnicodeDecodeError:
        m = pd.read_csv(ARCHIVO, sep=None, engine="python", encoding="latin-1")
    m["se_ve"] = m["se_ve"].fillna("").astype(str).str.strip()
    faltan = m["se_ve"].eq("").sum()
    if faltan:
        print(f"Atencion: {faltan} casos sin anotar; el resumen usa solo los anotados.")
    m = m[m["se_ve"].ne("")]
    n = len(m)
    filas = []
    for cat in CATEGORIAS + sorted(set(m["se_ve"]) - set(CATEGORIAS)):
        k = int(m["se_ve"].eq(cat).sum())
        bajo, alto = wilson(k, n)
        filas.append({"categoria": cat, "casos": k, "porcentaje": 100 * k / n if n else np.nan,
                      "ic95_inferior": bajo, "ic95_superior": alto})
    t = pd.DataFrame(filas)
    print(f"Casos anotados: {n}")
    print(t.round(1).to_string(index=False))
    t.to_csv(CARPETA_AUX / "muestra_extremas_35_50_resumen.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    resumir() if "--resumen" in sys.argv else generar()
