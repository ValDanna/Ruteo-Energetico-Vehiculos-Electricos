"""
Configuracion del modulo de terreno y pendiente de Medellin.

Todo parametro que cambia un resultado esta aqui, con su origen. El programa
medellin_pendientes_dtm2021.py no contiene umbrales, rutas ni constantes.
Las rutas son relativas a la carpeta de este archivo.
"""
from pathlib import Path

VERSION_SALIDA = "v3"

# Rutas
CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_ENTRADAS = CARPETA_PROYECTO / "datos_entrada"
CARPETA_SALIDAS = CARPETA_PROYECTO / "datos_salida"
CARPETA_SALIDAS_AUX = CARPETA_SALIDAS / "auxiliares"

# Entregados por el modulo del grafo. Conservan el nombre que les dio ese modulo porque la verificacion de procedencia compara contra su registro.
ARCHIVO_SEGMENTOS = CARPETA_ENTRADAS / "D2M_segmentos_para_pendiente.gpkg"
CAPA_SEGMENTOS = "segmentos"
ARCHIVO_HUELLAS_ENTRADA = CARPETA_ENTRADAS / "D2M_huellas_salidas.json"
ARCHIVO_CONTRATO = CARPETA_ENTRADAS / "D2M_contrato_intercambio.json"
NOMBRE_CONTRATO_EN_HUELLAS = "D2M_contrato_intercambio.json"

# DTM-LiDAR Medellin 2021 (Subsecretaria de Catastro), descargado del Banco de Imagenes de la Alcaldia. Nombre del .TIF 
ARCHIVO_MDT = CARPETA_ENTRADAS / "mdt" / "MDT1_05001_20210501_modelo completo origen Medellin.TIF"
# SHA-256 completo del .TIF,  (coincide con el prefijo bfd9709b... registrado al descargarlo). El programa se detiene si el archivo cambia.
SHA256_MDT = "bfd9709be3d6189c84052e5791fb5c1e8db73cf859eb438ef93934da4c47a7ed"

# SHA-256 del CSV, el programa se detiene si otra corrida no da el mismo archivo.

SHA256_SALIDA_ESPERADO = "2aaba7230df0845116775e5100d3bc9292f67c4041a33aed1082d28d69f68e5e"
# Tolerancia de auxiliares/aux_comparar_versiones.py para comparar dos versiones del archivo. 1e-10 esta muy por debajo de cualquier cambio con efecto en la pendiente (el error mediano es 0,18 pp) y por encima del redondeo de punto flotante.
TOLERANCIA_COMPARACION = 1e-10


def salidas():
    base = f"medellin_pendientes_{{}}_{VERSION_SALIDA}"
    return {
        "pendientes": CARPETA_SALIDAS / (base.replace("{}", "segmentos_dtm2021") + ".csv"),
        "validaciones": CARPETA_SALIDAS / (base.replace("{}", "validaciones") + ".csv"),
        "sensibilidad": CARPETA_SALIDAS / (base.replace("{}", "sensibilidad") + ".csv"),
        "huellas": CARPETA_SALIDAS / (base.replace("{}", "huellas") + ".json"),
        "manifiesto": CARPETA_SALIDAS / (base.replace("{}", "manifiesto") + ".json"),
        "bitacora": CARPETA_SALIDAS / (base.replace("{}", "bitacora") + ".log"),
    }


# Sistemas de referencia
# La red viene en MAGNA-SIRGAS Origen Nacional.
CRS_RED = "EPSG:9377"
# El .TIF declara EPSG:6257 (MAGNA-SIRGAS / Medellin urban grid) en un LOCAL_CS sin parametros, que pyproj no puede usar; por eso el CRS se fija y cada punto se reproyecta 9377 -> 6257 antes de leer la altura.
CRS_MDT = "EPSG:6257"

# Incertidumbre
# RMSEz medido con los 9 vertices de la Red de Control Vertical del IGAC (auxiliares/aux_vertices_igac.py). Es una estimacion de la NSSDA (FGDC, 1998) que pide 20 puntos. El 0,10 m de la ficha es la tolerancia de conformidad del producto, no la medicion y queda como sensibilidad (rama med_sigma054).
SIGMA_Z_M = 0.539
SIGMA_Z_ORIGEN = "RMSEz de 9 vertices IGAC"
# Parametro A del modelo exponencial (rango efectivo / 3), medido sobre el raster de Medellin con el metodo de Bogota: mediana de 11 ventanas planas de 200 m en el aeropuerto Olaya Herrera (auxiliares/aux_ancho_correlacion.py).
ANCHO_CORRELACION_M = 59.2
# Distinguible de cero si |neta| > K x error (aprox. 95 % bilateral).
K_SIGMA = 2.0

# Muestreo adaptativo
# Umbral Plano/Ondulado del Manual de Diseño Geometrico de Carreteras (INVIAS, 2008).
UMBRAL_PLANO_PCT = 3.0
# 50 m en plano y 10 m en pendiente, los mismos de Bogota para que las ciudades sean comparables. En la prueba de pasos de Bogota (aux_prueba_pasos.py de ese
# paquete) la acumulada de los planos baja de 0,72 % (paso 5 m) a 0,42 % (paso 50 m), es decir, en ellos la variacion es ruido; frente a 5 m, el paso de 50 m
# pierde mas de 0,5 pp en 16 de 100 segmentos y el de 10 m en 10 de 100. Efecto en Medellin sobre la acumulada de los planos: auxiliares/aux_paso_muestreo.py.
PASO_PLANO_M = 50.0
PASO_PENDIENTE_M = 10.0

