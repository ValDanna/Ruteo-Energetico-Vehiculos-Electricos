"""
Ancho de correlacion del error del MDT (parametro A de rho = exp(-L/A)), sobre el raster de Medellin.

Que hace: Busca en el recorte del Olaya Herrera todas las ventanas planas de
200 x 200 m que cumplen el criterio fijado en la configuracion (sin huellas de
edificio, sin bordes, pendiente baja), sin solaparse. En cada una toma una grilla
cada 5 m (41 x 41), resta un plano, calcula el variograma con xDEM (submuestra
2.000, semilla 42), ajusta el modelo exponencial y toma A = rango efectivo / 3.
El valor es la mediana de las ventanas.

Como se corre (desde codigo/):  python auxiliares/aux_ancho_correlacion.py
Lee:      recorte del Olaya Herrera, cortado del MDT (datos_entrada/mdt/).
Escribe:  datos_salida/auxiliares/aux_ancho_correlacion.csv (una fila por ventana)
          y recorte_mdt_olaya.tif.

Resultado (14-10-2026, recorte SHA 2eef0c7b...): 11 ventanas; A entre 35,2 y
75,4 m, mediana 59,2 m (Bogota: 53,6 m). 4 de las 11 tocan el tope del ajuste
(rango 226,3 m, A = 75,4 m): el residuo conserva algo de relieve real.
Atanasio Girardot y Ciudad del Rio no tienen ventanas de 200 m que cumplan el
criterio. Limitacion:Es el error se mide en terreno plano y se supone igual en ladera.
"""
import warnings

import numpy as np
import pandas as pd
from scipy.ndimage import laplace, uniform_filter

from _comun import C, carpeta_salida, recorte_olaya

warnings.filterwarnings("ignore")


def ventanas_planas(z):
    # Calcula una medida local de rugosidad a partir del valor absoluto del operador Laplaciano aplicado al modelo digital del terreno.
    # El filtro uniforme suaviza los valores para reducir variaciones locales    
    rugosidad = uniform_filter(np.abs(laplace(z)), 5)
    # Suaviza el MDT antes de calcular los gradientes de elevación.
    # La magnitud del gradiente se expresa como porcentaje de pendiente.    
    gy, gx = np.gradient(uniform_filter(z, 5))
    pendiente = np.hypot(gx, gy) * 100
    # Obtiene el tamaño de las ventanas de análisis y el paso entre posiciones consecutivas    
    w, paso = C.CORRELACION_VENTANA_PX, C.CORRELACION_PASO_BUSQUEDA_PX
    # Crea una matriz booleana para identificar las zonas que ya pertenecen a una ventana seleccionada y evitar solapamientos    
    ocupado = np.zeros(z.shape, bool)
    # Almacena las posiciones iniciales de las ventanas que cumplan los criterios de planitud y rugosidad    
    elegidas = []
    # Recorre el MDT con ventanas de tamaño w
    for i in range(0, z.shape[0] - w + 1, paso):
        for j in range(0, z.shape[1] - w + 1, paso):
            # Omite la ventana si alguna parte de ella ya está ocupada por una ventana seleccionada anteriormente            
            if ocupado[i:i + w, j:j + w].any():
                continue
            # Extrae los valores de rugosidad correspondientes a la ventana
            r = rugosidad[i:i + w, j:j + w]
            # Selecciona ventanas que cumplen tres condiciones:
            # La fracción de valores con rugosidad muy baja no supera el límite,
            # la fracción de valores con rugosidad alta tampoco lo supera,
            # y el percentil 95 de la pendiente está dentro del máximo permitido            
            if ((r < C.VENTANA_LISO_MAX).mean() <= C.VENTANA_FRACCION_MAX
                    and (r > C.VENTANA_RUGOSO_MIN).mean() <= C.VENTANA_FRACCION_MAX
                    and np.percentile(pendiente[i:i + w, j:j + w], 95) <= C.VENTANA_PENDIENTE_P95_MAX):
                elegidas.append((i, j))
                # Marca toda la ventana como ocupada para impedir que otra ventana seleccionada se solape con ella                
                ocupado[i:i + w, j:j + w] = True
    
    # Devuelve las posiciones de las ventanas que superaron los filtros
    return elegidas


