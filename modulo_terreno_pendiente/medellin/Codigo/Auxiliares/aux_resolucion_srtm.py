"""
aux_resolucion_srtm.py
Efecto de la resolucion del modelo de elevacion sobre la pendiente en toda la
red de Medellin (objetivo especifico, parte de resolucion).

Que hace: toma una muestra estratificada por clase INVIAS de tramos fisicos con
dato (un sentido por tramo, FT si existe; sin tuneles, cuya pendiente es de boca
a boca), 1.000 por clase o todos los que haya, con semilla 42. Consulta la altura
de los dos extremos de cada tramo en SRTM 30 m (Open Topo Data, lotes de 100) y
en Copernicus GLO-30 (la misma tesela local de aux_comparacion_30m.py) y calcula
la pendiente neta con la longitud del GeoPackage. La compara con la del
DTM-LiDAR 2021 (pendiente_neta_pct del archivo oficial): RMSE, correlacion,
misma clase INVIAS, pendiente exactamente nula, por clase INVIAS y por longitud.
Las cifras de toda la ciudad se ponderan por el peso de cada clase en la red
(tramos de la clase en la red / tramos de la clase en la muestra). Es el mismo
diseño de la comparacion de Bogota (aux_resolucion_2020_2025_srtm.py), sin el
MDT 2025, que no existe en Medellin.

Las diferencias se miden frente al DTM-LiDAR 2021, que tiene su propio error:
no son errores absolutos de los modelos de 30 m.

Como se corre (desde codigo/):  python auxiliares/aux_resolucion_srtm.py
Necesita internet (Open Topo Data). Las alturas consultadas se guardan en una
cache; si la corrida se corta, al volver a correrla solo consulta lo que falta.
Lee:      el archivo de pendientes, el gpkg y la tesela Copernicus (la descarga
          si no esta).
Escribe:  datos_salida/auxiliares/aux_resolucion_srtm_cache.csv (alturas consultadas)
          datos_salida/auxiliares/aux_resolucion_srtm_muestra.csv (un tramo por fila)
          datos_salida/auxiliares/aux_resolucion_srtm_resumen.csv (tabla de diferencias)

Resultado ( v2 96bfac06...): 4.000 tramos, 1.000 por clase (en la red:
10.266 planos, 4.169 ondulados, 1.928 montanosos y 7.020 escarpados). Toda la ciudad,
ponderado: SRTM RMSE 6,91 pp, correlacion 0,77, misma clase INVIAS 51,3 %; Copernicus
8,30 pp, 0,73 y 60,8 %. En plano, SRTM 6,39 pp (correlacion 0,20). En tramos de mas de
100 m, SRTM 3,56 y Copernicus 2,38 pp. Las 6.588 alturas SRTM del servicio son enteras.
Los dos modelos quedan en promedio 4,8 y 4,4 m por encima del DTM.
"""
import time

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos
from aux_comparacion_30m import elevaciones_copernicus

POR_CLASE = 1000
SEMILLA = 42
CLASES = list(C.ETIQUETAS_INVIAS)
BANDAS_L = [0, 20, 50, 100, np.inf]
ETIQ_L = ["<20 m", "20-50 m", "50-100 m", ">100 m"]
LOTE = 100


def clase_invias(neta):
    a = np.abs(neta)
    return np.select([a < C.INVIAS_LIMITE_ONDULADO, a < C.INVIAS_LIMITE_MONTANOSO, a <= C.INVIAS_LIMITE_ESCARPADO],
                     CLASES[:3], CLASES[3]).astype(object)


