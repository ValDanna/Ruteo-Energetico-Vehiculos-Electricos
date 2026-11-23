"""

Efecto de la resolucion del modelo de elevacion sobre la pendiente, la pendiente neta de los mismos segmentos de la Malla Vial
calculada con el MDT 2020 (0,5 m, el de produccion), el MDT 2025 (alturas en metros enteros), SRTM de 30 m y Copernicus DEM GLO-30.


Diseño:
  - Muestra estratificada por clase INVIAS (la del MDT 2020): N_POR_CLASE
    segmentos con dato por clase, un solo sentido por tramo fisico (el otro
    sentido tiene la misma pendiente con signo contrario), semilla fija.
  - La pendiente neta se calcula igual que en el archivo final:
    100 (z_fin - z_inicio) / longitud_m, con los extremos de la geometria y la
    longitud del GeoPackage. Para el MDT 2020 se usan z_inicio_m y z_fin_m del
    archivo final, sin volver a consultar.
  - MDT 2025: consulta punto a punto al ImageServer de Catastro.
  - SRTM: servicio Open Topo Data (srtm30m), en lotes de 100 puntos y una
    consulta por segundo (limite del servicio: 1.000 consultas diarias).
  - Copernicus GLO-30: se descarga la tesela del bucket publico de AWS y se lee
    localmente con rasterio (valor del pixel donde cae el punto, sin
    interpolar), igual que en Medellin. Cada punto se lee en la tesela que le
    corresponde (N04 W075 y, si algun punto queda al este de 74 W, N04 W074).
    Es un modelo de superficie: incluye edificios y vegetacion.
  - Las consultas se guardan en cache, si la corrida se corta, al volver a
    ejecutarla continua donde quedo.

Uso:   aux_resolucion_2020_2025_srtm.py [N_POR_CLASE]   (por defecto 1000)
Sale:  resolucion_segmentos.csv  (pendiente de cada modelo por segmento)
       resolucion_resumen.csv    (tabla de diferencias)
"""
import hashlib
import math
import sys
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from _comun import C, CARPETA_AUX, z2025

N_POR_CLASE = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
SEMILLA = 42
SRTM_URL = "https://api.opentopodata.org/v1/srtm30m"
CACHE_2025 = CARPETA_AUX / "resolucion_cache_mdt2025.csv"
CACHE_SRTM = CARPETA_AUX / "resolucion_cache_srtm.csv"
COPERNICUS_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
                  "Copernicus_DSM_COG_10_{t}_DEM/Copernicus_DSM_COG_10_{t}_DEM.tif")
DECIMALES = 7


def leer_cache(ruta):
    if not ruta.exists():
        return {}
    c = pd.read_csv(ruta, float_precision="round_trip")
    return {(round(a, DECIMALES), round(b, DECIMALES)): z for a, b, z in zip(c["lon"], c["lat"], c["z"])}


def guardar_cache(ruta, valores):
    pd.DataFrame([(k[0], k[1], v) for k, v in valores.items()], columns=["lon", "lat", "z"]).to_csv(
        ruta, index=False, float_format="%.17g")


def consultar_2025(puntos):
    valores = leer_cache(CACHE_2025)
    faltan = [p for p in puntos if p not in valores]
    print(f"MDT 2025: {len(puntos):,} puntos, {len(faltan):,} por consultar")
    for i, (lon, lat) in enumerate(faltan, 1):
        z = z2025(lon, lat)
        valores[(lon, lat)] = np.nan if z is None else z
        time.sleep(0.1)
        if i % 500 == 0 or i == len(faltan):
            guardar_cache(CACHE_2025, valores)
            print(f"  {i:,}/{len(faltan):,}")
    return valores


def consultar_srtm(puntos):
    valores = leer_cache(CACHE_SRTM)
    faltan = [p for p in puntos if p not in valores]
    print(f"SRTM: {len(puntos):,} puntos, {len(faltan):,} por consultar ({int(np.ceil(len(faltan) / 100))} consultas)")
    sesion = requests.Session()
    for i in range(0, len(faltan), 100):
        lote = faltan[i:i + 100]
        params = {"locations": "|".join(f"{lat},{lon}" for lon, lat in lote)}
        for intento in range(1, 4):
            try:
                r = sesion.get(SRTM_URL, params=params, timeout=60)
                r.raise_for_status()
                resultados = r.json()["results"]
                break
            except Exception as e:
                if intento == 3:
                    guardar_cache(CACHE_SRTM, valores)
                    sys.exit(f"Open Topo Data no respondio ({e}). Lo avanzado quedo en cache; vuelva a correr mas tarde.")
                time.sleep(5 * intento)
        if len(resultados) != len(lote):
            sys.exit("Open Topo Data devolvio un numero de resultados distinto al de puntos enviados.")
        for (lon, lat), res in zip(lote, resultados):
            valores[(lon, lat)] = np.nan if res.get("elevation") is None else float(res["elevation"])
        guardar_cache(CACHE_SRTM, valores)
        time.sleep(1.1)
    return valores


