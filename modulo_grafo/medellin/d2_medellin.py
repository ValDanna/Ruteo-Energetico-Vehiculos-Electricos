"""
d2_medellin.py — Grafo vial dirigido de Medellín (Bloque D, D2 Medellín).

Fuente: capa «Sentido vial» de la Secretaría de Movilidad de Medellín,
servida por ArcGIS REST en EPSG:9377.

Reglas que sigue (mismas de D2 Bogotá):
  * Todo crudo se congela en disco con su sha256; el manifiesto se escribe
    solo DESPUÉS de una descarga completa y verificada.
  * Si el manifiesto existe, no se toca la red: se relee lo congelado y se
    re-verifican los hashes.
  * ArcGIS devuelve errores con HTTP 200: una respuesta con clave "error"
    se rechaza y NO se congela.
  * La geometría de cada arista corre de u a v (pendiente positiva = sube
    en el sentido de la fila).
"""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import LineString, MultiLineString

EPSG = 9377
TZ_BOGOTA = timezone(timedelta(hours=-5))

# Extensión que declara el propio servicio (capa 3), para la prueba T02.
EXTENSION_SERVICIO = {
    "xmin": 4682774.6309, "ymin": 2215662.6774000004,
    "xmax": 4770332.488, "ymax": 2283076.8926999997,
}

SENTIDOS_VALIDOS = {"FT", "TF", "DW", "N"}


# ----------------------------------------------------------------------
# Utilidades de hash y congelamiento
# ----------------------------------------------------------------------
def ahora_iso() -> str:
    return datetime.now(TZ_BOGOTA).isoformat(timespec="seconds")


