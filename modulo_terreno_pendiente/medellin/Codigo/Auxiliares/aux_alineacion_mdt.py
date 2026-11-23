"""
Comprueba que la red (EPSG:9377) cae sobre las vias del MDT (EPSG:6257) despues
de reproyectar, sin depender de como lo muestre QGIS.

Que hace: Desplaza la red completa entre -8 y +8 m en x y en y sobre el recorte
del Olaya Herrera y mide la pendiente local mediana del MDT bajo las vias. Las
calzadas son mas lisas que su alrededor, asi que el minimo debe caer donde la red
esta bien puesta. Si la reproyeccion estuviera mal, el minimo se correria.

Como se corre (desde codigo/):  python auxiliares/aux_alineacion_mdt.py
Lee:      datos_entrada/D2M_segmentos_para_pendiente.gpkg y el recorte del Olaya
          Herrera, cortado del MDT (datos_entrada/mdt/).
Escribe:  datos_salida/auxiliares/aux_alineacion_mdt.csv (rejilla de desplazamientos)
          y recorte_mdt_olaya.tif.

Resultado: 3.060 segmentos no elevados
dentro del recorte, 61.486 puntos; minimo en (0, 0) m con pendiente mediana
3,68 %; sube en todas las direcciones (5,27 % a -8 m en x).
"""
import numpy as np
import pandas as pd
from shapely.geometry import box
# Importa la configuración y las funciones auxiliares para cargar los segmentos, preparar el recorte del MDT y gestionar la carpeta de resultados
from _comun import C, carpeta_salida, leer_segmentos, recorte_olaya


def main():
    # Carga el recorte del modelo digital del terreno (MDT), su transformación espacial, los límites del ráster y su huella SHA-256    
    z, transformacion, b, sha = recorte_olaya()
    # Calcula los gradientes de elevación en las direcciones vertical y horizontal    
    gy, gx = np.gradient(z)
    # Calcula la magnitud del gradiente para obtener una medida de la pendiente del terreno, expresada como porcentaje    
    pendiente = np.hypot(gx, gy) * 100
    # Carga los segmentos viales y transforma sus geometrías al sistema de coordenadas utilizado por el MDT
    g = leer_segmentos().to_crs(C.CRS_MDT)
    # Conserva los segmentos que intersectan el área cubierta por el recorte
    g = g[g.intersects(box(*b))]
    # Registra la cantidad inicial de segmentos que intersectan el recorte
    n_seg = len(g)
    # Conserva los segmentos completamente contenidos en un área interior con un margen de 30 metros respecto a los bordes del recorte.
    # Excluye también los segmentos identificados como elevados.    
    g = g[g.within(box(b.left + 30, b.bottom + 30, b.right - 30, b.top - 30)) & (g["es_elevado"] == False)]
    # Elimina duplicados para mantener un único registro por identificador
    g = g.drop_duplicates("id_eje")
    # Crea una lista con las coordenadas de los puntos que se utilizarán para evaluar la pendiente del terreno a lo largo de las vías
    puntos = []
    for geom in g.geometry:
        # Estima el número de puntos según la longitud de cada segmento, aproximadamente uno cada 2 metros        
        n = int(geom.length // 2)
        # Distribuye los puntos a lo largo de la geometría, incluyendo sus extremos y garantizando al menos dos puntos
        for f in np.linspace(0, 1, max(n, 2)):
            p = geom.interpolate(f, normalized=True)
            puntos.append((p.x, p.y))
    # Convierte las coordenadas de los puntos en una matriz NumPy        
    puntos = np.array(puntos)
    # Invierte la transformación espacial del ráster para convertir coordenadas del terreno en índices de columna y fila    
    inversa = ~transformacion

    def mediana(dx, dy):
        # Desplaza los puntos según los valores dx y dy evaluados y los transforma en índices de píxel del MDT        
        c, f = inversa * (puntos[:, 0] + dx, puntos[:, 1] + dy)
        # Obtiene la pendiente de los píxeles correspondientes y calcula la mediana        
        return float(np.nanmedian(pendiente[f.astype(int), c.astype(int)]))
 # Define la distancia máxima que se probará al desplazar los puntos
    d = C.ALINEACION_DESPLAZAMIENTO_MAX_M
    # Genera los desplazamientos posibles entre -d y d
    rango = np.arange(-d, d + 1, C.ALINEACION_ESPACIADO_M)
    # Evalúa todas las combinaciones de desplazamientos horizontales (dx) y verticales (dy), calculando la pendiente mediana para cada combinación    
    filas = [{"dx_m": int(dx), "dy_m": int(dy), "pendiente_mediana_pct": mediana(dx, dy)}
             for dy in rango for dx in rango]
    #Organiza en DataFrame
    tabla = pd.DataFrame(filas)
    minimo = tabla.loc[tabla["pendiente_mediana_pct"].idxmin()]
    tabla.to_csv(carpeta_salida() / "aux_alineacion_mdt.csv", index=False, encoding="utf-8-sig")
    # Imprime la huella del recorte, el número inicial de segmentos encontrados y la cantidad total de puntos de muestreo generados
    print(f"Recorte SHA {sha[:12]}...; segmentos en el recorte {n_seg:,}; puntos usados {len(puntos):,}")
     # Muestra el desplazamiento horizontal y vertical que obtuvo la menor pendiente mediana, junto con el valor de la pendiente
    print(f"Minimo en dx = {minimo.dx_m} m, dy = {minimo.dy_m} m "
          f"(pendiente mediana {minimo.pendiente_mediana_pct:.2f} %)")
    # Selecciona las combinaciones cuyo desplazamiento vertical es cero, organiza los resultados por desplazamiento horizontal y redondea la pendiente mediana a dos decimales    
    eje_x = tabla[tabla.dy_m == 0].set_index("dx_m")["pendiente_mediana_pct"].round(2)
    # Imprime el perfil de pendientes para los desplazamientos horizontales evaluados cuando el desplazamiento vertical permanece en cero    
    print("Perfil en x (dy = 0):", eje_x.to_dict())


if __name__ == "__main__":
    main()
