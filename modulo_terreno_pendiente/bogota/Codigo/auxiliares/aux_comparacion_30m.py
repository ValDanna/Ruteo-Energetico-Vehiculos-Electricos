"""
aux_comparacion_30m.py
Comparacion de la pendiente del MDT 2020 (LiDAR, 0,5 m) con SRTM (30 m) y
Copernicus DEM GLO-30 en dos sectores de prueba.

La red es de OpenStreetMap (osmnx, network_type="drive"), no la
Malla Vial; la pendiente es de dos nodos; SRTM y GLO-30 son modelos de
superficie. Resultado del 21-09-2026: sector plano 324 tramos (RMSE 3,12 pp
SRTM y 3,49 pp GLO-30), sector cerros 109 tramos (6,53 y 4,69 pp).

En vez de consultar Copernicus DEM punto por punto (limitado a 50/día
sin cuenta académica), se descarga UNA sola vez el archivo de esa zona
directo del bucket público de AWS (gratis, sin límite, sin clave) y se
lee la elevación localmente.

Bogotá cabe completa en una sola tesela de 1°x1° (N04, W075), así que
basta con una descarga de unos ~100 MB, una sola vez.

SRTM se sigue consultando con Open Topo Data (gratis, sin clave, ya
usado en la tarea 5 original, límites mucho más generosos).

Requisitos:
    pip install osmnx pandas requests rasterio
"""

import time
from datetime import datetime

from _comun import CARPETA_AUX

import osmnx as ox
import pandas as pd
import rasterio
import requests

ox.settings.overpass_url = "https://overpass.kumi.systems/api"
ox.settings.overpass_rate_limit = False
ox.settings.requests_timeout = 300

# ---------------------------------------------------------------------------
MDT2020_BASE_URL = (
    "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/"
    "topografia/modelodigitalterrenobogotaurbano/MapServer"
)
SRTM_BASE_URL = "https://api.opentopodata.org/v1/srtm30m"

# Bucket público de AWS (Sinergise), sin credenciales, sin límite 
# Bogotá (lat ~4.6N, lon ~-74.1) cae en la tesela N04 / W075.
COPERNICUS_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N04_00_W075_00_DEM/"
    "Copernicus_DSM_COG_10_N04_00_W075_00_DEM.tif"
)
ARCHIVO_COPERNICUS_LOCAL = str(CARPETA_AUX / "copernicus_dem_bogota.tif")

SECTORES = {
    "prueba": {"north": 4.655, "south": 4.645, "east": -74.075, "west": -74.085},
    "cerros_egipto": {"north": 4.600, "south": 4.592, "east": -74.065, "west": -74.072},
}

PAUSA_MDT2020 = 0.15
PAUSA_SRTM = 1.0

_sesion = requests.Session()


def consultar_elevacion_mdt2020(lon, lat, reintentos=3):
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "sr": "4326", "layers": "all", "tolerance": 1,
        "mapExtent": f"{lon-0.001},{lat-0.001},{lon+0.001},{lat+0.001}",
        "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json",
    }
    for intento in range(1, reintentos + 1):
        try:
            resp = _sesion.get(f"{MDT2020_BASE_URL}/identify", params=params, timeout=20)
            resultados = resp.json().get("results", [])
            if not resultados:
                return None
            valor = resultados[0]["attributes"].get("Stretch.Pixel Value")
            return None if valor in (None, "NoData") else float(valor)
        except Exception:
            if intento == reintentos:
                return None
            time.sleep(0.5 * intento)
    return None


