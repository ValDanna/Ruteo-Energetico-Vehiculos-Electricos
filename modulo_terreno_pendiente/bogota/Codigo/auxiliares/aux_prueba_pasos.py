"""
aux_prueba_pasos.py
Cuanto cambia la pendiente si el paso de muestreo es 5, 10, 20 o 50 m.

Toma una muestra estratificada de segmentos del gpkg (Plano y no Plano
segun el CSV final), consulta el MDT 2020 cada 5 m a lo largo de cada segmento
y recalcula neta y acumulada submuestreando ese mismo perfil cada 10, 20 y 50 m.
Asi las cuatro versiones usan las mismas elevaciones y solo cambia el paso.

Resultado  (200 segmentos de al menos 60 m): en plano la acumulada
baja 0,09 / 0,15 / 0,21 pp (mediana) al pasar de 5 m a 10 / 20 / 50 m; en
pendiente la mediana no cambia, pero el paso pierde mas de 0,5 pp en 10, 14 y
16 de 100 segmentos respectivamente (maximo 9,6 pp con 50 m).

Uso: python auxiliares/aux_prueba_pasos.py
Salida: datos_salida/auxiliares/prueba_pasos.csv
"""
import time

import geopandas as gpd
import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX, z2020

N_POR_GRUPO = 100     # segmentos por grupo; sube o baja segun el tiempo disponible
LONG_MIN_M = 60       # para que 50 m deje al menos un punto intermedio posible
PASOS = [5, 10, 20, 50]

final = pd.read_csv(C.ARCHIVO_PENDIENTES)
final = final[~final.fuera_cobertura_mdt & (final.pendiente_extrema != True)]
final = final[final.segmento_id.str.endswith("_FT") | ~final.segmento_id.str.replace("_TF", "_FT").isin(final.segmento_id)]
gdf = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)
gdf = gdf[gdf.longitud_m >= LONG_MIN_M].merge(final[["segmento_id", "clasificacion_invias"]], on="segmento_id")
gdf["grupo"] = np.where(gdf.clasificacion_invias == "Plano", "Plano", "No plano")
muestra = pd.concat([g.sample(min(N_POR_GRUPO, len(g)), random_state=42) for _, g in gdf.groupby("grupo")])
muestra_wgs = muestra.to_crs("EPSG:4326")

filas = []
for k, (i, seg) in enumerate(muestra.iterrows()):
    L = float(seg.longitud_m)
    d5 = np.unique(np.append(np.arange(0, L, 5.0), L))
    geo = muestra_wgs.loc[i].geometry
    z = []
    for d in d5:
        p = geo.interpolate(d / L, normalized=True)
        z.append(z2020(p.x, p.y)); time.sleep(0.05)
    z = np.array([np.nan if v is None else v for v in z])
    if np.isnan(z).any():
        continue
    for paso in PASOS:
        sel = np.isclose(np.mod(d5, paso), 0) | np.isclose(d5, L)
        zz, dd = z[sel], d5[sel]
        dz = np.diff(zz)
        filas.append({"segmento_id": seg.segmento_id, "grupo": seg.grupo, "longitud_m": L, "paso_m": paso,
                      "n_puntos": len(zz), "neta_pct": 100 * (zz[-1] - zz[0]) / L,
                      "acumulada_pct": 100 * np.abs(dz).sum() / L})
    print(f"  {k + 1}/{len(muestra)}", end="\r")

df = pd.DataFrame(filas)
ref = df[df.paso_m == 5].set_index("segmento_id")["acumulada_pct"]
df["acum_menos_acum5_pp"] = df["acumulada_pct"] - df["segmento_id"].map(ref)
print("\nMediana de la acumulada y de su diferencia frente a paso 5 m, por grupo y paso:")
print(df.groupby(["grupo", "paso_m"]).agg(n=("segmento_id", "size"),
                                          acumulada_mediana=("acumulada_pct", "median"),
                                          dif_vs_5m_mediana=("acum_menos_acum5_pp", "median"),
                                          dif_vs_5m_p90=("acum_menos_acum5_pp", lambda x: x.quantile(.9))).round(2).to_string())
print("\nLa neta no cambia con el paso (solo usa los extremos); se reporta como control.")
df.to_csv(CARPETA_AUX / "prueba_pasos.csv", index=False)
