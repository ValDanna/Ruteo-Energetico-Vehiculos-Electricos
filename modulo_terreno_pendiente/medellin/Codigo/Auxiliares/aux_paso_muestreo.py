"""
Efecto del paso de 50 m en los tramos planos sobre la pendiente acumulada.

Que hace: Primero cuenta en el archivo de pendientes los tramos que quedaron con
2 puntos y separa la causa: planos con paso de 50 m y menos de 100 m, o con
pendiente y paso de 10 m pero de 20 m o menos. Luego toma los tramos planos
(|neta| < 3 %) dentro del recorte del Olaya Herrera, un tramo fisico por calle,
sin tuneles ni elevados, y los vuelve a muestrear con 10 m usando el mismo
procedimiento del programa principal (puntos sobre la geometria en EPSG:9377,
reproyectados a EPSG:6257, pixel mas cercano). Compara la acumulada con 10 m
contra la de 50 m y contra el ruido esperado de la acumulada con paso de 10 m.
La neta no cambia porque sale de las esquinas. Esto no modifica el archivo oficial.

Lee:      el archivo de pendientes, el gpkg y el recorte del Olaya Herrera, cortado del MDT.
Escribe:  aux_paso_muestreo.csv (un tramo por fila) y recorte_mdt_olaya.tif.

Resultado v3: 13.430 tramos que no son tunel tienen 2 puntos; 11.645 son planos con paso de 50 m y 1.785
tienen pendiente pero miden 20 m o menos. En el Olaya, 1.522 tramos planos: la
acumulada con 10 m cambia 0,05 pp en mediana y 0,57 pp en el percentil 90; el
3,2 % cambia mas de 1 pp, 7 mas de 5 pp (tramos de 28 a 42 m) y ninguno pasa de
35 %. El ruido esperado con paso de 10 m es 2,40 pp con sigma_z 0,539 (0,44 pp con 0,10), la mediana y el percentil 90 de la diferencia quedan por debajo del ruido
"""
import sys

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos, recorte_olaya


def acumulada(geom, longitud, paso, z, inversa, a_mdt):
    """Calcula la pendiente acumulada de un tramo mediante un muestreo a paso fijo."""    
    # Genera puntos a lo largo de la geometría y consulta la elevación del MDT en cada uno para cuantificar las variaciones de altura entre puntos consecutivos.
    # mismo muestreo del programa principal, con un paso fijo
    n = max(2, int(longitud / paso) + 1)
    zs = []
    for f in np.linspace(0, 1, n):
        p = geom.interpolate(f, normalized=True)
        c, r = inversa * a_mdt.transform(p.x, p.y)
        zs.append(z[int(np.floor(r)), int(np.floor(c))])
    return 100 * np.abs(np.diff(zs)).sum() / longitud, n


def main():
    # Carga los resultados de pendientes
    df = leer_pendientes(sys.argv[1] if len(sys.argv) > 1 else None)
    # Identifica los tramos con cobertura del MDT y distingue los que fueron muestreados con dos puntos, separando los planos de los que presentan pendiente
    con_dato = df[~df["fuera_cobertura_mdt"]]
    plano = con_dato["pendiente_neta_pct"].abs() < C.UMBRAL_PLANO_PCT
    dos = (con_dato["n_puntos_muestreados"] == 2) & ~con_dato["es_tunel"]
    print(f"Tramos con 2 puntos (sin tuneles): {int(dos.sum()):,}; planos con paso de 50 m: "
          f"{int((dos & plano).sum()):,}; con pendiente y 20 m o menos: {int((dos & ~plano).sum()):,}")
    # Recupera el recorte del MDT y prepara las transformaciones de coordenadas necesarias para consultar las elevaciones a partir de las geometrías
    z, transformacion, b, sha = recorte_olaya()
    inversa = ~transformacion
    a_mdt = Transformer.from_crs(C.CRS_RED, C.CRS_MDT, always_xy=True)
    # Selecciona los tramos situados dentro de la zona de análisis y excluye los que no tienen cobertura, son túneles, son elevados o no son planos
    g = leer_segmentos().merge(df, on="segmento_id")
    # seleccion en el CRS del MDT; el muestreo usa la geometria original
    g = g[g.to_crs(C.CRS_MDT).within(box(b.left + 1, b.bottom + 1, b.right - 1, b.top - 1)).values]
    g = g[~g["fuera_cobertura_mdt"] & ~g["es_tunel"] & (g["es_elevado"] == False)]
    g = g[g["pendiente_neta_pct"].abs() < C.UMBRAL_PLANO_PCT]
    # Agrupa las representaciones del mismo tramo base y conserva una sola para evitar duplicar el análisis por sentido
    g = g.assign(base=g["segmento_id"].str.rsplit("_", n=1).str[0]).sort_values("segmento_id")
    g = g.drop_duplicates("base")
    # Calcula la pendiente acumulada de cada tramo con dos resoluciones de muestreo, de modo que se pueda evaluar cómo influye el paso entre puntos
    filas = []
    for _, s in g.iterrows():
        a10, n10 = acumulada(s.geometry, s["longitud_m"], C.PASO_PENDIENTE_M, z, inversa, a_mdt)
        a50, n50 = acumulada(s.geometry, s["longitud_m"], C.PASO_PLANO_M, z, inversa, a_mdt)
        filas.append({"segmento_id": s["segmento_id"], "longitud_m": s["longitud_m"],
                      "pendiente_neta_pct": s["pendiente_neta_pct"], "n_puntos_50m": n50,
                      "n_puntos_10m": n10, "acumulada_50m_pct": a50, "acumulada_10m_pct": a10,
                      "diferencia_pp": a10 - a50})
    # Exporta los resultados por tramo    
    t = pd.DataFrame(filas)
    t.to_csv(carpeta_salida() / "aux_paso_muestreo.csv", index=False, encoding="utf-8-sig")
    # Estima el ruido esperado en la pendiente acumulada a partir de la incertidumbre vertical del MDT y de la correlación espacial
    p = C.PASO_PENDIENTE_M
    sd = C.SIGMA_Z_M * np.sqrt(2 * (1 - np.exp(-p / C.ANCHO_CORRELACION_M)))
    ruido = 100 * np.sqrt(2 / np.pi) * sd / p
    # Resume las diferencias entre los dos pasos de muestreo y cuenta los casos que superan determinados umbrales de diferencia o pendiente acumulada    
    d = t["diferencia_pp"]
    print(f"Recorte SHA {sha[:12]}...; tramos planos en el Olaya: {len(t):,}")
    print(f"Diferencia (10 m - 50 m): mediana {d.median():.2f} pp, percentil 90 {d.quantile(0.9):.2f} pp, "
          f"maxima {d.max():.2f} pp")
    print(f"Mas de 1 pp: {100 * (d > 1).mean():.1f} %; mas de 5 pp: {int((d > 5).sum())}; "
          f"acumulada con 10 m sobre {C.UMBRAL_PENDIENTE_EXTREMA_PCT:.0f} %: "
          f"{int((t['acumulada_10m_pct'] > C.UMBRAL_PENDIENTE_EXTREMA_PCT).sum())}")
    print(f"Ruido esperado de la acumulada con paso de {p:.0f} m: {ruido:.2f} pp")


if __name__ == "__main__":
    main()
