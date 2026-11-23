"""
Marca los segmentos de la Malla Vial que van por un puente o un tunel segun
OpenStreetMap y cuenta cuantos tramos con pendiente extrema se explican asi.

La Malla Vial no trae ese atributo (en d1_malla.py los campos bridge
y tunnel quedan vacios). Sobre un puente, el MDT mide el terreno de abajo y no
el tablero, asi que la pendiente del segmento puede ser falsa.

Como se cruza:
  1. Se descargan de OSM las vias (highway=*) con bridge o tunnel distinto de
     "no", dentro del rectangulo de la Malla Vial.
  2. Cada via de OSM se ensancha BUFFER_M metros a cada lado.
  3. Un segmento se marca si al menos FRACCION_MIN de su longitud cae dentro
     de ese ensanche y su direccion difiere de la de OSM en menos de
     ANGULO_MAX_GRADOS (en cualquiera de los dos sentidos). La condicion de
     angulo evita marcar la calle que pasa por debajo del puente.
  4. Se repite con buffers de 5, 8 y 15 m para ver cuanto depende el conteo
     de ese parametro.

 solo marca y cuenta.

Uso:   python auxiliares/aux_puentes_tuneles_osm.py
Entra: el CSV final y D2_segmentos_para_pendiente.gpkg
Sale:  datos_salida/auxiliares/puentes_tuneles_segmentos.csv   (segmentos marcados)
       datos_salida/auxiliares/puentes_tuneles_resumen.csv     (conteos y efecto)
       datos_salida/auxiliares/osm_puentes_tuneles_bogota.gpkg  (lo descargado de OSM)
Usa el servicio Overpass de OpenStreetMap. Datos de OSM bajo licencia ODbL.
"""
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX

BUFFER_M = 8.0
BUFFERS_SENSIBILIDAD_M = [5.0, 8.0, 15.0]
FRACCION_MIN = 0.5
ANGULO_MAX_GRADOS = 30.0
ARCHIVO_OSM = CARPETA_AUX / "osm_puentes_tuneles_bogota.gpkg"
SERVIDORES_OVERPASS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                       "https://overpass.kumi.systems/api/interpreter",
                       "https://overpass-api.de/api/interpreter"]
INTENTOS_POR_SERVIDOR = 3


def consulta_overpass(sur, oeste, norte, este):
    """Solo vias (highway) marcadas como puente o tunel, con su geometria.
    Es una consulta liviana: no trae nodos sueltos, edificios ni relaciones."""
    caja = f"{sur},{oeste},{norte},{este}"
    return (f'[out:json][timeout:300];('
            f'way["highway"]["bridge"]["bridge"!="no"]({caja});'
            f'way["highway"]["tunnel"]["tunnel"!="no"]({caja});'
            f');out tags geom;')


def descargar_osm(limites_4326):
    """Vias de OSM con bridge o tunnel, guardadas para no volver a descargar."""
    if ARCHIVO_OSM.exists():
        print(f"Usando la descarga guardada: {ARCHIVO_OSM.name}")
        return gpd.read_file(ARCHIVO_OSM)
    import time

    import requests
    from shapely.geometry import LineString

    oeste, sur, este, norte = limites_4326
    datos = None
    for servidor in SERVIDORES_OVERPASS:
        for intento in range(1, INTENTOS_POR_SERVIDOR + 1):
            print(f"Descargando de OpenStreetMap ({servidor}, intento {intento})...")
            try:
                r = requests.post(servidor, data={"data": consulta_overpass(sur, oeste, norte, este)}, timeout=360)
                r.raise_for_status()
                datos = r.json()
                break
            except Exception as e:
                print(f"  no respondio: {type(e).__name__}")
                time.sleep(20)
        if datos is not None:
            break
    if datos is None:
        sys.exit("Ningun servidor de Overpass respondio. Intente mas tarde o desde otra conexion.")

    filas = []
    for el in datos.get("elements", []):
        geom = el.get("geometry") or []
        if el.get("type") != "way" or len(geom) < 2:
            continue
        t = el.get("tags", {})
        filas.append({"osm_id": el["id"], "highway": t.get("highway", ""),
                      "bridge": t.get("bridge", ""), "tunnel": t.get("tunnel", ""),
                      "geometry": LineString([(p["lon"], p["lat"]) for p in geom])})
    f = gpd.GeoDataFrame(filas, geometry="geometry", crs=C.CRS_CONSULTA)
    if f.empty:
        sys.exit("La descarga no trajo vias con puente o tunel. Revise el area consultada.")
    f["es_puente"] = ~f["bridge"].isin(["", "no"])
    f["es_tunel"] = ~f["tunnel"].isin(["", "no"])
    f.to_file(ARCHIVO_OSM, driver="GPKG")
    print(f"  {len(f):,} vias de OSM ({int(f['es_puente'].sum()):,} puente, {int(f['es_tunel'].sum()):,} tunel)")
    return f


