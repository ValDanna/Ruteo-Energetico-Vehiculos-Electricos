"""
aux_exactitud_ampliada.py
Mide la exactitud vertical del MDT 2020 contra TODOS los vertices de
nivelacion del IGAC en Bogota con coordenada CALCULADA (530 de 591 en el
geovisor de la Red de Control Vertical).

Que hace:
 1. Consulta el MDT 2020 en cada vertice (punto por punto, con avance guardado).
 2. Mide la pendiente del terreno alrededor de cada vertice con 4 puntos a
    10 m (este, oeste, norte, sur), para separar zona plana y ladera.
 3. Calcula el residuo MDT - IGAC y el umbral de investigacion de la ASPRS
    (3 desviaciones estandar, una sola vez, sobre todos los vertices con dato).
 4. A los vertices que superan el umbral les consulta tambien el MDT 2025,
    para ver si los dos MDT coinciden entre si (indicio de que el problema es
    del vertice) o no.
 5. Imprime RMSEz, mediana y NMAD por conjunto y por zona.

No modifica la etapa ni el archivo de pendientes: solo mide. Las exclusiones
se deciden despues, vertice por vertice, con evidencia (criterio ASPRS).

Uso:   python auxiliares/aux_exactitud_ampliada.py
Entra: igac_vertices_calculadas_bogota.csv (en la carpeta del codigo)
Sale:  datos_salida/auxiliares/exactitud_ampliada_vertices.csv
       datos_salida/auxiliares/exactitud_ampliada_resumen.csv
"""
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX, z2020, z2025

ENTRADA = Path(C.CARPETA_PROYECTO) / "igac_vertices_calculadas_bogota.csv"
AVANCE = CARPETA_AUX / "exactitud_ampliada_avance.csv"
SALIDA = CARPETA_AUX / "exactitud_ampliada_vertices.csv"
RESUMEN = CARPETA_AUX / "exactitud_ampliada_resumen.csv"
DISTANCIA_PENDIENTE_M = 10.0
METROS_POR_GRADO = 111_320.0


def pendiente_terreno(lon, lat):
    """Pendiente del terreno (%) con diferencias centradas a 10 m."""
    dlat = DISTANCIA_PENDIENTE_M / METROS_POR_GRADO
    dlon = DISTANCIA_PENDIENTE_M / (METROS_POR_GRADO * math.cos(math.radians(lat)))
    ze, zo = z2020(lon + dlon, lat), z2020(lon - dlon, lat)
    zn, zs = z2020(lon, lat + dlat), z2020(lon, lat - dlat)
    if None in (ze, zo, zn, zs):
        return None
    gx = (ze - zo) / (2 * DISTANCIA_PENDIENTE_M)
    gy = (zn - zs) / (2 * DISTANCIA_PENDIENTE_M)
    return 100 * math.hypot(gx, gy)


def estadisticos(r):
    r = r.dropna()
    if len(r) == 0:
        return {"n": 0}
    return {"n": len(r), "rmse_z_m": np.sqrt((r ** 2).mean()), "mediana_m": r.median(),
            "nmad_m": 1.4826 * np.median(np.abs(r - r.median())), "desv_m": r.std()}


v = pd.read_csv(ENTRADA)
hechos = pd.read_csv(AVANCE) if AVANCE.exists() else pd.DataFrame(columns=["vertice"])
listos = set(hechos["vertice"])
filas = hechos.to_dict("records")
pendientes = v[~v["vertice"].isin(listos) & ~v["fuera_mdt_urbano"]]
print(f"Vertices: {len(v)}  ya medidos: {len(listos)}  por medir: {len(pendientes)}")
for i, f in enumerate(pendientes.itertuples(), 1):
    z = z2020(f.lon, f.lat)
    p = pendiente_terreno(f.lon, f.lat) if z is not None else None
    filas.append({"vertice": f.vertice, "elevacion_mdt2020_m": z, "pendiente_terreno_pct": p})
    time.sleep(C.MDT_PAUSA_S)
    if i % 25 == 0 or i == len(pendientes):
        pd.DataFrame(filas).to_csv(AVANCE, index=False)
        print(f"  {i}/{len(pendientes)}")

v = v.merge(pd.DataFrame(filas), on="vertice", how="left")
v["residuo_m"] = v["elevacion_mdt2020_m"] - v["altitud_igac_m"]
con_dato = v["residuo_m"].notna()
umbral = 3 * v.loc[con_dato, "residuo_m"].std()
v["supera_umbral"] = con_dato & (v["residuo_m"].abs() > umbral)
v["zona"] = pd.cut(v["pendiente_terreno_pct"], [-1, 3, 8, 1e9],
                   labels=["plano (<3 %)", "inclinado (3-8 %)", "ladera (>8 %)"])

# MDT 2025 solo para los que superan el umbral (evidencia para investigarlos)
v["elevacion_mdt2025_m"] = np.nan
for idx in v.index[v["supera_umbral"]]:
    v.loc[idx, "elevacion_mdt2025_m"] = z2025(v.at[idx, "lon"], v.at[idx, "lat"])
    time.sleep(0.2)
v["residuo_2025_m"] = v["elevacion_mdt2025_m"] - v["altitud_igac_m"]
v.to_csv(SALIDA, index=False)

mat = con_dato & v["estado_geovisor"].eq("Materializado")
sin_umbral = mat & ~v["supera_umbral"]
# Conjunto oficial: el de la etapa principal, con las exclusiones documentadas
# en el archivo de vertices (dos etapas de investigacion, 496 vertices).
excluidos = pd.read_csv(C.ARCHIVO_VERTICES)
excluidos = set(excluidos.loc[excluidos["excluir"].astype(str).str.lower().eq("true"), "vertice"])
adoptado = con_dato & ~v["vertice"].isin(excluidos)
conjuntos = {
    "todos con dato": con_dato,
    "materializados": mat,
    "etapa 1, bajo el umbral de 3 desviaciones (sensibilidad)": sin_umbral,
    "adoptado (oficial)": adoptado,
    "muestra original v1, materializados": mat & v["en_muestra_original"],
}
for zona in v["zona"].cat.categories:
    conjuntos[f"materializados - {zona}"] = mat & v["zona"].eq(zona)
    conjuntos[f"etapa 1 (sensibilidad) - {zona}"] = sin_umbral & v["zona"].eq(zona)
    conjuntos[f"adoptado (oficial) - {zona}"] = adoptado & v["zona"].eq(zona)

tabla = pd.DataFrame([{"conjunto": k, **estadisticos(v.loc[m, "residuo_m"])} for k, m in conjuntos.items()])
tabla.to_csv(RESUMEN, index=False)

print(f"\nUmbral de investigacion (3 desv. sobre {int(con_dato.sum())} vertices con dato): {umbral:.2f} m")
print(tabla.round(3).to_string(index=False))
print("\nVertices que superan el umbral (investigar uno por uno):")
cols = ["vertice", "estado_geovisor", "altitud_igac_m", "residuo_m", "residuo_2025_m",
        "pendiente_terreno_pct", "en_muestra_original"]
print(v.loc[v["supera_umbral"], cols].sort_values("residuo_m").round(2).to_string(index=False))
print(f"\nGuardado: {SALIDA.name} y {RESUMEN.name}")
