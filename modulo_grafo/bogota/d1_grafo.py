"""
d1_grafo.py — Funciones del Bloque D1: grafo vial dirigido con pendiente por segmento.

Diseno:
  - Ninguna funcion escribe en disco. El cuaderno decide que guardar.
  - Ninguna funcion asume estado de una ejecucion anterior.
  - Toda funcion que devuelve geometria la devuelve en CRS_METRICO (EPSG:9377).
  - Las funciones de verificacion recalculan por un camino distinto al que
    produjo el numero, segun la regla 3 del equipo.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform as shp_transform

import geopandas as gpd

from constantes_d1 import (
    CRS_METRICO,
    CRS_GEOGRAFICO,
    MDT_IMAGESERVER,
    PASO_MUESTREO_M,
    LOTE_MUESTREO,
    LONGITUD_MINIMA_PENDIENTE_M,
    FILTRO_OSM_VEHICULO,
)

# La capa de red vive en d1_red.py: sesion con reintentos, descubrimiento de
# campos y diagnostico de DNS. Se separo tras el fallo intermitente de
# resolucion de nombres en la primera corrida.
from d1_red import (           # noqa: F401
    sesion_http,
    diagnostico_red,
    probar_imageserver,
    descargar_limite_localidad,
    cargar_limite_manual,
    _pedir_muestras,
    sello_de_tiempo,
)

ZONA_HORARIA_BOGOTA = timezone(timedelta(hours=-5))


# ===========================================================================
# 2. RED VIAL DIRIGIDA
# ===========================================================================

def descargar_grafo_osm(poligono_gdf: gpd.GeoDataFrame):
    """Construye el grafo vial dirigido de OSM dentro del poligono dado.

    Requiere osmnx. Devuelve (grafo, metadatos).
    El grafo respeta el sentido de circulacion: una via de una sola direccion
    produce una sola arista; una de doble sentido produce dos aristas opuestas.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise ImportError(
            "Falta osmnx. Instale con: pip install osmnx"
        ) from exc

    # osmnx trabaja en EPSG:4326 para la consulta.
    poly_wgs = poligono_gdf.to_crs(CRS_GEOGRAFICO).geometry.union_all()

    # Compatibilidad osmnx 1.x / 2.x
    try:
        ox.settings.use_cache = True
        ox.settings.log_console = False
    except AttributeError:
        ox.config(use_cache=True, log_console=False)

    grafo = ox.graph_from_polygon(
        poly_wgs,
        custom_filter=FILTRO_OSM_VEHICULO,
        simplify=True,
        retain_all=False,
        truncate_by_edge=True,
    )

    metadatos = {
        "fecha_descarga": sello_de_tiempo(),
        "filtro_osm": FILTRO_OSM_VEHICULO,
        "n_nodos": grafo.number_of_nodes(),
        "n_aristas": grafo.number_of_edges(),
        "osmnx_version": getattr(ox, "__version__", "desconocida"),
    }
    return grafo, metadatos


def grafo_a_segmentos(grafo) -> gpd.GeoDataFrame:
    """Convierte el grafo de osmnx en un GeoDataFrame de aristas dirigidas.

    Cada fila es un segmento dirigido con un `segmento_id` estable.
    El id se construye con (u, v, key) de OSM, que no cambia entre ejecuciones
    mientras no cambie el mapa. Es el identificador que Danna usa para devolver
    la pendiente y con el que Emily engancha el consumo.
    """
    import osmnx as ox

    aristas = ox.graph_to_gdfs(grafo, nodes=False, edges=True)
    aristas = aristas.reset_index()  # expone u, v, key como columnas

    aristas = aristas.to_crs(CRS_METRICO)

    aristas["segmento_id"] = (
        aristas["u"].astype(str) + "_" +
        aristas["v"].astype(str) + "_" +
        aristas["key"].astype(str)
    )

    # osm_id puede venir como lista cuando osmnx fusiona varias vias.
    if "osmid" in aristas.columns:
        aristas["osmid"] = aristas["osmid"].apply(
            lambda v: ",".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
        )
    for col in ("name", "highway", "maxspeed", "lanes", "ref", "bridge", "tunnel"):
        if col in aristas.columns:
            aristas[col] = aristas[col].apply(
                lambda v: "|".join(map(str, v)) if isinstance(v, (list, tuple))
                else (None if pd.isna(v) else str(v))
            )

    # Longitud recalculada en el CRS metrico. NO se usa la que trae osmnx,
    # que viene de un calculo geodesico distinto: mas adelante se comparan
    # las dos como verificacion independiente.
    aristas["longitud_m"] = aristas.geometry.length

    columnas = [c for c in [
        "segmento_id", "u", "v", "key", "osmid", "name", "highway",
        "oneway", "maxspeed", "lanes", "bridge", "tunnel",
        "longitud_m", "length", "geometry"
    ] if c in aristas.columns]

    return aristas[columnas].copy()


