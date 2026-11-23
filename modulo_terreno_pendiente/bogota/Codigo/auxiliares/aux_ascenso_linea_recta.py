"""

Ascenso acumulado por kilometro en linea recta entre el origen y el destino de
cada viaje de la muestra del ruteo, para clasificar los viajes por terreno sin depender de la ruta elegida.

Metodo:
  - Los pares vienen de D4_muestra_pares_od.csv. El identificador de cada esquina es su coordenada EPSG:9377 dividida por 2 y
    redondeada (x/2_y/2), se reconstruye multiplicando por 2 (error de hasta 1 m, despreciable frente al paso de 50 m).
  - Se traza la linea recta de origen a destino y se divide en n tramos iguales, n = techo(L / 50), de modo que el paso es de 50 m o algo menos.
    La altura de cada punto se consulta en el MDT 2020 punto por punto, con la misma consulta del programa principal.
  - Un solo sentido, de origen a destino, ascenso = suma de las subidas entre puntos consecutivos y descenso = suma de las bajadas.
    ascenso_por_km = ascenso / distancia en linea recta (m/km).
  - Se incluyen todos los viajes, tambien los que el ruteo excluye.
  - Piso de ruido: ascenso por km que produciria solo el error del MDT en un terreno perfectamente plano. Con errores normales de desviacion sigma_z y
    correlacion exponencial de ancho A, la diferencia entre dos puntos separados p metros tiene desviacion d = sigma_z * raiz(2 (1 - exp(-p/A))),
    y la subida media por tramo es d / raiz(2 pi). Por kilometro:
    piso = (1000 / p) * d / raiz(2 pi). Se escribe para cada viaje con su paso real y para el paso nominal de 50 m, y se comprueba por simulacion.

En lotes de 100 puntos consecutivos de una misma linea con la consulta multipunto, que da los mismos valores que la consulta punto por punto. 
Su defecto conocido es que, si un punto del lote no tiene dato, se pierden los siguientes, por eso un lote solo se acepta si devuelve un valor por punto, y si no se consulta punto por punto.
Dos hilos en paralelo, con cache que permite retomar si se corta. Los puntos sin dato del MDT se registran, el ascenso usa solo pares consecutivos con dato
y el viaje queda marcado como incompleto.

Uso:   aux_ascenso_linea_recta.py [--paso 50] [--hilos 2] [--lote 100] [--estimar] [--probar]
       --estimar solo cuenta los puntos, sin consultar.
       --probar consulta un lote y compara 10 de sus puntos con la consulta punto por punto.
Entra: D4_muestra_pares_od.csv
Sale:  ascenso_linea_recta_bogota.csv (un viaje por fila; columna par)
       ascenso_linea_recta_bogota_resumen.csv (piso de ruido y distribucion)
       ascenso_cache_mdt2020.csv (cache de alturas)
"""
import argparse
import hashlib
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

from _comun import C, CARPETA_AUX

ENTRADA = C.CARPETA_ENTRADAS / "D4_muestra_pares_od.csv"
SALIDA = CARPETA_AUX / "ascenso_linea_recta_bogota.csv"
RESUMEN = CARPETA_AUX / "ascenso_linea_recta_bogota_resumen.csv"
CACHE = CARPETA_AUX / "ascenso_cache_mdt2020.csv"
SIGMA = C.SIGMA_Z_ADOPTADO_M
ANCHO = C.ANCHO_CORRELACION_ADOPTADO_M
DEC = C.DECIMALES_CLAVE_CACHE

_local = threading.local()


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def piso_ruido(paso_m):
    """Ascenso por km (m/km) que produce solo el error del MDT con ese paso."""
    d = SIGMA * math.sqrt(2 * (1 - math.exp(-paso_m / ANCHO)))
    return (1000 / paso_m) * d / math.sqrt(2 * math.pi)


def piso_simulado(paso_m, km=20, repeticiones=200, semilla=42):
    """Comprobacion por simulacion: ruido normal con correlacion exponencial (proceso AR(1))."""
    rng = np.random.default_rng(semilla)
    n = int(km * 1000 / paso_m) + 1
    phi = math.exp(-paso_m / ANCHO)
    resultados = []
    for _ in range(repeticiones):
        e = np.empty(n)
        e[0] = rng.normal(0, SIGMA)
        ruido = rng.normal(0, SIGMA * math.sqrt(1 - phi ** 2), n)
        for i in range(1, n):
            e[i] = phi * e[i - 1] + ruido[i]
        dif = np.diff(e)
        resultados.append(dif[dif > 0].sum() / km)
    return float(np.mean(resultados))