# Clasificacion INVIAS sobre |pendiente neta| (contrato): < 3 Plano, [3, 6) Ondulado; [6, 8] Montanoso; > 8 Escarpado.
INVIAS_LIMITE_ONDULADO = 3.0
INVIAS_LIMITE_MONTANOSO = 6.0
INVIAS_LIMITE_ESCARPADO = 8.0
ETIQUETAS_INVIAS = ("Plano", "Ondulado", "Montañoso", "Escarpado")

# Cota física: la calle mas empinada verificada tiene 34,8 % (Guinness World Records, 2020). Por encima de 35 % el valor se marca, no se borra.
UMBRAL_PENDIENTE_EXTREMA_PCT = 35.0

# Tuneles: el MDT mide la montaña y no la via. Se marca todo tramo con "tunel" en el nombre y los tramos sin nombre cuyos dos nodos
# pertenecen a tramos de tunel (cierran un hueco de la cadena).
PATRON_TUNEL = r"t[uú]nel"

# Sensibilidad
# 0,539 adoptado, 0,10 es la tolerancia de la ficha, 0,536 es el sigma_z medido en Bogota, para comparar las dos ciudades
SENSIBILIDAD_SIGMAS_M = [0.539, 0.10, 0.536]
# None = independencia total (rho = 0). 35,2 y 75,4 m son la ventana minima y el tope de las 11 ventanas del Olaya Herrera.
SENSIBILIDAD_ANCHOS_M = [None, 35.2, 59.2, 75.4]

# Auxiliares
# Vertices de la Red de Control Vertical del IGAC en Medellin (shapefile
# red_nivelacion_20261013 del IGAC), con estado y motivo de exclusion. Se busca primero la copia de datos_entrada
ARCHIVO_VERTICES_IGAC = CARPETA_ENTRADAS / "igac_vertices_medellin.csv"
if not ARCHIVO_VERTICES_IGAC.exists():
    ARCHIVO_VERTICES_IGAC = CARPETA_PROYECTO / "igac_vertices_medellin.csv"
# Minimo de puntos de control para estimar exactitud vertical (NSSDA, FGDC 1998).
MINIMO_VERTICES_NSSDA = 20

# Recorte del MDT alrededor del aeropuerto Olaya Herrera (oeste, sur, este, norte
# en grados). Los auxiliares lo cortan del MDT con el mismo codigo del recorte usado el 08-10-2026; el SHA-256 comprueba que el arreglo es el mismo.
CAJA_OLAYA = (-75.600, 6.205, -75.580, 6.235)
ARCHIVO_RECORTE_OLAYA = CARPETA_SALIDAS_AUX / "recorte_mdt_olaya.tif"
SHA256_RECORTE_OLAYA = "2eef0c7b18aec6ad0930e62e1bb7869c7518acdd488d23a3ebbaa7caaa58c9dd"

# Ancho de correlacion: 
CORRELACION_VENTANA_PX = 201          # 200 m a 1 m de pixel
CORRELACION_ESPACIADO_M = 5           # grilla de 41 x 41 puntos, como en Bogota
CORRELACION_PASO_BUSQUEDA_PX = 20
CORRELACION_SUBMUESTRA = 2000
CORRELACION_SEMILLA = 42
DIVISOR_RANGO_EXPONENCIAL = 3.0       # scikit-gstat reporta el rango efectivo r; A = r/3
# Criterio de ventana plana, fijado antes de calcular el variograma: sin huellas de edificio (laplaciano < 0,005 en mas del 5 %), sin bordes (laplaciano > 0,2
# en mas del 5 %) y pendiente P95 del MDT suavizado a 5 m de 8 % o menos.
VENTANA_LISO_MAX = 0.005
VENTANA_RUGOSO_MIN = 0.2
VENTANA_FRACCION_MAX = 0.05
VENTANA_PENDIENTE_P95_MAX = 8.0

# Alineacion: desplazamientos de la red sobre el MDT, en metros. 8 m cubre de sobra el error de digitalizacion esperado de una red vial urbana.
ALINEACION_DESPLAZAMIENTO_MAX_M = 8
ALINEACION_ESPACIADO_M = 1

# Comparacion con modelos de 30 m. Sectores definidos por la regla del cuadrado minimo con 200 tramos fisicos de 30 m o mas.
COPERNICUS_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
                  "Copernicus_DSM_COG_10_N06_00_W076_00_DEM/"
                  "Copernicus_DSM_COG_10_N06_00_W076_00_DEM.tif")
ARCHIVO_COPERNICUS = CARPETA_ENTRADAS / "copernicus_dem_N06_W076.tif"
SHA256_COPERNICUS = "abbbcbcadc344cb4830cc59ee7c823af46132ca6bb588ce095636d81217aa2c0"
SRTM_URL = "https://api.opentopodata.org/v1/srtm30m"
SECTORES_30M = {"laureles_estadio": (-75.599, 6.246, -75.591, 6.254),
                "comuna13_san_javier": (-75.6315, 6.2415, -75.6185, 6.2545)}
LONGITUD_MINIMA_30M = 30.0

# Revision en Street View. Lista de 104 calles preparada por el modulo del grafo (95 tramos fisicos con pendiente_extrema y 9 calles con paso_nivel = 2), y la misma lista con la revision (se_ve_calle_para_carros, observacion).
CARPETA_RESPALDO = CARPETA_PROYECTO / "respaldo_eda"
ARCHIVO_LISTA_REVISION = CARPETA_RESPALDO / "D3M_revision_street_view_med_sigma010.csv"
ARCHIVO_REVISION_COMPLETADA = CARPETA_RESPALDO / "revision_104_medellin_completada.csv"
# Intervalo de Wilson al 95 % para las proporciones de la revision (z = 1,96).
Z_WILSON_95 = 1.96
