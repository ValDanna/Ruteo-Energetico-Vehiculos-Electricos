"""
d1_red.py — Capa de red del Bloque D1.

Reemplaza las funciones de descarga de d1_grafo.py. Corrige tres problemas
detectados en la primera ejecucion:

  1. Fallos intermitentes de DNS (getaddrinfo failed en Windows). Ahora todas
     las peticiones pasan por una sesion con reintentos y espera creciente.
  2. Se adivinaban los nombres de campo de la capa de localidades. Ahora se
     consulta la definicion de la capa y se descubren los campos reales.
  3. Los errores de ArcGIS se reportaban como "0 features". Ahora se muestra
     el mensaje que devuelve el servicio.

Uso en d1_grafo.py: borrar `descargar_limite_localidad` y `_pedir_muestras`,
y agregar arriba:

    from d1_red import (
        sesion_http, diagnostico_red,
        descargar_limite_localidad, cargar_limite_manual, _pedir_muestras,
    )
"""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # urllib3 antiguo
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

import geopandas as gpd

from constantes_d1 import CRS_METRICO, CRS_GEOGRAFICO, MDT_IMAGESERVER

ZONA_HORARIA_BOGOTA = timezone(timedelta(hours=-5))
HOST_IDECA = "serviciosgis.catastrobogota.gov.co"


def sello_de_tiempo() -> str:
    return datetime.now(ZONA_HORARIA_BOGOTA).isoformat(timespec="seconds")


# ===========================================================================
# Sesion HTTP con reintentos
# ===========================================================================

_SESION = None


def sesion_http(total_reintentos: int = 5, espera_base: float = 1.0):
    """Devuelve una sesion requests con reintentos automaticos.

    Reintenta ante errores de conexion (incluido el fallo de DNS que aparecio
    en la primera corrida) y ante respuestas 429, 500, 502, 503 y 504.
    La espera crece: 1 s, 2 s, 4 s, 8 s, 16 s.
    """
    global _SESION
    if _SESION is not None:
        return _SESION

    sesion = requests.Session()
    politica = Retry(
        total=total_reintentos,
        connect=total_reintentos,
        read=total_reintentos,
        status=total_reintentos,
        backoff_factor=espera_base,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=politica, pool_connections=10,
                            pool_maxsize=10)
    sesion.mount("https://", adaptador)
    sesion.mount("http://", adaptador)
    sesion.headers.update({
        "User-Agent": "TesisRuteoEnergeticoVE/1.0 (U. Externado, academico)"
    })
    _SESION = sesion
    return sesion


def diagnostico_red(host: str = HOST_IDECA, intentos: int = 5) -> dict:
    """Comprueba si el DNS resuelve de forma estable.

    Corra esto ANTES del muestreo del MDT. Si el DNS falla de forma
    intermitente, el muestreo (cientos de peticiones) no va a terminar.
    """
    resultados = []
    for i in range(intentos):
        t0 = time.time()
        try:
            ip = socket.gethostbyname(host)
            resultados.append({"intento": i + 1, "ok": True, "ip": ip,
                               "ms": round((time.time() - t0) * 1000, 1)})
        except socket.gaierror as exc:
            resultados.append({"intento": i + 1, "ok": False,
                               "error": str(exc),
                               "ms": round((time.time() - t0) * 1000, 1)})
        time.sleep(0.3)

    n_ok = sum(1 for r in resultados if r["ok"])
    tabla = pd.DataFrame(resultados)

    print(f"Resolucion DNS de {host}: {n_ok}/{intentos} intentos exitosos")
    print(tabla.to_string(index=False))

    if n_ok == 0:
        print("\nEl DNS no resuelve nunca. Posibles causas:")
        print("  - VPN o proxy activo que bloquea el dominio")
        print("  - DNS del proveedor con problemas")
        print("  Pruebe cambiar el DNS a 1.1.1.1 o 8.8.8.8, o desconectar la VPN.")
    elif n_ok < intentos:
        print("\nEl DNS resuelve de forma INTERMITENTE. Esto explica el error")
        print("de la primera corrida. La sesion con reintentos lo compensa,")
        print("pero el muestreo va a ir mas lento de lo normal.")
    else:
        print("\nDNS estable.")

    return {"host": host, "n_ok": n_ok, "n_intentos": intentos,
            "detalle": resultados, "estable": n_ok == intentos}


# ===========================================================================
# Limite de localidad
# ===========================================================================

# Endpoints ordenados por preferencia. El primero es el servicio oficial de
# IDECA; el segundo es un espejo de la CAR que publica la misma capa tomada del
# Mapa de Referencia de IDECA, y sirve cuando el primero no responde.
ENDPOINTS_LOCALIDAD = [
    {
        "url": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/"
               "ordenamientoterritorial/localidad/MapServer/0",
        "fuente": "IDECA - Localidad Bogota D.C. (servicio oficial)",
    },
    {
        "url": "https://sig.car.gov.co/arcgis/rest/services/visor/"
               "Division_Territorial/FeatureServer/5",
        "fuente": "CAR - Localidades Bogota (espejo del Mapa de Referencia IDECA)",
    },
]


