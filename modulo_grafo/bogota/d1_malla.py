"""
d1_malla.py — Malla Vial Integral de IDECA como fuente de red vial.

Reemplaza a OpenStreetMap como fuente primaria de geometria vial. Aporta lo que
OSM no tiene:

  - Sentido de circulacion oficial (campo MVISVIA)
  - Clasificacion POT (arterial, intermedia, local, rural)
  - Codigo de Identificacion Vial (CIV), identificador oficial y estable
  - Velocidad reglamentaria y numero de carriles

Servicio: Mapa de Referencia de IDECA, capa 13 (Malla Vial).
Actualizacion trimestral. La fecha del dato se registra en la bitacora.

La salida tiene el MISMO esquema de columnas que `d1_grafo.grafo_a_segmentos`,
de modo que el resto del cuaderno D1 no cambia.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString

import math

from d1_red import sesion_http, sello_de_tiempo
from d1_procedencia import congelar_get, sha256_bytes
from constantes_d1 import (
    CRS_METRICO, CRS_GEOGRAFICO, LONGITUD_MINIMA_LAZO_M,
    TOLERANCIA_NODO_M, CLASES_VEHICULO,
    MALLA_SERVICIO, MALLA_LICENCIA, MALLA_FUENTE,
    MALLA_PRODUCCION_VERSION, PREFIJO_CRUDO_MALLA, ruta_cruda,
)

# Clasificacion POT segun el campo MVITCLA.
CLASIFICACION_POT = {
    1: "arterial",
    2: "intermedia",
    3: "local",
    4: "peatonal",
    5: "rural",
    6: "sin_definir",
    7: "proyectada",
}



# Sentido de circulacion (campo MVISVIA). Dominio declarado en los metadatos
# de la capa, congelados el 2026-09-19:
#   FT -> "Desde hacia"    TF -> "Hacia desde"    B  -> "Doble Sentido"
#   SD -> "Sin definir"    N  -> "Sin sentido"
#
# FT y TF generan una arista; B genera dos. SD, N y los vacios NO tienen
# sentido oficial: se les crean DOS aristas y se marcan con
# sentido_supuesto = True.
#
# CORRECCION: antes se llamaba a esto "supuesto conservador". No lo es para
# la pregunta de alcanzabilidad: crear el sentido contrario nunca deja un
# tramo inalcanzable, pero justamente por eso puede habilitar rutas que no
# estan permitidas, y SOBREESTIMA la alcanzabilidad. Es un supuesto
# OPTIMISTA. La marca permite medirlo: el ruteo se corre con y sin las
# aristas supuestas (analisis de sensibilidad).
SENTIDO_DIRECTO = "FT"     # en el sentido de digitalizacion
SENTIDO_INVERSO = "TF"     # contrario al sentido de digitalizacion
SENTIDO_DOBLE = "B"        # doble sentido declarado por la fuente


# ===========================================================================
# 1. DESCARGA
# ===========================================================================

def descargar_malla_vial(limite_gdf,
                         margen_m: float = 100.0,
                         solo_vehiculo: bool = True,
                         tamano_pagina: int = 1000,
                         verboso: bool = True) -> tuple[gpd.GeoDataFrame, dict]:
    """Descarga la Malla Vial Integral que intersecta un poligono.

    El servicio limita cada respuesta a 1.000 registros, asi que se pagina con
    resultOffset. Devuelve (GeoDataFrame en CRS_METRICO, bitacora).
    """
    sesion = sesion_http()

    limite_m = limite_gdf.to_crs(CRS_METRICO)
    minx, miny, maxx, maxy = limite_m.total_bounds
    caja_m = gpd.GeoDataFrame(
        geometry=gpd.GeoSeries.from_wkt([
            f"POLYGON(({minx - margen_m} {miny - margen_m}, "
            f"{maxx + margen_m} {miny - margen_m}, "
            f"{maxx + margen_m} {maxy + margen_m}, "
            f"{minx - margen_m} {maxy + margen_m}, "
            f"{minx - margen_m} {miny - margen_m}))"
        ]), crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
    glon0, glat0, glon1, glat1 = caja_m.total_bounds

    envolvente = {"xmin": glon0, "ymin": glat0, "xmax": glon1, "ymax": glat1,
                  "spatialReference": {"wkid": 4326}}

    base = {
        "where": "1=1",
        "geometry": json.dumps(envolvente),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": 4326,
        "outSR": 4326,
        "outFields": "*",
        "returnGeometry": "true",
        "orderByFields": "OBJECTID",
        "f": "geojson",
    }

    # Conteo previo, para saber cuantas paginas esperar.
    try:
        r = sesion.get(f"{MALLA_SERVICIO}/query", timeout=120,
                       params={**base, "returnCountOnly": "true", "f": "json"})
        r.raise_for_status()
        total_esperado = r.json().get("count")
    except Exception:  # noqa: BLE001
        total_esperado = None

    if verboso:
        print(f"Descargando Malla Vial Integral de IDECA...")
        if total_esperado:
            print(f"  registros que intersectan el sector: {total_esperado:,}")

    partes = []
    desplazamiento = 0
    while True:
        params = {**base,
                  "resultOffset": desplazamiento,
                  "resultRecordCount": tamano_pagina}
        for intento in range(4):
            try:
                r = sesion.get(f"{MALLA_SERVICIO}/query", params=params,
                               timeout=180)
                r.raise_for_status()
                datos = r.json()
                break
            except Exception as exc:  # noqa: BLE001
                if intento == 3:
                    raise RuntimeError(
                        f"Fallo la pagina con offset {desplazamiento}: {exc}"
                    ) from exc
                time.sleep(3 * (intento + 1))

        if isinstance(datos, dict) and "error" in datos:
            raise RuntimeError(f"ArcGIS devolvio error: {datos['error']}")

        rasgos = datos.get("features") or []
        if not rasgos:
            break

        partes.append(gpd.GeoDataFrame.from_features(rasgos,
                                                     crs=CRS_GEOGRAFICO))
        desplazamiento += len(rasgos)
        if verboso:
            print(f"  descargados {desplazamiento:,}", end="\r")

        if len(rasgos) < tamano_pagina:
            break

    if verboso:
        print()

    if not partes:
        raise RuntimeError("La Malla Vial no devolvio ningun registro.")

    malla = pd.concat(partes, ignore_index=True)
    malla = gpd.GeoDataFrame(malla, geometry="geometry", crs=CRS_GEOGRAFICO)
    malla = malla[malla.geometry.notna() & ~malla.geometry.is_empty]
    malla = malla.to_crs(CRS_METRICO)

    # Recorte al poligono real, no solo a la caja envolvente.
    poligono = limite_m.geometry.union_all().buffer(margen_m)
    antes = len(malla)
    malla = malla[malla.geometry.intersects(poligono)].copy()

    malla["clasificacion_pot"] = malla["MVITCLA"].map(CLASIFICACION_POT)

    # Los identificadores oficiales llegan como enteros de ArcGIS. Se tipan
    # como pandas "string" de inmediato: con nulos presentes pandas infiere
    # float y escribe "475409.0" (mismo defecto detectado en B1).
    #
    # Int64 (con I mayuscula) es el entero anulable de pandas: acepta <NA>
    # sin convertirse a float. Pasar por el evita el int(nan) que rompio la
    # descarga de nueve localidades en la corrida del 2026-09-18.
    for campo in ("MVICODIGO", "MVICIV", "MVICCALZAD"):
        if campo in malla.columns:
            malla[campo] = (pd.to_numeric(malla[campo], errors="coerce")
                            .astype("Int64")
                            .astype("string"))
    # Diagnostico de los identificadores: condiciona el segmento_id estable.
    if "MVICODIGO" in malla.columns:
        n_nulos = int(malla["MVICODIGO"].isna().sum())
        n_dup = int(malla["MVICODIGO"].duplicated(keep=False).sum())
        bitacora_ids = {"n_ejes": int(len(malla)),
                        "mvicodigo_nulos": n_nulos,
                        "mvicodigo_en_filas_duplicadas": n_dup}
        if verboso and (n_nulos or n_dup):
            print()
            print(f"AVISO sobre MVICODIGO: {n_nulos:,} nulos, "
                  f"{n_dup:,} filas con codigo repetido.")
            print("Los nulos usan identificador de respaldo por coordenadas;")
            print("los repetidos se desempatan. Ambos quedan contados.")
    else:
        bitacora_ids = {"mvicodigo_presente": False}

    bitacora = {
        "fuente": MALLA_FUENTE,
        "url_servicio": MALLA_SERVICIO,
        "licencia": MALLA_LICENCIA,
        "fecha_descarga": sello_de_tiempo(),
        "bbox_consultado_wgs84": [glon0, glat0, glon1, glat1],
        "margen_m": margen_m,
        "n_descargados": int(antes),
        "n_tras_recorte": int(len(malla)),
    }

    if verboso:
        print(f"  tras recortar al poligono: {len(malla):,} ejes")
        print()
        print("Clasificacion POT:")
        print(malla["clasificacion_pot"].value_counts().to_string())
        print()
        print("Sentido de circulacion (MVISVIA):")
        print(malla["MVISVIA"].fillna("(nulo)").value_counts().to_string())

    if solo_vehiculo:
        n_antes = len(malla)
        malla = malla[malla["MVITCLA"].isin(CLASES_VEHICULO)].copy()
        bitacora["n_excluidos_no_vehiculo"] = int(n_antes - len(malla))
        if verboso:
            print()
            print(f"Excluidos {n_antes - len(malla):,} ejes peatonales o "
                  f"proyectados. Quedan {len(malla):,}.")

        bitacora["n_final"] = int(len(malla))
    bitacora["identificadores"] = bitacora_ids
    return malla.reset_index(drop=True), bitacora


# ===========================================================================
# 1B. DESCARGA CONGELADA (PRODUCCION)
# ===========================================================================
# descargar_malla_vial (arriba) consulta el servicio en vivo cada vez. Se
# conserva solo para las corridas historicas de D1. La produccion usa
# descargar_malla_congelada: la capa se actualiza trimestralmente, no declara
# fecha (editingInfo nulo) y no admite consulta historica. El crudo
# congelado ES el dato.

def _carpeta_congelados():
    return ruta_cruda() / "congelados"


def _borrar_congelado(nombre: str, extension: str) -> None:
    """Borra los tres archivos de un crudo que resulto ser un error.

    ArcGIS devuelve sus errores con HTTP 200, asi que congelar_get los guarda
    como si fueran dato valido, y todas las corridas siguientes leerian el
    error desde disco. Por eso un error se borra en vez de congelarse.
    """
    carpeta = _carpeta_congelados()
    for ruta in (carpeta / f"{nombre}{extension}",
                 carpeta / f"{nombre}{extension}.sha256",
                 carpeta / f"{nombre}.meta.json"):
        if ruta.exists():
            ruta.unlink()


def _leer_json_congelado(res: dict, nombre: str, extension: str) -> dict:
    datos = json.loads(res["contenido"].decode("utf-8"))
    if isinstance(datos, dict) and "error" in datos:
        _borrar_congelado(nombre, extension)
        raise RuntimeError(
            f"ArcGIS devolvio error en {nombre}: {datos['error']}\n"
            "Se borro ese crudo para no congelar un error. Vuelva a ejecutar.")
    return datos


def _postprocesar_malla(malla, poligono_m, margen_m: float,
                        solo_vehiculo: bool, verboso: bool):
    """Mismo tratamiento que descargar_malla_vial, aplicado al crudo leido
    de disco: recorte al poligono, clasificacion POT, tipado de ids y filtro
    de clases. Devuelve (malla, bitacora_parcial)."""
    malla = gpd.GeoDataFrame(malla, geometry="geometry", crs=CRS_GEOGRAFICO)
    malla = malla[malla.geometry.notna() & ~malla.geometry.is_empty]
    malla = malla.to_crs(CRS_METRICO)

    zona = poligono_m.buffer(margen_m)
    n_descargados = len(malla)
    malla = malla[malla.geometry.intersects(zona)].copy()
    n_tras_recorte = len(malla)

    malla["clasificacion_pot"] = malla["MVITCLA"].map(CLASIFICACION_POT)

    # Mismo tipado que descargar_malla_vial: Int64 -> string, para que un
    # nulo no convierta la columna en float y escriba "475409.0".
    for campo in ("MVICODIGO", "MVICIV", "MVICCALZAD"):
        if campo in malla.columns:
            malla[campo] = (pd.to_numeric(malla[campo], errors="coerce")
                            .astype("Int64").astype("string"))

    ids = {"n_ejes": int(len(malla)),
           "mvicodigo_nulos": int(malla["MVICODIGO"].isna().sum()),
           "mvicodigo_en_filas_duplicadas":
               int(malla["MVICODIGO"].duplicated(keep=False).sum())}

    n_no_vehiculo = 0
    if solo_vehiculo:
        antes = len(malla)
        malla = malla[malla["MVITCLA"].isin(CLASES_VEHICULO)].copy()
        n_no_vehiculo = antes - len(malla)

    if verboso:
        print(f"  ejes en el crudo            : {n_descargados:,}")
        print(f"  tras recortar al poligono   : {n_tras_recorte:,}")
        print(f"  excluidos (peatonal/proyect): {n_no_vehiculo:,}")
        print(f"  ejes finales                : {len(malla):,}")
        print(f"  MVICODIGO nulos             : {ids['mvicodigo_nulos']:,}")
        print(f"  MVICODIGO repetidos (filas) : "
              f"{ids['mvicodigo_en_filas_duplicadas']:,}")

    parcial = {"n_descargados": int(n_descargados),
               "n_tras_recorte": int(n_tras_recorte),
               "n_excluidos_no_vehiculo": int(n_no_vehiculo),
               "n_final": int(len(malla)),
               "identificadores": ids}
    return malla.reset_index(drop=True), parcial


def descargar_malla_congelada(poligono_m,
                              margen_m: float = 250.0,
                              solo_vehiculo: bool = True,
                              tamano_pagina: int = 1000,
                              verboso: bool = True):
    """Descarga la Malla Vial de la ciudad UNA vez y la congela por paginas.

    poligono_m: geometria shapely del area de estudio, en CRS_METRICO.

    Primera corrida: pide el conteo y todas las paginas (ordenadas por
    OBJECTID) y congela cada una. Solo al terminar escribe el manifiesto.
    Corridas siguientes: si el manifiesto existe, lee todo de disco,
    verifica cada hash y NO consulta el servidor.

    Devuelve (malla en CRS_METRICO, bitacora).
    """
    sesion = sesion_http()
    carpeta = _carpeta_congelados()
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_manifiesto = carpeta / f"{PREFIJO_CRUDO_MALLA}.manifiesto.json"

    # Caja de consulta en grados, redondeada HACIA AFUERA a 6 decimales
    # (~0,1 m): los parametros quedan identicos en cada corrida y la caja
    # nunca recorta la zona de interes.
    zona = gpd.GeoSeries([poligono_m.buffer(margen_m)],
                         crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
    x0, y0, x1, y1 = (float(v) for v in zona.total_bounds)
    glon0, glat0 = math.floor(x0 * 1e6) / 1e6, math.floor(y0 * 1e6) / 1e6
    glon1, glat1 = math.ceil(x1 * 1e6) / 1e6, math.ceil(y1 * 1e6) / 1e6

    base = {
        "where": "1=1",
        "geometry": json.dumps({"xmin": glon0, "ymin": glat0,
                                "xmax": glon1, "ymax": glat1,
                                "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": 4326, "outSR": 4326,
        "outFields": "*", "returnGeometry": "true",
        "orderByFields": "OBJECTID",
        "f": "geojson",
    }

    manifiesto = None
    if ruta_manifiesto.exists():
        manifiesto = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
        if manifiesto["parametros_consulta"] != base:
            raise RuntimeError(
                "La consulta actual NO es la que se congelo (cambio el "
                "poligono o el margen).\nNo se mezcla un crudo con otra "
                "consulta. Para recongelar a proposito, borre el manifiesto "
                f"y las paginas {PREFIJO_CRUDO_MALLA}_* de {carpeta}")

    if verboso:
        estado = "leyendo de disco" if manifiesto else "DESCARGANDO y congelando"
        print(f"Malla Vial v{MALLA_PRODUCCION_VERSION}: {estado}")

    # --- Conteo del servidor (tambien congelado) ---------------------------
    nombre_conteo = f"{PREFIJO_CRUDO_MALLA}_conteo"
    res = congelar_get(nombre_conteo, f"{MALLA_SERVICIO}/query",
                       {**base, "returnCountOnly": "true", "f": "json"},
                       sesion, extension=".json", verboso=False)
    total_esperado = int(_leer_json_congelado(res, nombre_conteo, ".json")["count"])

    # --- Paginas ------------------------------------------------------------
    paginas, partes = [], []
    n = 0
    while True:
        if manifiesto is not None and n >= len(manifiesto["paginas"]):
            break
        nombre = f"{PREFIJO_CRUDO_MALLA}_p{n:04d}"
        params = {**base,
                  "resultOffset": n * tamano_pagina,
                  "resultRecordCount": tamano_pagina}
        res = congelar_get(nombre, f"{MALLA_SERVICIO}/query", params, sesion,
                           extension=".geojson", verboso=False)
        datos = _leer_json_congelado(res, nombre, ".geojson")
        rasgos = datos.get("features") or []

        if manifiesto is not None:
            esperado = manifiesto["paginas"][n]["sha256"]
            if res["meta"]["sha256"] != esperado:
                raise RuntimeError(f"{nombre}: su hash no es el del manifiesto.")

        paginas.append({"nombre": nombre,
                        "sha256": res["meta"]["sha256"],
                        "n_registros": len(rasgos),
                        "fecha_descarga_bogota": res["meta"]["fecha_descarga_bogota"]})
        if rasgos:
            partes.append(gpd.GeoDataFrame.from_features(rasgos,
                                                         crs=CRS_GEOGRAFICO))
        if verboso:
            print(f"  pagina {n:4d}  {len(rasgos):5d} ejes  "
                  f"{'(disco)' if res['desde_disco'] else '(servidor)'}", end="\r")
        n += 1

        if manifiesto is None and len(rasgos) < tamano_pagina:
            break
    if verboso:
        print()

    if not partes:
        raise RuntimeError("La Malla Vial no devolvio ningun registro.")
    malla = pd.concat(partes, ignore_index=True)

    # --- Verificaciones de integridad del crudo -----------------------------
    # 1. Ninguna pagina intermedia puede venir incompleta: dejaria un hueco
    #    de ejes sin ningun error visible.
    incompletas = [p["nombre"] for p in paginas[:-1]
                   if p["n_registros"] != tamano_pagina]
    if incompletas:
        raise RuntimeError(f"Paginas intermedias incompletas: {incompletas}")
    # 2. El total leido debe ser el conteo que declaro el servidor.
    if len(malla) != total_esperado:
        raise RuntimeError(f"Se leyeron {len(malla):,} ejes y el servidor "
                           f"declaro {total_esperado:,}.")
    # 3. Un OBJECTID repetido indica paginas solapadas.
    if "OBJECTID" in malla.columns:
        n_dup = int(malla["OBJECTID"].duplicated().sum())
        if n_dup:
            raise RuntimeError(f"{n_dup:,} OBJECTID repetidos entre paginas.")

    fechas = sorted(p["fecha_descarga_bogota"] for p in paginas)
    sha_conjunto = sha256_bytes(
        "\n".join(p["sha256"] for p in paginas).encode("utf-8"))

    # --- Manifiesto: se escribe solo con la descarga completa y verificada --
    if manifiesto is None:
        manifiesto = {
            "fuente": MALLA_FUENTE,
            "servicio": MALLA_SERVICIO,
            "licencia": MALLA_LICENCIA,
            "version_malla": MALLA_PRODUCCION_VERSION,
            "parametros_consulta": base,
            "tamano_pagina": tamano_pagina,
            "total_esperado": total_esperado,
            "n_paginas": len(paginas),
            "fecha_primera_pagina": fechas[0],
            "fecha_ultima_pagina": fechas[-1],
            "sha256_conjunto": sha_conjunto,
            "paginas": paginas,
        }
        ruta_manifiesto.write_text(
            json.dumps(manifiesto, indent=2, ensure_ascii=False),
            encoding="utf-8")
        if verboso:
            print(f"  manifiesto escrito: {ruta_manifiesto.name}")
    elif manifiesto["sha256_conjunto"] != sha_conjunto:
        raise RuntimeError("El hash del conjunto no coincide con el manifiesto.")

    if fechas[0][:10] != fechas[-1][:10] and verboso:
        print("AVISO: las paginas se bajaron en dias distintos "
              f"({fechas[0][:10]} a {fechas[-1][:10]}). Si la capa se "
              "actualizo entre medio, el crudo mezcla versiones. Declararlo.")

    malla, parcial = _postprocesar_malla(malla, poligono_m, margen_m,
                                         solo_vehiculo, verboso)

    bitacora = {
        "fuente": MALLA_FUENTE,
        "url_servicio": MALLA_SERVICIO,
        "licencia": MALLA_LICENCIA,
        "version_malla": MALLA_PRODUCCION_VERSION,
        "fecha_corte": fechas[0][:10],
        "fecha_primera_pagina": fechas[0],
        "fecha_ultima_pagina": fechas[-1],
        "sha256_conjunto": sha_conjunto,
        "manifiesto": ruta_manifiesto.name,
        "n_paginas": len(paginas),
        "conteo_servidor": total_esperado,
        "margen_m": margen_m,
        "bbox_consultado_wgs84": [glon0, glat0, glon1, glat1],
        **parcial,
    }
    if verboso:
        print(f"  fecha de corte : {bitacora['fecha_corte']}")
        print(f"  sha del conjunto: {sha_conjunto}")
    return malla, bitacora

# ===========================================================================
# 2. CONSTRUCCION DEL GRAFO DIRIGIDO
# ===========================================================================

def _partes_lineales(geom):
    """Devuelve las LineString de una geometria, sea simple o multiple."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def construir_grafo_dirigido(malla: gpd.GeoDataFrame,
                             tolerancia_nodo_m: float = TOLERANCIA_NODO_M,
                             verboso: bool = True) -> gpd.GeoDataFrame:
    """Convierte la Malla Vial en aristas dirigidas con el esquema de D1.

    Los nodos se identifican agrupando los extremos de cada eje sobre una
    rejilla de `tolerancia_nodo_m`. Dos extremos que caen en la misma celda son
    el mismo nodo.

    El sentido se toma del campo oficial MVISVIA:
      FT  -> una arista, en el sentido de digitalizacion
      TF  -> una arista, en sentido contrario
      B   -> dos aristas (doble sentido oficial)
      otro-> dos aristas, marcadas sentido_supuesto=True (SD "Sin definir",
             N "Sin sentido" o vacio). Supuesto OPTIMISTA para
             alcanzabilidad: ver el comentario de SENTIDO_DOBLE.
    """
    tol = tolerancia_nodo_m

    def id_nodo(x, y):
        return f"{int(round(x / tol))}_{int(round(y / tol))}"

    filas = []
    conteo_sentido = defaultdict(int)
    n_multiparte = 0
    n_sin_codigo = 0
    n_lazos_descartados = 0

    for idx, eje in malla.iterrows():
        partes = _partes_lineales(eje.geometry)
        if len(partes) > 1:
            n_multiparte += 1

        crudo = eje.get("MVISVIA")
        sentido = "" if crudo is None or pd.isna(crudo) else str(crudo).strip().upper()
        conteo_sentido[sentido or "(nulo)"] += 1

        civ = eje.get("MVICIV")
        codigo = eje.get("MVICODIGO")
        nombre = eje.get("MVIETIQUET") or eje.get("MVINOMBRE")
        clase = eje.get("clasificacion_pot")
        carriles = eje.get("MVINUMC")
        velocidad = eje.get("MVIVELREG")

        for j, linea in enumerate(partes):
            coords = list(linea.coords)
            if len(coords) < 2:
                continue
            x0, y0 = coords[0][0], coords[0][1]
            x1, y1 = coords[-1][0], coords[-1][1]
            n0, n1 = id_nodo(x0, y0), id_nodo(x1, y1)
            # Descarte de lazos degenerados por GEOMETRIA, no por identidad de
            # nodos. Comparar n0 == n1 hacia depender el conjunto de segmentos
            # de la tolerancia de la rejilla: al subirla, mas extremos
            # colapsan y se descartaban mas segmentos. Medido el 2026-09-18:
            # 55 segmentos de 225.755 cambiaban entre tolerancia 2,0 y 3,0 m.
            if linea.length < LONGITUD_MINIMA_LAZO_M:
                n_lazos_descartados += 1
                continue

            # El sufijo FT/TF identifica la direccion de recorrido respecto
            # del sentido de digitalizacion del eje. Es lo que hace el
            # identificador estable Y su inverso calculable.
            if sentido == SENTIDO_DIRECTO:
                direcciones = [(n0, n1, linea, True, "FT")]
            elif sentido == SENTIDO_INVERSO:
                direcciones = [(n1, n0, LineString(coords[::-1]), True, "TF")]
            else:
                direcciones = [(n0, n1, linea, False, "FT"),
                               (n1, n0, LineString(coords[::-1]), False, "TF")]

            # pd.isna cubre None, NaN y pd.NA. La version anterior solo miraba
            # float, y el nulo de una columna "string" es pd.NA: el respaldo
            # nunca se activaba y los ejes sin codigo quedaban todos con raiz
            # "<NA>", desempatados segun el orden de lectura.
            if codigo is None or pd.isna(codigo):
                raiz = f"XY{id_nodo(x0, y0)}-{id_nodo(x1, y1)}"
                n_sin_codigo += 1
            else:
                raiz = str(codigo)

            for k, (u, v, geo, unico, suf) in enumerate(direcciones):
                filas.append({
                    "segmento_id": f"{raiz}_{j}_{suf}",
                    "id_eje": raiz,
                    "parte": j,
                    "sentido_recorrido": suf,
                    "id_por_respaldo": raiz.startswith("XY"),
                    "u": u, "v": v, "key": j * 2 + k,
                    "civ": civ, "mvi_codigo": codigo,
                    "name": nombre,
                    "highway": clase,
                    "oneway": bool(unico),
                    "maxspeed": velocidad,
                    "lanes": carriles,
                    "calzada": eje.get("MVICCALZAD"),
                    "bridge": None, "tunnel": None,
                    "sentido_oficial": sentido or None,
                    "sentido_supuesto": sentido not in (
                        SENTIDO_DIRECTO, SENTIDO_INVERSO, SENTIDO_DOBLE),
                    "geometry": geo,
                })

    segmentos = gpd.GeoDataFrame(filas, geometry="geometry", crs=CRS_METRICO)

    # segmento_id = <id del eje en la fuente>_<parte>_<FT|TF>.
    #
    # Por que se cambio: el id anterior era u_v_key, donde u y v salian de
    # redondear coordenadas a una rejilla de los ejes DESCARGADOS. Si cambiaba
    # el conjunto descargado —otro sector, la malla actualizada, otra
    # tolerancia de nodo— cambiaban todos los identificadores. Eso hacia
    # imposible comparar dos corridas (limitacion 11 de D2) y, mas grave,
    # hacia que las pendientes de Danna y los consumos de Emily apuntaran a
    # otros segmentos sin dar ningun error.
    #
    # Ahora el id depende solo del eje en la fuente y de la direccion de
    # recorrido. No depende de la rejilla ni del recorte. Y el inverso es
    # CALCULABLE: basta cambiar FT por TF.
    n_dup_id = int(segmentos["segmento_id"].duplicated(keep=False).sum())
    if n_dup_id:
        # Ocurre si la fuente repite MVICODIGO en ejes distintos. Se desempata
        # con un sufijo y se cuenta: es un defecto de la fuente, no del metodo.
        segmentos["segmento_id"] = (
            segmentos["segmento_id"] + "#"
            + segmentos.groupby("segmento_id").cumcount().astype(str)
        )
        segmentos.loc[~segmentos["segmento_id"].str.endswith("#0"),
                      "id_desempatado"] = True
        segmentos["segmento_id"] = segmentos["segmento_id"].str.replace(
            "#0$", "", regex=True)
    segmentos["id_desempatado"] = segmentos.get(
        "id_desempatado", pd.Series(False, index=segmentos.index)).fillna(False)

    segmentos["longitud_m"] = segmentos.geometry.length

    columnas = ["segmento_id", "id_eje", "parte", "sentido_recorrido",
                "id_por_respaldo", "id_desempatado",
                "u", "v", "key", "civ", "mvi_codigo", "calzada", "name",
                "highway", "oneway", "maxspeed", "lanes", "bridge", "tunnel",
                "sentido_oficial", "sentido_supuesto", "longitud_m",
                "geometry"]
    columnas = [c for c in columnas if c in segmentos.columns]
    segmentos = segmentos[columnas].reset_index(drop=True)

    if verboso:
        print(f"Ejes de entrada: {len(malla):,}")
        print(f"Aristas dirigidas: {len(segmentos):,}")
        print(f"Nodos distintos: {len(set(segmentos['u']) | set(segmentos['v'])):,}")
        print(f"Longitud total: {segmentos['longitud_m'].sum() / 1000:,.1f} km")
        if n_multiparte:
            print(f"Ejes con geometria multiparte: {n_multiparte:,}")
        print(f"Identificadores de respaldo (sin MVICODIGO): {n_sin_codigo:,}")
        print(f"Identificadores desempatados por codigo repetido: {n_dup_id:,}")
        print(f"Lazos degenerados descartados (< {LONGITUD_MINIMA_LAZO_M} m): "
              f"{n_lazos_descartados:,}")
        print()
        print("Aristas por sentido oficial:")
        for s, n in sorted(conteo_sentido.items(), key=lambda t: -t[1]):
            etiqueta = {"FT": "FT (un sentido, directo)",
                        "TF": "TF (un sentido, inverso)",
                        "B": "B (doble sentido oficial)"}.get(
                            s, f"{s} (doble sentido SUPUESTO)")
            print(f"  {etiqueta:<32} {n:,} ejes")

    return segmentos