# ===========================================================================
# 3. MUESTREO DE ELEVACION
# ===========================================================================

def densificar_segmento(linea: LineString, paso_m: float = PASO_MUESTREO_M):
    """Genera puntos a lo largo de una linea, espaciados `paso_m`.

    Siempre incluye el punto inicial y el final exactos, porque la pendiente
    neta del segmento se define entre sus extremos.
    Devuelve (lista_de_puntos, distancias_acumuladas).
    """
    largo = linea.length
    if largo <= 0:
        p = linea.interpolate(0.0)
        return [p], np.array([0.0])

    n_intervalos = max(1, int(np.ceil(largo / paso_m)))
    distancias = np.linspace(0.0, largo, n_intervalos + 1)
    puntos = [linea.interpolate(float(d)) for d in distancias]
    return puntos, distancias


def muestrear_elevacion(puntos, lote=LOTE_MUESTREO, mostrar_avance=True):
    """Muestrea el MDT en una lista de shapely Points (en EPSG:9377).

    Devuelve un DataFrame con: indice, x, y, elevacion_m, resolucion_m, zona_mdt.
    Los puntos fuera de cobertura quedan con elevacion NaN (no se inventa valor).
    """
    coords = [(p.x, p.y) for p in puntos]
    filas = [None] * len(coords)

    for inicio in range(0, len(coords), lote):
        trozo = coords[inicio:inicio + lote]
        muestras = _pedir_muestras(trozo)

        # getSamples omite los puntos sin dato, asi que hay que reubicar por
        # locationId y no por posicion en la respuesta. Este es exactamente el
        # tipo de desalineamiento de indices que causo el error del Bloque A.
        vistos = {}
        for m in muestras:
            loc_id = int(m.get("locationId", -1))
            vistos[loc_id] = m

        for j in range(len(trozo)):
            idx_global = inicio + j
            m = vistos.get(j)
            if m is None or m.get("value") in (None, "", "NoData"):
                filas[idx_global] = {
                    "indice": idx_global,
                    "x": trozo[j][0], "y": trozo[j][1],
                    "elevacion_m": np.nan,
                    "resolucion_m": np.nan,
                }
                continue
            try:
                valor = float(str(m["value"]).split()[0])
            except (ValueError, IndexError):
                valor = np.nan
            resolucion = m.get("resolution")
            if isinstance(resolucion, dict):
                resolucion = resolucion.get("x")
            filas[idx_global] = {
                "indice": idx_global,
                "x": trozo[j][0], "y": trozo[j][1],
                "elevacion_m": valor,
                "resolucion_m": float(resolucion) if resolucion else np.nan,
            }

        if mostrar_avance:
            print(f"  muestreados {min(inicio + lote, len(coords))}/{len(coords)}",
                  end="\r")

    if mostrar_avance:
        print()

    df = pd.DataFrame(filas)
    df["zona_mdt"] = df["resolucion_m"].apply(_zona_por_resolucion)
    df["rmse_z_m"] = df["resolucion_m"].apply(_rmse_por_resolucion)
    return df


# Estas dos funciones mapeaban la resolucion que devolvia getSamples a una
# zona del mosaico y a su RMSE Z. Se retiran del uso por dos razones:
#
#   1. getSamples devuelve 403. En la via actual (teselas por WMS) el campo
#      `resolucion_m` guarda la resolucion PEDIDA, no la del DEM subyacente.
#   2. Eran silenciosamente incorrectas: con resolucion pedida de 2,0 m
#      buscaban la clave mas cercana, encontraban 1,0 y devolvian "urbano"
#      con RMSE 0,100 m. Atribuian zona urbana a todo el muestreo de la
#      ciudad sin que nada fallara.
#
# Se conservan como funciones inertes para no romper la prueba sintetica y
# cualquier cuaderno de D1 que las llame. La incertidumbre vertical real se
# toma de constantes_d1.SIGMA_CUANTIZACION_M y del sigma_z que se adopte
# (ver el conflicto 0,114 vs 0,54 documentado en constantes_d1).

