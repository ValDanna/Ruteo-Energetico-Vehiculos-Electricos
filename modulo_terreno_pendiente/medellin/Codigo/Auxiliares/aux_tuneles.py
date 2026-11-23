"""
Tramos marcados con es_tunel y su pendiente de boca a boca.

Que hace: cruza el archivo de pendientes con el gpkg y lista cada fila con
es_tunel = True: nombre, motivo de la marca (nombre o hueco de la cadena),
longitud, alturas de las bocas, neta, ganancia y si sigue como pendiente extrema.

Lee:      el archivo de pendientes  y el gpkg.
Escribe:  aux_tuneles.csv

Resultado: 30 filas con es_tunel; 28 pornombre y 2 (MED_138412 FT y TF) sin nombre que cierran la cadena del Tunel de
Oriente. Tunel de Occidente (MED_132113): 2,26 %, 105,1 m de ganancia en el sentido de subida. Siguen raros: MED_138418_0_FT 42,47 % (pendiente_extrema,
una boca parece caer en puente o rampa) y MED_138419_0_FT 27,0 %, quedan marcadas las rampas de Las Palmas con la Calle 19 y
las "Via al Tunel" rurales.
"""
import sys

import pandas as pd

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos


def main():
    # Carga el archivo de pendientes
    df = leer_pendientes(sys.argv[1] if len(sys.argv) > 1 else None)

    # Los atributos principales de los segmentos viales para cruzarlos con los registros que el análisis identifica como túneles.
    g = leer_segmentos(geometria=False)[["segmento_id", "nombre", "jerarquia", "longitud_m", "es_elevado"]]
    t = df[df["es_tunel"]].merge(g, on="segmento_id", how="left")

    # Identifica cuáles segmentos tienen un nombre que coincide con el patrón configurado para túneles. Los que no coinciden se clasifican como casos en los que el túnel se identifica porque cierra la cadena.
    por_nombre = t["nombre"].fillna("").str.contains(C.PATRON_TUNEL, case=False, regex=True)
    t["motivo"] = por_nombre.map({True: "nombre", False: "cierra la cadena"})

    # Selecciona los campos relevantes para revisar los túneles, incluyendo sus elevaciones, pendientes, muestreo y clasificación de pendiente extrema.
    cols = ["segmento_id", "nombre", "motivo", "longitud_m", "z_inicio_m", "z_fin_m", "pendiente_neta_pct",
            "pendiente_acumulada_pct", "ganancia_elevacion_m", "n_puntos_muestreados", "es_elevado",
            "pendiente_extrema"]

    t[cols].to_csv(carpeta_salida() / "aux_tuneles.csv", index=False, encoding="utf-8-sig")
    print(f"Filas con es_tunel: {len(t)} ({int(por_nombre.sum())} por nombre, {int((~por_nombre).sum())} "
          f"que cierran la cadena)")
    print(t[cols].round(2).to_string(index=False))

    # Cuáles de los túneles identificados siguen marcados como segmentos con pendiente extrema en el archivo de pendientes.
    print("Siguen con pendiente_extrema:", t.loc[t["pendiente_extrema"] == True, "segmento_id"].tolist())

if __name__ == "__main__":
    main()