# ===========================================================================
# 3. DIAGNOSTICO Y VERIFICACION
# ===========================================================================

def diagnostico_conectividad(segmentos: gpd.GeoDataFrame,
                             verboso: bool = True) -> dict:
    """Mide si el grafo quedo conectado.

    Si el emparejamiento de nodos por rejilla fuera insuficiente, el grafo se
    partiria en muchas componentes pequenas. Este diagnostico lo detecta:
    un grafo sano tiene una componente que concentra casi toda la red.
    """
    import networkx as nx

    G = nx.DiGraph()
    for _, f in segmentos.iterrows():
        G.add_edge(f["u"], f["v"], longitud=f["longitud_m"])

    componentes = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    tam = [len(c) for c in componentes]
    mayor = tam[0] if tam else 0
    n_nodos = G.number_of_nodes()

    # Longitud que vive en la componente mayor.
    if componentes:
        nodos_mayor = componentes[0]
        largo_mayor = sum(
            f["longitud_m"] for _, f in segmentos.iterrows()
            if f["u"] in nodos_mayor and f["v"] in nodos_mayor
        )
    else:
        largo_mayor = 0.0

    largo_total = float(segmentos["longitud_m"].sum())

    salida = {
        "prueba": "conectividad del grafo",
        "n_nodos": n_nodos,
        "n_aristas": G.number_of_edges(),
        "n_componentes": len(componentes),
        "nodos_en_componente_mayor": mayor,
        "fraccion_nodos_componente_mayor": round(mayor / n_nodos, 4) if n_nodos else 0,
        "fraccion_longitud_componente_mayor": round(largo_mayor / largo_total, 4)
        if largo_total else 0,
        "tamano_top5_componentes": tam[:5],
        "pasa": (mayor / n_nodos) >= 0.90 if n_nodos else False,
    }

    if verboso:
        print(f"Componentes debilmente conexas: {len(componentes):,}")
        print(f"Componente mayor: {mayor:,} nodos "
              f"({100 * salida['fraccion_nodos_componente_mayor']:.1f} % del total)")
        print(f"Longitud en la componente mayor: "
              f"{100 * salida['fraccion_longitud_componente_mayor']:.1f} %")
        print(f"Tamano de las 5 mayores: {tam[:5]}")
        if not salida["pasa"]:
            print()
            print("La red quedo fragmentada. Suba tolerancia_nodo_m (pruebe 2.0)")
            print("y vuelva a construir el grafo.")

    return salida