def _zona_por_resolucion(res):
    """Retirada. Devuelve siempre "no_determinada": la via actual no informa
    a que DEM del mosaico pertenece cada punto."""
    return "no_determinada"


def _rmse_por_resolucion(res):
    """Retirada. Devuelve NaN para que quien la llame use el sigma_z
    declarado explicitamente en vez de uno inferido de la resolucion."""
    return np.nan


# ===========================================================================
# 4. PENDIENTE POR SEGMENTO
# ===========================================================================

def calcular_pendiente_segmento(distancias, elevaciones, rmse_z=0.10,
                                ancho_correlacion_m=None,
                                sigma_cuantizacion_m=None):
    """Calcula la pendiente de un segmento a partir de su perfil de elevacion.

    Se reportan tres estimadores distintos, porque miden cosas distintas:

      pendiente_neta       (z_fin - z_ini) / longitud
                           Es la que gobierna el termino gravitacional de la
                           energia: solo importa el desnivel total.

      pendiente_regresion  pendiente de la recta ajustada a z contra distancia.
                           Menos sensible a un error puntual en un extremo.

      pendiente_max_local  mayor pendiente entre dos puntos consecutivos.
                           Es la que limita la potencia en ascenso sostenido.

    Devuelve un dict. Las pendientes van en fraccion (0,08 = 8 %).
    """
    d = np.asarray(distancias, dtype=float)
    z = np.asarray(elevaciones, dtype=float)

    validos = ~np.isnan(z)
    n_validos = int(validos.sum())
    largo = float(d[-1]) if len(d) else 0.0

    salida = {
        "longitud_perfil_m": largo,
        "n_muestras": len(d),
        "n_muestras_validas": n_validos,
        "desnivel_m": np.nan,
        "pendiente_neta": np.nan,
        "pendiente_regresion": np.nan,
        "r2_regresion": np.nan,
        "pendiente_max_local": np.nan,
        "ascenso_acumulado_m": np.nan,
        "descenso_acumulado_m": np.nan,
        "sigma_pendiente": np.nan,
        "rho_correlacion": np.nan,
        "longitud_suficiente": False,
        "distinta_de_cero": False,
        "pendiente_confiable": False,
    }

    if n_validos < 2 or largo <= 0:
        return salida

    d_v, z_v = d[validos], z[validos]

    # --- pendiente neta entre extremos validos
    desnivel = float(z_v[-1] - z_v[0])
    tramo = float(d_v[-1] - d_v[0])
    if tramo <= 0:
        return salida
    salida["desnivel_m"] = desnivel
    salida["pendiente_neta"] = desnivel / tramo

    # --- regresion lineal
    coef = np.polyfit(d_v, z_v, 1)
    salida["pendiente_regresion"] = float(coef[0])
    z_pred = np.polyval(coef, d_v)
    ss_res = float(np.sum((z_v - z_pred) ** 2))
    ss_tot = float(np.sum((z_v - np.mean(z_v)) ** 2))
    salida["r2_regresion"] = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    # --- perfil punto a punto
    dz = np.diff(z_v)
    dd = np.diff(d_v)
    with np.errstate(divide="ignore", invalid="ignore"):
        pend_local = np.where(dd > 0, dz / dd, np.nan)
    if np.any(~np.isnan(pend_local)):
        salida["pendiente_max_local"] = float(np.nanmax(np.abs(pend_local)))
    salida["ascenso_acumulado_m"] = float(np.sum(dz[dz > 0]))
    salida["descenso_acumulado_m"] = float(-np.sum(dz[dz < 0]))

    # --- incertidumbre de la pendiente neta
    #
    # El error vertical tiene DOS componentes de naturaleza distinta y hay que
    # propagarlos por separado:
    #
    #   CORRELACIONADO (LiDAR, georreferenciacion): el error de dos puntos
    #   cercanos se parece, asi que al restar alturas se cancela en parte.
    #     Var = 2 * sigma_corr^2 * (1 - rho(L)),  con rho(L) = exp(-L/a)
    #
    #   INDEPENDIENTE (cuantizacion): el servicio entrega uint32 con alturas
    #   redondeadas a metro entero (VERIFICADO 2026-09-18 sobre una ventana de
    #   256x256 px: 179 valores distintos en 178 m de rango, cero decimales).
    #   El redondeo es un volado en cada pixel: NO se cancela nunca.
    #     Var = 2 * sigma_cuant^2
    #
    # Por que importa separarlos: si se aplica rho al error COMPLETO, en
    # segmentos cortos rho tiende a 1, la varianza tiende a 0 y sigma tiende a
    # 0. Un segmento de 1,75 m con pendiente aparente del 171 % quedaria
    # marcado como confiable. El termino de cuantizacion es el piso que lo
    # impide.
    #
    # Retrocompatible: con ancho_correlacion_m=None y sigma_cuantizacion_m=None
    # el resultado es identico a la version anterior.
    if not np.isnan(rmse_z):
        s_cuant = 0.0 if sigma_cuantizacion_m is None else float(sigma_cuantizacion_m)

        if sigma_cuantizacion_m is None:
            # Modo anterior: rmse_z es el error total, sin descomponer.
            s_corr = float(rmse_z)
        else:
            # rmse_z es el error total; se le descuenta la cuantizacion en
            # cuadratura para aislar la parte correlacionada. Si rmse_z fuera
            # menor que la cuantizacion (inconsistente), se acota en 0.
            s_corr = float(np.sqrt(max(rmse_z ** 2 - s_cuant ** 2, 0.0)))

        if ancho_correlacion_m:
            rho = float(np.exp(-tramo / ancho_correlacion_m))
        else:
            rho = 0.0
        salida["rho_correlacion"] = rho

        varianza = 2.0 * (s_corr ** 2) * (1.0 - rho) + 2.0 * (s_cuant ** 2)
        sigma = float(np.sqrt(varianza) / tramo)
        salida["sigma_pendiente"] = sigma

        # Dos criterios SEPARADOS, porque responden preguntas distintas:
        #   longitud_suficiente -> la medicion es utilizable
        #   distinta_de_cero    -> la pendiente se distingue del ruido
        # La marca combinada anterior mezclaba las dos, y por eso descartaba
        # las calles planas (su pendiente no supera 2 sigma), lo que obligaba
        # a duplicar cada tabla del informe. Para el ruteo la que importa es
        # la primera: el modelo de consumo usa pendiente_neta de todos modos.
        salida["longitud_suficiente"] = bool(tramo >= LONGITUD_MINIMA_PENDIENTE_M)
        salida["distinta_de_cero"] = bool(abs(salida["pendiente_neta"]) > 2 * sigma)
        # Se conserva el nombre anterior para no romper cuadernos existentes.
        salida["pendiente_confiable"] = bool(
            salida["longitud_suficiente"] and salida["distinta_de_cero"])

    return salida


