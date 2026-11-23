"""
aux_mdt2025_vs_igac.py
Mide el MDT 2025 contra los mismos vertices del IGAC, para comparar los dos
MDT de igual a igual y para contrastar los vertices atipicos.

Resultado (79 vertices materializados): RMSEz 1,168 m (2025)
frente a 1,033 m (2020); sin los dos atipicos, 0,773 frente a 0,533 m; NMAD
0,552 frente a 0,334 m. En 10-E-1 los dos MDT coinciden (-7,75 y -7,28 m).

Uso: python auxiliares/aux_mdt2025_vs_igac.py
     (requiere haber corrido la etapa: usa su tabla de exactitud vertical)
Salida: datos_salida/auxiliares/exactitud_vertical_mdt2025.csv
"""
import time

import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX, z2025

v = pd.read_csv(C.ARCHIVO_EXACTITUD)
valores = []
for lo, la in zip(v["lon"], v["lat"]):
    valores.append(z2025(lo, la))
    time.sleep(0.2)
v["elevacion_mdt2025_m"] = valores
v["residuo_2025_m"] = v["elevacion_mdt2025_m"] - v["altitud_igac_m"]


def resumen(r):
    r = r.dropna()
    return {"n": len(r), "rmse": np.sqrt((r ** 2).mean()), "mediana": r.median(),
            "nmad": 1.4826 * np.median(np.abs(r - r.median()))}


mat = v[v["estado_geovisor"].str.lower().eq("materializado") & v["residuo_m"].notna()]
sin_at = mat[~mat["vertice"].isin(["1-CM-5", "10-E-1"])]
tabla = pd.DataFrame({"2020 materializados": resumen(mat["residuo_m"]),
                      "2025 materializados": resumen(mat["residuo_2025_m"]),
                      "2020 sin atipicos": resumen(sin_at["residuo_m"]),
                      "2025 sin atipicos": resumen(sin_at["residuo_2025_m"])}).T
print(tabla.round(3).to_string())
print(v[v["vertice"].isin(["1-CM-5", "10-E-1", "NP-CD-443A", "NP-A63-CD"])][["vertice", "residuo_m", "residuo_2025_m"]])
v.to_csv(CARPETA_AUX / "exactitud_vertical_mdt2025.csv", index=False)
