"""
Conteo por localidad sobre el archivo final vigente (capitulo 1 y 10).

Cruza el CSV final con la columna `localidad` del archivo de segmentos y
reporta, por localidad: segmentos con dato, distribucion INVIAS y pendientes
extremas (filas y tramos fisicos). Un tramo fisico es el segmento_id sin el
sufijo _FT/_TF.

Uso: python auxiliares/aux_conteo_localidades.py
Salida: datos_salida/auxiliares/conteo_localidades.csv
"""
import geopandas as gpd
import pandas as pd

from _comun import C, CARPETA_AUX

archivo = C.ARCHIVO_PENDIENTES
print(f"Archivo final: {archivo}")
df = pd.read_csv(archivo)
seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS, ignore_geometry=True)
df = df.merge(seg[["segmento_id", "localidad"]], on="segmento_id", how="left", validate="one_to_one")
df["localidad"] = df["localidad"].fillna("SIN LOCALIDAD")
df["tramo_fisico"] = df["segmento_id"].str.rsplit("_", n=1).str[0]

con = df[~df["fuera_cobertura_mdt"].astype(bool)].copy()
con["extrema"] = con["pendiente_extrema"].astype(str).eq("True")

tabla = con.groupby("localidad").agg(
    segmentos_con_dato=("segmento_id", "size"),
    plano=("clasificacion_invias", lambda s: (s == "Plano").sum()),
    ondulado=("clasificacion_invias", lambda s: (s == "Ondulado").sum()),
    montanoso=("clasificacion_invias", lambda s: (s == "Montañoso").sum()),
    escarpado=("clasificacion_invias", lambda s: (s == "Escarpado").sum()),
    filas_extremas=("extrema", "sum"),
)
tabla["tramos_fisicos_extremos"] = con[con["extrema"]].groupby("localidad")["tramo_fisico"].nunique()
tabla = tabla.fillna(0).astype(int)
tabla["pct_escarpado_de_la_localidad"] = (tabla["escarpado"] / tabla["segmentos_con_dato"] * 100).round(2)
total_ext = tabla["tramos_fisicos_extremos"].sum()
tabla["pct_de_tramos_extremos"] = (tabla["tramos_fisicos_extremos"] / total_ext * 100).round(1)
tabla = tabla.sort_values("tramos_fisicos_extremos", ascending=False)

print(tabla.to_string())
print(f"\nTramos fisicos extremos: {total_ext}  (filas: {int(tabla['filas_extremas'].sum())})")
print(f"Segmentos fuera de cobertura sin localidad: "
      f"{int((df['fuera_cobertura_mdt'].astype(bool) & df['localidad'].eq('SIN LOCALIDAD')).sum())}")
tabla.to_csv(CARPETA_AUX / "conteo_localidades.csv")