def comparar_con_osm(segmentos_malla: gpd.GeoDataFrame,
                     segmentos_osm: gpd.GeoDataFrame,
                     verboso: bool = True) -> dict:
    """Contrasta la malla oficial contra OSM. Verificacion independiente.

    No se espera coincidencia exacta: son dos fuentes distintas y el resultado
    interesante es justamente en que difieren. Se reporta longitud total,
    numero de aristas y reparto por tipo.
    """
    largo_malla = float(segmentos_malla["longitud_m"].sum()) / 1000
    largo_osm = float(segmentos_osm["longitud_m"].sum()) / 1000

    salida = {
        "prueba": "malla oficial IDECA vs OpenStreetMap",
        "km_malla_ideca": round(largo_malla, 1),
        "km_osm": round(largo_osm, 1),
        "diferencia_km": round(largo_malla - largo_osm, 1),
        "diferencia_relativa": round((largo_malla - largo_osm) / largo_osm, 4)
        if largo_osm else None,
        "n_aristas_malla": len(segmentos_malla),
        "n_aristas_osm": len(segmentos_osm),
    }

    if verboso:
        print(f"Longitud de red (km)  IDECA: {largo_malla:>8.1f}   "
              f"OSM: {largo_osm:>8.1f}   dif: {largo_malla - largo_osm:>+8.1f}")
        print(f"Aristas dirigidas     IDECA: {len(segmentos_malla):>8,}   "
              f"OSM: {len(segmentos_osm):>8,}")
        print()
        print("Esta diferencia no es un error que haya que corregir: es un")
        print("resultado. Reportela indicando fecha de descarga de ambas fuentes.")

    return salida