def rumbo(geom):
    """Direccion de la recta entre el primer y el ultimo punto, en grados [0, 180)."""
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)
    (x0, y0), (x1, y1) = geom.coords[0], geom.coords[-1]
    return np.degrees(np.arctan2(y1 - y0, x1 - x0)) % 180


def diferencia_angular(a, b):
    d = np.abs(a - b) % 180
    return np.minimum(d, 180 - d)


def cruzar(seg, osm, buffer_m):
    """Devuelve, por segmento_id, si va sobre puente o tunel de OSM."""
    zona = osm[["es_puente", "es_tunel", "geometry"]].copy()
    zona["rumbo_osm"] = osm.geometry.apply(rumbo)
    zona["geometry"] = osm.geometry.buffer(buffer_m, cap_style=2)
    cand = gpd.sjoin(seg[["segmento_id", "longitud_m", "geometry"]], zona, predicate="intersects", how="inner")
    if cand.empty:
        return pd.DataFrame(columns=["segmento_id", "puente_osm", "tunel_osm"])
    zonas = zona.geometry.values
    cand["dentro_m"] = [g.intersection(zonas[i]).length for g, i in zip(cand.geometry.values, cand["index_right"])]
    cand["fraccion"] = cand["dentro_m"] / cand.geometry.length
    cand["dif_angulo"] = diferencia_angular(cand.geometry.apply(rumbo).to_numpy(), cand["rumbo_osm"].to_numpy())
    ok = cand[(cand["fraccion"] >= FRACCION_MIN) & (cand["dif_angulo"] <= ANGULO_MAX_GRADOS)]
    return ok.groupby("segmento_id").agg(puente_osm=("es_puente", "any"), tunel_osm=("es_tunel", "any")).reset_index()


def describir(df, nombre):
    con = df[~df["fuera_cobertura_mdt"]]
    a = con["pendiente_neta_pct"].abs()
    clases = con["clasificacion_invias"].value_counts(normalize=True) * 100
    return {"conjunto": nombre, "segmentos_con_dato": len(con),
            "neta_abs_mediana_pct": a.median(), "neta_abs_p90_pct": a.quantile(0.90),
            "neta_abs_p99_pct": a.quantile(0.99),
            **{f"{c.lower()}_pct": clases.get(c, 0.0) for c in C.ETIQUETAS_INVIAS},
            "extremas": int(con["pendiente_extrema"].sum()),
            "extremas_pct": 100 * con["pendiente_extrema"].mean()}