def pedir(lon, lat):
    if not hasattr(_local, "sesion"):
        _local.sesion = requests.Session()
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": "4326",
              "layers": "all", "tolerance": 1,
              "mapExtent": f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001}",
              "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"}
    for intento in range(1, C.MDT_REINTENTOS + 2):
        try:
            r = _local.sesion.get(C.MDT_URL, params=params, timeout=C.MDT_TIEMPO_ESPERA_S)
            r.raise_for_status()
            res = r.json().get("results", [])
            if not res:
                return np.nan
            v = res[0].get("attributes", {}).get(C.MDT_CAMPO_VALOR)
            return np.nan if v in (None, "NoData", "") else float(v)
        except Exception:
            time.sleep(1.0 * intento)
    raise RuntimeError(f"El servicio del MDT no respondio para ({lon}, {lat}); la cache conserva lo avanzado.")


def pedir_lote(lote):
    """Consulta multipunto (la de la primera version de la etapa). Devuelve la lista de alturas solo si el
    servicio respondio un resultado por punto; si falta alguno (defecto documentado en
    aux_alineacion_consulta.py: tras un punto sin dato se pierden los siguientes) devuelve None y el lote se
    consulta punto por punto."""
    if not hasattr(_local, "sesion"):
        _local.sesion = requests.Session()
    lons, lats = [p[0] for p in lote], [p[1] for p in lote]
    params = {"geometry": json.dumps({"points": [list(p) for p in lote], "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryMultipoint", "sr": "4326", "layers": "all", "tolerance": 1,
              "mapExtent": f"{min(lons) - 0.001},{min(lats) - 0.001},{max(lons) + 0.001},{max(lats) + 0.001}",
              "imageDisplay": "800,800,96", "returnGeometry": "false", "f": "json"}
    for intento in range(1, C.MDT_REINTENTOS + 2):
        try:
            r = _local.sesion.get(C.MDT_URL, params=params, timeout=60)
            r.raise_for_status()
            res = r.json().get("results", [])
            break
        except Exception:
            time.sleep(2.0 * intento)
    else:
        return None
    if len(res) != len(lote):
        return None
    vals = []
    for x in res:
        v = x.get("attributes", {}).get(C.MDT_CAMPO_VALOR)
        if v in (None, "NoData", ""):
            return None
        vals.append(float(v))
    return vals


def consultar(lote):
    vals = pedir_lote(lote)
    if vals is not None:
        return list(zip(lote, vals)), False
    return [(k, pedir(*k)) for k in lote], True


def guardar_cache(valores):
    filas = [(k[0], k[1], v) for k, v in valores.items()]
    pd.DataFrame(filas, columns=["lon", "lat", "elevacion_m"]).to_csv(CACHE, index=False, float_format="%.17g")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paso", type=float, default=50.0)
    ap.add_argument("--hilos", type=int, default=2)
    ap.add_argument("--lote", type=int, default=100)
    ap.add_argument("--estimar", action="store_true")
    ap.add_argument("--probar", action="store_true")
    args = ap.parse_args()

    if not ENTRADA.exists():
        sys.exit(f"Falta {ENTRADA.name} en datos_entrada (lo entrega el modulo del grafo).")
    pares = pd.read_csv(ENTRADA, dtype={"origen": str, "destino": str})
    print(f"Pares: {len(pares):,}  (SHA256 de la entrada {sha256(ENTRADA)})")

    def xy(serie):
        p = serie.str.split("_", expand=True).astype(float) * 2
        return p[0].to_numpy(), p[1].to_numpy()

    xo, yo = xy(pares["origen"])
    xd, yd = xy(pares["destino"])
    recta = np.hypot(xd - xo, yd - yo)
    dif_recta = np.abs(recta - pares["recta_m"].to_numpy())
    print(f"Distancia reconstruida frente a recta_m del archivo: diferencia maxima {dif_recta.max():.2f} m")
    a_wgs = Transformer.from_crs("EPSG:9377", "EPSG:4326", always_xy=True)

    perfiles = []
    orden = {}
    for i in range(len(pares)):
        n = max(1, math.ceil(recta[i] / args.paso))
        t = np.linspace(0, 1, n + 1)
        lon, lat = a_wgs.transform(xo[i] + t * (xd[i] - xo[i]), yo[i] + t * (yd[i] - yo[i]))
        claves = [(round(float(a), DEC), round(float(b), DEC)) for a, b in zip(lon, lat)]
        perfiles.append((n, recta[i] / n, claves))
        for k in claves:
            orden.setdefault(k, None)
    todos = list(orden)  # en el orden de las lineas: cada lote queda en un tramo corto de una misma linea
    print(f"Puntos a lo largo de las lineas: {sum(len(p[2]) for p in perfiles):,}; distintos: {len(todos):,}")

    valores = {}
    if CACHE.exists():
        ck = pd.read_csv(CACHE, float_precision="round_trip")
        valores = dict(zip(zip(ck["lon"].round(DEC), ck["lat"].round(DEC)), ck["elevacion_m"]))
    faltan = [k for k in todos if k not in valores]
    print(f"Ya en cache: {len(todos) - len(faltan):,}; por consultar: {len(faltan):,}")
    if args.estimar:
        return

    if args.probar:
        lote = faltan[:args.lote]
        t0 = time.time()
        vals = pedir_lote(lote)
        t1 = time.time()
        if vals is None:
            sys.exit(f"Prueba: la consulta por lote no devolvio un resultado por punto ({t1 - t0:.1f} s).")
        control = list(range(0, len(lote), max(1, len(lote) // 10)))
        dif = [abs(vals[j] - pedir(*lote[j])) for j in control]
        print(f"Prueba: lote de {len(lote)} puntos en {t1 - t0:.1f} s; "
              f"{len(control)} puntos comprobados uno por uno, diferencia maxima {max(dif):.3f} m")
        return

    if faltan:
        inicio = time.time()
        ultimo_guardado = time.time()
        lotes = [faltan[j:j + args.lote] for j in range(0, len(faltan), args.lote)]
        hechos = 0
        respaldo = 0
        print(f"Consultando {len(lotes):,} lotes de {args.lote} puntos con {args.hilos} hilos...", flush=True)
        with ThreadPoolExecutor(max_workers=args.hilos) as ex:
            for g0 in range(0, len(lotes), args.hilos * 5):
                grupo = lotes[g0:g0 + args.hilos * 5]
                for pares_kz, fue_respaldo in ex.map(consultar, grupo):
                    valores.update(pares_kz)
                    hechos += len(pares_kz)
                    respaldo += fue_respaldo
                vel = hechos / (time.time() - inicio)
                resta_h = (len(faltan) - hechos) / vel / 3600
                print(f"  {hechos:,}/{len(faltan):,}  ({vel:.0f} puntos/s; faltan unas {resta_h:.1f} h; "
                      f"lotes consultados punto por punto: {respaldo})", flush=True)
                if time.time() - ultimo_guardado > 120:
                    guardar_cache(valores)
                    ultimo_guardado = time.time()
        guardar_cache(valores)
        print(f"Lotes consultados punto por punto por el defecto de la consulta multipunto: {respaldo} de {len(lotes):,}")

    filas = []
    for i, (n, paso, claves) in enumerate(perfiles):
        z = np.array([valores[k] for k in claves], dtype=float)
        dz = np.diff(z)
        validos = ~np.isnan(dz)
        sube = dz[validos & (dz > 0)].sum()
        baja = abs(dz[validos & (dz < 0)].sum())
        km = recta[i] / 1000
        filas.append({"par": pares.at[i, "par"], "recta_km": km, "paso_m": paso, "n_puntos": n + 1,
                      "puntos_sin_dato": int(np.isnan(z).sum()), "completo": bool(validos.all()),
                      "ascenso_m": sube, "descenso_m": baja, "ascenso_por_km": sube / km if km > 0 else np.nan,
                      "piso_ruido_m_por_km": piso_ruido(paso)})
    out = pd.DataFrame(filas)
    out["sobre_piso_ruido"] = out["ascenso_por_km"] > out["piso_ruido_m_por_km"]
    out.to_csv(SALIDA, index=False, encoding="utf-8-sig")

    p50, sim50 = piso_ruido(50.0), piso_simulado(50.0)
    q = out["ascenso_por_km"].quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    res = [("piso de ruido a 50 m, formula (m/km)", p50), ("piso de ruido a 50 m, simulacion (m/km)", sim50),
           ("viajes", len(out)), ("viajes incompletos (algun punto sin dato)", int((~out["completo"]).sum())),
           ("viajes con ascenso por km bajo su piso de ruido", int((~out["sobre_piso_ruido"]).sum()))]
    res += [(f"ascenso por km, percentil {int(k * 100)} (m/km)", v) for k, v in q.items()]
    resumen = pd.DataFrame(res, columns=["medida", "valor"])
    resumen.to_csv(RESUMEN, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    print("\n" + resumen.round(2).to_string(index=False))
    if "terreno" in pares.columns:
        tabla = out.assign(terreno=pares["terreno"]).groupby("terreno")["ascenso_por_km"].describe(
            percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
        print("\nAscenso por km segun el terreno de la muestra (solo para describir la distribucion):")
        print(tabla.round(1).to_string())
    print(f"\nGuardado: {SALIDA.name}  SHA256 {sha256(SALIDA)}")
    print(f"Guardado: {RESUMEN.name}  SHA256 {sha256(RESUMEN)}")


if __name__ == "__main__":
    main()
