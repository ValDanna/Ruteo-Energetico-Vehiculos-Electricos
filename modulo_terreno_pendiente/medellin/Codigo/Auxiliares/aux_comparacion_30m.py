"""
Pendiente del LiDAR frente a dos modelos de 30 m (SRTM y Copernicus
GLO-30) en un sector plano y uno de ladera de Medellin.

Que hace: Toma los tramos fisicos (uno por segmento base, FT si existe) con dato
del MDT que caen completos en cada sector, consulta la altura de sus dos
extremos en SRTM (Open Topo Data, lotes de 100) y en Copernicus (tesela N06 W076
del bucket publico de AWS, leida localmente) y compara la pendiente neta de
cada fuente con pendiente_neta_pct. Metricas por banda de longitud (< 30, 30-90,
>= 90 m); el resultado principal es >= 30 m. En ladera se muestra tambien sin
los tramos con pendiente_extrema.

Lee:      el archivo de pendientes, el gpkg y la tesela Copernicus (la
          descarga si no esta). Necesita internet para SRTM.
Escribe:  datos_salida/auxiliares/aux_comparacion_30m_tramos.csv 
          datos_salida/auxiliares/aux_comparacion_30m_resumen.csv

Resultado: 262 tramos en Laureles-Estadio (204 de
30 m o mas) y 243 en Comuna 13 (210). Resultado principal (>= 30 m), RMSE en pp:
Laureles SRTM 5,17 y Copernicus 4,02; Comuna 13 SRTM 8,39 y Copernicus 7,56
(sin extremos 7,39 y 7,36). En tramos de 90 m o mas de Comuna 13, Copernicus 3,41
(correlacion 0,976). Tesela Copernicus SHA abbbcbca... En los sectores no hay
tuneles; la pendiente neta solo puede cambiar en el ultimo decimal entre
versiones.
"""
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import box

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos, sha256_archivo
# Define los intervalos de longitud para clasificar los tramos viales y facilite la comparación entre fuentes de elevación
BANDAS = [0, 30, 90, np.inf]
ETIQUETAS = ["<30 m", "30-90 m", ">=90 m"]


def tramos_del_sector(datos, caja):
    """Selecciona los tramos viales que están completamente dentro de un sector"""
    poligono = gpd.GeoSeries([box(*caja)], crs="EPSG:4326").to_crs(C.CRS_RED).iloc[0]
    return datos[datos.within(poligono)].copy()


