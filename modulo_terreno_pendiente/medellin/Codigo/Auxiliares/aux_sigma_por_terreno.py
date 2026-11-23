"""
Error vertical del DTM por tipo de terreno en los vertices utiles del IGAC.

Que hace: mide lapendiente del terreno alrededor de cada vertice con cuatro alturas del DTM a
10 m (este, oeste, norte y sur, diferencias centradas) y lo clasifica en plano
(3 % o menos), inclinado (mas de 3 y hasta 8 %) o ladera (mas de 8 %). Calcula
el RMSEz de DTM - IGAC por clase. 

Lee:      igac_vertices_medellin.csv y el DTM (datos_entrada/mdt/).
Escribe:  datos_salida/auxiliares/aux_sigma_por_terreno.csv (un vertice por fila)

Resultado: Plano 2 vertices, RMSEz 0,329 m; inclinado 0 vertices; ladera 7 vertices, RMSEz 0,585 m (0,16 m sin 19-NW-3,
que esta en 52 % de pendiente); los 9 juntos, 0,539 m.
"""
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from _comun import C, carpeta_salida

# Define la distancia utilizada para estimar la pendiente del terreno alrededor de cada vértice y los límites que se emplean para clasificar la inclinación.
DISTANCIA_PENDIENTE_M = 10.0         
LIMITES_PCT = [-1, 3, 8, 1e9]
CLASES = ["plano (<=3 %)", "inclinado (3-8 %)", "ladera (>8 %)"]


def altura(r, x, y):
    # Consulta la elevación del MDT en una coordenada determinada.
    # Comprueba que la ubicación esté dentro del raster y que el valor obtenido no corresponda a un dato NoData; en esos casos devuelve NaN.
    fila, col = r.index(x, y)
    if not (0 <= fila < r.height and 0 <= col < r.width):
        return np.nan
    z = float(r.read(1, window=((fila, fila + 1), (col, col + 1)))[0, 0])
    return np.nan if (r.nodata is not None and z == r.nodata) else z


def main():
    # Verifica la existencia del modelo digital del terreno y carga los vértices de referencia del IGAC
    if not C.ARCHIVO_MDT.exists():
        raise SystemExit(f"Hace falta el DTM en {C.ARCHIVO_MDT.relative_to(C.CARPETA_PROYECTO)}")
    v = pd.read_csv(C.ARCHIVO_VERTICES_IGAC, dtype={"vertice": str})
    v = v[~v["excluir"].astype(str).str.lower().eq("true")].copy()

    # Configura la transformación de coordenadas geográficas al sistema de referencia del MDT y establece la distancia para estimar las pendientes.
    t = Transformer.from_crs("EPSG:4326", C.CRS_MDT, always_xy=True)
    d = DISTANCIA_PENDIENTE_M
    filas = []

    # Recorre los vértices seleccionados y consulta la elevación del MDT en cada ubicación. También obtiene elevaciones cercanas en las direcciones X e Y
    # para aproximar la pendiente del terreno mediante diferencias centrales.
    with rasterio.open(C.ARCHIVO_MDT) as r:
        for f in v.itertuples():
            x, y = t.transform(f.lon, f.lat)
            z = altura(r, x, y)
            gx = (altura(r, x + d, y) - altura(r, x - d, y)) / (2 * d)
            gy = (altura(r, x, y + d) - altura(r, x, y - d)) / (2 * d)

            # Guarda la elevación de referencia, la del MDT, su diferencia y la magnitud de la pendiente estimada, expresada en porcentaje.
            filas.append({"vertice": f.vertice, "altura_igac_m": f.altura_igac_m, "z_mdt_m": z,
                          "diferencia_m": z - f.altura_igac_m, "pendiente_terreno_pct": 100 * np.hypot(gx, gy)})

    # Organiza los resultados en un DataFrame y clasifica cada vértice según el porcentaje de pendiente calculado
    out = pd.DataFrame(filas)
    out["clase_terreno"] = pd.cut(out["pendiente_terreno_pct"], LIMITES_PCT, labels=CLASES)
    out.to_csv(carpeta_salida() / "aux_sigma_por_terreno.csv", index=False, encoding="utf-8-sig")

    # Muestra los resultados redondeados y calcula el RMSE de las diferencias de elevación entre el MDT y el IGAC para cada clase de terreno y para el conjunto completo. Este indicador resume el tamaño de los errores
    # de elevación, sin considerar su signo.
    print(out.round(3).to_string(index=False))
    print("\nRMSEz por clase de terreno (informativo):")
    for clase in CLASES + ["todos"]:
        dd = out["diferencia_m"] if clase == "todos" else out.loc[out["clase_terreno"] == clase, "diferencia_m"]
        dd = dd.dropna()
        rmse = f"{np.sqrt((dd ** 2).mean()):.3f} m" if len(dd) else "sin vertices"
        print(f"  {clase}: n = {len(dd)}, RMSEz = {rmse}")

if __name__ == "__main__":
    main()
