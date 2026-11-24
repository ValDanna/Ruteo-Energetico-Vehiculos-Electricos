"""
carga.py — Capa de lectura de la página interactiva.

Regla: esta capa SOLO LEE. No recalcula inventario ni pendientes y no escribe
en ninguna carpeta de entregables. Todo lo que devuelve pasó pruebas que pueden
fallar; si una falla, lanza ErrorCarga y la página no arranca.

Funciones públicas:
    cargar_estaciones()  -> (GeoDataFrame, lista de pruebas)
    cargar_grafo()       -> (GeoDataFrame de segmentos, MultiDiGraph, lista de pruebas)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
from pyproj import Geod, Transformer

CRS_METRICO = "EPSG:9377"
CRS_GEOGRAFICO = "EPSG:4326"

# Conteos del cierre de B4. Si cambian, alguien regeneró B4 y hay que revisar.
ESPERADO_FILAS_B4 = 74
ESPERADO_PRINCIPALES = {"Bogota": 52, "Medellin": 19}

# distancia_m viene redondeada a 0,1 m. 0,5 m cubre redondeo y la diferencia
# geodésica vs proyectada a estas distancias; un error de unión da cientos de m.
TOLERANCIA_DISTANCIA_M = 0.5


class ErrorCarga(RuntimeError):
    """Una verificación falló. La página no debe mostrar datos."""


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def localizar_proyecto() -> Path:
    """F:\\Tesis sin rutas absolutas: variable de entorno o subir buscando 'Bloque A'."""
    env = os.environ.get("RUTA_PROYECTO_TESIS_RAIZ")
    if env:
        return Path(env)
    for carpeta in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (carpeta / "Bloque A").is_dir():
            return carpeta
    raise ErrorCarga("No encontré la carpeta que contiene 'Bloque A'. "
                     "Defina RUTA_PROYECTO_TESIS_RAIZ.")


RAIZ = localizar_proyecto()

# Única declaración de dónde está cada salida que consume la página.
RUTAS = {
    "b4_inventario": RAIZ / "Bloque B" / "Entregable B4" / "B4_inventario_atributos_ruteo.csv",
    "b4_huellas":    RAIZ / "Bloque B" / "Entregable B4" / "B4_huellas_salidas.json",
    "d1_grafo":      RAIZ / "Bloque D" / "entregables" / "D1" / "grafo_chapinero_pendiente.gpkg",
    "d1_limite":     RAIZ / "Bloque D" / "entregables" / "D1" / "limite_chapinero.gpkg",
    "d1_huellas":    RAIZ / "Bloque D" / "entregables" / "D1" / "D1_huellas_salidas.json",
}


def _importar_constantes():
    carpeta = RAIZ / "Bloque A"
    if str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))
    import constantes  # noqa: E402
    return constantes


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _prueba(nombre: str, pasa: bool, detalle: str) -> dict:
    return {"prueba": nombre, "pasa": bool(pasa), "detalle": detalle}


def _huella_esperada(huellas: dict, nombre: str) -> str | None:
    """Acepta el formato de B4 {archivo: hash} y el de D1 {archivos: {archivo: {sha256}}}."""
    if "archivos" in huellas:
        v = huellas["archivos"].get(nombre)
        return v.get("sha256") if v else None
    return huellas.get(nombre)


def verificar_huella(ruta: Path, ruta_huellas: Path) -> dict:
    nombre = f"huella {ruta.name}"
    if not ruta.exists():
        return _prueba(nombre, False, f"no existe {ruta}")
    if not ruta_huellas.exists():
        return _prueba(nombre, False, f"no existe {ruta_huellas.name}")
    esperado = _huella_esperada(json.load(open(ruta_huellas, encoding="utf-8")), ruta.name)
    if esperado is None:
        return _prueba(nombre, False, f"{ruta.name} no aparece en {ruta_huellas.name}")
    real = sha256(ruta)
    return _prueba(nombre, real == esperado,
                   f"esperado {esperado[:12]}…  real {real[:12]}…")


def _fallar_si_hay_errores(pruebas: list[dict], que: str):
    malas = [p for p in pruebas if not p["pasa"]]
    if malas:
        texto = "\n".join(f"  - {p['prueba']}: {p['detalle']}" for p in malas)
        raise ErrorCarga(f"No se cargan {que}. Fallaron {len(malas)} pruebas:\n{texto}")


# ---------------------------------------------------------------------------
# Estaciones
# ---------------------------------------------------------------------------

def cargar_estaciones() -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Inventario B4 con posición tomada de los insumos congelados A2 (OSM) y A3 (OCM).

    Posición dibujada: OSM si existe, si no OCM. Nunca un promedio, porque
    promediar inventa un punto que ninguna fuente declaró.
    """
    pruebas = [verificar_huella(RUTAS["b4_inventario"], RUTAS["b4_huellas"])]
    _fallar_si_hay_errores(pruebas, "estaciones")

    inv = pd.read_csv(RUTAS["b4_inventario"])
    osm, ocm = _importar_constantes().cargar_fuentes_estaciones()

    # --- claves -----------------------------------------------------------
    osm = osm.rename(columns={"id": "osm_uid", "lat": "lat_osm", "lon": "lon_osm"})
    ocm = ocm.rename(columns={"id": "ocm_id", "lat": "lat_ocm", "lon": "lon_ocm"})
    osm["osm_uid"] = osm["osm_uid"].astype(str)
    ocm["ocm_id"] = pd.to_numeric(ocm["ocm_id"], errors="raise").astype("Int64")
    inv["ocm_id"] = inv["ocm_id"].astype("Int64")

    formato_ok = osm["osm_uid"].str.match(r"^(node|way|relation)/\d+$").all()
    pruebas.append(_prueba(
        "osm id con tipo (node/way/relation)", formato_ok,
        "si falla, A2 guarda solo el número y la unión con B4 no es segura"))

    pruebas.append(_prueba("ids únicos en fuentes",
                           osm["osm_uid"].is_unique and ocm["ocm_id"].is_unique,
                           f"OSM {len(osm)}  OCM {len(ocm)}"))
    _fallar_si_hay_errores(pruebas, "estaciones")

    # --- unión por identificador, nunca por posición de fila --------------
    df = inv.merge(osm[["osm_uid", "lat_osm", "lon_osm"]], on="osm_uid",
                   how="left", validate="many_to_one")
    df = df.merge(ocm[["ocm_id", "lat_ocm", "lon_ocm"]], on="ocm_id",
                  how="left", validate="many_to_one")

    pruebas.append(_prueba("la unión no cambió filas", len(df) == ESPERADO_FILAS_B4,
                           f"{len(df)} filas, esperadas {ESPERADO_FILAS_B4}"))

    # Cada id declarado en B4 debe encontrar su coordenada.
    sin_osm = df["osm_uid"].notna() & df["lat_osm"].isna()
    sin_ocm = df["ocm_id"].notna() & df["lat_ocm"].isna()
    pruebas.append(_prueba("todo osm_uid de B4 existe en A2", not sin_osm.any(),
                           f"sin coordenada: {df.loc[sin_osm, 'osm_uid'].tolist()}"))
    pruebas.append(_prueba("todo ocm_id de B4 existe en A3", not sin_ocm.any(),
                           f"sin coordenada: {df.loc[sin_ocm, 'ocm_id'].tolist()}"))

    df["fuente_posicion"] = np.where(df["lat_osm"].notna(), "OSM", "OCM")
    df["lat"] = df["lat_osm"].fillna(df["lat_ocm"])
    df["lon"] = df["lon_osm"].fillna(df["lon_ocm"])
    pruebas.append(_prueba("cada fila tiene exactamente una posición dibujada",
                           df["lat"].notna().all(),
                           f"sin posición: {int(df['lat'].isna().sum())}"))

    # --- verificación independiente: distancia recalculada ----------------
    ambos = df["lat_osm"].notna() & df["lat_ocm"].notna() & df["distancia_m"].notna()
    sub = df[ambos]
    geod = Geod(ellps="GRS80")
    _, _, d_geo = geod.inv(sub["lon_osm"].values, sub["lat_osm"].values,
                           sub["lon_ocm"].values, sub["lat_ocm"].values)
    t = Transformer.from_crs(CRS_GEOGRAFICO, CRS_METRICO, always_xy=True)
    x1, y1 = t.transform(sub["lon_osm"].values, sub["lat_osm"].values)
    x2, y2 = t.transform(sub["lon_ocm"].values, sub["lat_ocm"].values)
    d_proy = np.hypot(x2 - x1, y2 - y1)
    # Se acepta si coincide con cualquiera de los dos métodos (B1 usó 9377, B2 geodésica).
    dif = np.minimum(np.abs(d_geo - sub["distancia_m"].values),
                     np.abs(d_proy - sub["distancia_m"].values))
    peor = float(dif.max()) if len(dif) else 0.0
    pruebas.append(_prueba(
        "distancia_m de B4 = distancia recalculada entre coordenadas unidas",
        len(sub) > 0 and peor <= TOLERANCIA_DISTANCIA_M,
        f"{len(sub)} pares, peor diferencia {peor:.2f} m (tol {TOLERANCIA_DISTANCIA_M} m)"))

    # --- conteos del cierre -----------------------------------------------
    principales = df[~df["es_secundario"]]
    conteo = principales["ciudad"].value_counts().to_dict()
    pruebas.append(_prueba("conteos del cierre B4", conteo == ESPERADO_PRINCIPALES,
                           f"obtenido {conteo}, esperado {ESPERADO_PRINCIPALES}"))

    _fallar_si_hay_errores(pruebas, "estaciones")

    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]),
                           crs=CRS_GEOGRAFICO)
    # Releer la geometría contra lat/lon: atrapa un cruce de argumentos x/y.
    ok_xy = np.allclose(gdf.geometry.x, gdf["lon"]) and np.allclose(gdf.geometry.y, gdf["lat"])
    pruebas.append(_prueba("geometría coincide con lat/lon", ok_xy, "x=lon, y=lat"))
    _fallar_si_hay_errores(pruebas, "estaciones")
    return gdf, pruebas


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------