def main():
    df = pd.read_csv(C.ARCHIVO_PENDIENTES)
    for col in ("pendiente_extrema", "fuera_cobertura_mdt"):
        df[col] = df[col].astype(str).eq("True")
    seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)[["segmento_id", "longitud_m", "geometry"]]
    # Solo el area con dato del MDT (zona urbana); la Malla Vial llega hasta Sumapaz.
    urbano = seg[seg["segmento_id"].isin(df.loc[~df["fuera_cobertura_mdt"], "segmento_id"])]
    osm = descargar_osm(urbano.to_crs(C.CRS_CONSULTA).total_bounds).to_crs(seg.crs)

    filas_sens = []
    for b in BUFFERS_SENSIBILIDAD_M:
        m = cruzar(seg, osm, b)
        marcados = df["segmento_id"].isin(m["segmento_id"])
        ext = df["pendiente_extrema"]
        filas_sens.append({"buffer_m": b, "segmentos_marcados": int(marcados.sum()),
                           "extremas_marcadas": int((marcados & ext).sum()),
                           "tramos_extremos_marcados": df.loc[marcados & ext, "segmento_id"].str.rsplit("_", n=1).str[0].nunique()})
        if b == BUFFER_M:
            principal = m

    df = df.merge(principal, on="segmento_id", how="left")
    df["puente_osm"] = df["puente_osm"].eq(True)
    df["tunel_osm"] = df["tunel_osm"].eq(True)
    df["estructura_osm"] = df["puente_osm"] | df["tunel_osm"]
    df["tramo_fisico"] = df["segmento_id"].str.rsplit("_", n=1).str[0]
    ext = df[df["pendiente_extrema"]]

    n_tramos = ext["tramo_fisico"].nunique()
    n_tramos_osm = ext.loc[ext["estructura_osm"], "tramo_fisico"].nunique()
    print(f"\nBuffer {BUFFER_M:.0f} m, fraccion minima {FRACCION_MIN}, angulo maximo {ANGULO_MAX_GRADOS:.0f} grados")
    print(f"Segmentos marcados: {int(df['estructura_osm'].sum()):,} "
          f"(puente {int(df['puente_osm'].sum()):,}, tunel {int(df['tunel_osm'].sum()):,})")
    print(f"Filas extremas sobre puente o tunel: {int(ext['estructura_osm'].sum()):,} de {len(ext):,} "
          f"({100 * ext['estructura_osm'].mean():.1f} %)")
    print(f"Tramos fisicos extremos sobre puente o tunel: {n_tramos_osm:,} de {n_tramos:,} "
          f"({100 * n_tramos_osm / n_tramos:.1f} %)")
    franjas = pd.cut(ext["pendiente_neta_pct"].abs(), [0, 35, 50, 75, np.inf], labels=["<=35 (solo acumulada)", "35-50", "50-75", ">75"])
    print("\nPor franja de |neta|:")
    print(ext.groupby(franjas, observed=False)["estructura_osm"].agg(["size", "sum"]).rename(columns={"size": "extremas", "sum": "sobre_puente_o_tunel"}).to_string())

    efecto = pd.DataFrame([describir(df, "todos"), describir(df[~df["estructura_osm"]], "sin puentes ni tuneles OSM"),
                           describir(df[df["estructura_osm"]], "solo puentes y tuneles OSM")])
    print("\nEfecto sobre la distribucion:")
    print(efecto.round(2).T.to_string())
    print("\nSensibilidad al buffer:")
    sens = pd.DataFrame(filas_sens)
    print(sens.to_string(index=False))

    salida = df[df["estructura_osm"]][["segmento_id", "puente_osm", "tunel_osm", "pendiente_neta_pct",
                                       "pendiente_acumulada_pct", "pendiente_extrema", "clasificacion_invias"]]
    salida.to_csv(CARPETA_AUX / "puentes_tuneles_segmentos.csv", index=False, encoding="utf-8-sig")
    resumen = efecto.assign(parametros=f"buffer {BUFFER_M} m; fraccion {FRACCION_MIN}; angulo {ANGULO_MAX_GRADOS}")
    with open(CARPETA_AUX / "puentes_tuneles_resumen.csv", "w", encoding="utf-8-sig", newline="") as f:
        resumen.to_csv(f, index=False)
        f.write("\n")
        sens.to_csv(f, index=False)
    print("\nGuardado: puentes_tuneles_segmentos.csv y puentes_tuneles_resumen.csv")


if __name__ == "__main__":
    main()