def sha256_bytes(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def error_arcgis(contenido: bytes) -> str | None:
    """Devuelve el texto del error si la respuesta es un error de ArcGIS."""
    try:
        datos = json.loads(contenido)
    except Exception:
        return None
    if isinstance(datos, dict) and "error" in datos:
        return json.dumps(datos["error"], ensure_ascii=False)[:400]
    return None


def congelar_get(url: str, destino: Path, params: dict | None = None,
                 timeout: int = 120) -> dict:
    """GET que congela la respuesta. Si el archivo ya existe, no descarga."""
    destino = Path(destino)
    if destino.exists():
        return {"url": url, "archivo": destino.name,
                "sha256": sha256_archivo(destino),
                "bytes": destino.stat().st_size, "descargado_ahora": False}
    cabeceras = {"Accept": "application/xml"} if destino.suffix == ".xml" else None
    r = requests.get(url, params=params, timeout=timeout, headers=cabeceras)
    r.raise_for_status()
    if destino.suffix == ".xml" and not r.content.lstrip().startswith(b"<"):
        raise RuntimeError(f"{url} no devolvió XML: {r.headers.get('Content-Type')}")
    err = error_arcgis(r.content)
    if err:
        raise RuntimeError(f"ArcGIS devolvió error con HTTP 200 en {url}: {err}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(destino)
    return {"url": r.url, "archivo": destino.name,
            "sha256": sha256_bytes(r.content), "bytes": len(r.content),
            "fecha_descarga": ahora_iso(), "descargado_ahora": True}


def _post_json(url: str, datos: dict, intentos: int = 4,
               pausa_s: float = 2.0, timeout: int = 180) -> bytes:
    ultimo = None
    for k in range(intentos):
        try:
            r = requests.post(url, data=datos, timeout=timeout)
            r.raise_for_status()
            err = error_arcgis(r.content)
            if err:
                raise RuntimeError(f"Error ArcGIS (HTTP 200): {err}")
            return r.content
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(pausa_s * (k + 1))
    raise RuntimeError(f"Fallaron {intentos} intentos contra {url}: {ultimo}")


def hash_conjunto(paginas: list[dict]) -> str:
    """sha256 de la concatenación, en orden de página, de los sha256 de página."""
    return sha256_bytes("".join(p["sha256"] for p in paginas).encode("ascii"))


# ----------------------------------------------------------------------
# Descarga congelada de la capa Sentido vial
# ----------------------------------------------------------------------
def descargar_sentido_vial_congelado(url_capa: str, carpeta: Path,
                                     lote: int = 500,
                                     pausa_s: float = 0.5) -> dict:
    """
    Descarga TODA la capa por lotes de objectId (no por offset, que puede
    saltarse o repetir filas si el servidor reordena), congela cada página
    y escribe el manifiesto al final. Si el manifiesto existe, verifica.
    """
    carpeta = Path(carpeta)
    ruta_manifiesto = carpeta / "manifiesto_sentido_vial.json"
    if ruta_manifiesto.exists():
        return verificar_congelado(carpeta)

    carpeta.mkdir(parents=True, exist_ok=True)
    url_query = url_capa.rstrip("/") + "/query"
    fecha = ahora_iso()

    # 1) Lista completa de objectIds y conteo, por dos caminos distintos.
    c_ids = _post_json(url_query, {"where": "1=1", "returnIdsOnly": "true",
                                   "f": "json"})
    d_ids = json.loads(c_ids)
    campo_oid = d_ids["objectIdFieldName"]
    ids = sorted(int(i) for i in d_ids["objectIds"])
    c_n = _post_json(url_query, {"where": "1=1", "returnCountOnly": "true",
                                 "f": "json"})
    n_servidor = int(json.loads(c_n)["count"])
    if len(ids) != n_servidor or len(set(ids)) != len(ids):
        raise RuntimeError(f"IDs ({len(ids)}, únicos {len(set(ids))}) no "
                           f"cuadran con el conteo del servidor ({n_servidor}).")
    (carpeta / "ids_objetos.json").write_bytes(c_ids)

    # 2) Páginas por lotes de objectId.
    paginas = []
    for i, k in enumerate(range(0, len(ids), lote)):
        sub = ids[k:k + lote]
        contenido = _post_json(url_query, {
            "objectIds": ",".join(map(str, sub)), "outFields": "*",
            "outSR": EPSG, "returnGeometry": "true", "f": "json"})
        d = json.loads(contenido)
        if d.get("exceededTransferLimit"):
            raise RuntimeError(f"Página {i}: el servidor truncó la respuesta.")
        sr = d.get("spatialReference", {})
        wkid = sr.get("latestWkid", sr.get("wkid"))
        if wkid != EPSG:
            raise RuntimeError(f"Página {i}: CRS {wkid}, se pidió {EPSG}.")
        recibidos = {int(f["attributes"][campo_oid]) for f in d["features"]}
        if recibidos != set(sub):
            raise RuntimeError(f"Página {i}: faltan {len(set(sub) - recibidos)} "
                               f"y sobran {len(recibidos - set(sub))} objetos.")
        nombre = f"pagina_{i:04d}.json"
        (carpeta / nombre).write_bytes(contenido)
        paginas.append({"archivo": nombre, "sha256": sha256_bytes(contenido),
                        "bytes": len(contenido), "n_objetos": len(sub),
                        "oid_min": sub[0], "oid_max": sub[-1]})
        time.sleep(pausa_s)

    manifiesto = {
        "fuente": "Secretaría de Movilidad de Medellín — capa «Sentido vial»",
        "url_capa": url_capa,
        "fecha_descarga": fecha,
        "fecha_fin_descarga": ahora_iso(),
        "crs": f"EPSG:{EPSG}",
        "campo_oid": campo_oid,
        "n_objetos": len(ids),
        "n_objetos_servidor": n_servidor,
        "lote": lote,
        "ids_objetos": {"archivo": "ids_objetos.json",
                        "sha256": sha256_bytes(c_ids)},
        "paginas": paginas,
        "hash_conjunto": hash_conjunto(paginas),
        "definicion_hash_conjunto": ("sha256 de la concatenación, en orden de "
                                     "página, de los sha256 hex de cada página"),
    }
    # El manifiesto va de último: su existencia certifica descarga completa.
    ruta_manifiesto.write_text(json.dumps(manifiesto, ensure_ascii=False,
                                          indent=2), encoding="utf-8")
    manifiesto["recien_descargado"] = True
    return manifiesto


def verificar_congelado(carpeta: Path) -> dict:
    carpeta = Path(carpeta)
    m = json.loads((carpeta / "manifiesto_sentido_vial.json")
                   .read_text(encoding="utf-8"))
    for p in m["paginas"]:
        h = sha256_archivo(carpeta / p["archivo"])
        if h != p["sha256"]:
            raise RuntimeError(f"{p['archivo']} cambió: {h} ≠ {p['sha256']}")
    if sha256_archivo(carpeta / "ids_objetos.json") != m["ids_objetos"]["sha256"]:
        raise RuntimeError("ids_objetos.json cambió.")
    if hash_conjunto(m["paginas"]) != m["hash_conjunto"]:
        raise RuntimeError("El hash de conjunto no cuadra.")
    m["recien_descargado"] = False
    return m


# ----------------------------------------------------------------------
# Lectura de lo congelado
# ----------------------------------------------------------------------
def _geometria_esri(g: dict | None):
    paths = (g or {}).get("paths") or []
    partes = [LineString([c[:2] for c in p]) for p in paths if len(p) >= 2]
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else MultiLineString(partes)


def leer_ejes_congelados(carpeta: Path, manifiesto: dict) -> gpd.GeoDataFrame:
    filas, geoms = [], []
    for p in manifiesto["paginas"]:
        d = json.loads((Path(carpeta) / p["archivo"]).read_bytes())
        for f in d["features"]:
            filas.append(f["attributes"])
            geoms.append(_geometria_esri(f.get("geometry")))
    gdf = gpd.GeoDataFrame(pd.DataFrame(filas), geometry=geoms,
                           crs=f"EPSG:{EPSG}")
    gdf.columns = [c.lower() if c != "geometry" else c for c in gdf.columns]
    return gdf


def normalizar(texto) -> str:
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.upper().split())


def dominio(layer_json: dict, campo: str) -> dict:
    """Valores codificados de un campo, leídos del JSON congelado de la capa."""
    for f in layer_json.get("fields", []):
        if f["name"].lower() == campo.lower() and f.get("domain"):
            return {cv["code"]: cv["name"]
                    for cv in f["domain"].get("codedValues", [])}
    return {}


# ----------------------------------------------------------------------
# Construcción del grafo dirigido
# ----------------------------------------------------------------------
def _nivel(v) -> int:
    try:
        return 0 if v is None or pd.isna(v) else int(v)
    except (TypeError, ValueError):
        return 0


def construir_aristas(ejes: gpd.GeoDataFrame, col_id: str,
                      prefijo: str = "MED", decimales: int = 2):
    """
    Una arista por cada parte y cada sentido permitido.
      FT -> sentido de digitalización; TF -> geometría invertida;
      DW -> ambas; N -> ninguna (restringido vehicular);
      nulo -> ambas, marcado sentido_asumido=True.
    Nodo = (x, y) redondeados a `decimales` + nivel (f_elev/t_elev), para
    que un puente no se conecte con la calle que pasa debajo.
    Devuelve (aristas GeoDataFrame, nodos DataFrame, partes_multiples DataFrame).
    """
    desconocidos = set(ejes["oneway"].dropna().unique()) - SENTIDOS_VALIDOS
    if desconocidos:
        n = int(ejes["oneway"].isin(desconocidos).sum())
        frac = ejes.loc[ejes["oneway"].isin(desconocidos)].geometry.length.sum() \
               / ejes.geometry.length.sum()
        print(f"⚠ Valores de oneway no documentados {desconocidos}: {n} ejes, "
              f"{frac:.2%} de la red. Se tratan como sin dato (doble vía asumida).")
        if frac > 0.01:
            raise ValueError("Más del 1% de la red con sentido no documentado: "
                             "revisar antes de asumir doble vía.")

    registros, multipartes = [], []
    for fila in ejes.itertuples(index=False):
        g = fila.geometry
        if g is None or g.is_empty:
            continue
        partes = list(g.geoms) if isinstance(g, MultiLineString) else [g]
        fe, te = _nivel(fila.f_elev), _nivel(fila.t_elev)
        ow = fila.oneway if isinstance(fila.oneway, str) else None
        if ow not in ("FT", "TF", "DW", "N"):
            ow = None   # valor no documentado (p. ej. '0'): se trata como sin dato
        if ow == "N":
            continue
        sentidos = {"FT": ["FT"], "TF": ["TF"], "DW": ["FT", "TF"],
                    None: ["FT", "TF"]}[ow]
        n_p = len(partes)
        if n_p > 1:
            multipartes.append({"id_eje": getattr(fila, col_id), "n_partes": n_p,
                                "f_elev": fe, "t_elev": te})
        nivel_interior = fe if fe == te else 0
        for p_i, parte in enumerate(partes):
            coords = list(parte.coords)
            n_ini = fe if p_i == 0 else nivel_interior
            n_fin = te if p_i == n_p - 1 else nivel_interior
            for s in sentidos:
                if s == "FT":
                    cs, nu, nv = coords, n_ini, n_fin
                else:
                    cs, nu, nv = coords[::-1], n_fin, n_ini
                registros.append({
                    "segmento_id": f"{prefijo}_{getattr(fila, col_id)}_{p_i}_{s}",
                    "id_eje": getattr(fila, col_id),
                    "parte": p_i, "n_partes": n_p,
                    "sentido_arista": s,
                    "oneway_fuente": ow if ow else "NULO",
                    "sentido_asumido": ow is None,
                    "clave_u": (round(cs[0][0], decimales),
                                round(cs[0][1], decimales), nu),
                    "clave_v": (round(cs[-1][0], decimales),
                                round(cs[-1][1], decimales), nv),
                    "nivel_u": nu, "nivel_v": nv,
                    "jerarquia_op": getattr(fila, "jerarquia_op", None),
                    "nombre": getattr(fila, "nombre", None),
                    "nro_carriles": getattr(fila, "nro_carriles", None),
                    "paso_nivel": getattr(fila, "paso_nivel", None),
                    "fecha_act": getattr(fila, "fecha_act", None),
                    "geometry": LineString(cs),
                })

    aristas = gpd.GeoDataFrame(registros, geometry="geometry",
                               crs=f"EPSG:{EPSG}")
    claves = sorted(set(aristas["clave_u"]) | set(aristas["clave_v"]))
    id_de = {c: f"{prefijo}_N{i:06d}" for i, c in enumerate(claves)}
    aristas["u"] = aristas["clave_u"].map(id_de)
    aristas["v"] = aristas["clave_v"].map(id_de)
    aristas["longitud_m"] = aristas.geometry.length
    aristas["es_elevado"] = ((aristas["nivel_u"] != 0) | (aristas["nivel_v"] != 0)
                             | (pd.to_numeric(aristas["paso_nivel"],
                                              errors="coerce").fillna(0) == 1))
    nodos = pd.DataFrame([{"node_id": id_de[c], "x": c[0], "y": c[1],
                           "nivel": c[2]} for c in claves])
    nodos = nodos.merge(aristas.groupby("u").size().rename("grado_salida"),
                        left_on="node_id", right_index=True, how="left")
    nodos = nodos.merge(aristas.groupby("v").size().rename("grado_entrada"),
                        left_on="node_id", right_index=True, how="left")
    nodos[["grado_salida", "grado_entrada"]] = (
        nodos[["grado_salida", "grado_entrada"]].fillna(0).astype(int))
    aristas = aristas.drop(columns=["clave_u", "clave_v"])
    aristas = aristas.sort_values("segmento_id").reset_index(drop=True)
    return aristas, nodos, pd.DataFrame(multipartes)


def huella_segmentos(gdf: gpd.GeoDataFrame, col_id: str = "segmento_id") -> str:
    """sha256 sobre (id + WKB) ordenado por id. No depende de la fecha de
    escritura del GeoPackage, a diferencia del sha256 del archivo."""
    h = hashlib.sha256()
    for sid, geom in sorted(zip(gdf[col_id], gdf.geometry), key=lambda t: t[0]):
        h.update(str(sid).encode("utf-8") + b"\x00" + geom.wkb + b"\x01")
    return h.hexdigest()

def fusionar_nodos_cercanos(aristas: gpd.GeoDataFrame, nodos: pd.DataFrame,
                            tolerancia_m: float, prefijo: str = "MED"):
    """
    Une nodos separados por menos de `tolerancia_m` dentro del mismo nivel.
    Nunca une los dos extremos de una misma arista: eso convertiría un tramo
    real en un bucle. La geometría NO se mueve; solo cambia a qué nodo apunta
    cada extremo, y la coordenada del nodo pasa a ser el promedio del grupo.
    Devuelve (aristas, nodos, informe).
    """
    from scipy.spatial import cKDTree

    padre = {n: n for n in nodos["node_id"]}

    def raiz(a):
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    # aristas incidentes a cada nodo, para vetar fusiones que crean bucles
    incidentes = {}
    for u, v in zip(aristas["u"], aristas["v"]):
        incidentes.setdefault(u, set()).add(v)
        incidentes.setdefault(v, set()).add(u)
    grupo = {n: {n} for n in padre}

    pares = []
    for nivel, g in nodos.groupby("nivel"):
        xy = g[["x", "y"]].to_numpy()
        ids = g["node_id"].to_numpy()
        for i, j in cKDTree(xy).query_pairs(tolerancia_m):
            pares.append((ids[i], ids[j], float(np.hypot(*(xy[i] - xy[j])))))
    pares.sort(key=lambda t: t[2])

    unidos, vetados = [], []
    for a, b, d in pares:
        ra, rb = raiz(a), raiz(b)
        if ra == rb:
            continue
        ga, gb = grupo[ra], grupo[rb]
        chico, grande = (ga, gb) if len(ga) <= len(gb) else (gb, ga)
        if any(vecino in grande for n in chico for vecino in incidentes.get(n, ())):
            vetados.append((a, b, d, "crearía un bucle"))
            continue
        padre[rb] = ra
        grupo[ra] = ga | gb
        grupo.pop(rb, None)
        unidos.append((a, b, d))

    nodos = nodos.copy()
    nodos["raiz"] = [raiz(n) for n in nodos["node_id"]]
    agrupado = (nodos.groupby("raiz")
                     .agg(x=("x", "mean"), y=("y", "mean"), nivel=("nivel", "first"),
                          n_fusionados=("node_id", "size"))
                     .reset_index())
    agrupado = agrupado.sort_values(["x", "y", "nivel"]).reset_index(drop=True)
    agrupado["node_id"] = [f"{prefijo}_N{i:06d}" for i in range(len(agrupado))]
    nuevo_de = dict(zip(agrupado["raiz"], agrupado["node_id"]))
    mapa = {n: nuevo_de[r] for n, r in zip(nodos["node_id"], nodos["raiz"])}

    aristas = aristas.copy()
    aristas["u"] = aristas["u"].map(mapa)
    aristas["v"] = aristas["v"].map(mapa)

    nodos = agrupado.drop(columns="raiz")[["node_id", "x", "y", "nivel", "n_fusionados"]]
    nodos = nodos.merge(aristas.groupby("u").size().rename("grado_salida"),
                        left_on="node_id", right_index=True, how="left")
    nodos = nodos.merge(aristas.groupby("v").size().rename("grado_entrada"),
                        left_on="node_id", right_index=True, how="left")
    nodos[["grado_salida", "grado_entrada"]] = (
        nodos[["grado_salida", "grado_entrada"]].fillna(0).astype(int))

    informe = {"tolerancia_m": tolerancia_m, "pares_evaluados": len(pares),
               "fusiones": len(unidos), "vetadas_por_bucle": len(vetados),
               "nodos_antes": len(mapa), "nodos_despues": len(nodos),
               "desplazamiento_max_m": float(max([d for _, _, d in unidos], default=0.0)),
               "detalle_vetadas": vetados}
    return aristas, nodos, informe

# ----------------------------------------------------------------------
# Pruebas de exportación (todas pueden fallar)
# ----------------------------------------------------------------------
def pruebas_exportacion(*, ids_congelados, ejes_todos, ejes_med, aristas,
                        nodos, limite, col_oid, ruta_gpkg=None,
                        capa_gpkg="segmentos", tol_nodo=0.01,
                        oids_excluidos=frozenset(), ids_excluidos=frozenset()) -> pd.DataFrame:
    r = []

    def reg(cod, nombre, ok, detalle):
        r.append({"prueba": cod, "nombre": nombre,
                  "resultado": "PASA" if ok else "FALLA", "detalle": detalle})

    # T01 completitud frente a la lista de IDs del servidor
    oids = set(ejes_todos[col_oid].astype(int))
    reg("T01", "Completitud de la descarga",
        oids == set(ids_congelados) and len(ejes_todos) == len(ids_congelados),
        f"{len(ejes_todos)} filas, {len(oids)} oid únicos, "
        f"{len(ids_congelados)} IDs congelados")

    # T02 CRS y extensión dentro de la que declara el servicio
    xmin, ymin, xmax, ymax = ejes_todos.total_bounds
    e = EXTENSION_SERVICIO
    dentro = (xmin >= e["xmin"] - 1 and ymin >= e["ymin"] - 1
              and xmax <= e["xmax"] + 1 and ymax <= e["ymax"] + 1)
    reg("T02", "CRS 9377 y extensión del servicio",
        ejes_todos.crs.to_epsg() == EPSG and dentro,
        f"EPSG {ejes_todos.crs.to_epsg()}, bbox "
        f"({xmin:.0f}, {ymin:.0f}, {xmax:.0f}, {ymax:.0f})")

    # T03 longitud geométrica vs longitud que calcula la base del servidor
    col_len = next((c for c in ejes_med.columns
                    if "length" in c.lower() and c != "geometry"), None)
    if col_len is None:
        reg("T03", "Longitud vs campo del servidor", False,
            "El servidor no devolvió campo de longitud: revisar manualmente")
    else:
        ref = pd.to_numeric(ejes_med[col_len], errors="coerce")
        dif = (ejes_med.geometry.length - ref).abs() / ref.clip(lower=1e-9)
        reg("T03", "Longitud vs campo del servidor", bool(dif.max() < 1e-4),
            f"campo {col_len}; dif. relativa máx {dif.max():.2e}")

    # T04 el recorte es el límite IGAC: nada entra por fuera de la regla
    lim = limite.geometry.union_all() if hasattr(limite.geometry, "union_all") \
        else limite.geometry.unary_union
    frac = ejes_med.geometry.intersection(lim).length / ejes_med.geometry.length
    # los tramos excluidos a propósito (no aptos para carros según OSM) no cuentan como omitidos
    fuera_total = ejes_todos[~ejes_todos[col_oid].isin(ejes_med[col_oid])
                             & ~ejes_todos[col_oid].isin(oids_excluidos)]
    f_omitida = (fuera_total.geometry.intersection(lim).length
                 / fuera_total.geometry.length).fillna(0)
    reg("T04", "Recorte por límite IGAC 05001",
        bool(frac.min() > 0.5) and bool((f_omitida > 0.5).sum() == 0),
        f"mínimo {frac.min():.1%} adentro entre los aceptados; "
        f"{int((f_omitida > 0.5).sum())} ejes omitidos con más de la mitad adentro")

    # T05 balance de sentidos
    partes = ejes_med.geometry.apply(
        lambda g: 0 if g is None or g.is_empty else
        (len(g.geoms) if isinstance(g, MultiLineString) else 1))
    ow = ejes_med["oneway"].where(ejes_med["oneway"].isin(SENTIDOS_VALIDOS),
                                  "NULO")
    mult = ow.map({"FT": 1, "TF": 1, "DW": 2, "N": 0, "NULO": 2})
    esperado = int((partes * mult).sum())
    reg("T05", "Balance de sentidos (2·DW + FT + TF)",
        esperado == len(aristas),
        f"esperadas {esperado}, construidas {len(aristas)}")

    # T06 orientación u→v: extremos de la geometría = coordenadas del nodo
    xy = nodos.set_index("node_id")[["x", "y"]]
    ini = np.array([g.coords[0] for g in aristas.geometry])
    fin = np.array([g.coords[-1] for g in aristas.geometry])
    du = np.hypot(*(ini - xy.loc[aristas["u"]].to_numpy()).T)
    dv = np.hypot(*(fin - xy.loc[aristas["v"]].to_numpy()).T)
    # Además: el inicio de la geometría debe estar más cerca de u que de v.
    # Con tolerancias grandes, esto es lo que detecta una arista corta invertida.
    ini_a_v = np.hypot(*(ini - xy.loc[aristas["v"]].to_numpy()).T)
    no_bucle = (aristas["u"] != aristas["v"]).to_numpy()
    invertidas = int(((ini_a_v < du) & no_bucle).sum())
    reg("T06", "Geometría corre de u a v",
        bool(max(du.max(), dv.max()) <= tol_nodo + 1e-6) and invertidas == 0,
        f"desfase máx {max(du.max(), dv.max()):.4f} m (tolerancia {tol_nodo} m); "
        f"{invertidas} geometrías más cerca de v que de u")

    # T07 unicidad del ID
    reg("T07", "segmento_id único", aristas["segmento_id"].is_unique,
        f"{aristas['segmento_id'].duplicated().sum()} duplicados")

    # T08 simetría de doble vía
    dw = aristas[aristas["oneway_fuente"].isin(["DW", "NULO"])]
    ft = dw[dw.sentido_arista == "FT"].set_index(["id_eje", "parte"])
    tf = dw[dw.sentido_arista == "TF"].set_index(["id_eje", "parte"])
    comunes = ft.index.intersection(tf.index)
    ok8 = len(comunes) == len(ft) == len(tf)
    if ok8 and len(comunes):
        ok8 = bool(np.allclose(ft.loc[comunes, "longitud_m"],
                               tf.loc[comunes, "longitud_m"], atol=1e-6)
                   and (ft.loc[comunes, "u"] == tf.loc[comunes, "v"]).all()
                   and (ft.loc[comunes, "v"] == tf.loc[comunes, "u"]).all())
    reg("T08", "Simetría FT/TF en doble vía", ok8,
        f"{len(ft)} FT, {len(tf)} TF, {len(comunes)} emparejadas")

    # T09 conservación de longitud
    long_fisica = ejes_med.geometry.length
    esperada = float((long_fisica * mult).sum())
    reg("T09", "Conservación de longitud dirigida",
        abs(esperada - aristas["longitud_m"].sum()) < 0.01,
        f"{esperada/1000:,.3f} km esperados vs "
        f"{aristas['longitud_m'].sum()/1000:,.3f} km construidos")

    # T10 nodos sin huérfanos y todo u,v existe
    usados = set(aristas["u"]) | set(aristas["v"])
    reg("T10", "Nodos consistentes",
        usados == set(nodos["node_id"]) and nodos["node_id"].is_unique,
        f"{len(nodos)} nodos, {len(usados)} referenciados")

    # T11 ida y vuelta del GeoPackage
    if ruta_gpkg is not None:
        leido = gpd.read_file(ruta_gpkg, layer=capa_gpkg)
        h1, h2 = huella_segmentos(aristas), huella_segmentos(leido)
        reg("T11", "Relectura del GeoPackage (huella)",
            h1 == h2 and len(leido) == len(aristas),
            f"huella memoria {h1[:12]}…, releída {h2[:12]}…")

        # T12 sin aristas degeneradas
    cortas = aristas[aristas["longitud_m"] < 0.1]
    reg("T12", "Sin aristas de longitud despreciable", len(cortas) == 0,
        f"{len(cortas)} aristas < 0,1 m; mínima {aristas['longitud_m'].min():.3f} m")

    # T13 los bucles (u == v) son lazos cerrados válidos: se cuentan, no se prohíben
    bucles = aristas[aristas["u"] == aristas["v"]]
    reg("T13", "Bucles identificados y acotados", len(bucles) < 0.001 * len(aristas),
        f"{len(bucles)} aristas cerradas sobre sí mismas "
        f"({len(bucles)/len(aristas):.3%}); máx {bucles['longitud_m'].max() if len(bucles) else 0:.0f} m")

    # T14 tramos repetidos en la fuente: se cuentan, no se corrigen
    claves = pd.Series([g.wkb for g in aristas.geometry], index=aristas.index)
    tabla = pd.DataFrame({"clave": claves, "id_eje": aristas["id_eje"].values})
    repetidos = tabla.groupby("clave")["id_eje"].nunique()
    n_rep = int((repetidos > 1).sum())
    reg("T14", "Tramos repetidos en la fuente, acotados", n_rep <= 1,
        f"{n_rep} geometría(s) bajo más de un id_eje; se conservan y se reportan")

    # T15 la exclusión de tramos no vehiculares se aplicó completa y sin efectos laterales
    oids_fuente = set(ejes_todos[col_oid].astype(int))
    quedaron = int(aristas["id_eje"].isin(ids_excluidos).sum())
    reg("T15", "Exclusión no vehicular (OSM) aplicada",
        len(oids_excluidos) == len(ids_excluidos) and set(oids_excluidos) <= oids_fuente
        and not ejes_med[col_oid].isin(oids_excluidos).any() and quedaron == 0,
        f"{len(ids_excluidos)} tramos excluidos; {quedaron} aristas de tramos excluidos en el grafo")
    return pd.DataFrame(r)