def elevaciones_copernicus(lons, lats):
    """Obtiene las elevaciones de Copernicus GLO-30 para una lista de coordenadas"""    
    import rasterio
    # Descarga la tesela únicamente si todavía no está
    if not C.ARCHIVO_COPERNICUS.exists():
        with requests.get(C.COPERNICUS_URL, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(C.ARCHIVO_COPERNICUS, "wb") as f:
                for bloque in r.iter_content(chunk_size=1024 * 1024):
                    f.write(bloque)
    # Comprueba la integridad del archivo mediante su huella SHA-256                
    sha = sha256_archivo(C.ARCHIVO_COPERNICUS)
    if sha != C.SHA256_COPERNICUS:
        print(f"  [AVISO] tesela Copernicus con SHA {sha[:12]}..., distinto del registrado")
    # Consulta el valor del raster en cada coordenada y normaliza los valores NoData para que no se interpreten como elevaciones válida        
    with rasterio.open(C.ARCHIVO_COPERNICUS) as r:
        v = np.array([x[0] for x in r.sample(zip(lons, lats))], dtype=float)
        if r.nodata is not None:
            v[v == r.nodata] = np.nan
    return v


def elevaciones_srtm(lons, lats):
    """Consulta las elevaciones SRTM mediante solicitudes agrupadas a la API"""
    # Inicializa los resultados como valores faltantes para las coordenadas que no puedan consultarse bien    
    v = np.full(len(lons), np.nan)
    # Divide las coordenadas en lotes para limitar el tamaño de las solicitudes
    for i in range(0, len(lons), 100):
        lote = range(i, min(i + 100, len(lons)))
        texto = "|".join(f"{lats[j]:.6f},{lons[j]:.6f}" for j in lote)
        # Reintenta cada solicitud hasta tres veces si ocurre un error
        for intento in range(1, 4):
            try:
                resp = requests.get(C.SRTM_URL, params={"locations": texto}, timeout=60)
                resp.raise_for_status()
                for j, res in zip(lote, resp.json()["results"]):
                    if res.get("elevation") is not None:
                        v[j] = float(res["elevation"])
                break
            except Exception as exc:
                print(f"  [aviso] SRTM lote {i // 100 + 1}, intento {intento}: {exc}")
                time.sleep(2 * intento)
        # Introduce una pausa entre lotes para espaciar las consultas        
        time.sleep(1.1)
    return v


def metricas(sub, columna):
     #Calcula métricas para comparar las pendientes de referencia con otra fuente.
     # Utiliza únicamente los tramos que tienen datos disponibles en ambas
    comp = sub.dropna(subset=["pendiente_neta_pct", columna])
    # Evita calcular indicadores comparativos con menos de tres observaciones
    if len(comp) < 3:
        return {"tramos": len(comp), "rmse_pp": np.nan, "sesgo_pp": np.nan,
                "suavizado_abs_pp": np.nan, "correlacion": np.nan}
    # Compara las pendientes del MDT de referencia con las estimadas por la fuente alternativa mediante error, sesgo, suavizado y correlación    
    dif = comp["pendiente_neta_pct"] - comp[columna]
    return {"tramos": len(comp), "rmse_pp": float(np.sqrt((dif ** 2).mean())), "sesgo_pp": float(dif.mean()),
            "suavizado_abs_pp": float((comp["pendiente_neta_pct"].abs() - comp[columna].abs()).mean()),
            "correlacion": float(comp["pendiente_neta_pct"].corr(comp[columna]))}


def main():
     #Carga las pendientes calculadas previamente y las relaciona con la red vial
    pend = leer_pendientes()
    g = leer_segmentos().merge(pend[["segmento_id", "pendiente_neta_pct", "pendiente_extrema",
                                     "fuera_cobertura_mdt", "es_tunel"]], on="segmento_id")
    # Excluye los segmentos sin cobertura del MDT y conserva una representación por tramo base para evitar contabilizar por separado sus dos direcciones
    g = g[g["fuera_cobertura_mdt"] == False]
    g["base"] = g["segmento_id"].str.rsplit("_", n=1).str[0]
    g = g.sort_values("segmento_id").drop_duplicates("base")
    # Extrae los tramos ubicados dentro de cada sector de análisis definido en la configuración y reúne los resultados en un GeoDataFrame    
    tramos = pd.concat([tramos_del_sector(g, caja).assign(sector=n) for n, caja in C.SECTORES_30M.items()],
                       ignore_index=True)
    # Transforma las coordenadas de los extremos de cada tramo al sistema geográfico WGS84
    a_wgs84 = Transformer.from_crs(C.CRS_RED, "EPSG:4326", always_xy=True)
    for extremo, f in [("ini", 0), ("fin", 1)]:
        p = tramos.geometry.interpolate(f, normalized=True)
        tramos[f"lon_{extremo}"], tramos[f"lat_{extremo}"] = a_wgs84.transform(p.x.values, p.y.values)
     # Construye un conjunto de coordenadas únicas para evitar consultar varias veces los mismos puntos cuando distintos tramos comparten algun extremo    
    puntos = pd.concat([tramos[["lon_ini", "lat_ini"]].set_axis(["lon", "lat"], axis=1),
                        tramos[["lon_fin", "lat_fin"]].set_axis(["lon", "lat"], axis=1)]).round(7).drop_duplicates()
    puntos = puntos.reset_index(drop=True)
    # Obtiene la elevación de cada punto con ambas fuentes independientes
    puntos["z_cop30"] = elevaciones_copernicus(puntos["lon"].values, puntos["lat"].values)
    puntos["z_srtm"] = elevaciones_srtm(puntos["lon"].values, puntos["lat"].values)
    # Asocia las elevaciones consultadas con los extremos correspondientes de cada tramo para calcular su pendiente
    for extremo in ["ini", "fin"]:
        claves = tramos[[f"lon_{extremo}", f"lat_{extremo}"]].round(7).set_axis(["lon", "lat"], axis=1)
        unido = claves.merge(puntos, on=["lon", "lat"], how="left")
        tramos[f"z_cop30_{extremo}"] = unido["z_cop30"].values
        tramos[f"z_srtm_{extremo}"] = unido["z_srtm"].values
    # Estima la pendiente neta de cada tramo con la diferencia de elevación entre sus extremos y su longitud horizontal        
    for fuente in ["cop30", "srtm"]:
        tramos[f"pendiente_{fuente}_pct"] = 100 * (tramos[f"z_{fuente}_fin"] - tramos[f"z_{fuente}_ini"]) / tramos["longitud_m"]
    # Clasifica los tramos por longitud para evaluar si el desempeño de las fuentes cambia según el tamaño del segmento    
    tramos["banda"] = pd.cut(tramos["longitud_m"], BANDAS, labels=ETIQUETAS, right=False)
    # Calcula las métricas por sector, versión de los datos y rango de longitud.
    # Se generan resultados con todos los tramos y, cuando corresponde, otra versión que excluye los segmentos identificados como pendientes extremas
    filas = []
    for sector, ds in tramos.groupby("sector", sort=False):
        versiones = [("con extremos", ds)]
        if (ds["pendiente_extrema"] == True).any():
            versiones.append(("sin extremos", ds[ds["pendiente_extrema"] != True]))
        # Incluye un grupo principal de tramos de al menos 30 m y los tres grupos por las bandas de longitud            
        for version, sub in versiones:
            grupos = [(">=30 m (principal)", sub[sub["longitud_m"] >= C.LONGITUD_MINIMA_30M])]
            grupos += [(b, sub[sub["banda"] == b]) for b in ETIQUETAS]
            # Compara por separado las estimaciones de SRTM y Copernicus
            for banda, gr in grupos:
                for col, fuente in [("pendiente_srtm_pct", "SRTM 30 m"), ("pendiente_cop30_pct", "Copernicus GLO-30")]:
                    filas.append({"sector": sector, "version": version, "banda": banda, "fuente": fuente,
                                  **metricas(gr, col)})
    # Organiza y exporta los resultados detallados por tramo y el resumen de las métricas calculadas para cada combinación de grupos                    
    resumen = pd.DataFrame(filas)
    salida = carpeta_salida()
    cols = ["sector", "segmento_id", "nombre", "longitud_m", "banda", "pendiente_extrema", "es_tunel",
            "pendiente_neta_pct", "pendiente_srtm_pct", "pendiente_cop30_pct"]
    tramos[cols].to_csv(salida / "aux_comparacion_30m_tramos.csv", index=False, encoding="utf-8-sig")
    resumen.to_csv(salida / "aux_comparacion_30m_resumen.csv", index=False, encoding="utf-8-sig")
    print(tramos.groupby("sector")["longitud_m"].agg(total="size", de_30_o_mas=lambda s: int((s >= 30).sum())))
    print(resumen.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