def cargar_grafo() -> tuple[gpd.GeoDataFrame, nx.MultiDiGraph, list[dict]]:
    """Segmentos de D1 y grafo dirigido reconstruido desde u, v."""
    pruebas = [verificar_huella(RUTAS["d1_grafo"], RUTAS["d1_huellas"])]
    _fallar_si_hay_errores(pruebas, "el grafo")

    seg = gpd.read_file(RUTAS["d1_grafo"], layer="segmentos")

    pruebas.append(_prueba("CRS del grafo es EPSG:9377",
                           seg.crs is not None and seg.crs.to_epsg() == 9377,
                           f"crs = {seg.crs}"))
    pruebas.append(_prueba("segmento_id único", seg["segmento_id"].is_unique,
                           f"{len(seg)} filas"))
    requeridas = {"segmento_id", "u", "v", "longitud_m", "pendiente_neta",
                  "pendiente_confiable", "en_sector"}
    faltan = requeridas - set(seg.columns)
    pruebas.append(_prueba("columnas del contrato D1", not faltan, f"faltan {sorted(faltan)}"))
    _fallar_si_hay_errores(pruebas, "el grafo")

    G = nx.MultiDiGraph()
    for f in seg[["segmento_id", "u", "v", "longitud_m", "pendiente_neta",
                  "pendiente_confiable"]].itertuples(index=False):
        G.add_edge(f.u, f.v, key=f.segmento_id, longitud_m=float(f.longitud_m),
                   pendiente=None if pd.isna(f.pendiente_neta) else float(f.pendiente_neta),
                   confiable=bool(f.pendiente_confiable))

    pruebas.append(_prueba("aristas del grafo = filas del gpkg",
                           G.number_of_edges() == len(seg),
                           f"{G.number_of_edges()} aristas, {len(seg)} filas"))

    # Independiente: longitud recalculada desde la geometría.
    dif = float((seg.geometry.length - seg["longitud_m"]).abs().max())
    pruebas.append(_prueba("longitud_m = longitud de la geometría", dif < 0.01,
                           f"peor diferencia {dif:.4f} m"))

    _fallar_si_hay_errores(pruebas, "el grafo")
    return seg, G, pruebas


if __name__ == "__main__":
    for nombre, fn in (("ESTACIONES", cargar_estaciones), ("GRAFO", cargar_grafo)):
        print("=" * 70, "\n", nombre)
        try:
            *_, pruebas = fn()
            print(pd.DataFrame(pruebas).to_string(index=False))
        except ErrorCarga as e:
            print(e)