def perfil_por_segmento(segmentos: gpd.GeoDataFrame,
                        muestras: pd.DataFrame,
                        mapa_indices: dict) -> pd.DataFrame:
    """Arma la tabla de pendiente por segmento.

    mapa_indices: {segmento_id: (indices_en_muestras, distancias_acumuladas)}
    """
    elev = muestras.set_index("indice")["elevacion_m"].to_dict()
    rmse = muestras.set_index("indice")["rmse_z_m"].to_dict()
    zona = muestras.set_index("indice")["zona_mdt"].to_dict()

    filas = []
    for seg_id, (indices, distancias) in mapa_indices.items():
        z = [elev.get(i, np.nan) for i in indices]
        rmses = [rmse.get(i, np.nan) for i in indices]
        zonas = [zona.get(i, "desconocida") for i in indices]

        rmse_seg = np.nanmax(rmses) if np.any(~np.isnan(rmses)) else np.nan
        zonas_unicas = sorted(set(z_ for z_ in zonas if z_ != "desconocida"))

        res = calcular_pendiente_segmento(distancias, z,
                                          rmse_z=rmse_seg if not np.isnan(rmse_seg) else 0.10)
        res["segmento_id"] = seg_id
        res["zona_mdt"] = "|".join(zonas_unicas) if zonas_unicas else "desconocida"
        res["cruza_zonas"] = len(zonas_unicas) > 1
        res["rmse_z_usado_m"] = rmse_seg
        filas.append(res)

    return pd.DataFrame(filas)


