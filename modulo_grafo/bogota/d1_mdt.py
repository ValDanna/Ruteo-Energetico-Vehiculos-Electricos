"""
d1_mdt.py — Acceso al Modelo Digital de Terreno de Bogota 2025.

Motivo de este modulo: la operacion getSamples del ImageServer devolvio
403 Forbidden. Este archivo hace dos cosas:

  1. `diagnosticar_acceso_mdt()` prueba seis formas distintas de leer elevacion
     y reporta cuales funcionan. Sirve para dejar documentado en la bitacora
     por que se eligio una via y no otra.

  2. Implementa la via alterna: descargar el raster por teselas vía WMS GetMap
     y muestrear localmente con rasterio.

La via del raster local NO es un parche: a escala de ciudad es la forma
correcta. Cientos de peticiones HTTP para Chapinero se vuelven decenas de
miles para Bogota. Bajar el raster una vez y muestrear en disco es mas rapido,
mas reproducible (el archivo queda guardado con su hash) y no depende de que el
servicio publico este arriba cuando la tutora corra el cuaderno.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from constantes_d1 import (
    CRS_METRICO, CRS_GEOGRAFICO, MDT_IMAGESERVER, ruta_cruda,
    RANGO_ELEVACION_M, SIGMA_CUANTIZACION_M,
)
from d1_red import sesion_http, sello_de_tiempo

MDT_WMS = f"{MDT_IMAGESERVER}/WMSServer"
CAPA_CRUDA = "modelodigitalterreno2025funcion:None"   # sin funcion de render
CAPA_BASE = "modelodigitalterreno2025funcion"

# Punto de prueba en zona urbana de Bogota.
PRUEBA_X9377, PRUEBA_Y9377 = 4_867_000.0, 2_050_000.0
PRUEBA_LON, PRUEBA_LAT = -74.0600, 4.6500

# RANGO_ELEVACION_M y SIGMA_CUANTIZACION_M ahora vienen de constantes_d1
# (regla del equipo: las convenciones compartidas viven en un solo archivo).

# Incertidumbre vertical efectiva del muestreo, en metros.
#
# ATENCION: el RMSE del LiDAR que entra aqui (0,114 m) esta marcado
# [SIN FUENTE] en constantes_d1 y esta EN CONFLICTO con la medicion de Danna
# contra 84 vertices del IGAC (0,54 m sin atipicos / 1,01 m con todos). El
# valor de abajo se conserva para no cambiar resultados anteriores en
# silencio, pero NO es el numero a citar en el informe: el sigma_z adoptado
# se decide con la tabla de sensibilidad. Ver constantes_d1, seccion 3.
#
# El termino de cuantizacion SI esta verificado: el servicio entrega uint32
# con alturas redondeadas a metro entero (comprobado 2026-09-18), de modo que
# 1/sqrt(12) = 0,289 m es un piso INDEPENDIENTE entre pixeles que no se
# cancela al restar alturas.
RMSE_Z_LIDAR_SIN_FUENTE_M = 0.114
PASO_CUANTIZACION_M = 1.0
SIGMA_Z_EFECTIVO = float(
    (RMSE_Z_LIDAR_SIN_FUENTE_M ** 2 + SIGMA_CUANTIZACION_M ** 2) ** 0.5
)

# Alias retrocompatible: varios modulos importan RMSE_Z_LIDAR_M.
RMSE_Z_LIDAR_M = RMSE_Z_LIDAR_SIN_FUENTE_M

# ===========================================================================
# 1. DIAGNOSTICO
# ===========================================================================

def diagnosticar_acceso_mdt(verboso: bool = True) -> pd.DataFrame:
    """Prueba seis formas de leer elevacion y reporta cual funciona."""
    sesion = sesion_http()
    resultados = []

    def registrar(metodo, ok, detalle, valor=None):
        resultados.append({"metodo": metodo, "funciona": ok,
                           "valor_prueba": valor, "detalle": str(detalle)[:180]})
        if verboso:
            marca = "OK  " if ok else "NO  "
            print(f"{marca} {metodo}")
            if valor is not None:
                print(f"       valor = {valor}")
            if not ok:
                print(f"       {str(detalle)[:150]}")

    # --- 1. Metadatos del servicio
    try:
        r = sesion.get(MDT_IMAGESERVER, params={"f": "json"}, timeout=60)
        r.raise_for_status()
        info = r.json()
        if "error" in info:
            registrar("ImageServer f=json", False, info["error"])
            info = {}
        else:
            registrar("ImageServer f=json", True,
                      f"capabilities={info.get('capabilities')} "
                      f"pixelType={info.get('pixelType')}")
    except Exception as exc:  # noqa: BLE001
        registrar("ImageServer f=json", False, exc)
        info = {}

    # --- 2. getSamples por GET
    try:
        geom = {"points": [[PRUEBA_X9377, PRUEBA_Y9377]],
                "spatialReference": {"wkid": 9377}}
        r = sesion.get(f"{MDT_IMAGESERVER}/getSamples", timeout=60, params={
            "geometry": json.dumps(geom),
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true", "f": "json"})
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            registrar("getSamples (GET)", False, d["error"])
        else:
            m = d.get("samples", [{}])
            registrar("getSamples (GET)", bool(m), "ok",
                      m[0].get("value") if m else None)
    except Exception as exc:  # noqa: BLE001
        registrar("getSamples (GET)", False, exc)

    # --- 3. identify
    try:
        geom = {"x": PRUEBA_X9377, "y": PRUEBA_Y9377,
                "spatialReference": {"wkid": 9377}}
        r = sesion.get(f"{MDT_IMAGESERVER}/identify", timeout=60, params={
            "geometry": json.dumps(geom), "geometryType": "esriGeometryPoint",
            "returnGeometry": "false", "f": "json"})
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            registrar("identify", False, d["error"])
        else:
            registrar("identify", d.get("value") is not None, "ok", d.get("value"))
    except Exception as exc:  # noqa: BLE001
        registrar("identify", False, exc)

    # --- 4. WMS GetFeatureInfo
    try:
        d_lon = 0.0005
        params = {
            "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
            "layers": CAPA_BASE, "query_layers": CAPA_BASE, "crs": "CRS:84",
            "bbox": f"{PRUEBA_LON - d_lon},{PRUEBA_LAT - d_lon},"
                    f"{PRUEBA_LON + d_lon},{PRUEBA_LAT + d_lon}",
            "width": 101, "height": 101, "i": 50, "j": 50,
            "info_format": "application/geo+json", "format": "image/png",
        }
        r = sesion.get(MDT_WMS, params=params, timeout=60)
        r.raise_for_status()
        texto = r.text[:400]
        ok = ("value" in texto.lower() or "pixel" in texto.lower()
              or "properties" in texto.lower())
        registrar("WMS GetFeatureInfo", ok, texto)
    except Exception as exc:  # noqa: BLE001
        registrar("WMS GetFeatureInfo", False, exc)

    # --- 5. WMS GetMap en GeoTIFF, capa cruda
    for capa, etiqueta in ((CAPA_CRUDA, "WMS GetMap tiff (capa :None)"),
                           (CAPA_BASE, "WMS GetMap tiff (capa base)")):
        try:
            d_lon = 0.002
            params = {
                "service": "WMS", "version": "1.3.0", "request": "GetMap",
                "layers": capa, "styles": "", "crs": "CRS:84",
                "bbox": f"{PRUEBA_LON - d_lon},{PRUEBA_LAT - d_lon},"
                        f"{PRUEBA_LON + d_lon},{PRUEBA_LAT + d_lon}",
                "width": 256, "height": 256, "format": "image/tiff",
            }
            r = sesion.get(MDT_WMS, params=params, timeout=90)
            r.raise_for_status()
            tipo = r.headers.get("Content-Type", "")
            if "xml" in tipo or "html" in tipo:
                registrar(etiqueta, False, r.text[:200])
                continue
            valor, detalle = _inspeccionar_tiff(r.content)
            registrar(etiqueta, valor is not None, detalle, valor)
        except Exception as exc:  # noqa: BLE001
            registrar(etiqueta, False, exc)

    tabla = pd.DataFrame(resultados)

    if verboso:
        print()
        funcionan = tabla[tabla["funciona"]]["metodo"].tolist()
        if funcionan:
            print(f"Metodos disponibles: {', '.join(funcionan)}")
            if any("GetMap" in m for m in funcionan):
                print("Use la via del raster: descargar_mdt_teselado() + "
                      "muestrear_elevacion_local()")
            elif any("getSamples" in m or "identify" in m for m in funcionan):
                print("Use la via punto a punto del ImageServer.")
        else:
            print("Ningun metodo funciona. Revise VPN, proxy o cortafuegos.")

    return tabla


def _inspeccionar_tiff(contenido: bytes):
    """Abre un GeoTIFF en memoria y devuelve un valor y una descripcion."""
    try:
        import rasterio
        from rasterio.io import MemoryFile
    except ImportError:
        return None, "falta rasterio: pip install rasterio"

    try:
        with MemoryFile(contenido) as mem, mem.open() as src:
            arr = src.read(1, masked=True)
            detalle = (f"dtype={src.dtypes[0]} bandas={src.count} "
                       f"crs={src.crs} min={float(arr.min()):.1f} "
                       f"max={float(arr.max()):.1f}")
            centro = float(arr[arr.shape[0] // 2, arr.shape[1] // 2])
            # Una elevacion de Bogota esta entre 2.400 y 3.700 m. Si el valor
            # cae entre 0 y 255 es casi seguro una imagen renderizada, no
            # elevacion cruda.
            if 0 <= centro <= 255 and src.dtypes[0].startswith("uint8"):
                return centro, "CUIDADO: parece imagen renderizada, no elevacion. " + detalle
            return round(centro, 2), detalle
    except Exception as exc:  # noqa: BLE001
        return None, f"no se pudo leer el tiff: {exc}"


# ===========================================================================
# 2. DESCARGA DEL RASTER POR TESELAS
# ===========================================================================

def descargar_mdt_teselado(limite_gdf,
                           resolucion_m: float = 1.0,
                           lado_tesela_px: int = 2048,
                           margen_m: float = 200.0,
                           capa: str = CAPA_CRUDA,
                           carpeta=None,
                           verboso: bool = True) -> dict:
    """Descarga el MDT que cubre un poligono, por teselas, vía WMS GetMap.

    Devuelve un dict con la ruta del mosaico, los hashes y la bitacora.
    El margen evita que los segmentos del borde queden sin dato.
    """
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.merge import merge as rio_merge

    sesion = sesion_http()
    carpeta = Path(carpeta) if carpeta else ruta_cruda()
    carpeta.mkdir(parents=True, exist_ok=True)
    carpeta_teselas = carpeta / "mdt_teselas"
    carpeta_teselas.mkdir(exist_ok=True)

    # Bounding box con margen, en el CRS metrico, luego a geograficas.
    limite_m = limite_gdf.to_crs(CRS_METRICO)
    minx, miny, maxx, maxy = limite_m.total_bounds
    minx, miny = minx - margen_m, miny - margen_m
    maxx, maxy = maxx + margen_m, maxy + margen_m

    ancho_m, alto_m = maxx - minx, maxy - miny
    px_total_x = int(math.ceil(ancho_m / resolucion_m))
    px_total_y = int(math.ceil(alto_m / resolucion_m))
    n_col = int(math.ceil(px_total_x / lado_tesela_px))
    n_fil = int(math.ceil(px_total_y / lado_tesela_px))

    if verboso:
        print(f"Area: {ancho_m/1000:.2f} x {alto_m/1000:.2f} km")
        print(f"Resolucion pedida: {resolucion_m} m")
        print(f"Pixeles totales: {px_total_x:,} x {px_total_y:,}")
        print(f"Teselas: {n_col} x {n_fil} = {n_col * n_fil}")
        print()

    paso_x = ancho_m / n_col
    paso_y = alto_m / n_fil

    import geopandas as gpd
    from shapely.geometry import box

    rutas = []
    bitacora_teselas = []

    for fila in range(n_fil):
        for col in range(n_col):
            x0 = minx + col * paso_x
            x1 = x0 + paso_x
            y0 = miny + fila * paso_y
            y1 = y0 + paso_y

            # Convertir la caja a geograficas: el WMS solo anuncia 4326/CRS:84.
            caja = gpd.GeoDataFrame(geometry=[box(x0, y0, x1, y1)],
                                    crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
            glon0, glat0, glon1, glat1 = caja.total_bounds

            ancho_px = min(lado_tesela_px,
                           max(16, int(math.ceil((x1 - x0) / resolucion_m))))
            alto_px = min(lado_tesela_px,
                          max(16, int(math.ceil((y1 - y0) / resolucion_m))))

            nombre = f"mdt_t{fila:02d}_{col:02d}.tif"
            destino = carpeta_teselas / nombre

            if destino.exists() and destino.stat().st_size > 1000:
                if verboso:
                    print(f"  {nombre} ya existe, se omite")
                rutas.append(destino)
                continue

            params = {
                "service": "WMS", "version": "1.3.0", "request": "GetMap",
                "layers": capa, "styles": "", "crs": "CRS:84",
                "bbox": f"{glon0},{glat0},{glon1},{glat1}",
                "width": ancho_px, "height": alto_px, "format": "image/tiff",
            }

            for intento in range(4):
                try:
                    r = sesion.get(MDT_WMS, params=params, timeout=300)
                    r.raise_for_status()
                    tipo = r.headers.get("Content-Type", "")
                    if "xml" in tipo or "html" in tipo:
                        raise RuntimeError(f"el WMS devolvio error: {r.text[:200]}")
                    destino.write_bytes(r.content)
                    break
                except Exception as exc:  # noqa: BLE001
                    if intento == 3:
                        raise RuntimeError(
                            f"No se pudo descargar {nombre}: {exc}") from exc
                    time.sleep(4 * (intento + 1))

            sha = hashlib.sha256(destino.read_bytes()).hexdigest()
            bitacora_teselas.append({
                "tesela": nombre, "bbox_wgs84": [glon0, glat0, glon1, glat1],
                "ancho_px": ancho_px, "alto_px": alto_px,
                "sha256_16": sha,
                "bytes": destino.stat().st_size,
            })
            rutas.append(destino)
            if verboso:
                print(f"  {nombre}  {destino.stat().st_size/1e6:6.2f} MB  sha={sha}")

    # Unir las teselas en un solo raster.
    if verboso:
        print("\nUniendo teselas...")

    fuentes = [rasterio.open(p) for p in rutas]
    try:
        mosaico, transformacion = rio_merge(fuentes)
        perfil = fuentes[0].profile.copy()
        perfil.update(height=mosaico.shape[1], width=mosaico.shape[2],
                      transform=transformacion, compress="deflate",
                      tiled=True, blockxsize=512, blockysize=512)
        ruta_mosaico = carpeta / "mdt_bogota2025_sector.tif"
        with rasterio.open(ruta_mosaico, "w", **perfil) as dst:
            dst.write(mosaico)
    finally:
        for f in fuentes:
            f.close()

    sha_mosaico = _sha256_archivo(ruta_mosaico)

    bitacora = {
        "fuente": "IDECA - MDT Bogota 2025 (WMS GetMap)",
        "url_wms": MDT_WMS,
        "capa": capa,
        "licencia": "CC BY 4.0",
        "fecha_descarga": sello_de_tiempo(),
        "resolucion_solicitada_m": resolucion_m,
        "bbox_9377": [minx, miny, maxx, maxy],
        "margen_m": margen_m,
        "n_teselas": len(rutas),
        "teselas": bitacora_teselas,
        "mosaico": str(ruta_mosaico.name),
        "sha256_mosaico": sha_mosaico,
    }

    with open(carpeta / "bitacora_mdt.json", "w", encoding="utf-8") as f:
        json.dump(bitacora, f, indent=2, ensure_ascii=False)

    if verboso:
        with rasterio.open(ruta_mosaico) as src:
            arr = src.read(1, masked=True)
            print(f"\nMosaico: {ruta_mosaico}")
            print(f"  tamano: {src.width:,} x {src.height:,} px")
            print(f"  dtype: {src.dtypes[0]}   CRS: {src.crs}")
            print(f"  elevacion: min={float(arr.min()):.1f} "
                  f"max={float(arr.max()):.1f} m")
            print(f"  sha256: {sha_mosaico[:16]}")
            if float(arr.max()) <= 255:
                print("\n  ATENCION: el maximo es <= 255. Eso sugiere una imagen")
                print("  renderizada y no elevacion. Revise el diagnostico.")

    return {"ruta_mosaico": ruta_mosaico, "bitacora": bitacora}


def _sha256_archivo(ruta) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


# ===========================================================================
# 3. MUESTREO LOCAL
# ===========================================================================

def muestrear_elevacion_local(puntos, ruta_raster,
                              rmse_z_por_defecto: float = SIGMA_Z_EFECTIVO,
                              verboso: bool = True) -> pd.DataFrame:
    """Muestrea elevacion sobre un raster local. Reemplaza a muestrear_elevacion.

    `puntos` son shapely Points en CRS_METRICO (EPSG:9377).
    Devuelve el mismo esquema de columnas que la version por servicio, para que
    el resto del cuaderno no cambie.

    Dos limitaciones que deben declararse en el informe:

    1. Por esta via NO se sabe de cual de los tres DEM del mosaico provino cada
       celda, porque el WMS entrega el mosaico ya integrado.
    2. El WMS entrega la elevacion redondeada a metro entero. Eso agrega un
       error de cuantizacion de 1/sqrt(12) = 0,289 m, mayor que el RMSE del
       propio LiDAR. La incertidumbre efectiva usada es SIGMA_Z_EFECTIVO.
    """
    import rasterio
    import geopandas as gpd
    from shapely.geometry import Point

    with rasterio.open(ruta_raster) as src:
        crs_raster = src.crs
        nodata = src.nodata

        gdf = gpd.GeoDataFrame(geometry=list(puntos), crs=CRS_METRICO)
        if crs_raster is not None and gdf.crs.to_string() != crs_raster.to_string():
            gdf_r = gdf.to_crs(crs_raster)
        else:
            gdf_r = gdf

        coords_raster = [(p.x, p.y) for p in gdf_r.geometry]

        if verboso:
            print(f"Muestreando {len(coords_raster):,} puntos sobre "
                  f"{Path(ruta_raster).name}...")
        t0 = time.time()
        valores = list(src.sample(coords_raster, indexes=1, masked=True))
        if verboso:
            print(f"  {time.time() - t0:.1f} s")

    elevaciones = []
    for v in valores:
        try:
            if np.ma.is_masked(v) or v is None:
                elevaciones.append(np.nan)
                continue
            val = float(np.asarray(v).ravel()[0])
            if nodata is not None and val == nodata:
                val = np.nan
            # El raster llega del WMS como entero sin signo: el NoData se
            # codifica como 0 y no como NaN. Bogota esta entre 2.400 y 3.700 m
            # s. n. m., asi que cualquier valor fuera de 2.000-4.000 es ausencia
            # de dato, no elevacion. Sin este filtro, un extremo en 0 produce
            # pendientes de cientos por ciento.
            if not (RANGO_ELEVACION_M[0] <= val <= RANGO_ELEVACION_M[1]):
                val = np.nan
            elevaciones.append(val)
        except Exception:  # noqa: BLE001
            elevaciones.append(np.nan)

    df = pd.DataFrame({
        "indice": range(len(puntos)),
        "x": [p.x for p in puntos],
        "y": [p.y for p in puntos],
        "elevacion_m": elevaciones,
    })
    df["resolucion_m"] = np.nan
    df["zona_mdt"] = "mosaico_integrado"
    df["rmse_z_m"] = rmse_z_por_defecto

    if verboso:
        n_nan = int(df["elevacion_m"].isna().sum())
        print(f"  sin dato: {n_nan:,} ({100 * n_nan / len(df):.2f} %)")
        print(f"  elevacion: {df['elevacion_m'].min():.1f} a "
              f"{df['elevacion_m'].max():.1f} m")

    return df


def consultar_elevacion_wms(x9377: float, y9377: float,
                            tiempo_espera: int = 60) -> float:
    """Consulta la elevacion de un punto vía WMS GetFeatureInfo.

    Es una via INDEPENDIENTE del raster descargado: pregunta al servidor por ese
    punto en concreto. Sirve para la verificacion cruzada, ahora que la API REST
    del ImageServer (getSamples, identify) devuelve 403.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    sesion = sesion_http()

    # A geograficas: el WMS solo acepta CRS:84 / EPSG:4326.
    g = gpd.GeoDataFrame(geometry=[Point(x9377, y9377)],
                         crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
    lon, lat = float(g.geometry.iloc[0].x), float(g.geometry.iloc[0].y)

    # Ventana pequena centrada en el punto. Con 101x101 pixeles, el pixel
    # central (50,50) corresponde al punto pedido.
    d = 0.0002
    params = {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": CAPA_CRUDA, "query_layers": CAPA_CRUDA, "crs": "CRS:84",
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "width": 101, "height": 101, "i": 50, "j": 50,
        "info_format": "application/geo+json", "format": "image/png",
    }

    r = sesion.get(MDT_WMS, params=params, timeout=tiempo_espera)
    r.raise_for_status()
    return _extraer_valor_featureinfo(r.text)


def _extraer_valor_featureinfo(texto: str) -> float:
    """Saca el valor de pixel de una respuesta de GetFeatureInfo.

    El formato varia entre servidores, asi que se intenta GeoJSON, luego XML y
    por ultimo se busca cualquier numero verosimil como elevacion de Bogota.
    """
    import re

    # --- GeoJSON
    try:
        datos = json.loads(texto)
        feats = datos.get("features") or []
        for f in feats:
            props = f.get("properties", {}) or {}
            for clave in ("Pixel Value", "value", "Value", "PixelValue",
                          "GRAY_INDEX", "band_1", "Band_1"):
                if clave in props:
                    return _a_float(props[clave])
            for v in props.values():
                val = _a_float(v)
                if val is not None and -100 < val < 6000:
                    return val
    except (json.JSONDecodeError, AttributeError):
        pass

    # --- XML de Esri
    for patron in (r'value\s*=\s*"([-\d.]+)"',
                   r'<value>([-\d.]+)</value>',
                   r'Pixel Value[^\d\-]*([-\d.]+)'):
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            val = _a_float(m.group(1))
            if val is not None:
                return val

    # --- ultimo recurso: cualquier numero en rango de elevacion de Bogota
    for token in re.findall(r"-?\d+\.?\d*", texto):
        val = _a_float(token)
        if val is not None and 1000 < val < 6000:
            return val

    return float("nan")


def _a_float(v):
    try:
        if v is None:
            return None
        s = str(v).strip().split()[0]
        if s.lower() in ("nodata", "nan", "", "null"):
            return None
        return float(s)
    except (ValueError, IndexError, TypeError):
        return None


def verificar_muestreo_contra_wms(df_local: pd.DataFrame,
                                  n_puntos: int = 40,
                                  tolerancia_m: float = 1.0,
                                  semilla: int = 42,
                                  verboso: bool = True) -> dict:
    """Verificacion independiente del raster descargado, vía GetFeatureInfo.

    Toma puntos al azar ya medidos sobre el raster local y vuelve a preguntar su
    elevacion al servidor, uno por uno. Si las dos vias coinciden, el raster que
    se descargo es el mismo dato que sirve IDECA.

    Es el reemplazo de la verificacion contra getSamples, que quedo bloqueada.
    Cumple la regla 3 del equipo: el numero se recalcula por un camino distinto
    al que lo produjo.

    Se usan pocos puntos (40 por defecto) porque cada uno es una peticion HTTP.
    La tolerancia de 1 m contempla que el servidor y el raster pueden caer en
    celdas vecinas por redondeo de la ventana de consulta.
    """
    validos = df_local[df_local["elevacion_m"].notna()]
    if len(validos) == 0:
        return {"prueba": "raster local vs WMS GetFeatureInfo",
                "pasa": False, "disponible": False,
                "motivo": "no hay elevaciones validas en el raster"}

    muestra = validos.sample(min(n_puntos, len(validos)), random_state=semilla)

    difs, fallos, comparados = [], 0, []
    for k, (_, fila) in enumerate(muestra.iterrows(), start=1):
        try:
            del_servidor = consultar_elevacion_wms(fila["x"], fila["y"])
            if del_servidor is None or np.isnan(del_servidor):
                fallos += 1
            else:
                d = abs(del_servidor - fila["elevacion_m"])
                difs.append(d)
                comparados.append({"x": fila["x"], "y": fila["y"],
                                   "local": round(fila["elevacion_m"], 2),
                                   "servidor": round(del_servidor, 2),
                                   "dif_m": round(d, 3)})
        except Exception:  # noqa: BLE001
            fallos += 1
        if verboso:
            print(f"  consultados {k}/{len(muestra)}  "
                  f"(fallidos: {fallos})", end="\r")
        time.sleep(0.15)   # cortesia con el servicio publico

    if verboso:
        print()

    if not difs:
        return {"prueba": "raster local vs WMS GetFeatureInfo",
                "pasa": False, "disponible": False,
                "motivo": f"ninguna consulta devolvio valor ({fallos} fallos)",
                "nota": "Declarar en la bitacora que esta verificacion cruzada "
                        "no pudo ejecutarse, y por que."}

    difs = np.array(difs)
    n_malos = int((difs > tolerancia_m).sum())

    salida = {
        "prueba": "raster local vs WMS GetFeatureInfo",
        "disponible": True,
        "n_comparados": len(difs),
        "n_consultas_fallidas": fallos,
        "diferencia_maxima_m": round(float(difs.max()), 3),
        "diferencia_mediana_m": round(float(np.median(difs)), 3),
        "diferencia_media_m": round(float(difs.mean()), 3),
        "n_fuera_de_tolerancia": n_malos,
        "tolerancia_m": tolerancia_m,
        "pasa": n_malos == 0,
    }
    if n_malos:
        salida["peores"] = sorted(comparados, key=lambda c: -c["dif_m"])[:5]
    return salida


def verificar_muestreo_contra_servicio(df_local: pd.DataFrame,

                                       n_puntos: int = 100,
                                       tolerancia_m: float = 0.5,
                                       semilla: int = 42) -> dict:
    """Verificacion independiente: compara el muestreo local contra el servicio.

    Toma una muestra al azar de puntos ya medidos sobre el raster y los vuelve a
    pedir al ImageServer punto a punto. Si las dos vias coinciden, el raster
    descargado es el mismo dato que sirve el servicio.

    Requiere que alguna via punto a punto funcione. Si no, devuelve
    `disponible=False` y eso mismo debe anotarse en la bitacora.
    """
    from d1_red import _pedir_muestras

    validos = df_local[df_local["elevacion_m"].notna()]
    if len(validos) == 0:
        return {"prueba": "raster local vs servicio", "disponible": False,
                "motivo": "no hay elevaciones validas", "pasa": False}

    muestra = validos.sample(min(n_puntos, len(validos)), random_state=semilla)
    coords = list(zip(muestra["x"], muestra["y"]))

    try:
        respuesta = _pedir_muestras(coords, reintentos=2)
    except Exception as exc:  # noqa: BLE001
        return {"prueba": "raster local vs servicio", "disponible": False,
                "motivo": f"el servicio punto a punto no responde: "
                          f"{type(exc).__name__}",
                "pasa": False,
                "nota": "Declarar en la bitacora que esta verificacion cruzada "
                        "no pudo ejecutarse y por que."}

    del_servicio = {}
    for m in respuesta:
        try:
            del_servicio[int(m["locationId"])] = float(str(m["value"]).split()[0])
        except (KeyError, ValueError, TypeError):
            continue

    difs = []
    for j, (_, fila) in enumerate(muestra.iterrows()):
        if j in del_servicio:
            difs.append(abs(del_servicio[j] - fila["elevacion_m"]))

    if not difs:
        return {"prueba": "raster local vs servicio", "disponible": False,
                "motivo": "el servicio no devolvio valores comparables",
                "pasa": False}

    difs = np.array(difs)
    n_malos = int((difs > tolerancia_m).sum())
    return {
        "prueba": "raster local vs servicio",
        "disponible": True,
        "n_comparados": len(difs),
        "diferencia_maxima_m": round(float(difs.max()), 3),
        "diferencia_mediana_m": round(float(np.median(difs)), 3),
        "n_fuera_de_tolerancia": n_malos,
        "pasa": n_malos == 0,
    }

def verificar_mosaico_contra_getmap(df_local, ruta_raster,
                                    n_ventanas: int = 4,
                                    lado_m: float = 400.0,
                                    tolerancia_m: float = 1.0,
                                    fraccion_borde_admitida: float = 0.05,
                                    semilla: int = 42,
                                    verboso: bool = True) -> dict:
    """Verifica el mosaico descargado contra ventanas pedidas de nuevo al WMS.

    Reemplaza a `verificar_muestreo_contra_wms`, que resulto invalida:
    GetFeatureInfo en un ImageServer NO devuelve el valor del pixel, sino la
    ficha del catalogo del mosaico (nombre de tesela, OBJECTID, resolucion).
    El parser tomaba el OBJECTID por elevacion.

    Aqui se pide de nuevo al servidor una ventana pequena, con otro recorte y
    otro teselado, y se comparan contra el mosaico todos los puntos que caen
    dentro. Verifica el georreferenciamiento de las teselas, la union del
    mosaico, la reproyeccion 9377 -> CRS del raster y el filtro de NoData.

    LIMITACION: no es independiente de la fuente, solo del procesamiento. Un
    error sistematico del propio servicio no se detectaria. Declararlo asi.

    Se admite una fraccion pequena de puntos fuera de tolerancia: la ventana
    nueva y el mosaico tienen rejillas de pixel distintas, de modo que un punto
    sobre el borde de una celda puede caer en celdas vecinas.
    """
    import geopandas as gpd
    from shapely.geometry import box
    from rasterio.io import MemoryFile
    import rasterio

    sesion = sesion_http()
    validos = df_local[df_local["elevacion_m"].notna()]
    if len(validos) == 0:
        return {"prueba": "mosaico vs ventana nueva del WMS", "pasa": False,
                "disponible": False, "motivo": "no hay elevaciones validas"}

    centros = validos.sample(min(n_ventanas, len(validos)), random_state=semilla)

    difs, n_vent, fallos = [], 0, 0
    for k, (_, c) in enumerate(centros.iterrows(), start=1):
        caja = gpd.GeoDataFrame(
            geometry=[box(c["x"] - lado_m / 2, c["y"] - lado_m / 2,
                          c["x"] + lado_m / 2, c["y"] + lado_m / 2)],
            crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
        a, b, cc, d = caja.total_bounds
        lado_px = int(max(64, min(2048, lado_m)))

        try:
            r = sesion.get(MDT_WMS, timeout=180, params={
                "service": "WMS", "version": "1.3.0", "request": "GetMap",
                "layers": CAPA_CRUDA, "styles": "", "crs": "CRS:84",
                "bbox": f"{a},{b},{cc},{d}",
                "width": lado_px, "height": lado_px, "format": "image/tiff"})
            r.raise_for_status()
            if "xml" in r.headers.get("Content-Type", ""):
                raise RuntimeError(r.text[:150])
        except Exception:  # noqa: BLE001
            fallos += 1
            continue

        with MemoryFile(r.content) as mem, mem.open() as src:
            gp = gpd.GeoDataFrame(
                geometry=gpd.points_from_xy(validos["x"], validos["y"]),
                crs=CRS_METRICO).to_crs(src.crs)
            xs = np.array([p.x for p in gp.geometry])
            ys = np.array([p.y for p in gp.geometry])
            dentro = (xs >= a) & (xs <= cc) & (ys >= b) & (ys <= d)
            if not dentro.any():
                continue
            n_vent += 1
            frescos = [float(v[0]) for v in
                       src.sample(list(zip(xs[dentro], ys[dentro])))]
            locales = validos["elevacion_m"].to_numpy()[dentro]
            for f, l in zip(frescos, locales):
                if not (RANGO_ELEVACION_M[0] <= f <= RANGO_ELEVACION_M[1]):
                    continue
                difs.append(abs(f - l))

        if verboso:
            print(f"  ventana {k}/{len(centros)} — acumulados "
                  f"{len(difs):,} puntos", end="\r")

    if verboso:
        print()

    if not difs:
        return {"prueba": "mosaico vs ventana nueva del WMS", "pasa": False,
                "disponible": False,
                "motivo": f"ninguna ventana devolvio puntos ({fallos} fallos)"}

    difs = np.array(difs)
    n_malos = int((difs > tolerancia_m).sum())
    frac = n_malos / len(difs)
    mediana = float(np.median(difs))

    return {
        "prueba": "mosaico vs ventana nueva del WMS",
        "disponible": True,
        "n_ventanas": n_vent,
        "n_comparados": len(difs),
        "diferencia_mediana_m": round(mediana, 3),
        "diferencia_maxima_m": round(float(difs.max()), 3),
        "n_fuera_de_tolerancia": n_malos,
        "fraccion_fuera": round(frac, 4),
        "tolerancia_m": tolerancia_m,
        "pasa": mediana <= tolerancia_m and frac <= fraccion_borde_admitida,
    }