def main():
    import xdem

    z, _, _, sha = recorte_olaya()
     # Define el tamaño de las ventanas y el espaciamiento entre muestras
    w, e = C.CORRELACION_VENTANA_PX, C.CORRELACION_ESPACIADO_M

    # Lista en la que se almacenarán los resultados de cada ventana analizada
    filas = []
    for i, j in ventanas_planas(z):
        g = z[i:i + w:e, j:j + w:e]
        n = g.shape[0]
   # Genera las coordenadas de fila y columna de los puntos de la ventana     
        yy, xx = np.mgrid[0:n, 0:n]
        # Construye la matriz de diseño para ajustar un plano a las elevaciones
        A = np.column_stack([xx.ravel(), yy.ravel(), np.ones(n * n)])
        # Estima los coeficientes del plano mediante mínimos cuadrados
        coef, *_ = np.linalg.lstsq(A, g.ravel(), rcond=None)
        # Calcula los residuos como la diferencia entre las elevaciones observadas y las elevaciones estimadas por el plano ajustado        
        residuo = g - (coef[0] * xx + coef[1] * yy + coef[2])
        # Calcula el variograma empírico de los residuos para analizar cómo cambia su variabilidad con la distancia espacial.
        # El espaciamiento, el tamaño de la submuestra y la semilla aleatoria       
        vario = xdem.spatialstats.sample_empirical_variogram(
            values=residuo, gsd=e, subsample=C.CORRELACION_SUBMUESTRA, random_state=C.CORRELACION_SEMILLA)
        # Ajusta un modelo exponencial al variograma empírico.
        # El ajuste permite estimar el rango efectivo de correlación espacial        
        _, par = xdem.spatialstats.fit_sum_model_variogram(list_models=["Exponential"], empirical_variogram=vario)
        # Extrae el rango efectivo estimado para la ventana analizada
        r = float(par["range"].iloc[0])
        # Guarda la posición de la ventana, el rango efectivo estimado, el parámetro A derivado de ese rango y la desviación estándar de los residuos del plano ajustado    
        filas.append({"fila_px": i, "columna_px": j, "rango_efectivo_m": r,
                      "A_m": r / C.DIVISOR_RANGO_EXPONENCIAL, "desv_residuo_m": float(residuo.std())})
    tabla = pd.DataFrame(filas)
    tabla.to_csv(carpeta_salida() / "aux_ancho_correlacion.csv", index=False, encoding="utf-8-sig")
    # Identifica el mayor rango efectivo estimado entre las ventanas analizadas
    tope = tabla["rango_efectivo_m"].max()
    # Imprime la huella del MDT utilizado y el número de ventanas seleccionadas
    print(f"Recorte SHA {sha[:12]}...; ventanas planas: {len(tabla)}")
    print(tabla.round(2).to_string(index=False))
    # Resume los valores de A: mediana, mínimo y máximo.
    # También cuenta cuántas ventanas tienen un rango efectivo prácticamente igual al máximo obtenido, usando una tolerancia de 1e-6    

    print(f"A: mediana {tabla['A_m'].median():.1f} m, minimo {tabla['A_m'].min():.1f} m, "
          f"maximo {tabla['A_m'].max():.1f} m; ventanas en el tope del ajuste: "
          f"{int((tabla['rango_efectivo_m'] >= tope - 1e-6).sum())}")
    # Imprime el ancho de correlación espacial definido para compararlo con las estimaciones obtenidas    
    print(f"Valor en la configuracion: {C.ANCHO_CORRELACION_M} m")


if __name__ == "__main__":
    main()