def consultar_elevacion_srtm(lon, lat, reintentos=3):
    params = {"locations": f"{lat},{lon}"}
    for intento in range(1, reintentos + 1):
        try:
            resp = _sesion.get(SRTM_BASE_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            resultados = data.get("results", [])
            if not resultados:
                return None
            valor = resultados[0].get("elevation")
            return float(valor) if valor is not None else None
        except Exception:
            if intento == reintentos:
                return None
            time.sleep(1.0 * intento)
    return None


def descargar_tesela_copernicus():
    import os
    if os.path.exists(ARCHIVO_COPERNICUS_LOCAL):
        print(f"  Ya existe {ARCHIVO_COPERNICUS_LOCAL}, no se vuelve a descargar.")
        return

    print(f"  Descargando tesela de Copernicus DEM (una sola vez, ~decenas de MB)...")
    with _sesion.get(COPERNICUS_TILE_URL, stream=True, timeout=180) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        descargado = 0
        with open(ARCHIVO_COPERNICUS_LOCAL, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                descargado += len(chunk)
                if total:
                    print(f"    {descargado/1e6:.1f} / {total/1e6:.1f} MB...", end="\r")
    print(f"\n  Descarga completa: {ARCHIVO_COPERNICUS_LOCAL}")


def leer_elevacion_copernicus_local(raster, lon, lat):
    try:
        fila, columna = raster.index(lon, lat)
        valor = raster.read(1)[fila, columna]
        if valor == raster.nodata:
            return None
        return float(valor)
    except Exception:
        return None


if __name__ == "__main__":
    print(f"Inicio: {datetime.now().isoformat()}\n")

    print("Paso 1 — Copernicus DEM (descarga directa, una sola vez)...")
    descargar_tesela_copernicus()
    raster_copernicus = rasterio.open(ARCHIVO_COPERNICUS_LOCAL)
    print(f"  CRS de la tesela: {raster_copernicus.crs}")

    resumen_final = []

    for nombre_sector, bbox in SECTORES.items():
        print(f"\n{'#'*60}\nSECTOR: {nombre_sector}\n{'#'*60}")

        G = ox.graph_from_bbox(
            bbox=(bbox["west"], bbox["south"], bbox["east"], bbox["north"]),
            network_type="drive",
        )
        nodos, tramos = ox.graph_to_gdfs(G)
        print(f"Nodos: {len(nodos)}, Tramos: {len(tramos)}")

        elev_lidar, elev_srtm, elev_cop30 = {}, {}, {}
        for i, (nid, fila) in enumerate(nodos.iterrows(), start=1):
            lon, lat = fila.geometry.x, fila.geometry.y
            elev_lidar[nid] = consultar_elevacion_mdt2020(lon, lat)
            time.sleep(PAUSA_MDT2020)
            elev_srtm[nid] = consultar_elevacion_srtm(lon, lat)
            time.sleep(PAUSA_SRTM)
            elev_cop30[nid] = leer_elevacion_copernicus_local(raster_copernicus, lon, lat)
            if i % 30 == 0:
                print(f"  {i}/{len(nodos)} nodos consultados...")

        filas = []
        for (u, v, key), fila in tramos.iterrows():
            distancia_m = fila.get("length")

            def pend(elev_dict):
                e0, e1 = elev_dict.get(u), elev_dict.get(v)
                if e0 is None or e1 is None or not distancia_m:
                    return None
                return (e1 - e0) / distancia_m * 100

            filas.append({
                "nodo_inicio": u, "nodo_fin": v, "key": key, "distancia_m": distancia_m,
                "pendiente_lidar_pct": pend(elev_lidar),
                "pendiente_srtm_pct": pend(elev_srtm),
                "pendiente_cop30_pct": pend(elev_cop30),
            })
        base = pd.DataFrame(filas)

        for columna, nombre_fuente in [("pendiente_srtm_pct", "SRTM (30 m)"),
                                        ("pendiente_cop30_pct", "Copernicus DEM COP30 (30 m)")]:
            comp = base.dropna(subset=["pendiente_lidar_pct", columna])
            dif = comp["pendiente_lidar_pct"] - comp[columna]
            rmse = (dif ** 2).mean() ** 0.5
            corr = comp["pendiente_lidar_pct"].corr(comp[columna])
            print(f"  {nombre_fuente}: {len(comp)} tramos, RMSE={rmse:.2f} pp, correlación={corr:.3f}")
            resumen_final.append({"sector": nombre_sector, "fuente": nombre_fuente,
                                   "tramos": len(comp), "rmse_pp": rmse, "correlacion": corr})

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        base.to_csv(CARPETA_AUX / f"comparacion_30m_{nombre_sector}_{fecha}.csv", index=False)

    print(f"\n{'='*60}\nRESUMEN FINAL\n{'='*60}")
    print(pd.DataFrame(resumen_final).to_string(index=False))
