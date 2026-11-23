"""
Ascenso acumulado por kilometro en linea recta entre el origen y el destino de
cada viaje de la muestra del ruteo de Medellin, para estratificar los viajes por
terreno sin depender de la ruta elegida. 

Metodo:
  - Los pares vienen de D4M_muestra_pares_od.csv (modulo del grafo, SHA
    95a6116e...), el id de cada esquina no es su coordenada (MED_N005838); la coordenada EPSG:9377 se toma de nodos_medellin.csv
    (D2 Medellin), cuyo SHA se comprueba contra D2M_huellas_salidas.json. La distancia reconstruida se compara con recta_m del archivo.
  - Se traza la linea recta de origen a destino y se divide en n tramos iguales, n = techo(L / 50), de modo que el paso es de 50 m o algo menos.
    Cada punto se reproyecta de 9377 a 6257 y su altura es el valor del pixel del DTM-LiDAR 2021 donde cae, sin interpolar (la misma consulta del programa
    principal: raster.index y fuera de la grilla o nodata = sin dato).
  - Un solo sentido, de origen a destino: ascenso = suma de las subidas entre puntos consecutivos, descenso = suma de las bajadas; solo pares consecutivos
    con dato. ascenso_por_km = ascenso / distancia en linea recta (m/km).
  - Se incluyen todos los viajes, tambien los que el ruteo excluye.
  - Piso de ruido: ascenso por km que produciria solo el error del MDT en un terreno plano. Con errores normales de desviacion sigma_z y
    correlacion exponencial de ancho A, la diferencia entre dos puntos separados p metros tiene desviacion d = sigma_z * raiz(2 (1 - exp(-p/A))),
    y la subida media por tramo es d / raiz(2 pi). Por kilometro: piso = (1000 / p) * d / raiz(2 pi). Se reporta para cada viaje con su paso
    real y para el paso nominal de 50 m, y se comprueba por simulacion, sigma_z y A son los de la configuracion (0,539 m y 59,2 m, rama med_sigma054).
  - Regla de incompletos: Sale el viaje si puntos_sin_dato / n_puntos > 0,10.

Como se corre: aux_ascenso_linea_recta_medellin.py
Lee:      D4M_muestra_pares_od.csv, nodos_medellin.csv,
          D2M_huellas_salidas.json y el MDT.
Escribe:  ascenso_linea_recta_medellin.csv (un viaje por fila; columna par)
          ascenso_linea_recta_medellin_resumen.csv (piso de ruido y distribucion)

Resultado (sigma_z 0,539 m, ancho 59,2 m): 4.200 viajes, 506.086 puntos.
Distancia reconstruida frente a recta_m: 5,0e-07 m. Altura del MDT frente a z_origen_m y
z_destino_m de la muestra: mediana 0,000 m (maximo 0,62 y 0,22 m). Piso de ruido a 50 m:
4,59 m/km (formula) y 4,60 (simulacion). 5 viajes incompletos, 3 salen por la regla del
10 %; 292 bajo su piso de ruido. Ascenso por km de la muestra (sin ponderar), percentiles
5/10/25/50/75/90/95: 2,87 / 6,92 / 18,23 / 37,71 / 67,63 / 103,45 / 132,90 m/km.
Mediana por terreno: plano 20,4; cruzado 43,6; ladera 60,0 m/km. ascenso_linea_recta_medellin.csv.
"""
import json
import math
import sys

import numpy as np
import pandas as pd
from pyproj import Transformer

from _comun import C, carpeta_salida, sha256_archivo

MUESTRA = C.CARPETA_RESPALDO / "D4M_muestra_pares_od.csv"
SHA256_MUESTRA = "95a6116e6b440570b6b008dbbc7b48be946554c223a00418bb0dde790f4aa0b1"
NODOS = C.CARPETA_ENTRADAS / "nodos_medellin.csv"
PASO_M = 50.0
MAX_FRACCION_SIN_DATO = 0.10
FILAS_POR_FRANJA = 1024
SIGMA = C.SIGMA_Z_M
ANCHO = C.ANCHO_CORRELACION_M


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