def _describir_capa(url_capa: str, sesion, tiempo_espera: int = 60) -> dict:
    """Pregunta al servicio como se llaman sus campos, en vez de adivinar."""
    r = sesion.get(url_capa, params={"f": "json"}, timeout=tiempo_espera)
    r.raise_for_status()
    datos = r.json()
    if "error" in datos:
        raise RuntimeError(f"El servicio respondio con error: {datos['error']}")
    campos = [c.get("name") for c in datos.get("fields", [])]
    return {
        "nombre_capa": datos.get("name"),
        "campos": campos,
        "n_maximo_registros": datos.get("maxRecordCount"),
        "tipo_geometria": datos.get("geometryType"),
    }


def _campo_de_nombre(campos: list[str]) -> str | None:
    """Encuentra el campo que contiene el nombre de la localidad."""
    candidatos = [c for c in campos if c and "NOM" in c.upper()]
    if not candidatos:
        return None
    # Prefiere los que mencionen localidad explicitamente.
    for c in candidatos:
        if "LOC" in c.upper():
            return c
    return candidatos[0]


def descargar_limite_localidad(nombre: str = "CHAPINERO",
                               tiempo_espera: int = 90,
                               verboso: bool = True) -> gpd.GeoDataFrame:
    """Descarga el poligono de una localidad de Bogota.

    Estrategia: en lugar de adivinar el nombre del campo, se consulta la
    definicion de la capa, se descargan TODAS las localidades con where=1=1 y
    se filtra en memoria. Asi el filtrado no depende de la sintaxis SQL del
    servidor ni de mayusculas, tildes o espacios.
    """
    sesion = sesion_http()
    nombre_norm = _normalizar(nombre)
    errores = []

    for cfg in ENDPOINTS_LOCALIDAD:
        url_capa = cfg["url"]
        try:
            if verboso:
                print(f"Consultando {cfg['fuente']}...")
            info = _describir_capa(url_capa, sesion, tiempo_espera)
            campo = _campo_de_nombre(info["campos"])
            if verboso:
                print(f"  capa '{info['nombre_capa']}' — campo de nombre: {campo}")
            if campo is None:
                errores.append(f"{url_capa} -> sin campo de nombre. "
                               f"Campos: {info['campos']}")
                continue

            r = sesion.get(f"{url_capa}/query", timeout=tiempo_espera, params={
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": 4326,
                "f": "geojson",
            })
            r.raise_for_status()
            datos = r.json()

            if "error" in datos:
                errores.append(f"{url_capa} -> ArcGIS: {datos['error']}")
                continue
            if not datos.get("features"):
                errores.append(f"{url_capa} -> respuesta sin features")
                continue

            gdf = gpd.GeoDataFrame.from_features(datos["features"],
                                                 crs=CRS_GEOGRAFICO)
            gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            if verboso:
                print(f"  descargadas {len(gdf)} localidades")

            gdf["_nombre_norm"] = gdf[campo].astype(str).map(_normalizar)
            sel = gdf[gdf["_nombre_norm"].str.contains(nombre_norm, na=False)]

            if len(sel) == 0:
                disponibles = sorted(gdf[campo].astype(str).unique())
                errores.append(f"{url_capa} -> '{nombre}' no esta. "
                               f"Disponibles: {disponibles}")
                continue

            sel = sel.drop(columns=["_nombre_norm"]).to_crs(CRS_METRICO)
            sel = sel.reset_index(drop=True)
            sel["fuente_limite"] = cfg["fuente"]
            sel["url_servicio"] = url_capa
            sel["campo_nombre"] = campo
            sel["fecha_descarga"] = sello_de_tiempo()

            if verboso:
                print(f"  encontrada: {sel[campo].iloc[0]}  "
                      f"({sel.geometry.area.sum() / 1e6:.2f} km²)")
            return sel

        except Exception as exc:  # noqa: BLE001
            errores.append(f"{url_capa} -> {type(exc).__name__}: {exc}")
            if verboso:
                print(f"  fallo: {type(exc).__name__}")

    raise RuntimeError(
        "No se pudo descargar el limite de la localidad.\n\n"
        + "\n".join(f"  - {e}" for e in errores)
        + "\n\nAlternativa: descargue el GeoJSON de localidades desde\n"
          "  https://datosabiertos.bogota.gov.co/dataset/localidad-bogota-d-c\n"
          "guardelo en datos_crudos/ y use cargar_limite_manual(ruta, 'CHAPINERO').\n"
          "Anote en la bitacora que ese paso fue manual (regla 2 del equipo)."
    )


