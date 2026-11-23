"""
Caracterizacion de los segmentos con pendiente_extrema (> 35 %).

Que hace: Cuenta las filas extremas y los tramos fisicos (FT y TF del mismo
tramo cuentan una vez), las separa por jerarquia, tuneles y tramos elevados y
por bandas de |neta|. La revision en Street View se hace con
aux_revision_street_view.py sobre la lista de 104 calles.

Lee:      el archivo de pendientes (por defecto el de datos_salida) y el gpkg.
Escribe:  datos_salida/auxiliares/aux_pendientes_extremas.csv (todas las filas)

Resultado: 189 filas, 95 tramos fisicos (el Tunel de Occidente ya no es extremo con la pendiente de boca a boca). 185 filas
se disparan por la neta y 4 solo por la acumulada. Longitud mediana 56,6 m y
desnivel mediano 22,1 m: no son tramos cortos ni ruido. De los 95 tramos, 52 no
tienen jerarquia, 2 son elevados y 1 es tunel (MED_138418_0_FT, 42,47 %, que
tambien es elevado). |neta|: 79 entre 35 y 50 %, 12 entre 50 y 67 %, 2 sobre
67 % y 2 por debajo de 35 % (marcados por la acumulada).
"""
import sys

import pandas as pd

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos


def main():
# Carga los resultados de pendientes y los relaciona con la información geográfica y descriptiva de los segmentos viales
    df = leer_pendientes(sys.argv[1] if len(sys.argv) > 1 else None)
    g = leer_segmentos()
    e = g.merge(df, on="segmento_id")
# Filtra los segmentos identificados con pendientes extremas y calcula el valor absoluto de la pendiente neta
    e = e[e["pendiente_extrema"] == True].copy()
    e["base"] = e["segmento_id"].str.rsplit("_", n=1).str[0]
    e["neta_abs"] = e["pendiente_neta_pct"].abs()
# Identifica los tramos físicos únicos, conservando para cada uno la representación con mayor pendiente neta absoluta
    fisicos = e.sort_values("neta_abs", ascending=False).drop_duplicates("base")
    # Presenta un resumen del número de registros y tramos físicos detectados, y distingue los casos que superan el umbral por pendiente neta de aquellos que se clasificaron como extremos sin superar ese umbral
    print(f"Filas con pendiente_extrema: {len(e)}; tramos fisicos: {len(fisicos)}")
    print(f"Disparadas por la neta: {int((e['neta_abs'] > C.UMBRAL_PENDIENTE_EXTREMA_PCT).sum())}; "
          f"solo por la acumulada: {int((e['neta_abs'] <= C.UMBRAL_PENDIENTE_EXTREMA_PCT).sum())}")
    # Características relevantes de los tramos físicos, como la disponibilidad de jerarquía vial y la presencia de estructuras elevadas o túneles    
    print(f"Tramos fisicos sin jerarquia: {int(fisicos['jerarquia'].isna().sum())}; "
          f"elevados: {int(fisicos['es_elevado'].sum())}; tuneles: {int(fisicos['es_tunel'].sum())}")
    print(f"Longitud mediana {e['longitud_m'].median():.1f} m; "
          f"desnivel mediano {(e['z_fin_m'] - e['z_inicio_m']).abs().median():.1f} m")
    print("Rango de |neta| en tramos fisicos:",
          pd.cut(fisicos["neta_abs"], [0, 35, 50, 67, 1000]).value_counts().sort_index().to_dict())
    # Comprueba si un segmento específico aparece entre los registros extremos
    print("Incluye MED_138418_0_FT:", "MED_138418_0_FT" in set(e["segmento_id"]))
    # Exporta el listado detallado de pendientes extremas, ordenado de mayor a menor pendiente neta absoluta
    cols = ["segmento_id", "nombre", "jerarquia", "longitud_m", "pendiente_neta_pct", "pendiente_acumulada_pct",
            "es_elevado", "es_tunel"]
    e.sort_values("neta_abs", ascending=False)[cols].to_csv(carpeta_salida() / "aux_pendientes_extremas.csv",
                                                           index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
