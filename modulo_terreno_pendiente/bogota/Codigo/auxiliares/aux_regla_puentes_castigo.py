"""


Regla: una arista marcada como pendiente extrema se castiga en el ruteo; si es
puente o tunel, solo se castiga cuando la pendiente NETA supera 35 %, porque en
esas estructuras el modelo de terreno mide el terreno de abajo o la montaña y
la acumulada no representa la via.

Este script cuenta que filas extremas dejarian de castigarse en Bogota con esa
regla, usando como puente o tunel la marca de OpenStreetMap de
aux_puentes_tuneles_osm.py (8 m, la misma del documento).

Entrada: archivo final de pendientes y puentes_tuneles_segmentos.csv
Uso: aux_regla_puentes_castigo.py
Sale: regla_puentes_castigo.csv (filas extremas sobre puente o tunel)
"""
import pandas as pd

from _comun import C, CARPETA_AUX

UMBRAL = C.UMBRAL_PENDIENTE_EXTREMA_PCT


def es_verdadero(serie):
    return serie.astype(str).str.lower().eq("true")


def main():
    df = pd.read_csv(C.ARCHIVO_PENDIENTES, dtype={"segmento_id": str})
    pt = pd.read_csv(CARPETA_AUX / "puentes_tuneles_segmentos.csv", dtype={"segmento_id": str},
                     encoding="utf-8-sig", usecols=["segmento_id", "puente_osm", "tunel_osm"])
    df = df.merge(pt, on="segmento_id", how="left")
    df["puente_osm"] = es_verdadero(df["puente_osm"])
    df["tunel_osm"] = es_verdadero(df["tunel_osm"])
    df["estructura"] = df["puente_osm"] | df["tunel_osm"]

    ext = df[es_verdadero(df["pendiente_extrema"])].copy()
    ext["neta_abs"] = ext["pendiente_neta_pct"].abs()
    ext["tramo_fisico"] = ext["segmento_id"].str.rsplit("_", n=1).str[0]
    ext["castigada_regla_actual"] = True
    ext["castigada_regla_medellin"] = ~ext["estructura"] | (ext["neta_abs"] > UMBRAL)

    salen = ext[~ext["castigada_regla_medellin"]]
    solo_acum = ext[ext["neta_abs"] <= UMBRAL]
    print(f"Filas extremas: {len(ext):,} ({ext['tramo_fisico'].nunique():,} tramos fisicos)")
    print(f"  extremas solo por la acumulada (neta <= {UMBRAL:g} %): {len(solo_acum)} filas")
    print(f"  extremas sobre puente o tunel OSM: {int(ext['estructura'].sum())} filas")
    print(f"Con la regla de Medellin dejan de castigarse: {len(salen)} filas "
          f"({salen['tramo_fisico'].nunique()} tramos fisicos); quedan {int(ext['castigada_regla_medellin'].sum()):,}")
    cols = ["segmento_id", "pendiente_neta_pct", "pendiente_acumulada_pct", "puente_osm", "tunel_osm",
            "castigada_regla_medellin"]
    print("\nFilas extremas sobre puente o tunel:")
    print(ext.loc[ext["estructura"], cols].round(2).to_string(index=False))
    ext.loc[ext["estructura"], cols].to_csv(CARPETA_AUX / "regla_puentes_castigo.csv", index=False,
                                            encoding="utf-8-sig")
    print("\nGuardado: regla_puentes_castigo.csv")


if __name__ == "__main__":
    main()
