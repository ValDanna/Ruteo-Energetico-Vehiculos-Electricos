"""
d1_bogota.py — Escalamiento del Bloque D a Bogota completa (tarea 6).

El cuaderno de Chapinero no sirve tal cual a escala de ciudad. Tres cosas
cambian:

  1. EL RASTER NO CABE EN MEMORIA. A 1 m, Bogota urbana son 42.000 x 34.000
     pixeles: 5,7 GB en un solo arreglo. Aqui se procesa TESELA POR TESELA:
     se descarga una, se muestrean los puntos que caen dentro, se libera.
     Nunca existe el mosaico completo.

  2. LA MALLA SE DESCARGA POR LOCALIDAD. Una sola consulta para toda la ciudad
     satura el servicio. Se descarga localidad por localidad y se unifica,
     eliminando los ejes repetidos en los solapes.

  3. LA VERIFICACION SE HACE POR MUESTREO. Comprobar 3,3 millones de puntos uno
     por uno tarda mas que todo el resto del proceso.

Ademas el proceso es REANUDABLE: cada tesela guarda su resultado parcial, asi
que una interrupcion no obliga a empezar de cero.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box

from constantes_d1 import (
    CRS_METRICO, CRS_GEOGRAFICO, PASO_MUESTREO_M,
    LONGITUD_MINIMA_PENDIENTE_M, ruta_cruda,
)
from d1_red import sesion_http, sello_de_tiempo, ENDPOINTS_LOCALIDAD, _describir_capa
from d1_mdt import MDT_WMS, CAPA_CRUDA, SIGMA_Z_EFECTIVO
from constantes_d1 import (
    SIGMA_CUANTIZACION_M, SIGMA_Z_POR_ZONA, LOCALIDADES_CON_RURAL,
    RANGO_ELEVACION_M,
)
import d1_malla
import d1_grafo as d1
from d1_procedencia import congelar_get

# Sumapaz es rural, ocupa mas superficie que toda el area urbana y solo esta
# cubierta por el DEM de 10 m (RMSE Z < 3 m), con el que la pendiente vial no
# es estimable. Se excluye y se declara.
LOCALIDADES_EXCLUIDAS = {"SUMAPAZ"}

# A escala de ciudad se pide el MDT a 2 m en vez de 1 m. Justificacion: el paso
# de muestreo es de 10 m, de modo que un DEM mas fino que ~5 m no aporta
# informacion adicional a la pendiente LONGITUDINAL de un segmento. A cambio,
# las teselas bajan de 357 a 99 y el volumen de 5,0 a 1,4 GB.
RESOLUCION_CIUDAD_M = 2.0


# ===========================================================================
# 1. LIMITES DE TODAS LAS LOCALIDADES
# ===========================================================================

def descargar_localidades(excluir: set[str] | None = None,
                          verboso: bool = True) -> gpd.GeoDataFrame:
    """Descarga las 20 localidades de Bogota en una sola consulta."""
    excluir = {e.upper() for e in (excluir or LOCALIDADES_EXCLUIDAS)}
    sesion = sesion_http()
    errores = []

    # El limite de localidades decide que ejes entran (recorte), en_ciudad y
    # la localidad de cada segmento. Por eso tambien se congela.
    #
    # Si alguna fuente ya esta congelada se prueba PRIMERO: si no, una corrida
    # en la que la fuente 0 volviera a responder cambiaria de fuente de
    # limites en silencio.
    carpeta = ruta_cruda() / "congelados"

    def _nombre_crudo(i):
        return f"D_localidades_bogota_fuente{i}"

    orden = sorted(
        enumerate(ENDPOINTS_LOCALIDAD),
        key=lambda t: not (carpeta / f"{_nombre_crudo(t[0])}.geojson").exists())

    for i_cfg, cfg in orden:
        url = cfg["url"]
        nombre_crudo = _nombre_crudo(i_cfg)
        try:
            res = congelar_get(
                nombre_crudo, f"{url}/query",
                {"where": "1=1", "outFields": "*", "returnGeometry": "true",
                 "outSR": 4326, "f": "geojson"},
                sesion, extension=".geojson", tiempo_espera=120,
                verboso=verboso)
            datos = json.loads(res["contenido"].decode("utf-8"))
            if "error" in datos or not datos.get("features"):
                errores.append(f"{url}: {datos.get('error', 'sin features')}")
                d1_malla._borrar_congelado(nombre_crudo, ".geojson")
                continue

            gdf = gpd.GeoDataFrame.from_features(datos["features"],
                                                 crs=CRS_GEOGRAFICO)

            # El campo de nombre se busca en el crudo congelado, no en una
            # consulta en vivo a la definicion de la capa.
            campos = [c for c in gdf.columns if c != "geometry"]
            campo = next((c for c in campos
                          if "NOM" in c.upper() and "LOC" in c.upper()), None)
            campo = campo or next((c for c in campos if "NOM" in c.upper()), None)
            if campo is None:
                errores.append(f"{url}: sin campo de nombre")
                continue
            gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].to_crs(CRS_METRICO)
            gdf["nombre"] = gdf[campo].astype(str).str.strip().str.upper()
            gdf["excluida"] = gdf["nombre"].isin(excluir)
            gdf["area_km2"] = gdf.geometry.area / 1e6
            gdf["fuente_limite"] = cfg["fuente"]
            # Fecha de la DESCARGA congelada, no de esta ejecucion.
            gdf["fecha_descarga"] = res["meta"]["fecha_descarga_bogota"]
            gdf["sha256_crudo"] = res["meta"]["sha256"]

            if verboso:
                print(f"Localidades descargadas: {len(gdf)}")
                print(f"Excluidas: {sorted(gdf.loc[gdf['excluida'], 'nombre'])}")
                print(f"Área a procesar: "
                      f"{gdf.loc[~gdf['excluida'], 'area_km2'].sum():,.1f} km² "
                      f"(total {gdf['area_km2'].sum():,.1f} km²)")
            return gdf.sort_values("nombre").reset_index(drop=True)

        except Exception as exc:  # noqa: BLE001
            # Si esta fuente YA estaba congelada, cualquier fallo (hash que no
            # coincide, archivo corrupto) debe detener todo. Pasar a la fuente
            # siguiente cambiaria los limites sin avisar.
            if (carpeta / f"{nombre_crudo}.geojson").exists():
                raise
            errores.append(f"{url}: {type(exc).__name__}: {exc}")

    raise RuntimeError("No se pudieron descargar las localidades.\n"
                       + "\n".join(f"  - {e}" for e in errores))


# ===========================================================================
# 2. MALLA VIAL DE TODA LA CIUDAD
# ===========================================================================

def descargar_malla_ciudad(localidades: gpd.GeoDataFrame,
                           margen_m: float = 250.0,
                           verboso: bool = True) -> tuple[gpd.GeoDataFrame, dict]:
    """Descarga la Malla Vial localidad por localidad y unifica.

    El margen de 250 m es el codo de la curva de conectividad medida en
    Chapinero. A escala de ciudad importa menos —las localidades vecinas ya
    aportan continuidad— pero se conserva para los bordes exteriores.

    Los solapes producen ejes repetidos. Se eliminan por MVICODIGO y, si ese
    campo faltara, por la representacion WKT de la geometria.
    """
    activas = localidades[~localidades["excluida"]]
    partes, bitacoras = [], []

    for i, (_, loc) in enumerate(activas.iterrows(), start=1):
        nombre = loc["nombre"]
        una = gpd.GeoDataFrame(geometry=[loc.geometry], crs=CRS_METRICO)
        t0 = time.time()
        try:
            trozo, bit = d1_malla.descargar_malla_vial(
                una, margen_m=margen_m, verboso=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i:2}/{len(activas)}] {nombre:<22} FALLO: {exc}")
            bitacoras.append({"localidad": nombre, "error": str(exc)[:200]})
            continue

        trozo["localidad_origen"] = nombre
        partes.append(trozo)
        bit["localidad"] = nombre
        bitacoras.append(bit)
        if verboso:
            print(f"  [{i:2}/{len(activas)}] {nombre:<22} "
                  f"{len(trozo):>6,} ejes   ({time.time() - t0:>5.1f} s)")

    # Un fallo parcial es MAS peligroso que un fallo total: el cuaderno sigue,
    # escribe salidas y los numeros parecen razonables. En la corrida del
    # 2026-09-18 fallaron 9 de 19 localidades y el proceso termino sin avisar,
    # produciendo 7.650 km de red en vez de ~19.000 y medianas de pendiente
    # calculadas sobre astillas del margen. Ahora se detiene.
    fallidas = [b["localidad"] for b in bitacoras if "error" in b]
    if not partes:
        raise RuntimeError("Ninguna localidad devolvio malla vial.")
    if fallidas:
        raise RuntimeError(
            f"Fallaron {len(fallidas)} de {len(activas)} localidades: "
            f"{sorted(fallidas)}\n"
            "No se continua: una malla incompleta produce estadisticas "
            "plausibles y equivocadas.\n"
            "Errores:\n"
            + "\n".join(f"  - {b['localidad']}: {b.get('error')}"
                        for b in bitacoras if "error" in b)
        )

    malla = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True),
                             geometry="geometry", crs=CRS_METRICO)
    n_bruto = len(malla)

    # Deduplicacion. MVICODIGO identifica el eje; si se repite por el solape,
    # se conserva la primera aparicion.
    # Deduplicacion de los solapes entre localidades.
    #
    # El riesgo (limitacion 13 de D2): si MVICODIGO tuviera valores repetidos
    # para ejes DISTINTOS, deduplicar por el perderia ejes legitimos. Antes
    # esto se asumia; ahora se comprueba, contrastando contra la geometria.
    clave = "MVICODIGO" if "MVICODIGO" in malla.columns else None
    malla["_wkt"] = malla.geometry.to_wkt()

    n_unicos_geometria = int(malla["_wkt"].nunique())
    if clave and malla[clave].notna().all():
        n_unicos_codigo = int(malla[clave].nunique())
        if n_unicos_codigo < n_unicos_geometria:
            # Hay mas geometrias distintas que codigos: el codigo fusionaria
            # ejes que no son el mismo. Se deduplica por el par.
            print(f"AVISO: {n_unicos_geometria - n_unicos_codigo:,} ejes de "
                  f"geometria distinta comparten MVICODIGO. Se deduplica por "
                  f"(codigo, geometria) para no perderlos.")
            malla = malla.drop_duplicates(subset=[clave, "_wkt"], keep="first")
            metodo_dedup = "(MVICODIGO, geometria WKT)"
        else:
            malla = malla.drop_duplicates(subset=[clave], keep="first")
            metodo_dedup = "MVICODIGO"
    else:
        n_unicos_codigo = None
        malla = malla.drop_duplicates(subset=["_wkt"], keep="first")
        metodo_dedup = "geometria WKT (MVICODIGO con nulos)"

    malla = malla.drop(columns=["_wkt"])

    malla = malla.reset_index(drop=True)

    bitacora = {
        "fuente": d1_malla.MALLA_FUENTE,
        "url_servicio": d1_malla.MALLA_SERVICIO,
        "licencia": d1_malla.MALLA_LICENCIA,
        "fecha_descarga": sello_de_tiempo(),
        "margen_m": margen_m,
        "n_localidades": int(len(activas)),
        "localidades_excluidas": sorted(
            localidades.loc[localidades["excluida"], "nombre"]),
        "n_ejes_bruto": int(n_bruto),
        "n_ejes_unicos": int(len(malla)),
        "n_duplicados_por_solape": int(n_bruto - len(malla)),
        "clave_deduplicacion": metodo_dedup,
        "n_unicos_por_codigo": n_unicos_codigo,
        "n_unicos_por_geometria": n_unicos_geometria,
        "por_localidad": bitacoras,
    }

    if verboso:
        print()
        print(f"Ejes descargados (con solapes): {n_bruto:,}")
        print(f"Ejes únicos tras deduplicar   : {len(malla):,} "
              f"({n_bruto - len(malla):,} repetidos por solape)")
        print()
        print("Clasificación POT:")
        print(malla["clasificacion_pot"].value_counts().to_string())

    return malla, bitacora


# ===========================================================================
# 3. MUESTREO DE ELEVACION POR TESELAS
# ===========================================================================

def _rejilla_de_teselas(minx, miny, maxx, maxy, resolucion_m, lado_px):
    """Divide un bbox en teselas de lado_px pixeles a la resolucion dada."""
    lado_m = lado_px * resolucion_m
    n_col = max(1, int(math.ceil((maxx - minx) / lado_m)))
    n_fil = max(1, int(math.ceil((maxy - miny) / lado_m)))
    teselas = []
    for f in range(n_fil):
        for c in range(n_col):
            teselas.append({
                "fila": f, "col": c,
                "x0": minx + c * lado_m, "x1": min(maxx, minx + (c + 1) * lado_m),
                "y0": miny + f * lado_m, "y1": min(maxy, miny + (f + 1) * lado_m),
            })
    return teselas, n_fil, n_col


def _firma_de_puntos(xs, ys, resolucion_m, lado_px, margen_m) -> str:
    """Huella del conjunto de puntos y de los parametros de teselado.

    Por que existe: los indices que guarda cada parcial son POSICIONES dentro
    del arreglo de puntos, no identificadores. Si ese arreglo cambia entre dos
    corridas —porque la Malla Vial se actualizo, porque una localidad que fallo
    ahora responde, o porque cambio PASO_MUESTREO_M— las posiciones guardadas
    apuntan a otros puntos y la reanudacion escribe elevaciones en el lugar
    equivocado. No se produce ningun error: salen pendientes plausibles y mal
    asignadas. Es el mismo desalineamiento de indices del Bloque A.

    La firma lo vuelve detectable: se compara antes de reutilizar nada.
    """
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(xs, dtype="<f8").tobytes())
    h.update(np.ascontiguousarray(ys, dtype="<f8").tobytes())
    h.update(f"|n={len(xs)}|res={resolucion_m}|lado={lado_px}|margen={margen_m}"
             .encode("utf-8"))
    return h.hexdigest()


def muestrear_elevacion_por_teselas(puntos,
                                    resolucion_m: float = RESOLUCION_CIUDAD_M,
                                    lado_px: int = 2048,
                                    margen_m: float = 100.0,
                                    carpeta=None,
                                    guardar_teselas: bool = True,
                                    reanudar: bool = True,
                                    rehacer_si_cambia: bool = False,
                                    verboso: bool = True) -> tuple[pd.DataFrame, dict]:
    """Muestrea elevacion procesando tesela por tesela, sin mosaico en memoria.

    Para cada tesela: se calcula que puntos caen dentro; si no hay ninguno NO se
    descarga (gran parte del bbox de la ciudad no tiene vias). Se descarga el
    GeoTIFF, se muestrean esos puntos, se libera la tesela.

    Reanudable: cada tesela escribe su resultado parcial en disco. Si el proceso
    se interrumpe, al reejecutar se saltan las ya hechas. La reanudacion solo se
    acepta si el conjunto de puntos es EL MISMO que produjo los parciales; ver
    `_firma_de_puntos`. Si cambio, con `rehacer_si_cambia=True` los parciales se
    mandan a cuarentena y se recalculan; los .tif descargados se conservan,
    porque dependen de la geografia y no del orden de los puntos.
    """
    import rasterio
    from rasterio.io import MemoryFile

    sesion = sesion_http()
    carpeta = Path(carpeta) if carpeta else ruta_cruda() / f"mdt_ciudad_{int(resolucion_m)}m"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "parciales").mkdir(exist_ok=True)
    if guardar_teselas:
        (carpeta / "teselas").mkdir(exist_ok=True)

    xs = np.array([p.x for p in puntos], dtype=float)
    ys = np.array([p.y for p in puntos], dtype=float)
    n = len(xs)

    elevacion = np.full(n, np.nan, dtype=float)

    # --- Control de reanudacion segura -------------------------------------
    firma = _firma_de_puntos(xs, ys, resolucion_m, lado_px, margen_m)
    ruta_firma = carpeta / "firma_puntos.json"
    carpeta_parciales = carpeta / "parciales"

    try:
        firma_previa = json.loads(ruta_firma.read_text(encoding="utf-8")).get("firma")
    except Exception:  # noqa: BLE001
        firma_previa = None

    n_parciales = len(list(carpeta_parciales.glob("*.npz")))
    firma_coincide = (firma_previa == firma)

    if n_parciales and not firma_coincide:
        if not rehacer_si_cambia:
            raise RuntimeError(
                f"Hay {n_parciales} parciales en {carpeta_parciales} que NO "
                f"corresponden a este conjunto de puntos.\n"
                f"  firma guardada: {firma_previa}\n"
                f"  firma actual  : {firma}\n"
                "Los indices guardados apuntan a otros puntos: reutilizarlos "
                "asignaria elevaciones al segmento equivocado sin dar error.\n"
                "Vuelva a llamar con rehacer_si_cambia=True para mandarlos a "
                "cuarentena y recalcular. Las teselas .tif se conservan, asi "
                "que no se vuelve a descargar el raster."
            )
        cuarentena = carpeta / f"parciales_obsoletos_{time.strftime('%Y%m%d_%H%M%S')}"
        carpeta_parciales.rename(cuarentena)
        carpeta_parciales.mkdir(exist_ok=True)
        n_parciales = 0
        if verboso:
            print(f"AVISO: el conjunto de puntos cambio respecto de la corrida "
                  f"anterior.\n  Parciales movidos a {cuarentena.name}. "
                  f"Los .tif se reutilizan.")

    ruta_firma.write_text(json.dumps({
        "firma": firma, "n_puntos": int(n), "resolucion_m": resolucion_m,
        "lado_px": lado_px, "margen_m": margen_m,
        "fecha": sello_de_tiempo(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    if verboso:
        print(f"Firma del conjunto de puntos: {firma[:16]}  "
              f"({'reanudando' if (reanudar and n_parciales) else 'corrida nueva'})")

    minx, maxx = xs.min() - margen_m, xs.max() + margen_m
    miny, maxy = ys.min() - margen_m, ys.max() + margen_m
    teselas, n_fil, n_col = _rejilla_de_teselas(minx, miny, maxx, maxy,
                                                resolucion_m, lado_px)

    if verboso:
        print(f"Puntos a muestrear : {n:,}")
        print(f"Extensión          : {(maxx-minx)/1000:.1f} x {(maxy-miny)/1000:.1f} km")
        print(f"Resolución pedida  : {resolucion_m} m")
        print(f"Rejilla de teselas : {n_col} x {n_fil} = {len(teselas)}")

    # Que teselas contienen puntos. Las vacias no se descargan.
    for t in teselas:
        t["mascara"] = ((xs >= t["x0"]) & (xs < t["x1"]) &
                        (ys >= t["y0"]) & (ys < t["y1"]))
        t["n_puntos"] = int(t["mascara"].sum())
    con_datos = [t for t in teselas if t["n_puntos"] > 0]

    if verboso:
        print(f"Teselas con puntos : {len(con_datos)} de {len(teselas)} "
              f"({100 * len(con_datos) / len(teselas):.0f} %) — "
              f"las vacías no se descargan")
        print()

    registro, n_desc, n_saltadas, n_fallos = [], 0, 0, 0
    t_inicio = time.time()

    for k, t in enumerate(con_datos, start=1):
        nombre = f"t{t['fila']:03d}_{t['col']:03d}"
        parcial = carpeta / "parciales" / f"{nombre}.npz"

        if reanudar and parcial.exists():
            try:
                d = np.load(parcial, allow_pickle=False)
                # Segunda barrera: un parcial sin firma, o con otra, no se usa.
                firma_parcial = (str(d["firma"].item())
                                 if "firma" in d.files else None)
                if firma_parcial != firma:
                    raise ValueError("parcial de otro conjunto de puntos")
                idx_guardados = d["indices"]
                if idx_guardados.size and int(idx_guardados.max()) >= n:
                    raise ValueError("indices fuera de rango")
                elevacion[idx_guardados] = d["valores"]
                n_saltadas += 1
                registro.append({"tesela": nombre, "estado": "reanudada",
                                 "n_puntos": t["n_puntos"]})
                continue
            except Exception:  # noqa: BLE001
                pass   # parcial corrupto o ajeno: se rehace

        caja = gpd.GeoDataFrame(
            geometry=[box(t["x0"], t["y0"], t["x1"], t["y1"])],
            crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
        a, b, cc, d_ = caja.total_bounds
        ancho = max(16, int(math.ceil((t["x1"] - t["x0"]) / resolucion_m)))
        alto = max(16, int(math.ceil((t["y1"] - t["y0"]) / resolucion_m)))

        contenido, sha = None, None
        destino = carpeta / "teselas" / f"{nombre}.tif" if guardar_teselas else None

        if destino is not None and destino.exists() and destino.stat().st_size > 1000:
            contenido = destino.read_bytes()
        else:
            for intento in range(4):
                try:
                    r = sesion.get(MDT_WMS, timeout=300, params={
                        "service": "WMS", "version": "1.3.0", "request": "GetMap",
                        "layers": CAPA_CRUDA, "styles": "", "crs": "CRS:84",
                        "bbox": f"{a},{b},{cc},{d_}",
                        "width": ancho, "height": alto, "format": "image/tiff"})
                    r.raise_for_status()
                    if "xml" in r.headers.get("Content-Type", ""):
                        raise RuntimeError(r.text[:150])
                    contenido = r.content
                    break
                except Exception as exc:  # noqa: BLE001
                    if intento == 3:
                        n_fallos += 1
                        registro.append({"tesela": nombre, "estado": "fallo",
                                         "error": str(exc)[:120],
                                         "n_puntos": t["n_puntos"]})
                        contenido = None
                    else:
                        time.sleep(3 * (intento + 1))

        if contenido is None:
            continue

        if destino is not None and not destino.exists():
            destino.write_bytes(contenido)
        sha = hashlib.sha256(contenido).hexdigest()

        idx = np.nonzero(t["mascara"])[0]
        try:
            with MemoryFile(contenido) as mem, mem.open() as src:
                gp = gpd.GeoDataFrame(
                    geometry=gpd.points_from_xy(xs[idx], ys[idx]),
                    crs=CRS_METRICO).to_crs(src.crs)
                coords = [(p.x, p.y) for p in gp.geometry]
                vals = np.array([float(v[0]) for v in src.sample(coords)],
                                dtype=float)
        except Exception as exc:  # noqa: BLE001
            n_fallos += 1
            registro.append({"tesela": nombre, "estado": "ilegible",
                             "error": str(exc)[:120], "n_puntos": t["n_puntos"]})
            continue

        fuera = ~((vals >= RANGO_ELEVACION_M[0]) & (vals <= RANGO_ELEVACION_M[1]))
        vals[fuera] = np.nan

        elevacion[idx] = vals
        np.savez_compressed(parcial, indices=idx, valores=vals,
                            firma=np.array(firma))

        n_desc += 1
        registro.append({"tesela": nombre, "estado": "descargada",
                         "n_puntos": t["n_puntos"], "sha256_16": sha,
                         "n_sin_dato": int(np.isnan(vals).sum()),
                         "bbox_wgs84": [a, b, cc, d_]})

        if verboso:
            transcurrido = time.time() - t_inicio
            hechas = n_desc + n_saltadas
            faltan = len(con_datos) - k
            eta = (transcurrido / max(1, n_desc)) * faltan if n_desc else 0
            print(f"  [{k:>3}/{len(con_datos)}] {nombre}  "
                  f"{t['n_puntos']:>7,} pts  sha={sha}  "
                  f"ETA {eta/60:>5.1f} min", end="\r")

    if verboso:
        print()

    df = pd.DataFrame({
        "indice": np.arange(n), "x": xs, "y": ys, "elevacion_m": elevacion,
    })
    df["resolucion_m"] = resolucion_m
    df["zona_mdt"] = "mosaico_integrado"
    df["rmse_z_m"] = SIGMA_Z_EFECTIVO

    bitacora = {
        "fuente": "IDECA - MDT Bogota 2025 (WMS GetMap, por teselas)",
        "url_wms": MDT_WMS, "capa": CAPA_CRUDA, "licencia": "CC BY 4.0",
        "fecha": sello_de_tiempo(),
        "resolucion_m": resolucion_m,
        "lado_tesela_px": lado_px,
        "n_teselas_rejilla": len(teselas),
        "n_teselas_con_puntos": len(con_datos),
        "n_teselas_descargadas": n_desc,
        "n_teselas_reanudadas": n_saltadas,
        "n_teselas_fallidas": n_fallos,
        "n_puntos": int(n),
        "firma_puntos": firma,
        "n_sin_dato": int(np.isnan(elevacion).sum()),
        "minutos": round((time.time() - t_inicio) / 60, 1),
        "carpeta": str(carpeta),
        "teselas": registro,
    }

    with open(carpeta / "bitacora_mdt_ciudad.json", "w", encoding="utf-8") as f:
        json.dump(bitacora, f, indent=2, ensure_ascii=False, default=str)

    if verboso:
        print(f"Teselas descargadas: {n_desc}   reanudadas: {n_saltadas}   "
              f"fallidas: {n_fallos}")
        print(f"Sin dato: {bitacora['n_sin_dato']:,} "
              f"({100 * bitacora['n_sin_dato'] / n:.2f} %)")
        val = elevacion[~np.isnan(elevacion)]
        if len(val):
            print(f"Elevación: {val.min():.0f} a {val.max():.0f} m s. n. m.")
        print(f"Tiempo: {bitacora['minutos']:.1f} min")

    return df, bitacora


# ===========================================================================
# 4. PENDIENTE A ESCALA DE CIUDAD
# ===========================================================================

def perfil_por_segmento_rapido(mapa_indices: dict,
                               muestras: pd.DataFrame,
                               sigma_z_por_segmento: dict | None = None,
                               ancho_correlacion_m: float | None = None,
                               verboso: bool = True) -> pd.DataFrame:
    """Version vectorizada de d1_grafo.perfil_por_segmento.

    La original construye un diccionario con una entrada por punto. Con 3,3
    millones de puntos eso son cientos de megabytes y varios minutos. Aqui se
    usa un arreglo indexado por posicion, porque los indices son 0..N-1.
    """
    elev = muestras["elevacion_m"].to_numpy(dtype=float)
    rmse = muestras["rmse_z_m"].to_numpy(dtype=float)

    filas = []
    total = len(mapa_indices)
    for j, (seg_id, (indices, distancias)) in enumerate(mapa_indices.items(), 1):
        idx = np.asarray(indices, dtype=int)
        z = elev[idx]
        r = rmse[idx]
        if sigma_z_por_segmento is not None:
            rmse_seg = float(sigma_z_por_segmento.get(seg_id, SIGMA_Z_EFECTIVO))
        else:
            rmse_seg = (float(np.nanmax(r)) if np.any(~np.isnan(r))
                        else SIGMA_Z_EFECTIVO)

        res = d1.calcular_pendiente_segmento(
            distancias, z, rmse_z=rmse_seg,
            ancho_correlacion_m=ancho_correlacion_m,
            sigma_cuantizacion_m=SIGMA_CUANTIZACION_M,
        )
        res["segmento_id"] = seg_id
        res["zona_mdt"] = "mosaico_integrado"
        res["cruza_zonas"] = False
        res["rmse_z_usado_m"] = rmse_seg
        filas.append(res)

        if verboso and j % 20000 == 0:
            print(f"  {j:,}/{total:,} segmentos", end="\r")

    if verboso:
        print(f"  {total:,}/{total:,} segmentos")
    return pd.DataFrame(filas)


def densificar_red_ciudad(segmentos: gpd.GeoDataFrame,
                          paso: float = PASO_MUESTREO_M,
                          verboso: bool = True):
    """Densifica la red completa. Devuelve (puntos, mapa_indices)."""
    mapa, puntos, cont = {}, [], 0
    total = len(segmentos)
    for j, (_, fila) in enumerate(segmentos.iterrows(), 1):
        p, dist = d1.densificar_segmento(fila.geometry, paso)
        mapa[fila["segmento_id"]] = (list(range(cont, cont + len(p))), dist)
        puntos.extend(p)
        cont += len(p)
        if verboso and j % 20000 == 0:
            print(f"  {j:,}/{total:,} segmentos, {cont:,} puntos", end="\r")
    if verboso:
        print(f"  {total:,}/{total:,} segmentos, {cont:,} puntos")
    return puntos, mapa


# ===========================================================================
# 5. VERIFICACIONES A ESCALA
# ===========================================================================

def verificar_muestreo_en_geometria_muestreado(segmentos, muestras, mapa_indices,
                                               n_segmentos: int = 3000,
                                               tolerancia_m: float = 0.5,
                                               semilla: int = 42) -> dict:
    """Igual que la prueba de Chapinero, pero sobre una muestra de segmentos.

    Comprobar los 3,3 millones de puntos uno por uno tarda mas que todo el
    proceso. Con 3.000 segmentos al azar, un defecto sistematico de indices
    aparece con certeza practica.
    """
    from shapely.geometry import Point

    rng = np.random.default_rng(semilla)
    ids = list(mapa_indices.keys())
    elegidos = rng.choice(len(ids), size=min(n_segmentos, len(ids)),
                          replace=False)
    geoms = segmentos.set_index("segmento_id").geometry
    xs = muestras["x"].to_numpy()
    ys = muestras["y"].to_numpy()

    peor, n_malos, n_total = 0.0, 0, 0
    ejemplos = []
    for e in elegidos:
        seg_id = ids[e]
        geom = geoms.get(seg_id)
        if geom is None:
            continue
        for i in mapa_indices[seg_id][0]:
            n_total += 1
            dd = geom.distance(Point(xs[i], ys[i]))
            peor = max(peor, dd)
            if dd > tolerancia_m:
                n_malos += 1
                if len(ejemplos) < 5:
                    ejemplos.append({"segmento_id": seg_id, "indice": int(i),
                                     "distancia_m": round(dd, 3)})

    return {
        "prueba": "cada muestra cae sobre su propio segmento (muestreado)",
        "n_segmentos_evaluados": int(len(elegidos)),
        "n_puntos_evaluados": n_total,
        "n_fuera_de_tolerancia": n_malos,
        "distancia_maxima_m": round(peor, 4),
        "ejemplos": ejemplos,
        "pasa": n_malos == 0,
    }


def verificar_longitudes_muestreado(segmentos, n: int = 5000,
                                    tolerancia_relativa: float = 0.01,
                                    semilla: int = 42) -> dict:
    """Longitud proyectada contra geodesica, sobre una muestra de segmentos."""
    sub = segmentos.sample(min(n, len(segmentos)), random_state=semilla)
    res = d1.verificar_longitudes(sub, tolerancia_relativa)
    res["prueba"] = "longitud proyectada vs geodesica (muestreado)"
    return res


def comparar_con_chapinero(tabla_ciudad: pd.DataFrame,
                           ruta_csv_chapinero,
                           verboso: bool = True) -> dict:
    """Contrasta la corrida de ciudad contra la de Chapinero.

    Es una verificacion independiente de alto nivel: los mismos segmentos,
    procesados con otra resolucion de MDT y otra arquitectura de muestreo,
    deben dar pendientes equivalentes. Si difieren mucho, el escalamiento
    introdujo un sesgo.
    """
    try:
        chap = pd.read_csv(ruta_csv_chapinero)
    except Exception as exc:  # noqa: BLE001
        return {"prueba": "ciudad vs Chapinero", "disponible": False,
                "motivo": f"no se pudo leer el CSV: {exc}", "pasa": False}

    comun = chap.merge(tabla_ciudad, on="segmento_id",
                       suffixes=("_chap", "_ciudad"))
    comun = comun[comun["pendiente_neta_chap"].notna()
                  & comun["pendiente_neta_ciudad"].notna()]

    if len(comun) == 0:
        return {"prueba": "ciudad vs Chapinero", "disponible": False,
                "motivo": "ningun segmento_id en comun (los nodos dependen "
                          "del conjunto descargado, asi que los id cambian)",
                "pasa": False,
                "nota": "Compare las distribuciones en vez de segmento a "
                        "segmento."}

    dif = (comun["pendiente_neta_ciudad"] - comun["pendiente_neta_chap"]).abs() * 100
    salida = {
        "prueba": "ciudad vs Chapinero, segmento a segmento",
        "disponible": True,
        "n_comparados": int(len(comun)),
        "dif_mediana_pp": round(float(dif.median()), 4),
        "dif_p95_pp": round(float(dif.quantile(0.95)), 4),
        "dif_maxima_pp": round(float(dif.max()), 4),
        "pasa": float(dif.median()) <= 100 * np.sqrt(2) * SIGMA_Z_EFECTIVO / 70,
    }
    if verboso:
        print(f"Segmentos comparables: {salida['n_comparados']:,}")
        print(f"Diferencia mediana   : {salida['dif_mediana_pp']:.4f} pp")
        print(f"Diferencia p95       : {salida['dif_p95_pp']:.4f} pp")
    return salida


def comparar_distribuciones(tabla_ciudad: pd.DataFrame,
                            ruta_csv_chapinero,
                            verboso: bool = True) -> dict:
    """Compara las DISTRIBUCIONES de pendiente, sin depender de los id.

    Los identificadores de nodo dependen del conjunto de ejes descargado, asi
    que al cambiar de sector cambian. Esta comparacion es robusta a eso.
    """
    try:
        chap = pd.read_csv(ruta_csv_chapinero)
    except Exception as exc:  # noqa: BLE001
        return {"prueba": "distribuciones ciudad vs Chapinero",
                "disponible": False, "motivo": str(exc)[:120], "pasa": False}

    a = (chap["pendiente_neta"].dropna().abs() * 100).to_numpy()
    b = (tabla_ciudad["pendiente_neta"].dropna().abs() * 100).to_numpy()
    if len(a) == 0 or len(b) == 0:
        return {"prueba": "distribuciones ciudad vs Chapinero",
                "disponible": False, "motivo": "serie vacia", "pasa": False}

    filas = []
    for etq, q in (("mediana", 50), ("p75", 75), ("p90", 90), ("p99", 99)):
        filas.append({"estadistico": etq,
                      "chapinero_pct": round(float(np.percentile(a, q)), 3),
                      "ciudad_pct": round(float(np.percentile(b, q)), 3)})
    tabla = pd.DataFrame(filas)
    if verboso:
        print(tabla.to_string(index=False))
        print()
        print("Nota: Chapinero es de las localidades mas empinadas de Bogota,")
        print("asi que se espera que la ciudad completa tenga pendientes MENORES.")
        print("No es una prueba de igualdad, es un contraste de contexto.")

    return {"prueba": "distribuciones ciudad vs Chapinero",
            "disponible": True, "tabla": filas, "pasa": True}


def verificar_muestreo_por_ventanas(muestras: pd.DataFrame,
                                    resolucion_m: float = RESOLUCION_CIUDAD_M,
                                    n_ventanas: int = 6,
                                    lado_m: float = 500.0,
                                    tolerancia_m: float = 2.0,
                                    fraccion_admitida: float = 0.10,
                                    semilla: int = 42,
                                    verboso: bool = True) -> dict:
    """Verifica el muestreo por teselas contra ventanas nuevas del WMS.

    Version de ciudad de d1_mdt.verificar_mosaico_contra_getmap. La diferencia
    es que aqui la ventana se pide A LA MISMA RESOLUCION que las teselas.

    Sin eso la prueba falla por una razon equivocada: las teselas de ciudad se
    piden a 2 m y la funcion de D1 pedia la ventana a 1 m, de modo que se
    comparaban dos rejillas distintas y la diferencia medida no era del proceso
    sino de la resolucion.

    La tolerancia es mayor que en D1 (2 m en vez de 1) porque a 2 m de celda un
    desfase de media celda sobre una ladera del 25 % ya produce medio metro de
    diferencia, y a eso se suma el redondeo a metro entero de la fuente.
    """
    import geopandas as gpd
    from rasterio.io import MemoryFile

    sesion = sesion_http()
    validos = muestras[muestras["elevacion_m"].notna()]
    if len(validos) == 0:
        return {"prueba": "muestreo por teselas vs ventana nueva del WMS",
                "pasa": False, "disponible": False,
                "motivo": "no hay elevaciones validas"}

    centros = validos.sample(min(n_ventanas, len(validos)), random_state=semilla)
    xs = validos["x"].to_numpy()
    ys = validos["y"].to_numpy()
    zs = validos["elevacion_m"].to_numpy()

    difs, n_vent, fallos = [], 0, 0
    for k, (_, c) in enumerate(centros.iterrows(), start=1):
        x0, x1 = c["x"] - lado_m / 2, c["x"] + lado_m / 2
        y0, y1 = c["y"] - lado_m / 2, c["y"] + lado_m / 2
        caja = gpd.GeoDataFrame(geometry=[box(x0, y0, x1, y1)],
                                crs=CRS_METRICO).to_crs(CRS_GEOGRAFICO)
        a, b, cc, d_ = caja.total_bounds
        lado_px = max(64, int(round(lado_m / resolucion_m)))

        try:
            r = sesion.get(MDT_WMS, timeout=240, params={
                "service": "WMS", "version": "1.3.0", "request": "GetMap",
                "layers": CAPA_CRUDA, "styles": "", "crs": "CRS:84",
                "bbox": f"{a},{b},{cc},{d_}",
                "width": lado_px, "height": lado_px, "format": "image/tiff"})
            r.raise_for_status()
            if "xml" in r.headers.get("Content-Type", ""):
                raise RuntimeError(r.text[:150])
        except Exception:  # noqa: BLE001
            fallos += 1
            continue

        dentro = (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
        if not dentro.any():
            continue
        n_vent += 1

        with MemoryFile(r.content) as mem, mem.open() as src:
            gp = gpd.GeoDataFrame(
                geometry=gpd.points_from_xy(xs[dentro], ys[dentro]),
                crs=CRS_METRICO).to_crs(src.crs)
            frescos = np.array(
                [float(v[0]) for v in
                 src.sample([(p.x, p.y) for p in gp.geometry])], dtype=float)

        locales = zs[dentro]
        ok = ((frescos >= RANGO_ELEVACION_M[0]) & (frescos <= RANGO_ELEVACION_M[1]))
        difs.extend(np.abs(frescos[ok] - locales[ok]).tolist())

        if verboso:
            print(f"  ventana {k}/{len(centros)} — acumulados {len(difs):,} puntos",
                  end="\r")

    if verboso:
        print()
    if not difs:
        return {"prueba": "muestreo por teselas vs ventana nueva del WMS",
                "pasa": False, "disponible": False,
                "motivo": f"ninguna ventana devolvio puntos ({fallos} fallos)"}

    difs = np.array(difs)
    n_malos = int((difs > tolerancia_m).sum())
    frac = n_malos / len(difs)
    mediana = float(np.median(difs))

    return {
        "prueba": "muestreo por teselas vs ventana nueva del WMS",
        "disponible": True,
        "resolucion_m": resolucion_m,
        "n_ventanas": n_vent,
        "n_comparados": int(len(difs)),
        "diferencia_mediana_m": round(mediana, 3),
        "diferencia_maxima_m": round(float(difs.max()), 3),
        "n_fuera_de_tolerancia": n_malos,
        "fraccion_fuera": round(frac, 4),
        "tolerancia_m": tolerancia_m,
        "pasa": mediana <= tolerancia_m and frac <= fraccion_admitida,
    }


# ===========================================================================
# 6. EMPAREJAMIENTO DE ARISTAS OPUESTAS, VERSION DE CIUDAD
# ===========================================================================

def aristas_inversas_coherentes_rapido(tabla, segmentos, tolerancia_m: float = 0.5,
                                       verboso: bool = True):
    """Equivalente exacto de d1_grafo.aristas_inversas_coherentes, mas rapido.

    La version de D1 calcula la distancia de Hausdorff entre cada arista y todas
    sus candidatas opuestas. A escala de ciudad son cientos de miles de llamadas
    a shapely dentro de un doble iterrows.

    Aqui se evita el calculo caro cuando se puede decidir sin el, sin cambiar
    ningun resultado:

      1. IGUALDAD EXACTA DE COORDENADAS. Cuando la Malla Vial declara doble
         sentido, `construir_grafo_dirigido` crea la arista opuesta con
         LineString(coords[::-1]). Su geometria invertida coincide entonces
         coordenada por coordenada, no solo dentro de la tolerancia. Comparar
         tuplas resuelve la mayoria de los casos y cuesta casi nada.

      2. PRUEBA DE ENVOLVENTE. Si las envolventes difieren en mas que la
         tolerancia en cualquier direccion, existe un punto de una que queda
         fuera del entorno de la otra, de modo que la distancia de Hausdorff
         supera la tolerancia con certeza. No hace falta calcularla: basta para
         descartar 'calzada_unica'. Es una cota, no una heuristica.

      3. El calculo completo se conserva para el unico caso donde hace falta
         desempatar: cuando hay mas de una candidata opuesta entre el mismo par
         de nodos.

    `verificar_equivalencia_emparejamiento` comprueba sobre una muestra que esta
    version devuelve lo mismo que la original, segun la regla 3 del equipo.
    """
    from shapely.geometry import LineString

    sid = segmentos["segmento_id"].to_numpy()
    u = segmentos["u"].astype(str).to_numpy()
    v = segmentos["v"].astype(str).to_numpy()
    geoms = segmentos.geometry.to_numpy()
    cajas = segmentos.geometry.bounds.to_numpy(dtype=float)

    candidatos = {}
    for i in range(len(sid)):
        candidatos.setdefault((u[i], v[i]), []).append(i)

    _coords = {}

    def coords_de(i):
        c = _coords.get(i)
        if c is None:
            g = geoms[i]
            c = () if (g is None or g.is_empty) else tuple(g.coords)
            _coords[i] = c
        return c

    inversos, tipos = {}, {}
    n_exactas = n_caja = n_hausdorff = 0

    for i in range(len(sid)):
        posibles = candidatos.get((v[i], u[i]))
        if not posibles:
            inversos[sid[i]], tipos[sid[i]] = None, "sin_opuesta"
            continue

        ci = coords_de(i)
        ci_rev = ci[::-1]

        if len(posibles) == 1:
            j = posibles[0]
            elegido, tipo = j, "calzada_separada"
            if ci and coords_de(j) == ci_rev:
                tipo = "calzada_unica"
                n_exactas += 1
            elif ci and coords_de(j):
                if float(np.abs(cajas[i] - cajas[j]).max()) > tolerancia_m:
                    n_caja += 1          # descartada por cota, sin Hausdorff
                else:
                    g_inv = LineString(ci_rev)
                    gc = geoms[j]
                    d = max(g_inv.hausdorff_distance(gc),
                            gc.hausdorff_distance(g_inv))
                    n_hausdorff += 1
                    if d <= tolerancia_m:
                        tipo = "calzada_unica"
            inversos[sid[i]], tipos[sid[i]] = sid[elegido], tipo
            continue

        # Varias candidatas: se calcula completo, como en D1, para desempatar.
        elegido, tipo, mejor_d = None, "calzada_separada", np.inf
        if ci:
            g_inv = LineString(ci_rev)
            for j in posibles:
                gc = geoms[j]
                if gc is None or gc.is_empty:
                    continue
                d = max(g_inv.hausdorff_distance(gc), gc.hausdorff_distance(g_inv))
                n_hausdorff += 1
                if d < mejor_d:
                    mejor_d, elegido = d, j
            if elegido is not None and mejor_d <= tolerancia_m:
                tipo = "calzada_unica"
        if elegido is None:
            elegido = posibles[0]
        inversos[sid[i]], tipos[sid[i]] = sid[elegido], tipo

    if verboso:
        print(f"Emparejamiento de aristas opuestas:")
        print(f"  resueltas por coordenadas exactas : {n_exactas:,}")
        print(f"  descartadas por envolvente        : {n_caja:,}")
        print(f"  con distancia de Hausdorff        : {n_hausdorff:,}")

    tabla = tabla.copy()
    tabla["segmento_inverso_id"] = tabla["segmento_id"].map(inversos)
    tabla["tipo_opuesta"] = tabla["segmento_id"].map(tipos)
    return tabla


def verificar_equivalencia_emparejamiento(tabla, segmentos, n: int = 4000,
                                          semilla: int = 42,
                                          verboso: bool = True) -> dict:
    """Compara la version rapida contra la de D1 sobre una submuestra.

    Regla 3 del equipo: el resultado se recalcula por un camino distinto al que
    lo produjo. Aqui el camino distinto es directamente la implementacion
    original, aplicada a un subconjunto de aristas lo bastante pequeno para que
    sea viable.
    """
    sub = segmentos.sample(min(n, len(segmentos)), random_state=semilla)
    # El subconjunto debe incluir las opuestas, o el emparejamiento no existe.
    pares = set(zip(sub["v"].astype(str), sub["u"].astype(str)))
    extra = segmentos[[(a, b) in pares for a, b in
                       zip(segmentos["u"].astype(str), segmentos["v"].astype(str))]]
    sub = pd.concat([sub, extra]).drop_duplicates(subset=["segmento_id"])

    t_sub = tabla[tabla["segmento_id"].isin(set(sub["segmento_id"]))][["segmento_id"]]

    ref = d1.aristas_inversas_coherentes(t_sub, sub)
    rap = aristas_inversas_coherentes_rapido(t_sub, sub, verboso=False)

    m = ref.merge(rap, on="segmento_id", suffixes=("_ref", "_rap"))
    dif_tipo = int((m["tipo_opuesta_ref"] != m["tipo_opuesta_rap"]).sum())
    dif_inv = int((m["segmento_inverso_id_ref"].fillna("")
                   != m["segmento_inverso_id_rap"].fillna("")).sum())

    salida = {
        "prueba": "emparejamiento rapido equivale al de D1",
        "n_comparados": int(len(m)),
        "diferencias_en_tipo": dif_tipo,
        "diferencias_en_inverso": dif_inv,
        "pasa": dif_tipo == 0 and dif_inv == 0,
    }
    if verboso:
        print(f"Aristas comparadas : {len(m):,}")
        print(f"Difieren en tipo   : {dif_tipo}")
        print(f"Difieren en inverso: {dif_inv}")
    return salida

def asignar_sigma_z_por_zona(segmentos, verboso: bool = True) -> dict:
    """Asigna a cada segmento el sigma_z del DEM que lo cubre.

    PROXY DECLARADO: el catalogo del ImageServer, que diria exactamente que
    raster del mosaico cubre cada punto, devuelve HTTP 403. Se usa como
    sustituto la clasificacion POT rural mas la pertenencia a una localidad
    con territorio rural. La asignacion sobreestima el error en algunos
    segmentos urbanos de esas localidades: es deliberado, va del lado
    conservador.
    """
    es_rural = segmentos["highway"].eq("rural")
    if "localidad" in segmentos.columns:
        es_rural = es_rural | (
            segmentos["highway"].isin(["rural", "sin_definir"])
            & segmentos["localidad"].isin(LOCALIDADES_CON_RURAL))

    sigma = np.where(es_rural, SIGMA_Z_POR_ZONA["zy3_rural"],
                     SIGMA_Z_POR_ZONA["lidar"])

    if verboso:
        n_r = int(es_rural.sum())
        print(f"Asignacion de sigma_z por zona del mosaico (proxy declarado):")
        print(f"  LiDAR      sigma_z = {SIGMA_Z_POR_ZONA['lidar']:.3f} m : "
              f"{len(segmentos) - n_r:,} segmentos")
        print(f"  ZY3 rural  sigma_z = {SIGMA_Z_POR_ZONA['zy3_rural']:.3f} m : "
              f"{n_r:,} segmentos ({100*n_r/len(segmentos):.2f} %)")

    return dict(zip(segmentos["segmento_id"], sigma))


def sensibilidad_confiabilidad(tabla, sigma_z_candidatos,
                               anchos_correlacion=(None,),
                               sigma_cuantizacion_m=None,
                               longitud_minima_m=LONGITUD_MINIMA_PENDIENTE_M,
                               verboso: bool = True) -> pd.DataFrame:
    """Recalcula la confiabilidad para varios sigma_z, SIN reprocesar nada.

    Por que se puede: sigma solo depende del error vertical y de la longitud
    del segmento, y la longitud ya esta en la tabla. No entra el muestreo del
    MDT. Recorrer todas las combinaciones cuesta segundos.

    Es la tabla que reemplaza la discusion sobre que numero adoptar: en lugar
    de elegir uno, se mide cuanto importa la eleccion. Mismo criterio que se
    uso con el umbral textual del Bloque B3.
    """
    if sigma_cuantizacion_m is None:
        sigma_cuantizacion_m = SIGMA_CUANTIZACION_M

    L = tabla["longitud_perfil_m"].to_numpy(dtype=float)
    p = tabla["pendiente_neta"].to_numpy(dtype=float)
    valido = (~np.isnan(p)) & (L > 0)

    filas = []
    for etiqueta, s_total in sigma_z_candidatos.items():
        for a in anchos_correlacion:
            s_corr = np.sqrt(max(s_total ** 2 - sigma_cuantizacion_m ** 2, 0.0))
            rho = np.exp(-L / a) if a else np.zeros_like(L)
            var = 2 * (s_corr ** 2) * (1 - rho) + 2 * (sigma_cuantizacion_m ** 2)
            with np.errstate(divide="ignore", invalid="ignore"):
                sig = np.sqrt(var) / L

            largo = valido & (L >= longitud_minima_m)
            distinta = valido & (np.abs(p) > 2 * sig)

            filas.append({
                "sigma_z_m": s_total,
                "etiqueta_sigma": etiqueta,
                "ancho_correlacion_m": a if a else "sin correccion",
                "n_con_pendiente": int(valido.sum()),
                "n_longitud_suficiente": int(largo.sum()),
                "pct_longitud_suficiente": round(100 * largo.sum() / valido.sum(), 2),
                "n_distinta_de_cero": int(distinta.sum()),
                "n_confiable_combinado": int((largo & distinta).sum()),
                "pct_confiable_combinado": round(
                    100 * (largo & distinta).sum() / valido.sum(), 2),
            })

    res = pd.DataFrame(filas)
    if verboso:
        print(res.to_string(index=False))
        print()
        print("n_longitud_suficiente NO depende de sigma_z: es solo el corte de")
        print("longitud. Lo que cambia con sigma_z es n_distinta_de_cero, o sea")
        print("cuantas pendientes se distinguen del ruido.")
    return res