def verificar_inverso_por_identificador(segmentos: gpd.GeoDataFrame,
                                        tabla=None,
                                        verboso: bool = True) -> dict:
    """Compara el emparejamiento geometrico de opuestas contra el que se
    deduce del identificador.

    Regla 3 del equipo: el resultado se recalcula por un camino distinto al
    que lo produjo. `aristas_inversas_coherentes` decide por geometria
    (distancia de Hausdorff entre nodos). Aqui se decide por ALGEBRA sobre el
    identificador: el inverso de <eje>_<parte>_FT es <eje>_<parte>_TF, y punto.
    Son dos vias completamente independientes.

    Solo aplica a ejes de doble sentido, que son los unicos que generan las
    dos direcciones. Un eje de un solo sentido no tiene arista opuesta y el
    identificador tampoco se la inventa.
    """
    existentes = set(segmentos["segmento_id"])

    def inverso_esperado(sid):
        if sid.endswith("_FT"):
            return sid[:-3] + "_TF"
        if sid.endswith("_TF"):
            return sid[:-3] + "_FT"
        return None

    esperado = {}
    for sid in segmentos["segmento_id"]:
        inv = inverso_esperado(sid)
        esperado[sid] = inv if (inv and inv in existentes) else None

    n_con_inverso = sum(1 for v in esperado.values() if v)
    salida = {
        "prueba": "inverso por identificador vs por geometria",
        "n_segmentos": int(len(segmentos)),
        "n_con_inverso_algebraico": n_con_inverso,
    }

    if tabla is not None and "segmento_inverso_id" in tabla.columns:
        geo = tabla.set_index("segmento_id")["segmento_inverso_id"].to_dict()
        tipo = (tabla.set_index("segmento_id")["tipo_opuesta"].to_dict()
                if "tipo_opuesta" in tabla.columns else {})
        sentido = segmentos.set_index("segmento_id")["sentido_oficial"].to_dict()

        coinciden = 0
        # Dos clases de discrepancia, y solo una es defecto:
        #  - doble_calzada: el eje es de un solo sentido y la geometria le
        #    encontro una opuesta que pertenece a OTRO eje. Es correcto: son
        #    dos vias fisicas distintas y el identificador no debe unirlas.
        #  - contradiccion: ambos senalan un inverso y NO es el mismo. Eso si
        #    es defecto y debe ser cero.
        doble_calzada, contradiccion = 0, 0
        ej_calzada, ej_contra = [], []

        for sid, inv_alg in esperado.items():
            inv_geo = geo.get(sid)
            if isinstance(inv_geo, float) and pd.isna(inv_geo):
                inv_geo = None
            if inv_alg is None and inv_geo is None:
                continue
            if inv_alg == inv_geo:
                coinciden += 1
                continue

            caso = {"segmento_id": sid,
                    "por_identificador": inv_alg,
                    "por_geometria": inv_geo,
                    "tipo_opuesta": tipo.get(sid),
                    "sentido_oficial": sentido.get(sid)}

            if inv_alg is None and inv_geo is not None:
                doble_calzada += 1
                if len(ej_calzada) < 5:
                    ej_calzada.append(caso)
            else:
                contradiccion += 1
                if len(ej_contra) < 5:
                    ej_contra.append(caso)

        salida.update({
            "n_coinciden": coinciden,
            "n_doble_calzada": doble_calzada,
            "n_contradicciones": contradiccion,
            "ejemplos_doble_calzada": ej_calzada,
            "ejemplos": ej_contra,
            # Solo las contradicciones son defecto.
            "pasa": contradiccion == 0,
        })
    else:
        salida["pasa"] = n_con_inverso > 0
        salida["nota"] = "sin tabla de pendiente; solo se conto el algebraico"

    if verboso:
        print(f"Segmentos con inverso deducible del id: {n_con_inverso:,}")
        if "n_coinciden" in salida:
            print(f"  coinciden con la geometria          : "
                  f"{salida['n_coinciden']:,}")
            print(f"  doble calzada (geometria si, id no) : "
                  f"{salida['n_doble_calzada']:,}  <- esperado, no es defecto")
            print(f"  CONTRADICCIONES (ambos, distintos)  : "
                  f"{salida['n_contradicciones']:,}  <- debe ser 0")
            if salida["n_contradicciones"]:
                for e in salida["ejemplos"]:
                    print(f"    {e}")
    return salida