def alturas_mdt(x6257, y6257):
    """Valor del pixel donde cae cada punto (sin interpolar), igual que consultar_elevacion
    del programa principal: fuera de la grilla o nodata = NaN. Lee el raster por franjas
    de filas para no cargarlo entero."""
    import rasterio
    from rasterio.transform import rowcol
    z = np.full(len(x6257), np.nan)
    with rasterio.open(C.ARCHIVO_MDT) as r:
        # rowcol es la funcion que usa raster.index por dentro, aplicada a todos los puntos a la vez
        filas, cols = rowcol(r.transform, x6257, y6257)
        filas, cols = np.asarray(filas), np.asarray(cols)
        dentro = (filas >= 0) & (cols >= 0) & (filas < r.height) & (cols < r.width)
        idx = np.flatnonzero(dentro)
        idx = idx[np.argsort(filas[idx], kind="stable")]
        franja = filas[idx] // FILAS_POR_FRANJA
        for f in np.unique(franja):
            sel = idx[franja == f]
            f0, f1 = filas[sel].min(), filas[sel].max() + 1
            c0, c1 = cols[sel].min(), cols[sel].max() + 1
            bloque = r.read(1, window=((f0, f1), (c0, c1)))
            v = bloque[filas[sel] - f0, cols[sel] - c0].astype(float)
            if r.nodata is not None:
                v[bloque[filas[sel] - f0, cols[sel] - c0] == r.nodata] = np.nan
            z[sel] = v
    return z