def aristas_inversas_coherentes(tabla, segmentos, tolerancia_m=0.5):
    """Empareja cada arista dirigida con su opuesta, comparando GEOMETRIA.

    Distingue dos casos que antes se mezclaban:
      - 'calzada_unica': la opuesta tiene la misma geometria invertida. Su
        pendiente DEBE ser simetrica.
      - 'calzada_separada': existe arista opuesta entre los mismos nodos pero
        con trazado distinto (avenida con separador). Su pendiente NO tiene por
        que ser simetrica: son dos vias fisicas diferentes.
    """
    from shapely.geometry import LineString

    info = segmentos.set_index("segmento_id")[["u", "v"]].copy()
    geoms = segmentos.set_index("segmento_id").geometry.to_dict()

    candidatos = {}
    for sid, fila in info.iterrows():
        candidatos.setdefault((str(fila["u"]), str(fila["v"])), []).append(sid)

    inversos, tipos = {}, {}
    for sid, fila in info.iterrows():
        posibles = candidatos.get((str(fila["v"]), str(fila["u"])), [])
        if not posibles:
            inversos[sid], tipos[sid] = None, "sin_opuesta"
            continue

        g = geoms.get(sid)
        elegido, tipo = None, "calzada_separada"
        if g is not None and not g.is_empty:
            g_inv = LineString(list(g.coords)[::-1])
            mejor_d = np.inf
            for cand in posibles:
                gc = geoms.get(cand)
                if gc is None or gc.is_empty:
                    continue
                d = max(g_inv.hausdorff_distance(gc), gc.hausdorff_distance(g_inv))
                if d < mejor_d:
                    mejor_d, elegido = d, cand
            if elegido is not None and mejor_d <= tolerancia_m:
                tipo = "calzada_unica"
        if elegido is None:
            elegido = posibles[0]
        inversos[sid], tipos[sid] = elegido, tipo

    tabla = tabla.copy()
    tabla["segmento_inverso_id"] = tabla["segmento_id"].map(inversos)
    tabla["tipo_opuesta"] = tabla["segmento_id"].map(tipos)
    return tabla


# ===========================================================================
# 5. VERIFICACIONES INDEPENDIENTES (regla 3 del equipo)
# ===========================================================================

def verificar_longitudes(segmentos: gpd.GeoDataFrame,
                         tolerancia_relativa: float = 0.01) -> dict:
    """Compara la longitud proyectada contra la longitud geodesica.

    Son dos caminos de calculo distintos: uno usa la proyeccion 9377, el otro
    calcula sobre el elipsoide con pyproj. Si difieren mas de la tolerancia,
    algo esta mal en el CRS.
    """
    from pyproj import Geod

    geod = Geod(ellps="GRS80")
    wgs = segmentos.to_crs(CRS_GEOGRAFICO)

    largos_geo = []
    for geom in wgs.geometry:
        if geom is None or geom.is_empty:
            largos_geo.append(np.nan)
            continue
        lons, lats = zip(*list(geom.coords))
        largos_geo.append(geod.line_length(lons, lats))

    proyectada = segmentos["longitud_m"].to_numpy(dtype=float)
    geodesica = np.array(largos_geo, dtype=float)

    validos = (~np.isnan(geodesica)) & (geodesica > 0)
    dif_rel = np.full(len(geodesica), np.nan)
    dif_rel[validos] = np.abs(proyectada[validos] - geodesica[validos]) / geodesica[validos]

    n_malos = int(np.sum(dif_rel[validos] > tolerancia_relativa))
    return {
        "prueba": "longitud proyectada vs geodesica",
        "n_evaluados": int(validos.sum()),
        "n_fuera_de_tolerancia": n_malos,
        "dif_relativa_max": float(np.nanmax(dif_rel)) if validos.any() else np.nan,
        "dif_relativa_mediana": float(np.nanmedian(dif_rel)) if validos.any() else np.nan,
        "pasa": n_malos == 0,
    }


