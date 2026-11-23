"""
Sistema de referencia del DTM-LiDAR 2021: Para saber cual gobierna, el del archivo o el de la ficha.

Que hace: Imprime el CRS que trae el encabezado del .TIF, sus limites y su
resolucion; muestra los archivos .prj o .aux.xml que lo acompanen; y transforma
cada vertice util del IGAC a EPSG:9377 (sistema de la ficha) y a EPSG:6257
(sistema del archivo) para ver en cual cae dentro del raster y comparar la
altura del DTM con la del IGAC.

Lee:      el DTM (datos_entrada/mdt/) e igac_vertices_medellin.csv.
Escribe:  datos_salida/auxiliares/aux_crs_mdt.csv (un vertice por fila)

Resultado:El encabezado declara LOCAL_CS
"MAGNA_Medellin_Antioquia_2010" con AUTHORITY EPSG 6257 y sin parametros,
limites 816.953,59-846.021,59 E y 1.172.948,85-1.198.028,85 N; resolucion 1 m;
sin .prj, .aux.xml ni .tfw. Los 9 vertices utiles caen dentro del raster en
EPSG:6257 (RMSEz 0,539 m) y ninguno en EPSG:9377. Gobierna EPSG:6257.
"""
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from _comun import C, carpeta_salida
# Define los sistemas de referencia que se van a contrastar para determinar cuál permite ubicar los vértices del IGAC sobre el MDT
SISTEMAS = {"ficha EPSG:9377": "EPSG:9377", "archivo EPSG:6257": "EPSG:6257"}



def main():
     # Verifica que el modelo digital del terreno esté disponible y carga los vértices de referencia del IGAC
    if not C.ARCHIVO_MDT.exists():
        raise SystemExit(f"Hace falta el DTM en {C.ARCHIVO_MDT.relative_to(C.CARPETA_PROYECTO)}")
    v = pd.read_csv(C.ARCHIVO_VERTICES_IGAC, dtype={"vertice": str})
    v = v[~v["excluir"].astype(str).str.lower().eq("true")]
    # Inspecciona los metadatos del raster y los archivos auxiliares para identificar información sobre su sistema de coordenadas y cobertura
    with rasterio.open(C.ARCHIVO_MDT) as r:
        print("a) Encabezado del .TIF")
        print(f"   CRS (WKT): {r.crs.to_wkt() if r.crs else 'sin CRS'}")
        print(f"   limites: {r.bounds}")
        print(f"   resolucion: {r.res}")

        print("\nb) Archivos que acompanan al .TIF")
        acompanantes = [p for p in C.ARCHIVO_MDT.parent.iterdir()
                        if p.suffix.lower() in (".prj", ".xml", ".tfw", ".aux") and p != C.ARCHIVO_MDT]
        if not acompanantes:
            print("   ninguno (.prj, .aux.xml ni .tfw): el sistema solo sale del encabezado")
        for p in acompanantes:
            print(f"   {p.name}:\n{p.read_text(encoding='utf-8', errors='replace')[:2000]}")
        # Evalúa la ubicación de cada vértice bajo los dos sistemas de referencia.
        # Para los puntos que caen dentro de la extensión del raster, extrae la elevación del MDT y la compara con la altura registrada por el IGAC
        print("\nc) y d) Vertices utiles del IGAC en cada sistema")
        b = r.bounds
        filas = []
        for f in v.itertuples():
            for nombre, epsg in SISTEMAS.items():
                x, y = Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform(f.lon, f.lat)
                dentro = b.left <= x <= b.right and b.bottom <= y <= b.top
                z = np.nan
                if dentro:
                    fila, col = r.index(x, y)
                    z = float(r.read(1, window=((fila, fila + 1), (col, col + 1)))[0, 0])
                    if r.nodata is not None and z == r.nodata:
                        z = np.nan
                filas.append({"vertice": f.vertice, "sistema": nombre, "x": round(x, 1), "y": round(y, 1),
                              "dentro_del_raster": dentro, "z_mdt_m": z, "altura_igac_m": f.altura_igac_m,
                              "diferencia_m": z - f.altura_igac_m})
     # Guarda los resultados por vértice y sistema de referencia para permitir una revisión de las coordenadas y diferencias de elevación            
    out = pd.DataFrame(filas)
    out.to_csv(carpeta_salida() / "aux_crs_mdt.csv", index=False, encoding="utf-8-sig")
    print(out.round(3).to_string(index=False))
    # Resume la cantidad de vértices ubicados dentro del raster y calcula el RMSE vertical por sistema como indicador de la diferencia frente al IGAC    
    print("\nResumen por sistema:")
    for nombre in SISTEMAS:
        s = out[out["sistema"] == nombre]
        d = s["diferencia_m"].dropna()
        rmse = f"{np.sqrt((d ** 2).mean()):.3f} m" if len(d) else "sin datos"
        print(f"   {nombre}: {int(s['dentro_del_raster'].sum())} de {len(s)} vertices dentro del raster; RMSEz {rmse}")


if __name__ == "__main__":
    main()
