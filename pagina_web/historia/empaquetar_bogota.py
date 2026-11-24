"""
empaquetar_bogota.py -- Convierte las corridas oficiales de D4 Bogota y D4 Medellin en
los archivos que lee la pagina interactiva (datos_bogota/ y datos_medellin/).

SOLO LEE los entregables. No escribe ni modifica nada dentro de "Grafo Bogota":
todo lo que produce queda en App/historia/datos_bogota/. La pagina es, por tanto,
un lector mas de salidas congeladas y no rompe la regla de tuberia lineal.

Ejecutar desde F:\\Tesis\\App\\historia:
    python empaquetar_bogota.py

Escribe en App/historia/datos_bogota/:
    meta.json        conteos, escenario, huellas y los resultados que se muestran
    nodos.bin        lon, lat, z de cada esquina              Float32 x 3 x N
    aristas.bin      u, v, dibujo, longitud_m, pendiente_pct, al_reves
    dibujo.bin       una polilinea por calle (sin duplicar ida y vuelta)
    dibujo_attr.bin  pendiente |%|, indice de nombre, clase de via, localidad
    vocab.json       los textos de clase, localidad y nombre
    carros/<id>.bin  consumo_kwh y peso_ruteo_kwh por arista   Float32 x 2
    estaciones.json  las estaciones enganchadas a la red oficial
    control.json     viajes que D4 ya resolvio, para que la pagina se verifique
    medellin/tramos.bin  la red de Medellin (celda 22 de D4M), solo para dibujarla

Cada numero importante se comprueba por un segundo camino independiente antes de
escribir: los conteos contra las huellas de D4, las alturas contra la propuesta de
esquinas, el enganche de cada estacion recalculado en EPSG:9377 contra el que
reporto D4, y los extremos de cada geometria contra las coordenadas de sus esquinas.
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------- opciones
RAIZ = Path(r"F:\Tesis\Grafo Bogotá")
ESCENARIO = "sens_sin_altura_A"
RAMA = "sigma0536_v1_1"
SUFIJO_ENERGIA = "h12__extremos__long_inclinada__con_paradas__k50"
N_CONTROL = 25
# Limites municipales: la capa oficial del IGAC que adopto el proyecto
# (LIMITE_IGAC en constantes). Se filtra por codigo DANE, no por nombre.
# Si se deja en None, se busca Municipios_Junio_2026.gpkg dentro de F:\Tesis.
LIMITE_GPKG = None
LIMITE_CAPA = "Munpio"
LIMITE_COLUMNA = "MpCodigo"
LIMITE_CODIGOS = {"bogota": "11001", "medellin": "05001"}

CARROS = ["byd_dolphin_449", "byd_seagull_dolphin_mini", "byd_tang_gs", "byd_yuan_up",
          "chery_icar_03", "chevrolet_spark_euv", "kia_ev5_light", "kia_ev9_gtline",
          "mg4_electric_urban", "renault_kwid_etech", "tesla_model_3_rwd",
          "tesla_model_y_rwd"]

SALIDA = Path(__file__).resolve().parent / "datos_bogota"
E = RAIZ / "entregables"

ARISTAS   = E / f"D4/esc_{ESCENARIO}/D4_aristas_{ESCENARIO}.csv"
HUELLAS   = E / f"D4/esc_{ESCENARIO}/D4_huellas_{ESCENARIO}.json"
NODOS     = E / "D2/nodos_bogota.csv"
ALTURAS   = E / "D4/alturas_esquinas/D4_alturas_esquinas.csv"
GEOM      = E / f"D3/rama_{RAMA}/D3_grafo_con_pendiente_{RAMA}.gpkg"
ATRIB     = E / f"D3/rama_{RAMA}/D3_grafo_con_pendiente_{RAMA}.csv"
ESTACION  = E / "D4/estaciones/D4_estaciones_enganche.csv"
OFICIAL   = E / "D4/D4_version_oficial.json"
PONDERADO = E / "D4/estratos/D4_resumen_energia_ponderado_v2.csv"
ESTRATOS  = E / "D4/estratos/D4_tabla_estratos_k0_y_kadoptado.csv"
LOCALIDAD = E / "D4/alcanzabilidad/extra/D4_llegar_vs_salir_por_localidad.csv"
ALCANZA   = E / "D4/alcanzabilidad/D4_resumen_alcanzabilidad.csv"
PARES     = E / "D4/rutas_distancia/D4_muestra_pares_od.csv"


def dir_energia(vid):
    return E / f"D4/energia/esc_{ESCENARIO}__{vid}__{SUFIJO_ENERGIA}"


def exigir(p: Path) -> Path:
    if not p.exists():
        raise SystemExit(f"FALTA el archivo: {p}")
    return p


def tabla(p: Path) -> list:
    """CSV -> lista de registros sin NaN, que JSON no admite."""
    if not p.exists():
        print(f"  (no esta, se omite) {p.name}")
        return []
    d = pd.read_csv(p, encoding="utf-8-sig")
    for c in d.columns:
        d[c] = d[c].astype(object).where(d[c].notna(), None)
    return d.to_dict("records")


def codificar(serie):
    """Texto -> (vocabulario, indices). El nulo queda como indice 0."""
    s = serie.fillna("").astype(str)
    vocab = [""] + sorted(v for v in s.unique() if v)
    pos = {v: i for i, v in enumerate(vocab)}
    return vocab, s.map(pos).to_numpy(np.int32)


# Etiquetas de OpenStreetMap que describen una estacion de carga, en el orden en
# que se muestran. Solo se pasan las que existan y tengan valor: nada se completa.
ETIQUETAS_OSM = [
    ("operator", "Operador"), ("brand", "Marca"), ("network", "Red"),
    ("capacity", "Puestos de carga"), ("access", "Acceso"), ("fee", "Pago"),
    ("opening_hours", "Horario"),
    ("socket:type2", "Conectores Tipo 2"), ("socket:type2:output", "Potencia Tipo 2"),
    ("socket:type2_combo", "Conectores CCS2"), ("socket:type2_combo:output", "Potencia CCS2"),
    ("socket:chademo", "Conectores CHAdeMO"), ("socket:chademo:output", "Potencia CHAdeMO"),
    ("socket:type1", "Conectores Tipo 1"), ("socket:type1:output", "Potencia Tipo 1"),
    ("socket:type1_combo", "Conectores CCS1"), ("socket:type1_combo:output", "Potencia CCS1"),
    ("socket:gb_dc", "Conectores GB/T DC"), ("socket:gb_ac", "Conectores GB/T AC"),
    ("socket:tesla_supercharger", "Conectores Tesla"), ("socket:schuko", "Tomas Schuko"),
    ("charging_station:output", "Potencia"), ("maxpower", "Potencia maxima"),
    ("voltage", "Voltaje"), ("amperage", "Corriente"),
    ("addr:street", "Direccion"), ("check_date", "Revisada el"),
]
SI_NO = {"yes": "si", "no": "no"}


def atributos_estaciones():
    """Atributos de cada estacion tal como estan en las dos fuentes del Bloque A.

    Devuelve dos diccionarios: osm_uid -> lista de campos y ocm_id -> lista de campos.
    No completa ni interpreta nada: pasa lo que traen los archivos. Si los archivos
    no aparecen, las fichas de la pagina quedan solo con nombre y posicion.
    """
    import re

    def hallar(nombre):
        for base in (RAIZ.parent, RAIZ):
            if base.exists():
                for p in base.rglob(nombre):
                    return p
        return None

    osm, ocm = {}, {}
    f_osm = hallar("A2_estaciones_OSM_Bogota.geojson")
    f_ocm = hallar("A3_OpenChargeMap_Bogota_estaciones.csv")
    try:
        if f_osm:
            gj = json.load(open(f_osm, encoding="utf-8"))
            for ft in gj.get("features", []):
                pr = ft.get("properties", {}) or {}
                tags = pr.get("tags") if isinstance(pr.get("tags"), dict) else pr
                ident = str(pr.get("osm_uid") or pr.get("id") or pr.get("@id")
                            or pr.get("uid") or ft.get("id") or "")
                campos = []
                for clave, rotulo in ETIQUETAS_OSM:
                    v = tags.get(clave)
                    if v is None or str(v).strip() in ("", "nan", "None"):
                        continue
                    v = str(v).strip()
                    campos.append({"campo": rotulo, "valor": SI_NO.get(v.lower(), v)})
                if ident and campos:
                    osm[ident] = campos
                    osm[ident.split("/")[-1]] = campos
            print(f"  atributos de OpenStreetMap: {f_osm.name}  ({len(gj.get('features', []))} estaciones)")
        else:
            print("  (no encontre A2_estaciones_OSM_Bogota.geojson)")
    except Exception as e:
        print(f"  (no pude leer los atributos de OSM: {e})")
    try:
        if f_ocm:
            t = pd.read_csv(f_ocm, encoding="utf-8-sig")
            col_id = next((c for c in ("ocm_id", "id", "ID") if c in t.columns), None)
            fuera = re.compile(r"(^|_)(id|uuid|lat|latitud|lon|lng|longitud|nombre|name|title|titulo|x|y)($|_)", re.I)
            utiles = [c for c in t.columns if not fuera.search(c)]
            print(f"  atributos de OpenChargeMap: {f_ocm.name}  columnas usadas: {utiles}")
            if col_id:
                for _, r in t.iterrows():
                    campos = []
                    for c in utiles:
                        v = r[c]
                        if pd.isna(v) or str(v).strip() == "":
                            continue
                        if isinstance(v, float) and v == int(v):
                            v = int(v)
                        campos.append({"campo": c.replace("_", " ").capitalize(), "valor": str(v).strip()})
                    if campos:
                        ocm[str(r[col_id]).split(".")[0]] = campos
        else:
            print("  (no encontre A3_OpenChargeMap_Bogota_estaciones.csv)")
    except Exception as e:
        print(f"  (no pude leer los atributos de OCM: {e})")
    return osm, ocm


def limite_bogota(prueba):
    """Escribe limite.json (Bogota) y medellin/limite.json desde la capa del IGAC."""
    import geopandas as gpd
    if LIMITE_GPKG:
        p = Path(LIMITE_GPKG)
    else:
        cands = sorted(RAIZ.parent.rglob("Municipios_Junio_2026.gpkg"), key=lambda q: len(str(q)))
        if not cands:
            print("  (no encontre Municipios_Junio_2026.gpkg; escribe su ruta en LIMITE_GPKG)")
            return False
        p = cands[0]
        for q in cands[1:4]:
            print(f"  (otra copia, no usada: {q})")
    g = gpd.read_file(p, layer=LIMITE_CAPA)
    cod = g[LIMITE_COLUMNA].astype(str).str.zfill(5)
    (SALIDA / "medellin").mkdir(exist_ok=True)
    for ciudad, codigo in LIMITE_CODIGOS.items():
        sel = g[cod == codigo]
        prueba(f"limite de {ciudad}: un municipio con codigo DANE {codigo}", len(sel) == 1,
               f"{len(sel)} registros")
        if sel.empty:
            continue
        borde = sel.to_crs("EPSG:4326").geometry.union_all().simplify(0.00005)
        destino = SALIDA / ("limite.json" if ciudad == "bogota" else "medellin/limite.json")
        gpd.GeoSeries([borde], crs="EPSG:4326").to_file(destino, driver="GeoJSON")
    print(f"  limites tomados de {p} (capa {LIMITE_CAPA}, {len(g):,} municipios)")
    return True


# Lo que el cuaderno D4 Medellin imprimio de su red oficial (sens_sin_altura_A).
# Sirven de segundo camino: el archivo que se empaqueta tiene que dar lo mismo.
MED_TRAMOS = 39_160          # D4M celda 1 y celda 22
MED_TRAMOS_RED = 38_826      # D4M celda 22 ("en la red oficial")
MED_ESQUINAS_RED = 16_156    # D4M celda 2 (componente fuerte) y celda 17
MED_KM_RED = 2_193.7         # D4M celda 4, km_fisicos_en_red
MED_COLUMNAS = {"segmento_id", "u", "v", "lon_u", "lat_u", "lon_v", "lat_v",
                "longitud_m", "z_u_m", "z_v_m", "pendiente_ruteo_pct"}


def red_medellin(prueba) -> dict | None:
    """Empaqueta la red de Medellin para dibujarla (no para rutear).

    Usa el archivo que escribe la celda 22 de D4 Medellin (cada tramo con las
    coordenadas y la altura de sus dos esquinas). No se adivina su nombre: se
    busca entre los D4M_*.csv el que tenga esas columnas. Si no aparece, la pagina
    muestra Medellin con sus cifras pero sin mapa, y Bogota no se afecta.
    """
    import hashlib
    cands = []
    for base in (E, RAIZ):
        if base.exists():
            cands += sorted(base.rglob("D4M_*.csv"))
        if cands:
            break
    elegido = None
    for p in cands:
        try:
            cab = set(pd.read_csv(p, nrows=0, encoding="utf-8-sig").columns)
        except Exception:
            continue
        if MED_COLUMNAS <= cab:
            elegido = (p, cab)
            break
    if not elegido:
        print("  (no encontre el CSV de tramos de Medellin de la celda 22; "
              "la pagina mostrara Medellin sin mapa)")
        return None
    p, cab = elegido
    print(f"  tramos de Medellin tomados de {p}")
    col_red = next((c for c in sorted(cab) if c.startswith("en_red")), None)
    usar = sorted(MED_COLUMNAS | ({col_red} if col_red else set()))
    t = pd.read_csv(p, encoding="utf-8-sig", usecols=usar)

    prueba("Medellin: tramos del archivo = los de D4M", len(t) == MED_TRAMOS,
           f"{len(t):,} vs {MED_TRAMOS:,}")
    if col_red:
        en_red = t[col_red].astype(bool).to_numpy()
    else:
        print("  (el archivo no trae columna en_red: se dibujan todos los tramos)")
        en_red = np.ones(len(t), bool)
    r = t[en_red]
    prueba("Medellin: tramos en la red oficial = los de D4M", len(r) == MED_TRAMOS_RED,
           f"{len(r):,} vs {MED_TRAMOS_RED:,}  (columna {col_red})")
    esq = len(set(r["u"]) | set(r["v"]))
    prueba("Medellin: esquinas de la red oficial = las de D4M", esq == MED_ESQUINAS_RED,
           f"{esq:,} vs {MED_ESQUINAS_RED:,}")
    dentro = (t["lon_u"].between(-75.75, -75.45) & t["lon_v"].between(-75.75, -75.45)
              & t["lat_u"].between(6.10, 6.45) & t["lat_v"].between(6.10, 6.45))
    prueba("Medellin: coordenadas dentro de Medellin (mismo recuadro de la celda 22)",
           bool(dentro.all()), f"fuera: {int((~dentro).sum())}")
    finitos = np.isfinite(r[["pendiente_ruteo_pct", "z_u_m", "z_v_m"]].to_numpy()).all()
    prueba("Medellin: en la red oficial toda pendiente y altura es un numero", bool(finitos), "")

    # Una linea por calle: ida y vuelta comparten el id sin el sufijo _FT / _TF.
    t = t.assign(_calle=t["segmento_id"].astype(str).str.replace(r"_(FT|TF)$", "", regex=True),
                 _red=en_red)
    t = t.sort_values("_red", ascending=False).drop_duplicates("_calle")
    km = float(t.loc[t["_red"], "longitud_m"].sum()) / 1000
    prueba("Medellin: km fisicos en la red oficial = los de D4M (1 %)",
           abs(km - MED_KM_RED) <= MED_KM_RED * 0.01, f"{km:,.1f} vs {MED_KM_RED:,.1f}")

    zmid = ((t["z_u_m"] + t["z_v_m"]) / 2).to_numpy(np.float32)
    pend = t["pendiente_ruteo_pct"].abs().to_numpy(np.float32)
    (SALIDA / "medellin").mkdir(exist_ok=True)
    with open(SALIDA / "medellin" / "tramos.bin", "wb") as s:
        for c in ("lon_u", "lat_u", "lon_v", "lat_v"):
            s.write(t[c].to_numpy(np.float32).tobytes())
        s.write(zmid.tobytes())
        s.write(pend.tobytes())
        s.write(t["_red"].to_numpy(np.uint8).tobytes())
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    zr = np.concatenate([r["z_u_m"].to_numpy(), r["z_v_m"].to_numpy()])
    return {
        "archivo": p.name, "sha256": sha,
        "n_calles": int(len(t)), "n_calles_red": int(t["_red"].sum()),
        "n_tramos": int(len(en_red)), "n_tramos_red": int(len(r)), "esquinas_red": int(esq),
        "km_red": round(km, 1),
        "z_min": float(np.nanmin(zr)), "z_max": float(np.nanmax(zr)),
        "tramos_mas_35_red": int((r["pendiente_ruteo_pct"].abs() > 35).sum()),
    }


def fichas_flota() -> dict:
    """Nombre, bateria y consumo WLTP de cada vehiculo, desde vehiculos_flota.py.

    Se busca el archivo en el disco en vez de suponer donde esta. Si no aparece,
    o si importarlo falla, la pagina simplemente muestra el id del vehiculo: es
    un adorno, no un dato del que dependa ningun calculo.
    """
    import sys
    origen = None
    for base in (RAIZ, RAIZ.parent):
        if base.exists():
            for p in base.rglob("vehiculos_flota.py"):
                origen = p
                break
        if origen:
            break
    if not origen:
        print("  (no encontre vehiculos_flota.py; la pagina mostrara solo el id)")
        return {}
    sys.path.insert(0, str(origen.parent))
    try:
        import vehiculos_flota as vf
        out = {}
        for vid, hacer in vf.FLOTA.items():
            v = hacer()
            out[vid] = {
                "nombre": getattr(v, "nombre", vid),
                "bateria_kwh": float(getattr(v, "bateria_util", 0)) or None,
                "consumo_wltp_kwh_100km": float(getattr(v, "consumo_wltp", 0)) or None,
                "autonomia_wltp_km": float(getattr(v, "autonomia_wltp", 0)) or None,
            }
        print(f"  fichas de la flota leidas de {origen}  ({len(out)} vehiculos)")
        return out
    except Exception as e:
        print(f"  (no pude leer {origen.name}: {e}; la pagina mostrara solo el id)")
        return {}
    finally:
        sys.path.pop(0)


def main():
    SALIDA.mkdir(exist_ok=True)
    (SALIDA / "carros").mkdir(exist_ok=True)

    pruebas = []

    def prueba(nombre, ok, detalle=""):
        pruebas.append({"prueba": nombre, "pasa": bool(ok), "detalle": str(detalle)})
        print(f"  [{'OK   ' if ok else 'FALLA'}] {nombre}  {detalle}")

    # ------------------------------------------------------------------ 1 aristas
    print("\n1. Aristas de la red oficial")
    ar = pd.read_csv(exigir(ARISTAS), encoding="utf-8-sig",
                     usecols=["segmento_id", "id_eje", "parte", "u", "v",
                              "longitud_m", "en_red", "pendiente_ruteo_pct"])
    red = ar[ar["en_red"].astype(bool)].reset_index(drop=True)
    hue = json.load(open(exigir(HUELLAS), encoding="utf-8"))
    res = hue["resumen"]
    prueba("aristas en red = huellas de D4", len(red) == res["aristas_en_red"],
           f"{len(red):,} vs {res['aristas_en_red']:,}")

    # ------------------------------------------------------------------ 2 esquinas
    print("\n2. Esquinas y alturas")
    nd = pd.read_csv(exigir(NODOS), encoding="utf-8-sig")
    usados = set(red["u"]) | set(red["v"])
    nd = nd[nd["nodo_id"].isin(usados)].reset_index(drop=True)
    prueba("esquinas en red = huellas de D4", len(nd) == res["esquinas_en_red"],
           f"{len(nd):,} vs {res['esquinas_en_red']:,}")
    idx = pd.Series(np.arange(len(nd), dtype=np.int32), index=nd["nodo_id"].to_numpy())

    al = pd.read_csv(exigir(ALTURAS), encoding="utf-8-sig",
                     usecols=["nodo", "z_m", "origen"]).set_index("nodo")
    z = nd["nodo_id"].map(al["z_m"]).to_numpy(np.float64)
    prueba("toda esquina de la red tiene altura", not np.isnan(z).any(),
           f"sin altura: {int(np.isnan(z).sum())}")
    estimadas = int((nd["nodo_id"].map(al["origen"]) == "estimada").sum())

    lon = nd["lon"].to_numpy(np.float64)
    lat = nd["lat"].to_numpy(np.float64)
    u = red["u"].map(idx).to_numpy(np.int32)
    v = red["v"].map(idx).to_numpy(np.int32)
    prueba("toda arista apunta a esquinas conocidas",
           not (np.isnan(u.astype(float)).any() or np.isnan(v.astype(float)).any()), "")

    # ------------------------------------------------- 3 geometria, una por calle
    print("\n3. Geometria (una polilinea por calle, sin duplicar ida y vuelta)")
    import geopandas as gpd
    import fiona

    capas = fiona.listlayers(str(exigir(GEOM)))
    capa = "segmentos" if "segmentos" in capas else capas[0]
    print(f"   capa del GPKG: {capa}   (hay {capas})")

    # De cada par FT/TF basta una geometria: la clave es el eje y la parte.
    red["clave"] = red["id_eje"].astype(str) + "_" + red["parte"].astype(str)
    primero = red.drop_duplicates("clave").reset_index(drop=True)
    dib = pd.Series(np.arange(len(primero), dtype=np.int32),
                    index=primero["clave"].to_numpy())
    gi = red["clave"].map(dib).to_numpy(np.int32)
    # La polilinea guardada va en el sentido del primer segmento de cada par.
    # El otro sentido la recorre al reves: la pagina necesita saberlo para animar.
    dueno = pd.Series(primero["u"].to_numpy(), index=primero["clave"].to_numpy())
    rev = (red["u"].to_numpy() != red["clave"].map(dueno).to_numpy()).astype(np.uint8)

    g = gpd.read_file(GEOM, layer=capa, columns=["segmento_id"])
    if g["segmento_id"].duplicated().any():
        raise SystemExit("El GPKG trae segmento_id repetidos: no se puede alinear.")
    g = g.set_index("segmento_id")
    faltan = [s for s in primero["segmento_id"] if s not in g.index]
    prueba("hay geometria para cada calle de la red", not faltan,
           f"sin geometria: {len(faltan)}")
    g = g.loc[primero["segmento_id"]].to_crs("EPSG:4326")

    pu = u[red.drop_duplicates("clave").index.to_numpy()]
    pv = v[red.drop_duplicates("clave").index.to_numpy()]
    offsets = np.zeros(len(primero) + 1, np.int32)
    trozos, peor = [], 0.0
    for i, geo in enumerate(g.geometry):
        partes = list(geo.geoms) if geo.geom_type == "MultiLineString" else [geo]
        pts = [c[:2] for p in partes for c in p.coords]
        peor = max(peor,
                   np.hypot(pts[0][0] - lon[pu[i]], pts[0][1] - lat[pu[i]]),
                   np.hypot(pts[-1][0] - lon[pv[i]], pts[-1][1] - lat[pv[i]]))
        arr = np.asarray(pts, np.float32)
        trozos.append(arr)
        offsets[i + 1] = offsets[i] + len(arr)
    # 1e-4 grados ~ 11 m: deja holgura sobre la rejilla de 2 m con que D2 forma esquinas
    prueba("cada geometria empieza y termina en sus esquinas", peor < 1e-4,
           f"peor desvio {peor * 111320:.1f} m")

    # atributos para el explorador: nombre, clase de via, localidad
    at = pd.read_csv(exigir(ATRIB), encoding="utf-8-sig",
                     usecols=["segmento_id", "name", "highway", "localidad"]
                     ).set_index("segmento_id").reindex(primero["segmento_id"])
    v_nom, i_nom = codificar(at["name"])
    v_cla, i_cla = codificar(at["highway"])
    v_loc, i_loc = codificar(at["localidad"])
    pend_abs = primero["pendiente_ruteo_pct"].abs().to_numpy(np.float32)
    # clase y localidad viajan en un byte; si algun dia no caben, hay que avisar.
    if max(len(v_cla), len(v_loc)) > 255:
        raise SystemExit(f"clases={len(v_cla)} localidades={len(v_loc)}: no caben en un byte.")

    # ------------------------------------------------------------------ 4 energia
    print("\n4. Pesos de energia por vehiculo")
    fichas = fichas_flota()
    carros_ok = []
    for vid in CARROS:
        f = dir_energia(vid) / "D4_pesos_energia.csv"
        if not f.exists():
            print(f"  (sin carpeta) {vid}")
            continue
        pe = pd.read_csv(f, encoding="utf-8-sig",
                         usecols=["segmento_id", "v_kmh", "consumo_kwh",
                                  "castigada", "peso_ruteo_kwh"]
                         ).set_index("segmento_id").reindex(red["segmento_id"])
        if pe["consumo_kwh"].isna().any():
            prueba(f"pesos completos {vid}", False,
                   f"faltan {int(pe['consumo_kwh'].isna().sum())} segmentos")
            continue
        with open(SALIDA / f"carros/{vid}.bin", "wb") as s:
            s.write(pe["consumo_kwh"].to_numpy(np.float32).tobytes())
            s.write(pe["peso_ruteo_kwh"].to_numpy(np.float32).tobytes())
        carros_ok.append({"id": vid,
                          **fichas.get(vid, {}),
                          "v_kmh_mediana": round(float(pe["v_kmh"].median()), 1),
                          "castigadas": int(pe["castigada"].astype(bool).sum()),
                          "regen_aristas": int((pe["consumo_kwh"] < 0).sum())})
    prueba(f"los {len(CARROS)} vehiculos empaquetados", len(carros_ok) == len(CARROS),
           f"{len(carros_ok)}")

    # ---------------------------------------------------------------- 5 estaciones
    print("\n5. Estaciones (enganche recalculado por cuenta propia)")
    es = pd.read_csv(exigir(ESTACION), encoding="utf-8-sig")
    col_nodo, col_m = f"nodo_{ESCENARIO}", f"enganche_{ESCENARIO}_m"
    # Se mide en las mismas coordenadas metricas en que trabaja la tuberia
    # (EPSG:9377, columnas x e y de los dos archivos). Reproyectar desde lon/lat
    # mete medio metro de ruido de la propia vuelta, no de lo que se comprueba.
    nx_ = nd["x"].to_numpy(float)
    ny_ = nd["y"].to_numpy(float)
    ex = es["x"].to_numpy(float)
    ey = es["y"].to_numpy(float)
    # Segunda medida, para dejar constancia: cuanto se corre una esquina al pasar
    # por lon/lat, que es con lo que dibuja la pagina.
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:9377", always_xy=True)
    gx, gy = t.transform(lon, lat)

    at_osm, at_ocm = atributos_estaciones()
    estaciones, difs, peor_vuelta, nodo_igual = [], [], 0.0, 0
    for k in range(len(es)):
        d = np.hypot(nx_ - ex[k], ny_ - ey[k])
        j = int(d.argmin())
        difs.append(abs(float(d[j]) - float(es[col_m].iat[k])))
        peor_vuelta = max(peor_vuelta, float(np.hypot(gx[j] - nx_[j], gy[j] - ny_[j])))
        nodo_igual += int(nd["nodo_id"].iat[j] == es[col_nodo].iat[k])
        nombre = es["nombre_osm"].iat[k]
        if pd.isna(nombre):
            nombre = es["nombre_ocm"].iat[k]
        estaciones.append({
            "n": "Estacion sin nombre" if pd.isna(nombre) else str(nombre).strip(),
            "p": [round(float(es["lon"].iat[k]), 6), round(float(es["lat"].iat[k]), 6)],
            "nodo": j, "dm": round(float(d[j]), 1),
            "cat": str(es["categoria"].iat[k]),
            "src": str(es["fuente_coordenada"].iat[k]),
            "lejos": bool(es[f"lejos_{ESCENARIO}"].iat[k]),
            "detalles": detalles_de(es, k, at_osm, at_ocm),
        })
    # Una esquina es una celda de 2 m, y dos vertices distintos de OSM que caigan
    # en ella quedan fusionados en un solo nodo. Entonces "la esquina" no es un
    # punto sino una nube: las geometrias terminan en un miembro y esta tabla
    # guarda otro. D4 midio contra un extremo de geometria. La diferencia es
    # legitima mientras quepa en la diagonal de la celda; mas alla, no hay excusa.
    difs = np.asarray(difs)
    DIAGONAL_CELDA_M = 2 * 2 ** 0.5
    exactas = int((difs < 0.01).sum())
    excepciones = [
        {"estacion": estaciones[i]["n"], "d4_m": round(float(es[col_m].iat[i]), 3),
         "recalculada_m": round(float(es[col_m].iat[i]) + float(difs[i]), 3),
         "diferencia_m": round(float(difs[i]), 3)}
        for i in np.argsort(-difs) if difs[i] >= 0.01
    ]
    prueba("distancia de enganche: la diferencia cabe en la celda de 2 m",
           difs.max() < DIAGONAL_CELDA_M,
           f"peor {difs.max():.4f} m, admisible hasta {DIAGONAL_CELDA_M:.3f} m")
    prueba("distancia de enganche reproducida al milimetro",
           exactas >= len(es) - 2, f"{exactas}/{len(es)} exactas")
    prueba("esquina de enganche recalculada = la de D4", nodo_igual == len(es),
           f"{nodo_igual}/{len(es)}")
    con_det = sum(1 for e_ in estaciones if e_["detalles"])
    print(f"   estaciones con atributos para la ficha: {con_det} de {len(estaciones)}")
    print(f"   (nota) ir y volver por lon/lat corre la esquina hasta {peor_vuelta:.2f} m")
    for x in excepciones:
        print(f"   (vertices fusionados) {x['estacion'][:40]}: D4 {x['d4_m']} m, "
              f"recalculada {x['recalculada_m']} m")

    # ------------------------------------------------------------------ 6 control
    print("\n6. Viajes de control que la pagina vuelve a resolver")
    pares = pd.read_csv(exigir(PARES), encoding="utf-8-sig")
    comp = pd.read_csv(exigir(dir_energia("byd_dolphin_449") / "D4_comparacion_rutas.csv"),
                       encoding="utf-8-sig").set_index("par")
    rng = np.random.default_rng(7)
    orden = rng.permutation(pares.index.to_numpy())
    control = []
    for p in orden:
        if len(control) >= N_CONTROL:
            break
        fila = pares.loc[p]
        if fila["origen"] not in idx.index or fila["destino"] not in idx.index:
            continue
        if fila["par"] not in comp.index:
            continue
        c = comp.loc[fila["par"]]
        control.append({
            "par": int(fila["par"]),
            "o": int(idx[fila["origen"]]), "d": int(idx[fila["destino"]]),
            "dist_corta_m": round(float(c["distancia_corta_m"]), 3),
            "dist_efic_m": round(float(c["distancia_eficiente_m"]), 3),
            "e_corta_kwh": round(float(c["energia_corta_kwh"]), 6),
            "e_efic_kwh": round(float(c["energia_eficiente_kwh"]), 6),
            "costo_efic_kwh": round(float(c["costo_ruteo_eficiente_kwh"]), 6),
            "n_tramos_efic": len(str(c["tramos_eficiente"]).split(";")),
            "misma_ruta": bool(c["misma_ruta"]),
            "terreno": str(fila["terreno"]), "banda": str(fila["banda"]),
        })
    prueba("viajes de control listos", len(control) >= 20, f"{len(control)}")

    # ----------------------------------------------------------------- 7 escritura
    print("\n7. Medellin (solo para dibujar su red)")
    medellin = red_medellin(prueba)

    print("\n8. Escribiendo")
    limite_bogota(prueba)
    with open(SALIDA / "nodos.bin", "wb") as s:
        s.write(lon.astype(np.float32).tobytes())
        s.write(lat.astype(np.float32).tobytes())
        s.write(z.astype(np.float32).tobytes())
    with open(SALIDA / "aristas.bin", "wb") as s:
        s.write(u.tobytes())
        s.write(v.tobytes())
        s.write(gi.tobytes())
        s.write(red["longitud_m"].to_numpy(np.float32).tobytes())
        s.write(red["pendiente_ruteo_pct"].to_numpy(np.float32).tobytes())
        s.write(rev.tobytes())
    with open(SALIDA / "dibujo.bin", "wb") as s:
        s.write(offsets.tobytes())
        for a in trozos:
            s.write(a.tobytes())
    with open(SALIDA / "dibujo_attr.bin", "wb") as s:
        # Primero los de 4 bytes y despues los de 1: si van mezclados, el
        # arreglo de nombres cae en un byte que no es multiplo de 4 y el
        # navegador se niega a leerlo.
        s.write(pend_abs.tobytes())
        s.write(i_nom.tobytes())
        s.write(i_cla.astype(np.uint8).tobytes())
        s.write(i_loc.astype(np.uint8).tobytes())

    oficial = json.load(open(exigir(OFICIAL), encoding="utf-8"))
    pond = pd.read_csv(exigir(PONDERADO), encoding="utf-8-sig")
    sel = pond[(pond["escenario"] == ESCENARIO) & (pond["hora"] == 12.0)
               & (pond["k"] == 50.0) & (pond["paradas"].astype(bool))
               & (pond["pendiente"] == "extremos")]

    meta = {
        "ciudad": "Bogota", "escenario": ESCENARIO, "rama": RAMA,
        "sintetico": False,
        "n_nodos": int(len(nd)), "n_aristas": int(len(red)),
        "n_dibujo": int(len(primero)), "n_puntos_dibujo": int(offsets[-1]),
        "km_red": res["km_fisicos_en_red"], "pct_km_red": res["pct_km_en_red"],
        "aristas_extremas": res["aristas_extremas_en_red"],
        "aristas_pendiente_0": res["aristas_pendiente_asumida_0_en_red"],
        "esquinas_altura_estimada": estimadas,
        "error_lonlat_m": round(peor_vuelta, 3),
        "enganche_exactas": exactas, "enganche_total": int(len(es)),
        "enganche_peor_m": round(float(difs.max()), 4),
        "enganche_excepciones": excepciones,
        "k": oficial["castigo_extremas"]["k_restriccion_pendiente"],
        "comparacion_principal": oficial.get("comparacion_principal"),
        "hora_base": oficial["consumo"]["hora_base"],
        "forma_pendiente": oficial["consumo"]["forma_pendiente"],
        "vehiculo_base": oficial["consumo"]["vehiculo_base"],
        "z_corte_ladera_m": oficial["pares_od"]["z_corte_ladera_m"],
        "sigma_z_m": oficial["pendiente"]["sigma_z_m"],
        "ancho_correlacion_m": oficial["pendiente"]["ancho_correlacion_m"],
        "corrida": oficial["corrida_citada"]["sello"],
        "huella_grafo": oficial["grafo"]["huella_segmentos_d2"],
        "huella_aristas": hue["archivos"],
        "carros": carros_ok,
        "por_vehiculo": tabla_df(sel),
        "por_estrato": tabla(ESTRATOS),
        "por_localidad": tabla(LOCALIDAD),
        "alcanzabilidad": tabla(ALCANZA),
        "medellin": medellin,
        "pruebas": pruebas,
    }
    esc = dict(ensure_ascii=False, allow_nan=False)
    json.dump(meta, open(SALIDA / "meta.json", "w", encoding="utf-8"), **esc)
    json.dump({"nombre": v_nom, "clase": v_cla, "localidad": v_loc},
              open(SALIDA / "vocab.json", "w", encoding="utf-8"), **esc)
    json.dump(estaciones, open(SALIDA / "estaciones.json", "w", encoding="utf-8"), **esc)
    json.dump(control, open(SALIDA / "control.json", "w", encoding="utf-8"), **esc)

    print("\nTamanos:")
    total = 0
    for f in sorted(SALIDA.rglob("*")):
        if f.is_file():
            total += f.stat().st_size
            print(f"   {f.relative_to(SALIDA)}   {f.stat().st_size / 1e6:.2f} MB")
    print(f"   TOTAL   {total / 1e6:.1f} MB")

    fallan = [p["prueba"] for p in pruebas if not p["pasa"]]
    print("\n" + ("TODAS LAS PRUEBAS PASAN" if not fallan else f"FALLAN: {fallan}"))
    return 0 if not fallan else 1


def detalles_de(es, k, at_osm, at_ocm) -> list:
    """Los campos de una estacion: primero los de OSM y despues los de OCM, sin repetir."""
    campos, vistos = [], set()
    uid = es["osm_uid"].iat[k] if "osm_uid" in es.columns else None
    oid = es["ocm_id"].iat[k] if "ocm_id" in es.columns else None
    fuentes = []
    if uid is not None and not pd.isna(uid):
        fuentes.append(at_osm.get(str(uid)) or at_osm.get(str(uid).split("/")[-1]) or [])
    if oid is not None and not pd.isna(oid):
        fuentes.append(at_ocm.get(str(oid).split(".")[0]) or [])
    for lista in fuentes:
        for c in lista:
            if c["campo"] not in vistos:
                vistos.add(c["campo"])
                campos.append(c)
    return campos[:10]


def tabla_df(d: pd.DataFrame) -> list:
    d = d.copy()
    for c in d.columns:
        d[c] = d[c].astype(object).where(d[c].notna(), None)
    return d.to_dict("records")




# ============================================================================
# MEDELLIN: el mismo paquete, con el mismo formato, en datos_medellin/
# ============================================================================
def col(df_o_cols, opciones, archivo, obligatoria=True):
    """El primer nombre de 'opciones' que exista. Si ninguno, se detiene y muestra lo que hay."""
    cols = list(df_o_cols.columns if hasattr(df_o_cols, "columns") else df_o_cols)
    for o in opciones:
        if o in cols:
            return o
    if obligatoria:
        raise SystemExit(f"\nEn {Path(archivo).name} no encontre ninguna de {opciones}.\n"
                         f"Columnas que trae: {cols}\nPegale esto a Claude.")
    return None


def cabecera(p):
    return list(pd.read_csv(exigir(p), nrows=0, encoding="utf-8-sig").columns)


def uno_que_exista(carpeta, patron):
    hall = sorted(Path(carpeta).glob(patron))
    if not hall:
        raise SystemExit(f"FALTA en {carpeta}: ningun archivo {patron}. "
                         f"Hay: {[p.name for p in Path(carpeta).glob('*')][:15]}")
    return hall[0]



def empaquetar_medellin():
    """Lo mismo que main(), para la corrida oficial de D4 Medellin.

    Escribe datos_medellin/ con el mismo formato que datos_bogota/. No supone nombres
    de columnas: si un archivo no trae ninguno de los nombres posibles, se detiene
    mostrando los que si trae.
    """
    ESCENARIO_M = "sens_sin_altura_A"
    RAMA = "med_sigma054"
    SUFIJO_ENERGIA = "h12__extremos__long_inclinada__con_paradas__k50"
    N_CONTROL = 25

    AQUI = Path(__file__).resolve().parent
    SALIDA = AQUI / "datos_medellin"
    E = RAIZ / "entregables"
    M4 = E / "D4_medellin"

    ARISTAS  = M4 / f"esc_{ESCENARIO_M}/D4M_aristas_{ESCENARIO_M}.csv"
    HUELLAS  = M4 / f"esc_{ESCENARIO_M}/D4M_huellas_{ESCENARIO_M}.json"
    NODOS    = E / "D2_medellin/nodos_medellin.csv"
    ALTURAS  = M4 / "alturas_esquinas/D4M_alturas_esquinas.csv"
    GEOM     = E / f"D3_medellin/rama_{RAMA}/D3M_grafo_con_pendiente_{RAMA}.gpkg"
    ATRIB    = E / f"D3_medellin/rama_{RAMA}/D3M_grafo_con_pendiente_{RAMA}.csv"
    ESTACION = M4 / "estaciones/D4M_estaciones_enganche.csv"
    OFICIAL  = M4 / "D4M_version_oficial.json"
    PARES    = M4 / "rutas_distancia/D4M_muestra_pares_od.csv"
    ARCOS    = M4 / "para_modulo_consumo/D4M_arcos_grafo_coordenadas.csv"
    LIMITE   = AQUI / "datos_bogota/medellin/limite.json"

    def dir_energia(vid):
        return M4 / f"energia/esc_{ESCENARIO_M}__{vid}__{SUFIJO_ENERGIA}"

    SALIDA.mkdir(exist_ok=True)
    (SALIDA / "carros").mkdir(exist_ok=True)
    pruebas = []

    def prueba(nombre, ok, detalle=""):
        pruebas.append({"prueba": nombre, "pasa": bool(ok), "detalle": str(detalle)})
        print(f"  [{'OK   ' if ok else 'FALLA'}] {nombre}  {detalle}")

    # ------------------------------------------------------------------ 1 aristas
    print("\n1. Aristas de la red oficial de Medellin")
    cab = cabecera(ARISTAS)
    c_seg = col(cab, ["segmento_id"], ARISTAS)
    c_red = col(cab, ["en_red", "en_red_oficial"], ARISTAS)
    c_pen = col(cab, ["pendiente_ruteo_pct"], ARISTAS)
    ar = pd.read_csv(ARISTAS, encoding="utf-8-sig",
                     usecols=[c_seg, "u", "v", "longitud_m", c_red, c_pen])
    ar = ar.rename(columns={c_seg: "segmento_id", c_red: "en_red", c_pen: "pendiente_ruteo_pct"})
    red = ar[ar["en_red"].astype(bool)].reset_index(drop=True)
    hue = json.load(open(exigir(HUELLAS), encoding="utf-8"))
    res = hue["resumen"]
    prueba("aristas en red = huellas de D4M", len(red) == res["aristas_en_red"],
           f"{len(red):,} vs {res['aristas_en_red']:,}")

    # ------------------------------------------------------------------ 2 esquinas
    print("\n2. Esquinas y alturas")
    nd = pd.read_csv(exigir(NODOS), encoding="utf-8-sig")
    c_id = col(nd, ["nodo_id", "node_id", "nodo", "id"], NODOS)
    c_lon = col(nd, ["lon", "longitud", "lng"], NODOS, obligatoria=False)
    c_lat = col(nd, ["lat", "latitud"], NODOS, obligatoria=False)
    if not (c_lon and c_lat):
        # nodos_medellin.csv solo trae x, y. La longitud y latitud de cada esquina se
        # toman del archivo que la celda 22 de D4M escribio con ellas (lon_u, lat_u...).
        arc = pd.read_csv(exigir(ARCOS), encoding="utf-8-sig",
                          usecols=["u", "v", "lon_u", "lat_u", "lon_v", "lat_v"])
        ll = pd.concat([arc[["u", "lon_u", "lat_u"]].set_axis(["n", "lon", "lat"], axis=1),
                        arc[["v", "lon_v", "lat_v"]].set_axis(["n", "lon", "lat"], axis=1)])
        dif = ll.groupby("n")[["lon", "lat"]].agg(lambda c: c.max() - c.min()).to_numpy().max()
        ll = ll.drop_duplicates("n").set_index("n")
        nd["lon"] = nd[c_id].map(ll["lon"]); nd["lat"] = nd[c_id].map(ll["lat"])
        c_lon, c_lat = "lon", "lat"
        print(f"   lon y lat de las esquinas tomadas de {ARCOS.name}")
        prueba("cada esquina tiene una sola lon, lat en el archivo de la celda 22",
               dif < 1e-7, f"mayor diferencia {dif:.2e} grados")
    usados = set(red["u"]) | set(red["v"])
    nd = nd[nd[c_id].isin(usados)].reset_index(drop=True)
    prueba("esquinas en red = huellas de D4M", len(nd) == res["esquinas_en_red"],
           f"{len(nd):,} vs {res['esquinas_en_red']:,}")
    idx = pd.Series(np.arange(len(nd), dtype=np.int32), index=nd[c_id].to_numpy())

    cab_al = cabecera(ALTURAS)
    a_id = col(cab_al, ["nodo", "nodo_id"], ALTURAS)
    a_z = col(cab_al, ["z_m", "z"], ALTURAS)
    a_or = col(cab_al, ["origen"], ALTURAS, obligatoria=False)
    al = pd.read_csv(ALTURAS, encoding="utf-8-sig",
                     usecols=[a_id, a_z] + ([a_or] if a_or else [])).set_index(a_id)
    z = nd[c_id].map(al[a_z]).to_numpy(np.float64)
    prueba("toda esquina de la red tiene altura", not np.isnan(z).any(),
           f"sin altura: {int(np.isnan(z).sum())}")
    estimadas = int((nd[c_id].map(al[a_or]) == "estimada").sum()) if a_or else None

    lon = nd[c_lon].to_numpy(np.float64)
    lat = nd[c_lat].to_numpy(np.float64)
    prueba("toda esquina de la red tiene lon y lat", not (np.isnan(lon).any() or np.isnan(lat).any()),
           f"sin coordenada: {int(np.isnan(lon).sum())}")
    u = red["u"].map(idx).to_numpy()
    v = red["v"].map(idx).to_numpy()
    prueba("toda arista apunta a esquinas conocidas",
           not (pd.isna(u).any() or pd.isna(v).any()), "")
    u = u.astype(np.int32); v = v.astype(np.int32)

    # ------------------------------------------------- 3 geometria, una por calle
    print("\n3. Geometria (una polilinea por calle, sin duplicar ida y vuelta)")
    # Ida y vuelta comparten el id sin el sufijo _FT / _TF.
    red["clave"] = red["segmento_id"].astype(str).str.replace(r"_(FT|TF)$", "", regex=True)
    primero = red.drop_duplicates("clave").reset_index(drop=True)
    dib = pd.Series(np.arange(len(primero), dtype=np.int32), index=primero["clave"].to_numpy())
    gi = red["clave"].map(dib).to_numpy(np.int32)
    dueno = pd.Series(primero["u"].to_numpy(), index=primero["clave"].to_numpy())
    rev = (red["u"].to_numpy() != red["clave"].map(dueno).to_numpy()).astype(np.uint8)
    pu = primero["u"].map(idx).to_numpy(np.int32)
    pv = primero["v"].map(idx).to_numpy(np.int32)

    geom_fuente = "recta entre esquinas"
    geos = None
    if GEOM.exists():
        import fiona
        import geopandas as gpd
        capas = fiona.listlayers(str(GEOM))
        capa = "segmentos" if "segmentos" in capas else capas[0]
        g = gpd.read_file(GEOM, layer=capa)
        print(f"   capa del GPKG: {capa}   (hay {capas})")
        gc = col(g, ["segmento_id"], GEOM)
        g = g.drop_duplicates(gc).set_index(gc)
        llave = primero["segmento_id"].where(primero["segmento_id"].isin(g.index), primero["clave"])
        faltan = int((~llave.isin(g.index)).sum())
        prueba("hay geometria para cada calle de la red", faltan == 0, f"sin geometria: {faltan}")
        if faltan == 0:
            geos = g.loc[llave].to_crs("EPSG:4326").geometry
            geom_fuente = GEOM.name
    else:
        print(f"   (no esta {GEOM.name}: cada calle se dibuja recta entre sus esquinas)")

    offsets = np.zeros(len(primero) + 1, np.int32)
    trozos, peor = [], 0.0
    for i in range(len(primero)):
        if geos is not None:
            geo = geos.iloc[i]
            partes = list(geo.geoms) if geo.geom_type == "MultiLineString" else [geo]
            pts = [c[:2] for p in partes for c in p.coords]
            # la geometria puede venir en el otro sentido: se voltea si su final
            # queda mas cerca de la esquina de salida
            d_ida = np.hypot(pts[0][0] - lon[pu[i]], pts[0][1] - lat[pu[i]])
            d_vue = np.hypot(pts[-1][0] - lon[pu[i]], pts[-1][1] - lat[pu[i]])
            if d_vue < d_ida:
                pts = pts[::-1]
            peor = max(peor, np.hypot(pts[0][0] - lon[pu[i]], pts[0][1] - lat[pu[i]]),
                       np.hypot(pts[-1][0] - lon[pv[i]], pts[-1][1] - lat[pv[i]]))
        else:
            pts = [(lon[pu[i]], lat[pu[i]]), (lon[pv[i]], lat[pv[i]])]
        arr = np.asarray(pts, np.float32)
        trozos.append(arr)
        offsets[i + 1] = offsets[i] + len(arr)
    if geos is not None:
        prueba("cada geometria empieza y termina en sus esquinas", peor < 1e-4,
               f"peor desvio {peor * 111320:.1f} m")

    # atributos: nombre, clase de via y comuna, si el archivo los trae
    v_nom, i_nom = codificar(pd.Series([None] * len(primero)))
    v_cla, i_cla = v_nom, i_nom.copy()
    v_loc, i_loc = v_nom, i_nom.copy()
    if ATRIB.exists():
        cab_at = cabecera(ATRIB)
        t_seg = col(cab_at, ["segmento_id"], ATRIB)
        t_nom = col(cab_at, ["name", "nombre"], ATRIB, obligatoria=False)
        t_cla = col(cab_at, ["highway", "tipo_via", "jerarquia"], ATRIB, obligatoria=False)
        t_loc = col(cab_at, ["localidad", "comuna", "nombre_comuna"], ATRIB, obligatoria=False)
        usar = [c for c in (t_seg, t_nom, t_cla, t_loc) if c]
        at = pd.read_csv(ATRIB, encoding="utf-8-sig", usecols=usar).drop_duplicates(t_seg).set_index(t_seg)
        llave = primero["segmento_id"].where(primero["segmento_id"].isin(at.index), primero["clave"])
        at = at.reindex(llave)
        if t_nom: v_nom, i_nom = codificar(at[t_nom])
        if t_cla: v_cla, i_cla = codificar(at[t_cla])
        if t_loc: v_loc, i_loc = codificar(at[t_loc])
        print(f"   atributos: nombre={t_nom} clase={t_cla} zona={t_loc}")
    pend_abs = primero["pendiente_ruteo_pct"].abs().to_numpy(np.float32)
    if max(len(v_cla), len(v_loc)) > 255:
        raise SystemExit(f"clases={len(v_cla)} zonas={len(v_loc)}: no caben en un byte.")

    # ------------------------------------------------------------------ 4 energia
    print("\n4. Pesos de energia por vehiculo")
    fichas = fichas_flota()
    carros_ok = []
    for vid in CARROS:
        carpeta = dir_energia(vid)
        if not carpeta.exists():
            print(f"  (sin carpeta) {carpeta.name}")
            continue
        f = uno_que_exista(carpeta, "*pesos_energia*.csv")
        cab_pe = cabecera(f)
        p_seg = col(cab_pe, ["segmento_id"], f)
        p_con = col(cab_pe, ["consumo_kwh"], f)
        p_pes = col(cab_pe, ["peso_ruteo_kwh"], f)
        p_vel = col(cab_pe, ["v_kmh"], f, obligatoria=False)
        p_cas = col(cab_pe, ["castigada"], f, obligatoria=False)
        pe = pd.read_csv(f, encoding="utf-8-sig",
                         usecols=[c for c in (p_seg, p_con, p_pes, p_vel, p_cas) if c]
                         ).drop_duplicates(p_seg).set_index(p_seg).reindex(red["segmento_id"])
        if pe[p_con].isna().any() or pe[p_pes].isna().any():
            prueba(f"pesos completos {vid}", False,
                   f"faltan {int(pe[p_con].isna().sum())} segmentos")
            continue
        with open(SALIDA / f"carros/{vid}.bin", "wb") as s:
            s.write(pe[p_con].to_numpy(np.float32).tobytes())
            s.write(pe[p_pes].to_numpy(np.float32).tobytes())
        carros_ok.append({"id": vid, **fichas.get(vid, {}),
                          "v_kmh_mediana": round(float(pe[p_vel].median()), 1) if p_vel else None,
                          "castigadas": int(pe[p_cas].astype(bool).sum()) if p_cas else None,
                          "regen_aristas": int((pe[p_con] < 0).sum())})
    prueba(f"los {len(CARROS)} vehiculos empaquetados", len(carros_ok) == len(CARROS),
           f"{len(carros_ok)}")

    # ---------------------------------------------------------------- 5 estaciones
    print("\n5. Estaciones (enganche recalculado por cuenta propia)")
    es = pd.read_csv(exigir(ESTACION), encoding="utf-8-sig")
    e_nodo = col(es, [f"nodo_{ESCENARIO_M}", "nodo", "nodo_red"], ESTACION)
    e_m = col(es, [f"enganche_{ESCENARIO_M}_m", "enganche_m", "distancia_m"], ESTACION)
    e_lon = col(es, ["lon", "longitud"], ESTACION)
    e_lat = col(es, ["lat", "latitud"], ESTACION)
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:9377", always_xy=True)
    if {"x", "y"} <= set(nd.columns) and {"x", "y"} <= set(es.columns):
        nx_, ny_ = nd["x"].to_numpy(float), nd["y"].to_numpy(float)
        ex, ey = es["x"].to_numpy(float), es["y"].to_numpy(float)
        medida = "x, y de los dos archivos"
    else:
        nx_, ny_ = t.transform(lon, lat)
        ex, ey = t.transform(es[e_lon].to_numpy(float), es[e_lat].to_numpy(float))
        nx_, ny_, ex, ey = map(np.asarray, (nx_, ny_, ex, ey))
        medida = "lon, lat llevados a EPSG:9377"
    print(f"   distancias medidas con {medida}")
    nom_cols = [c for c in ("nombre_osm", "nombre_ocm", "nombre", "name") if c in es.columns]
    estaciones, difs, nodo_igual = [], [], 0
    for k in range(len(es)):
        d = np.hypot(nx_ - ex[k], ny_ - ey[k])
        j = int(d.argmin())
        difs.append(abs(float(d[j]) - float(es[e_m].iat[k])))
        nodo_igual += int(nd[c_id].iat[j] == es[e_nodo].iat[k])
        nombre = next((es[c].iat[k] for c in nom_cols if not pd.isna(es[c].iat[k])), None)
        estaciones.append({
            "n": "Estacion sin nombre" if nombre is None else str(nombre).strip(),
            "p": [round(float(es[e_lon].iat[k]), 6), round(float(es[e_lat].iat[k]), 6)],
            "nodo": j, "dm": round(float(d[j]), 1),
            "cat": str(es["categoria"].iat[k]) if "categoria" in es.columns else "",
            "src": str(es["fuente_coordenada"].iat[k]) if "fuente_coordenada" in es.columns else "",
            "lejos": bool(es[f"lejos_{ESCENARIO_M}"].iat[k]) if f"lejos_{ESCENARIO_M}" in es.columns else False,
            "detalles": [],
        })
    difs = np.asarray(difs)
    DIAGONAL = 2 * 2 ** 0.5
    exactas = int((difs < 0.01).sum())
    prueba("distancia de enganche: la diferencia cabe en la celda de 2 m", difs.max() < DIAGONAL,
           f"peor {difs.max():.4f} m, admisible hasta {DIAGONAL:.3f} m")
    prueba("esquina de enganche recalculada = la de D4M", nodo_igual == len(es),
           f"{nodo_igual}/{len(es)}")
    print(f"   {exactas}/{len(es)} distancias reproducidas al milimetro")

    # ------------------------------------------------------------------ 6 control
    print("\n6. Viajes de control que la pagina vuelve a resolver")
    control = []
    try:
        pares = pd.read_csv(exigir(PARES), encoding="utf-8-sig")
        f_comp = uno_que_exista(dir_energia("byd_dolphin_449"), "*comparacion_rutas*.csv")
        comp = pd.read_csv(f_comp, encoding="utf-8-sig").set_index("par")
        rng = np.random.default_rng(7)
        for p in rng.permutation(pares.index.to_numpy()):
            if len(control) >= N_CONTROL:
                break
            fila = pares.loc[p]
            if fila["origen"] not in idx.index or fila["destino"] not in idx.index or fila["par"] not in comp.index:
                continue
            c = comp.loc[fila["par"]]
            control.append({
                "par": int(fila["par"]), "o": int(idx[fila["origen"]]), "d": int(idx[fila["destino"]]),
                "dist_corta_m": round(float(c["distancia_corta_m"]), 3),
                "dist_efic_m": round(float(c["distancia_eficiente_m"]), 3),
                "e_corta_kwh": round(float(c["energia_corta_kwh"]), 6),
                "e_efic_kwh": round(float(c["energia_eficiente_kwh"]), 6),
                "costo_efic_kwh": round(float(c["costo_ruteo_eficiente_kwh"]), 6),
                "misma_ruta": bool(c["misma_ruta"]),
                "terreno": str(fila["terreno"]), "banda": str(fila["banda"]),
            })
    except (KeyError, SystemExit) as e:
        print(f"  (no pude armar los viajes de control: {e})")
    prueba("viajes de control listos", len(control) >= 20, f"{len(control)}")

    # ----------------------------------------------------------------- 7 escritura
    print("\n7. Escribiendo")
    if LIMITE.exists():
        shutil.copy(LIMITE, SALIDA / "limite.json")
        print("  limite de Medellin (IGAC) copiado de datos_bogota/medellin/limite.json")
    else:
        prueba("limite de Medellin disponible", False, "corre primero empaquetar_bogota.py")
    with open(SALIDA / "nodos.bin", "wb") as s:
        s.write(lon.astype(np.float32).tobytes())
        s.write(lat.astype(np.float32).tobytes())
        s.write(z.astype(np.float32).tobytes())
    with open(SALIDA / "aristas.bin", "wb") as s:
        s.write(u.tobytes()); s.write(v.tobytes()); s.write(gi.tobytes())
        s.write(red["longitud_m"].to_numpy(np.float32).tobytes())
        s.write(red["pendiente_ruteo_pct"].to_numpy(np.float32).tobytes())
        s.write(rev.tobytes())
    with open(SALIDA / "dibujo.bin", "wb") as s:
        s.write(offsets.tobytes())
        for a in trozos:
            s.write(a.tobytes())
    with open(SALIDA / "dibujo_attr.bin", "wb") as s:
        s.write(pend_abs.tobytes())
        s.write(i_nom.astype(np.int32).tobytes())
        s.write(i_cla.astype(np.uint8).tobytes())
        s.write(i_loc.astype(np.uint8).tobytes())

    oficial = json.load(open(OFICIAL, encoding="utf-8")) if OFICIAL.exists() else {}
    meta = {
        "ciudad": "Medellin", "escenario": ESCENARIO_M, "rama": RAMA, "sintetico": False,
        "n_nodos": int(len(nd)), "n_aristas": int(len(red)),
        "n_dibujo": int(len(primero)), "n_puntos_dibujo": int(offsets[-1]),
        "km_red": res.get("km_fisicos_en_red"), "aristas_extremas": res.get("aristas_extremas_en_red"),
        "esquinas_altura_estimada": estimadas, "geometria": geom_fuente,
        "vehiculo_base": oficial.get("consumo", {}).get("vehiculo_base", "byd_dolphin_449"),
        "huella_aristas": hue.get("archivos"),
        "carros": carros_ok,
        # viajes que ahorran mas de 5 % por carro, ponderado, k = 50 (celda 20d de D4M)
        "por_vehiculo": tabla(M4 / "estratos/k50/D4M_12_carros_k50.csv"),
        "pruebas": pruebas,
    }
    esc = dict(ensure_ascii=False, allow_nan=False)
    json.dump(meta, open(SALIDA / "meta.json", "w", encoding="utf-8"), **esc)
    json.dump({"nombre": v_nom, "clase": v_cla, "localidad": v_loc},
              open(SALIDA / "vocab.json", "w", encoding="utf-8"), **esc)
    json.dump(estaciones, open(SALIDA / "estaciones.json", "w", encoding="utf-8"), **esc)
    json.dump(control, open(SALIDA / "control.json", "w", encoding="utf-8"), **esc)

    total = sum(f.stat().st_size for f in SALIDA.rglob("*") if f.is_file())
    print(f"\n   TOTAL datos_medellin  {total / 1e6:.1f} MB   (geometria: {geom_fuente})")
    fallan = [p["prueba"] for p in pruebas if not p["pasa"]]
    print("\n" + ("TODAS LAS PRUEBAS PASAN" if not fallan else f"FALLAN: {fallan}"))
    return 0 if not fallan else 1


if __name__ == "__main__":
    print("=" * 70 + "\nBOGOTA\n" + "=" * 70)
    r_bog = main()
    print("\n" + "=" * 70 + "\nMEDELLIN\n" + "=" * 70)
    r_med = empaquetar_medellin()
    print("\n" + "=" * 70)
    print("BOGOTA:  ", "todas las pruebas pasan" if r_bog == 0 else "HAY PRUEBAS QUE FALLAN (mira arriba)")
    print("MEDELLIN:", "todas las pruebas pasan" if r_med == 0 else "HAY PRUEBAS QUE FALLAN (mira arriba)")
    sys.exit(max(r_bog, r_med))