def _normalizar(texto: str) -> str:
    """Minusculas, sin tildes, sin espacios extra. Para comparar nombres."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.lower().split())


def cargar_limite_manual(ruta, nombre: str = "CHAPINERO",
                         campo: str | None = None) -> gpd.GeoDataFrame:
    """Lee el limite desde un archivo descargado a mano.

    Salida de emergencia documentada. Si usa esto, escriba en la bitacora que
    la descarga fue manual, con la fecha y la URL de origen.
    """
    gdf = gpd.read_file(ruta)
    if gdf.crs is None:
        gdf = gdf.set_crs(CRS_GEOGRAFICO)

    if campo is None:
        campo = _campo_de_nombre(list(gdf.columns))
    if campo is None:
        raise ValueError(f"No hay campo de nombre. Columnas: {list(gdf.columns)}")

    nombre_norm = _normalizar(nombre)
    sel = gdf[gdf[campo].astype(str).map(_normalizar).str.contains(nombre_norm,
                                                                   na=False)]
    if len(sel) == 0:
        raise ValueError(f"'{nombre}' no esta en el archivo. "
                         f"Disponibles: {sorted(gdf[campo].astype(str).unique())}")

    sel = sel.to_crs(CRS_METRICO).reset_index(drop=True)
    sel["fuente_limite"] = f"ARCHIVO MANUAL: {ruta}"
    sel["url_servicio"] = "descarga manual - ver bitacora"
    sel["campo_nombre"] = campo
    sel["fecha_descarga"] = sello_de_tiempo()
    print(f"ATENCION: limite cargado de archivo manual ({ruta}).")
    print("Debe quedar anotado en la bitacora metodologica.")
    return sel


# ===========================================================================
# Muestreo del MDT (misma logica, ahora sobre la sesion con reintentos)
# ===========================================================================

def _pedir_muestras(puntos_xy, tiempo_espera=180, reintentos=4):
    """Una peticion a getSamples del ImageServer, con reintentos."""
    sesion = sesion_http()
    geometria = {
        "points": [[float(x), float(y)] for x, y in puntos_xy],
        "spatialReference": {"wkid": 9377},
    }
    datos_envio = {
        "geometry": json.dumps(geometria),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "interpolation": "RSP_BilinearInterpolation",
        "outFields": "*",
        "f": "json",
    }

    ultimo_error = None
    for intento in range(reintentos):
        try:
            # POST: la geometria de 400 puntos excede el largo comodo de una URL.
            r = sesion.post(f"{MDT_IMAGESERVER}/getSamples",
                            data=datos_envio, timeout=tiempo_espera)
            r.raise_for_status()
            datos = r.json()
            if "error" in datos:
                raise RuntimeError(f"ImageServer: {datos['error']}")
            return datos.get("samples", [])
        except Exception as exc:  # noqa: BLE001
            ultimo_error = exc
            espera = 3 * (intento + 1)
            print(f"    reintento {intento + 1}/{reintentos} en {espera}s "
                  f"({type(exc).__name__})")
            time.sleep(espera)

    raise RuntimeError(
        f"getSamples fallo tras {reintentos} intentos: {ultimo_error}\n"
        f"Ejecute diagnostico_red() para ver si el problema es de DNS."
    )


def probar_imageserver(verboso: bool = True) -> dict:
    """Comprueba que el ImageServer del MDT responde y muestrea bien.

    Usa un punto conocido dentro de Bogota. Corra esto ANTES del muestreo
    completo: son 2 segundos y evita descubrir el problema a mitad de camino.
    """
    sesion = sesion_http()
    salida = {"servicio_responde": False, "muestreo_funciona": False}

    try:
        r = sesion.get(MDT_IMAGESERVER, params={"f": "json"}, timeout=60)
        r.raise_for_status()
        info = r.json()
        if "error" in info:
            salida["error_servicio"] = info["error"]
        else:
            salida["servicio_responde"] = True
            salida["nombre"] = info.get("name")
            salida["tipo_pixel"] = info.get("pixelType")
            salida["banda_min_max"] = info.get("minValues"), info.get("maxValues")
            salida["extent_sr"] = info.get("extent", {}).get("spatialReference")
            if verboso:
                print(f"ImageServer responde: {info.get('name')}")
                print(f"  tipo de pixel: {info.get('pixelType')}")
                print(f"  CRS del extent: {salida['extent_sr']}")
    except Exception as exc:  # noqa: BLE001
        salida["error_servicio"] = f"{type(exc).__name__}: {exc}"
        if verboso:
            print(f"El ImageServer no respondio: {exc}")

    # Punto de prueba: zona central de Bogota, en EPSG:9377.
    try:
        muestras = _pedir_muestras([(4_867_000.0, 2_050_000.0)], reintentos=2)
        if muestras:
            valor = muestras[0].get("value")
            salida["muestreo_funciona"] = True
            salida["valor_prueba"] = valor
            salida["resolucion_prueba"] = muestras[0].get("resolution")
            if verboso:
                print(f"  muestreo de prueba: elevacion = {valor} m, "
                      f"resolucion = {muestras[0].get('resolution')}")
                print("  (una elevacion cercana a 2.600 m es lo esperable en Bogota)")
        else:
            if verboso:
                print("  el muestreo devolvio vacio: punto fuera de cobertura")
    except Exception as exc:  # noqa: BLE001
        salida["error_muestreo"] = f"{type(exc).__name__}: {exc}"
        if verboso:
            print(f"  el muestreo fallo: {exc}")

    return salida
