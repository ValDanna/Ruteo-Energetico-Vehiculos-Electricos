"""
aux_revision_visual_extremas.py
Prepara la revision visual de los tramos con pendiente extrema.

Toma los N tramos fisicos de mayor |pendiente neta| entre los marcados como
pendiente_extrema y escribe, para cada uno, tres enlaces de Google Maps
(inicio, centro y fin) y dos columnas vacias para anotar: se_ve
(Calle_normal / Calle_abierta / No_se_ve / Escalera) y observacion.

La anotacion es manual. Las condiciones de Google prohiben capturas de Street
View y crear datos a partir de sus imagenes; el anexo de la tesis reporta la
categoria observada y no reproduce imagenes.

Uso: python auxiliares/aux_revision_visual_extremas.py [N]   (por defecto 52)
Salida: datos_salida/auxiliares/revision_visual_extremas.csv (UTF-8 con BOM)
"""
import sys

import geopandas as gpd
import pandas as pd

from _comun import C, CARPETA_AUX

N = int(sys.argv[1]) if len(sys.argv) > 1 else 52
df = pd.read_csv(C.ARCHIVO_PENDIENTES)
ext = df[df["pendiente_extrema"].astype(str).eq("True")].copy()
ext["tramo_fisico"] = ext["segmento_id"].str.rsplit("_", n=1).str[0]
ext["magnitud"] = ext["pendiente_neta_pct"].abs()
top = ext.sort_values("magnitud", ascending=False).drop_duplicates("tramo_fisico").head(N)

seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS).to_crs(C.CRS_CONSULTA)
seg = seg.set_index("segmento_id")
filas = []
for i, (_, f) in enumerate(top.iterrows(), 1):
    g = seg.loc[f["segmento_id"]]
    enlaces = {}
    for nombre, frac in (("inicio", 0.0), ("centro", 0.5), ("fin", 1.0)):
        p = g.geometry.interpolate(frac, normalized=True)
        enlaces[f"url_{nombre}"] = f"https://www.google.com/maps?q={p.y:.6f},{p.x:.6f}"
    filas.append({"caso": i, "segmento_id": f["segmento_id"],
                  "localidad": g.get("localidad"), "longitud_m": round(float(g["longitud_m"]), 1),
                  "pendiente_neta_pct": round(f["pendiente_neta_pct"], 1),
                  "pendiente_acumulada_pct": round(f["pendiente_acumulada_pct"], 1),
                  "n_puntos_muestreados": f["n_puntos_muestreados"], **enlaces,
                  "se_ve": "", "observacion": ""})
salida = pd.DataFrame(filas)
salida.to_csv(CARPETA_AUX / "revision_visual_extremas.csv", index=False, encoding="utf-8-sig")
print(f"{len(salida)} casos, |neta| de {salida['pendiente_neta_pct'].abs().max()} a "
      f"{salida['pendiente_neta_pct'].abs().min()} %")
