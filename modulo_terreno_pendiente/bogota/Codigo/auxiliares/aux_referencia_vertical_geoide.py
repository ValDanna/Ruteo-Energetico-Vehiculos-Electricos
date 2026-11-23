"""
Referencia vertical del MDT 2020: alturas ortometricas o elipsoidales.

No declara la referencia vertical en ninguna de sus fuentes. Este
script la establece con los datos. Compara el sesgo del MDT frente a los
vertices de nivelacion del IGAC (alturas sobre el nivel del mar) con la
ondulacion del geoide en esos mismos vertices segun GEOCOL2004 (Sanchez, 2003).
Si el MDT estuviera en alturas elipsoidales, el sesgo seria del orden de esa
ondulacion; si esta en ortometricas, el sesgo es cercano a cero.

Entrada:
  - datos_salida/bogota_exactitud_vertical_mdt2020_<version>.csv 
  - datos_entrada/GEOCOL2004_20191118.isg.txt (modelo de geoide en formato ISG,
    descargado de isgeoid.polimi.it, "Retrieve geoid ISG format")

Uso:   aux_referencia_vertical_geoide.py
Sale:  referencia_vertical_geoide.csv 
"""
import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX

ARCHIVO_GEOIDE = C.CARPETA_ENTRADAS / "GEOCOL2004_20191118.isg.txt"


def leer_isg(ruta):
    texto = open(ruta, encoding="latin-1").read()
    cabecera, datos = texto.split("end_of_head", 1)
    h = {}
    for linea in cabecera.splitlines():
        if "=" in linea and not linea.startswith("begin_of_head"):
            k, v = linea.split("=", 1)
            try:
                h[k.strip()] = float(v)
            except ValueError:
                pass
    valores = np.array(datos.split("\n", 1)[1].split(), float)
    filas, columnas = int(h["nrows"]), int(h["ncols"])
    malla = valores[:filas * columnas].reshape(filas, columnas)
    malla[malla == h["nodata"]] = np.nan
    return h, malla


def ondulacion(h, malla, lat, lon):
    """Interpolacion bilineal. La primera fila es la del norte; los valores se
    toman en el centro de cada celda (la lectura en los nodos cambia menos de 0,3 m)."""
    i = (h["lat max"] - lat) / h["delta lat"] - 0.5
    j = (lon - h["lon min"]) / h["delta lon"] - 0.5
    i0, j0 = np.floor(i).astype(int), np.floor(j).astype(int)
    fi, fj = i - i0, j - j0
    return (malla[i0, j0] * (1 - fi) * (1 - fj) + malla[i0, j0 + 1] * (1 - fi) * fj
            + malla[i0 + 1, j0] * fi * (1 - fj) + malla[i0 + 1, j0 + 1] * fi * fj)


def main():
    h, malla = leer_isg(ARCHIVO_GEOIDE)
    v = pd.read_csv(C.ARCHIVO_EXACTITUD)
    v["excluir"] = v["excluir"].astype(str).str.lower().eq("true")
    v = v[v["residuo_m"].notna() & ~v["excluir"]].copy()
    v["ondulacion_geoide_m"] = ondulacion(h, malla, v["lat"].to_numpy(), v["lon"].to_numpy())

    sesgo, mediana = v["residuo_m"].mean(), v["residuo_m"].median()
    n_geo = v["ondulacion_geoide_m"]
    print(f"Vertices del conjunto adoptado: {len(v)}")
    print(f"Sesgo del MDT frente al IGAC: media {sesgo:+.3f} m, mediana {mediana:+.3f} m")
    print(f"Ondulacion del geoide (GEOCOL2004): media {n_geo.mean():.2f} m, "
          f"de {n_geo.min():.2f} a {n_geo.max():.2f} m")
    print("Si el MDT estuviera en alturas elipsoidales, el sesgo seria cercano a la ondulacion.")
    print("Conclusion: alturas ORTOMETRICAS" if abs(sesgo) < 0.1 * n_geo.mean()
          else "Revisar: el sesgo no es cercano a cero")
    v[["vertice", "lat", "lon", "residuo_m", "ondulacion_geoide_m"]].to_csv(
        CARPETA_AUX / "referencia_vertical_geoide.csv", index=False, encoding="utf-8-sig")
    print("Guardado: referencia_vertical_geoide.csv")


if __name__ == "__main__":
    main()