def nombre_tesela(lon, lat):
    """Nombre de la tesela de 1 x 1 grado de Copernicus que contiene el punto."""
    la, lo = math.floor(lat), math.floor(lon)
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}_00_{'E' if lo >= 0 else 'W'}{abs(lo):03d}_00"


def consultar_copernicus(puntos):
    import rasterio
    valores = {}
    por_tesela = {}
    for p in puntos:
        por_tesela.setdefault(nombre_tesela(*p), []).append(p)
    for tesela, lista in sorted(por_tesela.items()):
        ruta = C.CARPETA_ENTRADAS / f"copernicus_dem_{tesela}.tif"
        if not ruta.exists():
            print(f"Copernicus: descargando la tesela {tesela} (una sola vez)...")
            with requests.get(COPERNICUS_URL.format(t=tesela), stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(ruta, "wb") as f:
                    for bloque in r.iter_content(chunk_size=1024 * 1024):
                        f.write(bloque)
        h = hashlib.sha256()
        with open(ruta, "rb") as f:
            for bloque in iter(lambda: f.read(1024 * 1024), b""):
                h.update(bloque)
        print(f"Copernicus: tesela {tesela}, {len(lista):,} puntos, SHA256 {h.hexdigest()}")
        with rasterio.open(ruta) as r:
            b = r.bounds
            fuera = [p for p in lista if not (b.left <= p[0] < b.right and b.bottom <= p[1] < b.top)]
            if fuera:
                sys.exit(f"{len(fuera)} puntos quedan fuera de la tesela {tesela}; revise la asignacion de teselas.")
            z = np.array([v[0] for v in r.sample(lista)], dtype=float)
            if r.nodata is not None:
                z[z == r.nodata] = np.nan
        valores.update(zip(lista, z))
    print(f"Copernicus: {int(np.isnan(list(valores.values())).sum())} puntos sin dato")
    return valores


def clase_invias(a):
    return np.where(a < 3, "Plano", np.where(a < 6, "Ondulado", np.where(a <= 8, "Montañoso", "Escarpado")))


def comparar(t, col, nombre_grupo, grupo):
    """Diferencias frente al MDT 2020. Usa el peso de cada clase en la ciudad,
    para que la fila "toda la ciudad" no quede sesgada por la muestra estratificada."""
    k = t.dropna(subset=["neta_2020", col])
    if k.empty:
        return None
    w = k["peso"] / k["peso"].sum()
    d = k[col] - k["neta_2020"]
    media = lambda x: float((w * x).sum())
    mx, my = media(k["neta_2020"]), media(k[col])
    cov = media((k["neta_2020"] - mx) * (k[col] - my))
    corr = cov / np.sqrt(media((k["neta_2020"] - mx) ** 2) * media((k[col] - my) ** 2))
    return {"modelo": col.replace("neta_", ""), "grupo": nombre_grupo, "valor_grupo": grupo, "segmentos": len(k),
            "sesgo_pp": media(d), "rmse_pp": float(np.sqrt(media(d ** 2))), "mediana_dif_abs_pp": d.abs().median(),
            "correlacion": corr,
            "misma_clase_invias_pct": 100 * media(clase_invias(k[col].abs()) == clase_invias(k["neta_2020"].abs())),
            "neta_exactamente_cero_pct": 100 * media(k[col] == 0),
            "extrema_mayor_35_pct": 100 * media(k[col].abs() > 35),
            "extrema_mayor_35_pct_2020": 100 * media(k["neta_2020"].abs() > 35)}


def main():
    df = pd.read_csv(C.ARCHIVO_PENDIENTES, float_precision="round_trip")
    con = df[~df["fuera_cobertura_mdt"].astype(str).eq("True")].copy()
    con["tramo_fisico"] = con["segmento_id"].str.rsplit("_", n=1).str[0]
    con = con.sort_values("segmento_id").drop_duplicates("tramo_fisico")
    muestra = pd.concat([g.sample(n=min(N_POR_CLASE, len(g)), random_state=SEMILLA)
                         for _, g in con.groupby("clasificacion_invias")])
    tamano_ciudad = con["clasificacion_invias"].value_counts()
    tamano_muestra = muestra["clasificacion_invias"].value_counts()
    muestra["peso"] = muestra["clasificacion_invias"].map(tamano_ciudad / tamano_muestra)
    print(f"Muestra: {len(muestra):,} segmentos ({N_POR_CLASE} por clase, semilla {SEMILLA})")
    print(muestra["clasificacion_invias"].value_counts().to_string())

    seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)
    seg = seg[seg["segmento_id"].isin(muestra["segmento_id"])][["segmento_id", "longitud_m", "geometry"]]
    # Primer y ultimo vertice de la geometria: los mismos puntos que usa la etapa.
    geo = seg.to_crs(C.CRS_CONSULTA).geometry
    seg["p_ini"] = [(round(g.coords[0][0], DECIMALES), round(g.coords[0][1], DECIMALES)) for g in geo]
    seg["p_fin"] = [(round(g.coords[-1][0], DECIMALES), round(g.coords[-1][1], DECIMALES)) for g in geo]
    t = muestra.merge(seg.drop(columns="geometry"), on="segmento_id")

    puntos = sorted(set(t["p_ini"]) | set(t["p_fin"]))
    v25 = consultar_2025(puntos)
    vsr = consultar_srtm(puntos)
    vcop = consultar_copernicus(puntos)

    L = t["longitud_m"].astype(float)
    t["neta_2020"] = t["pendiente_neta_pct"]
    t["neta_2025"] = 100 * (t["p_fin"].map(v25) - t["p_ini"].map(v25)) / L
    t["neta_srtm"] = 100 * (t["p_fin"].map(vsr) - t["p_ini"].map(vsr)) / L
    t["dz_ini_2025_m"] = t["p_ini"].map(v25) - t["z_inicio_m"]
    t["dz_ini_srtm_m"] = t["p_ini"].map(vsr) - t["z_inicio_m"]
    t["neta_cop30"] = 100 * (t["p_fin"].map(vcop) - t["p_ini"].map(vcop)) / L
    t["dz_ini_cop30_m"] = t["p_ini"].map(vcop) - t["z_inicio_m"]
    t["banda_longitud"] = pd.cut(L, [0, 20, 50, 100, np.inf], labels=["< 20 m", "20-50 m", "50-100 m", "> 100 m"])

    filas = []
    for col in ("neta_2025", "neta_srtm", "neta_cop30"):
        filas.append(comparar(t, col, "toda la ciudad", "ponderado por clase"))
        for clase in C.ETIQUETAS_INVIAS:
            filas.append(comparar(t[t["clasificacion_invias"] == clase], col, "clase INVIAS 2020", clase))
        filas.append(comparar(t[t["clasificacion_invias"] == "Plano"], col, "terreno", "plano (< 3 %)"))
        filas.append(comparar(t[t["clasificacion_invias"] != "Plano"], col, "terreno", "con pendiente (>= 3 %)"))
        for banda in t["banda_longitud"].cat.categories:
            filas.append(comparar(t[t["banda_longitud"] == banda], col, "longitud", banda))
    resumen = pd.DataFrame([f for f in filas if f])
    for nombre, col in (("MDT 2025", "dz_ini_2025_m"), ("SRTM", "dz_ini_srtm_m"), ("Copernicus", "dz_ini_cop30_m")):
        d = t[col].dropna()
        print(f"Diferencia de elevacion frente al MDT 2020 ({nombre}): media {d.mean():+.2f} m, RMSE {np.sqrt((d ** 2).mean()):.2f} m")

    pd.set_option("display.width", 200)
    print("\nDiferencias de pendiente neta frente al MDT 2020 (pp = puntos porcentuales):")
    print(resumen.round(2).to_string(index=False))
    t.drop(columns=["p_ini", "p_fin"]).to_csv(CARPETA_AUX / "resolucion_segmentos.csv", index=False, encoding="utf-8-sig")
    resumen.to_csv(CARPETA_AUX / "resolucion_resumen.csv", index=False, encoding="utf-8-sig")
    print("\nGuardado: resolucion_segmentos.csv y resolucion_resumen.csv")


if __name__ == "__main__":
    main()