def consultar_srtm(puntos, ruta_cache):
    """Altura SRTM de cada punto; guarda la cache despues de cada lote."""
    if ruta_cache.exists():
        cache = pd.read_csv(ruta_cache)
    else:
        cache = pd.DataFrame({"lon": pd.Series(dtype=float), "lat": pd.Series(dtype=float),
                              "z_srtm": pd.Series(dtype=float)})
    hechos = set(zip(cache["lon"].round(7), cache["lat"].round(7)))
    faltan = puntos[[(lo, la) not in hechos for lo, la in zip(puntos["lon"], puntos["lat"])]].reset_index(drop=True)
    print(f"Puntos: {len(puntos):,}; en cache: {len(puntos) - len(faltan):,}; por consultar: {len(faltan):,}")
    for i in range(0, len(faltan), LOTE):
        lote = faltan.iloc[i:i + LOTE]
        texto = "|".join(f"{la:.7f},{lo:.7f}" for lo, la in zip(lote["lon"], lote["lat"]))
        for intento in range(1, 5):
            try:
                r = requests.get(C.SRTM_URL, params={"locations": texto}, timeout=60)
                r.raise_for_status()
                z = [res.get("elevation") for res in r.json()["results"]]
                break
            except Exception as exc:
                print(f"  [aviso] lote {i // LOTE + 1}, intento {intento}: {exc}")
                time.sleep(5 * intento)
        else:
            raise SystemExit("Open Topo Data no respondio. Vuelva a correr: la cache conserva lo consultado.")
        nuevo = lote.assign(z_srtm=[np.nan if v is None else float(v) for v in z])
        cache = pd.concat([cache, nuevo], ignore_index=True)
        cache.to_csv(ruta_cache, index=False)
        print(f"  lote {i // LOTE + 1} de {int(np.ceil(len(faltan) / LOTE))}")
        time.sleep(1.1)        # limite publico de Open Topo Data: 1 consulta por segundo
    return cache


def ponderado(x, w):
    return float(np.sum(w * x) / np.sum(w))


def corr_ponderada(x, y, w):
    mx, my = ponderado(x, w), ponderado(y, w)
    cov = ponderado((x - mx) * (y - my), w)
    return float(cov / np.sqrt(ponderado((x - mx) ** 2, w) * ponderado((y - my) ** 2, w)))


def medidas(d, col, w=None):
    d = d.dropna(subset=[col])
    w = np.ones(len(d)) if w is None else d[w].to_numpy()
    x, y = d["pendiente_neta_pct"].to_numpy(), d[col].to_numpy()
    return {"tramos": len(d),
            "rmse_pp": np.sqrt(ponderado((y - x) ** 2, w)) if len(d) else np.nan,
            "correlacion": corr_ponderada(x, y, w) if len(d) > 2 else np.nan,
            "misma_clase_pct": 100 * ponderado((clase_invias(y) == d["clasificacion_invias"].to_numpy()).astype(float), w) if len(d) else np.nan,
            "nula_exacta_pct": 100 * ponderado((y == 0).astype(float), w) if len(d) else np.nan,
            "extremas_pct": 100 * ponderado((np.abs(y) > C.UMBRAL_PENDIENTE_EXTREMA_PCT).astype(float), w) if len(d) else np.nan}