def verificar_muestreo_en_geometria(segmentos: gpd.GeoDataFrame,
                                    muestras: pd.DataFrame,
                                    mapa_indices: dict,
                                    tolerancia_m: float = 0.5) -> dict:
    """Comprueba que cada punto muestreado cae sobre la geometria de SU segmento.

    Esta es la prueba que habria atrapado el error del Bloque A: verifica que
    la fila que se une es la fila que produjo el dato.
    """
    geoms = segmentos.set_index("segmento_id").geometry.to_dict()
    coords = muestras.set_index("indice")[["x", "y"]].to_dict("index")

    peor = 0.0
    n_malos = 0
    n_total = 0
    ejemplos = []

    for seg_id, (indices, _dist) in mapa_indices.items():
        geom = geoms.get(seg_id)
        if geom is None:
            continue
        for i in indices:
            c = coords.get(i)
            if c is None:
                continue
            n_total += 1
            d = geom.distance(Point(c["x"], c["y"]))
            peor = max(peor, d)
            if d > tolerancia_m:
                n_malos += 1
                if len(ejemplos) < 5:
                    ejemplos.append({"segmento_id": seg_id, "indice": i,
                                     "distancia_m": round(d, 3)})

    return {
        "prueba": "cada muestra cae sobre su propio segmento",
        "n_evaluados": n_total,
        "n_fuera_de_tolerancia": n_malos,
        "distancia_maxima_m": round(peor, 4),
        "ejemplos": ejemplos,
        "pasa": n_malos == 0,
    }


def verificar_signo_inverso(tabla, tolerancia=1e-6):
    """La pendiente debe ser simetrica SOLO en pares de calzada unica."""
    pend = tabla.set_index("segmento_id")["pendiente_neta"].to_dict()
    n_pares = n_malos = 0
    peor = 0.0
    ejemplos = []
    vistos = set()

    for _, f in tabla.iterrows():
        if f.get("tipo_opuesta") != "calzada_unica":
            continue
        inv = f.get("segmento_inverso_id")
        if inv is None or (isinstance(inv, float) and pd.isna(inv)):
            continue
        clave = tuple(sorted([f["segmento_id"], inv]))
        if clave in vistos:
            continue
        p1, p2 = f["pendiente_neta"], pend.get(inv, np.nan)
        if pd.isna(p1) or pd.isna(p2):
            continue
        vistos.add(clave)
        n_pares += 1
        err = abs(p1 + p2)
        peor = max(peor, err)
        if err > tolerancia:
            n_malos += 1
            if len(ejemplos) < 5:
                ejemplos.append({"segmento_id": f["segmento_id"], "inverso": inv,
                                 "p1": round(float(p1), 6), "p2": round(float(p2), 6)})

    conteo = (tabla["tipo_opuesta"].value_counts().to_dict()
              if "tipo_opuesta" in tabla else {})
    return {
        "prueba": "pendiente simetrica en calzada unica",
        "n_pares_calzada_unica": n_pares,
        "n_calzada_separada": int(conteo.get("calzada_separada", 0)),
        "n_sin_opuesta": int(conteo.get("sin_opuesta", 0)),
        "n_fuera_de_tolerancia": n_malos,
        "error_maximo": float(peor),
        "ejemplos": ejemplos,
        "pasa": n_malos == 0,
    }


def verificar_identificadores_unicos(segmentos: gpd.GeoDataFrame) -> dict:
    """Cada segmento aparece exactamente una vez."""
    n = len(segmentos)
    n_unicos = segmentos["segmento_id"].nunique()
    return {
        "prueba": "segmento_id unico",
        "n_segmentos": n,
        "n_identificadores_unicos": n_unicos,
        "pasa": n == n_unicos,
    }


def resumen_pruebas(pruebas: list[dict]) -> pd.DataFrame:
    """Tabla compacta de resultados, para pegar en el informe."""
    filas = []
    for p in pruebas:
        filas.append({
            "prueba": p["prueba"],
            "resultado": "PASA" if p["pasa"] else "FALLA",
            "detalle": ", ".join(
                f"{k}={v}" for k, v in p.items()
                if k not in ("prueba", "pasa", "ejemplos")
            ),
        })
    return pd.DataFrame(filas)
