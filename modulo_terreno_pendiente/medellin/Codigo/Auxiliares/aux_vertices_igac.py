"""
Revision de los vertices de la Red de Control Vertical del IGAC en Medellin:
Da el sigma_z desde la v3 (0,539 m, estimacion con 9 vertices).

Que hace: cuenta los vertices por tipo de coordenada y estado
(igac_vertices_medellin.csv) y los compara con el minimo de la NSSDA. Si el MDT esta disponible,
calcula ademas MDT - IGAC en cada vertice (lat/lon -> EPSG:6257, pixel mas
cercano), desde la v3 ese valor es el sigma_z final.

Lee:      igac_vertices_medellin.csv.
Escribe:  aux_vertices_igac.csv

Resultado: 29 vertices en Medellin; 12 con coordenada calculada (9 materializados, 3 destruidos) y 17 con coordenada
aproximada. Quedan 9 utiles, menos que los 20 de la NSSDA. RMSEz con los 29:
131,9 m, por los vertices de coordenada aproximada (los 6 atipicos del intento
del 29-09 son de ese tipo). RMSEz con los 9 utiles: 0,539 m; media -0,23 m y
desviacion 0,52 m, sin un desplazamiento constante que se cancele en la
pendiente; mediana -0,10 m y NMAD 0,20 m. 19-NW-3 (-1,50 m) pesa mas que los
demas, pero no supera 3 desviaciones (1,55 m), sin el, 0,22 m. En todos los casos el valor queda por encima de los
0,10 m de la ficha, que es un valor del productor y no una medicion independiente. 
Desde la v3 se adopta 0,539 m como sigma_z oficial, declarado como estimacion porque 9 vertices no alcanzan los 20 de la NSSDA, 0,10 m queda como sensibilidad.
"""
import numpy as np
import pandas as pd

from _comun import C, carpeta_salida


def main():
    v = pd.read_csv(C.ARCHIVO_VERTICES_IGAC, dtype={"vertice": str})
    utiles = v[~v["excluir"]]
    print(f"Vertices en Medellin: {len(v)}")
    print(pd.crosstab(v["tipo_coordenada"], v["estado"]).to_string())
    print(f"Utiles (calculada y materializado): {len(utiles)}; minimo NSSDA: {C.MINIMO_VERTICES_NSSDA}")
    print(f"Atipicos del intento del 29-09 con coordenada aproximada: "
          f"{int(v['observacion'].fillna('').str.contains('atipico').sum())}")

    if C.ARCHIVO_MDT.exists():
        import rasterio
        from pyproj import Transformer
        t = Transformer.from_crs("EPSG:4326", C.CRS_MDT, always_xy=True)
        with rasterio.open(C.ARCHIVO_MDT) as r:
            z = []
            for lat, lon in zip(v["lat"], v["lon"]):
                fila, col = r.index(*t.transform(lon, lat))
                dentro = 0 <= fila < r.height and 0 <= col < r.width
                valor = float(r.read(1, window=((fila, fila + 1), (col, col + 1)))[0, 0]) if dentro else np.nan
                z.append(np.nan if (r.nodata is not None and valor == r.nodata) else valor)
        v["z_mdt_m"] = z
        v["diferencia_m"] = v["z_mdt_m"] - v["altura_igac_m"]
        for nombre, grupo in [("todos", v), ("utiles", v[~v["excluir"]])]:
            d = grupo["diferencia_m"].dropna()
            print(f"RMSEz {nombre} ({len(d)} con dato): {np.sqrt((d ** 2).mean()):.3f} m "
                  f"(el de los utiles es el sigma_z adoptado desde la v3)")
    else:
        print("MDT no disponible: no se calculan diferencias MDT - IGAC")
    v.to_csv(carpeta_salida() / "aux_vertices_igac.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