def main():
    pend = leer_pendientes()
    g = leer_segmentos().merge(pend[["segmento_id", "pendiente_neta_pct", "clasificacion_invias", "z_inicio_m", "z_fin_m",
                                     "fuera_cobertura_mdt", "es_tunel"]], on="segmento_id")
    g = g[(g["fuera_cobertura_mdt"] == False) & (g["es_tunel"] == False)].copy()
    g["base"] = g["segmento_id"].str.rsplit("_", n=1).str[0]
    marco = g.sort_values("segmento_id").drop_duplicates("base")

    partes = []
    for clase in CLASES:
        sub = marco[marco["clasificacion_invias"] == clase]
        n = min(POR_CLASE, len(sub))
        partes.append(sub.sample(n=n, random_state=SEMILLA).assign(peso=len(sub) / n, tramos_en_red=len(sub)))
    m = pd.concat(partes, ignore_index=True)
    print("Tramos en la red y en la muestra por clase:")
    print(m.groupby("clasificacion_invias").agg(red=("tramos_en_red", "first"), muestra=("segmento_id", "size")).reindex(CLASES))

    a_wgs84 = Transformer.from_crs(C.CRS_RED, "EPSG:4326", always_xy=True)
    for extremo, f in [("ini", 0), ("fin", 1)]:
        p = m.geometry.interpolate(f, normalized=True)
        lon, lat = a_wgs84.transform(p.x.values, p.y.values)
        m[f"lon_{extremo}"], m[f"lat_{extremo}"] = np.round(lon, 7), np.round(lat, 7)
    puntos = pd.concat([m[["lon_ini", "lat_ini"]].set_axis(["lon", "lat"], axis=1),
                        m[["lon_fin", "lat_fin"]].set_axis(["lon", "lat"], axis=1)]).drop_duplicates().reset_index(drop=True)
    salida = carpeta_salida()
    cache = consultar_srtm(puntos, salida / "aux_resolucion_srtm_cache.csv")
    cache = cache.assign(lon=cache["lon"].round(7), lat=cache["lat"].round(7)).drop_duplicates(["lon", "lat"])
    puntos = puntos.merge(cache, on=["lon", "lat"], how="left")
    puntos["z_cop30"] = elevaciones_copernicus(puntos["lon"].values, puntos["lat"].values)
    for extremo in ["ini", "fin"]:
        u = m[[f"lon_{extremo}", f"lat_{extremo}"]].set_axis(["lon", "lat"], axis=1).merge(puntos, on=["lon", "lat"], how="left")
        m[f"z_srtm_{extremo}"], m[f"z_cop30_{extremo}"] = u["z_srtm"].values, u["z_cop30"].values
    for fuente in ["srtm", "cop30"]:
        m[f"pendiente_{fuente}_pct"] = 100 * (m[f"z_{fuente}_fin"] - m[f"z_{fuente}_ini"]) / m["longitud_m"]
    m["banda_longitud"] = pd.cut(m["longitud_m"], BANDAS_L, labels=ETIQ_L, right=False).astype(str)

    filas = []
    for col, fuente in [("pendiente_srtm_pct", "SRTM 30 m"), ("pendiente_cop30_pct", "Copernicus GLO-30")]:
        z = "srtm" if "srtm" in col else "cop30"
        dz = pd.concat([m[f"z_{z}_ini"] - m["z_inicio_m"], m[f"z_{z}_fin"] - m["z_fin_m"]])
        wz = pd.concat([m["peso"], m["peso"]])
        ok = dz.notna()
        base = {"fuente": fuente, "grupo": "toda la ciudad (ponderado)",
                "dif_elevacion_media_m": ponderado(dz[ok].to_numpy(), wz[ok].to_numpy()),
                "dif_elevacion_rmse_m": np.sqrt(ponderado(dz[ok].to_numpy() ** 2, wz[ok].to_numpy()))}
        filas.append({**base, **medidas(m, col, "peso")})
        for clase in CLASES:
            filas.append({"fuente": fuente, "grupo": f"clase {clase}", **medidas(m[m["clasificacion_invias"] == clase], col)})
        for banda in ETIQ_L:
            filas.append({"fuente": fuente, "grupo": f"longitud {banda} (ponderado)",
                          **medidas(m[m["banda_longitud"] == banda], col, "peso")})
    resumen = pd.DataFrame(filas)
    ext_lidar = 100 * (m.loc[m["clasificacion_invias"] == "Escarpado", "pendiente_neta_pct"].abs() > C.UMBRAL_PENDIENTE_EXTREMA_PCT).mean()

    cols = ["segmento_id", "nombre", "longitud_m", "clasificacion_invias", "peso", "banda_longitud",
            "z_inicio_m", "z_fin_m", "z_srtm_ini", "z_srtm_fin", "z_cop30_ini", "z_cop30_fin",
            "pendiente_neta_pct", "pendiente_srtm_pct", "pendiente_cop30_pct"]
    m[cols].to_csv(salida / "aux_resolucion_srtm_muestra.csv", index=False, encoding="utf-8-sig")
    resumen.to_csv(salida / "aux_resolucion_srtm_resumen.csv", index=False, encoding="utf-8-sig")
    print(f"\nTramos sin altura SRTM: {int(m['pendiente_srtm_pct'].isna().sum())}; sin Copernicus: {int(m['pendiente_cop30_pct'].isna().sum())}")
    print(f"Extremas (> 35 %) en la muestra de escarpados con el DTM-LiDAR 2021: {ext_lidar:.1f} %")
    pd.set_option("display.width", 200)
    print(resumen.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