def main():
    for ruta in (MUESTRA, NODOS, C.ARCHIVO_HUELLAS_ENTRADA, C.ARCHIVO_MDT):
        if not ruta.exists():
            sys.exit(f"Falta {ruta.name} en {ruta.parent}")
    sha_muestra = sha256_archivo(MUESTRA)
    if sha_muestra != SHA256_MUESTRA:
        sys.exit(f"La muestra no es la de la corrida oficial: SHA {sha_muestra}")
    huellas = json.loads(C.ARCHIVO_HUELLAS_ENTRADA.read_text(encoding="utf-8"))
    sha_nodos = sha256_archivo(NODOS)
    if sha_nodos != huellas["sha256_archivos"].get("nodos_medellin.csv"):
        sys.exit(f"nodos_medellin.csv (SHA {sha_nodos}) no es el registrado en D2M_huellas_salidas.json")
    print(f"Muestra verificada: {sha_muestra}\nNodos verificados: {sha_nodos}")

    pares = pd.read_csv(MUESTRA, dtype={"origen": str, "destino": str})
    if len(pares) != 4200 or not pares["par"].is_unique:
        sys.exit(f"Se esperaban 4.200 pares sin repetidos; hay {len(pares):,} y repetidos: {not pares['par'].is_unique}")
    nodos = pd.read_csv(NODOS, dtype={"node_id": str}).set_index("node_id")
    faltan = set(pares["origen"]).union(pares["destino"]) - set(nodos.index)
    if faltan:
        sys.exit(f"{len(faltan)} esquinas de la muestra no estan en nodos_medellin.csv, por ejemplo {sorted(faltan)[:3]}")
    xo, yo = nodos.loc[pares["origen"], "x"].to_numpy(), nodos.loc[pares["origen"], "y"].to_numpy()
    xd, yd = nodos.loc[pares["destino"], "x"].to_numpy(), nodos.loc[pares["destino"], "y"].to_numpy()
    recta = np.hypot(xd - xo, yd - yo)
    dif_recta = np.abs(recta - pares["recta_m"].to_numpy())
    print(f"Pares: {len(pares):,}. Distancia reconstruida frente a recta_m: diferencia maxima {dif_recta.max():.2e} m")
    if dif_recta.max() > 1.0:
        sys.exit("La distancia reconstruida no coincide con recta_m: revisar las coordenadas de los nodos.")

    a_mdt = Transformer.from_crs(C.CRS_RED, C.CRS_MDT, always_xy=True)
    perfiles, xs, ys = [], [], []
    inicio = 0
    for i in range(len(pares)):
        n = max(1, math.ceil(recta[i] / PASO_M))
        t = np.linspace(0, 1, n + 1)
        perfiles.append((n, recta[i] / n, inicio))
        inicio += n + 1
        xs.append(xo[i] + t * (xd[i] - xo[i]))
        ys.append(yo[i] + t * (yd[i] - yo[i]))
    x6257, y6257 = a_mdt.transform(np.concatenate(xs), np.concatenate(ys))
    print(f"Puntos a lo largo de las lineas: {len(x6257):,}. Leyendo el MDT...", flush=True)
    z_todos = alturas_mdt(np.asarray(x6257), np.asarray(y6257))

    filas = []
    for i, (n, paso, inicio) in enumerate(perfiles):
        z = z_todos[inicio:inicio + n + 1]
        dz = np.diff(z)
        validos = ~np.isnan(dz)
        sube = dz[validos & (dz > 0)].sum()
        baja = abs(dz[validos & (dz < 0)].sum())
        km = recta[i] / 1000
        filas.append({"par": pares.at[i, "par"], "recta_km": km, "paso_m": paso, "n_puntos": n + 1,
                      "puntos_sin_dato": int(np.isnan(z).sum()), "completo": bool(validos.all()),
                      "ascenso_m": sube, "descenso_m": baja, "ascenso_por_km": sube / km if km > 0 else np.nan,
                      "piso_ruido_m_por_km": piso_ruido(paso), "_z0": z[0], "_z1": z[-1]})
    out = pd.DataFrame(filas)
    out["sobre_piso_ruido"] = out["ascenso_por_km"] > out["piso_ruido_m_por_km"]

    # Comprobaciones
    comp = out[out["completo"]]
    cierre = (comp["ascenso_m"] - comp["descenso_m"] - (comp["_z1"] - comp["_z0"])).abs()
    if len(comp) and cierre.max() > 1e-6:
        sys.exit(f"Ascenso - descenso no es igual al desnivel en los viajes completos (max {cierre.max():.2e} m)")
    print(f"Comprobacion: ascenso - descenso = z destino - z origen en {len(comp):,} viajes completos "
          f"(diferencia maxima {cierre.max() if len(comp) else 0:.1e} m)")
    for col_m, col_z in [("z_origen_m", "_z0"), ("z_destino_m", "_z1")]:
        if col_m in pares.columns:
            d = (out[col_z] - pares[col_m]).abs()
            print(f"Informativo: altura del MDT frente a {col_m} de la muestra: diferencia maxima {d.max():.3f} m, "
                  f"mediana {d.median():.3f} m ({int(d.isna().sum())} sin dato)")

    columnas = ["par", "recta_km", "paso_m", "n_puntos", "puntos_sin_dato", "completo", "ascenso_m",
                "descenso_m", "ascenso_por_km", "piso_ruido_m_por_km", "sobre_piso_ruido"]
    salida = carpeta_salida()
    ruta_out = salida / "ascenso_linea_recta_medellin.csv"
    ruta_res = salida / "ascenso_linea_recta_medellin_resumen.csv"
    out[columnas].to_csv(ruta_out, index=False, encoding="utf-8-sig")

    sale = out["puntos_sin_dato"] / out["n_puntos"] > MAX_FRACCION_SIN_DATO
    p50, sim50 = piso_ruido(PASO_M), piso_simulado(PASO_M)
    q = out["ascenso_por_km"].quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    res = [("piso de ruido a 50 m, formula (m/km)", p50), ("piso de ruido a 50 m, simulacion (m/km)", sim50),
           ("viajes", len(out)), ("viajes incompletos (algun punto sin dato)", int((~out["completo"]).sum())),
           ("viajes con ascenso por km bajo su piso de ruido", int((~out["sobre_piso_ruido"]).sum())),
           ("viajes que salen por la regla de incompletos (mas de 10 % de puntos sin dato)", int(sale.sum()))]
    res += [(f"ascenso por km, percentil {int(round(k * 100))} (m/km)", v) for k, v in q.items()]
    resumen = pd.DataFrame(res, columns=["medida", "valor"])
    resumen.to_csv(ruta_res, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    print(f"\nsigma_z {SIGMA} m, ancho {ANCHO} m")
    print(resumen.round(2).to_string(index=False))
    print("\nAscenso por km segun el terreno de la muestra (solo para describir la distribucion):")
    tabla = out.assign(terreno=pares["terreno"]).groupby("terreno", sort=False)["ascenso_por_km"].describe(
        percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])[["count", "10%", "25%", "50%", "75%", "90%"]]
    print(tabla.round(1).to_string())
    quedan = out.loc[~sale, "ascenso_por_km"]
    rangos = pd.cut(quedan, [-np.inf, 10, 40, np.inf], right=False, labels=["menor de 10", "de 10 a 40", "mayor de 40"])
    print(f"\nSin los {int(sale.sum())} viajes que salen por la regla de incompletos ({len(quedan):,} viajes), "
          f"ascenso por km (solo distribucion, cortes no fijados):")
    print(rangos.value_counts(sort=False).to_string())
    print(f"\nGuardado: {ruta_out.name}  SHA256 {sha256_archivo(ruta_out)}")
    print(f"Guardado: {ruta_res.name}  SHA256 {sha256_archivo(ruta_res)}")


if __name__ == "__main__":
    main()
