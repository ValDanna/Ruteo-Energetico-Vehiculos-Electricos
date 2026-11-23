"""
Configuracion de la etapa de terreno y pendiente de Bogotá

Todo parámetro que cambia un resultado se maneja acá, con su origen. El codigo
bogota_pendientes_mdt2020.py no contiene umbrales, rutas ni constantes propias.
Las rutas son relativas a la carpeta de este archivo, esto para que el código pueda ejecutarse desde cualquier directorio
"""
from pathlib import Path

VERSION_SALIDA = "v1"

# Rutas
CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_ENTRADAS = CARPETA_PROYECTO / "datos_entrada"
CARPETA_SALIDAS = CARPETA_PROYECTO / "datos_salida"
CARPETA_CACHE = CARPETA_PROYECTO / "cache"

# Entregados por la etapa que se generan en el grafo
ARCHIVO_SEGMENTOS = CARPETA_ENTRADAS / "D2_segmentos_para_pendiente.gpkg"
CAPA_SEGMENTOS = "segmentos"
ARCHIVO_HUELLAS_ENTRADA = CARPETA_ENTRADAS / "D2_huellas_salidas.json"
ARCHIVO_CONTRATO = CARPETA_ENTRADAS / "D2_contrato_intercambio.json"
# Archivos de la etapa anterior cuyo SHA-256 (que es el mismo código) y se verifica ademas del gpkg
ARCHIVOS_CON_HUELLA_DE_ARCHIVO = ["D2_contrato_intercambio.json"]

# Vertices de la Red de Control Vertical del IGAC, con su estado en el geovisor, en donde está ubicado y es el documento que se usa para medir oz, está especificado los datos usados
ARCHIVO_VERTICES = CARPETA_ENTRADAS / "igac_vertices_control_bogota.csv"

# Cache de elevaciones: cada coordenada consultada se guarda y no se vuelve a pedir, lo cuál permite reanudar una corrida interrumpida
ARCHIVO_CACHE = CARPETA_CACHE / "bogota_elevaciones_mdt2020_cache.csv"

ARCHIVO_PENDIENTES = CARPETA_SALIDAS / f"bogota_pendientes_segmentos_mdt2020_{VERSION_SALIDA}.csv"
ARCHIVO_EXACTITUD = CARPETA_SALIDAS / f"bogota_exactitud_vertical_mdt2020_{VERSION_SALIDA}.csv"
ARCHIVO_CORRELACION = CARPETA_SALIDAS / f"bogota_ancho_correlacion_{VERSION_SALIDA}.csv"
ARCHIVO_GRILLA = CARPETA_SALIDAS / f"bogota_grilla_correlacion_{VERSION_SALIDA}.csv"
ARCHIVO_SENSIBILIDAD = CARPETA_SALIDAS / f"bogota_sensibilidad_incertidumbre_{VERSION_SALIDA}.csv"
ARCHIVO_HUELLAS_SALIDA = CARPETA_SALIDAS / f"bogota_pendientes_huellas_{VERSION_SALIDA}.json"
ARCHIVO_MANIFIESTO = CARPETA_SALIDAS / f"bogota_pendientes_manifiesto_{VERSION_SALIDA}.json"
ARCHIVO_BITACORA = CARPETA_SALIDAS / f"bogota_pendientes_bitacora_{VERSION_SALIDA}.log"

# Sistemas de referencia
# Metrico de la etapa del grafo (MAGNA-SIRGAS Origen Nacional, el cuál es un sistema de coordenadas). Las longitudes vienen del gpkg y no se recalculan
CRS_METRICO = "EPSG:9377"
# Las consultas al MDT es en WGS84 es el sistema de coordenadas en grados de latitud y longitud que usan el GPS; el servicio reproyecta
CRS_CONSULTA = "EPSG:4326"

# Servicio del MDT 2020
# MDT de la zona urbana de Bogota 2020, Catastro Distrital. Es un MapServer: No publica WCS ni raster descargable (diagnostico_mdt_bogota.py), por eso se consulta punto a punto con identify.
MDT_URL = ("https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/"
           "topografia/modelodigitalterrenobogotaurbano/MapServer/identify")
MDT_CAMPO_VALOR = "Stretch.Pixel Value"
MDT_TIEMPO_ESPERA_S = 20
MDT_REINTENTOS = 3
MDT_PAUSA_S = 0.05
# Siete decimales en grados son aprox 1 cm: Dos consultas a la misma coordenada que comparten valor y los dos sentidos de un tramo usan la misma elevación
DECIMALES_CLAVE_CACHE = 7
# La consulta es punto a punto. La consulta multipunto deja sin valor los puntos que siguen a uno sin dato dentro del mismo lote (prueba A, aux_alineacion_consulta.py), recuperar esos puntos rescato 2.596 segmentos que habían quedado fuera de cobertura


# Exactitud vertical
# NSSDA (National Standard for Spatial Data Accuracy) (FGDC, 1998) comenta cómo se reporta la exactitud de un dato geográfico, referencia usada para medir el error del MDT contra los vértices del IGAC, exactitud al 95 % = 1,96 x RMSEz
FACTOR_NSSDA_95 = 1.96
# Umbral de investigacion de posibles errores grandes (Flood, 2004): Residuos mayores que 3 desviaciones estandar, sobre los vertices materializados con dato (los destruidos no influyen). 
# Etapa 1 sobre todos ellos; etapa 2 sin los que superan la etapa 1, porque los errores grandes inflan la desviación y maquillan a los moderados (validacion ampliada: 10,18 m y luego 2,64 m). 
# El umbral solo decide a quienes estudiar a detalle, ningun vertice se excluye sin evidencia escrita en igac_vertices_control_bogota.csv.
DESVIACIONES_INVESTIGACION = 3.0
# Vertices: los 530 de la Red de Control Vertical del IGAC en Bogota con coordenada CALCULADA (shapefile red_nivelacion_20261013 del IGAC). 
# Los 61 con coordenada APROXIMADA no se usan. Quedan 496 tras quitar 12 fuera del MDT urbano, 1 sin dato, 13 destruidos y 8 con error demostrado en la referencia.
# El codigo lo recalcula y se detiene si no coincide. Resultado de la medicion del 13-10-2026: RMSEz = 0,5363 m (con 496 vertices).
SIGMA_Z_ADOPTADO_M = 0.536
TOLERANCIA_SIGMA_Z_M = 0.001

# Ancho de correlacion
# Metodo de terreno estable (Hugonnet et al., 2022) sobre una grilla de puntos consultados al MDT en un parque del sector de prueba plano.
CORRELACION_CENTRO_LON = -74.0810
CORRELACION_CENTRO_LAT = 4.6490
CORRELACION_MEDIO_LADO_M = 100      # ventana de 200 x 200 m
CORRELACION_ESPACIADO_M = 5         # 41 x 41 = 1.681 puntos
CORRELACION_SUBMUESTRA = 2000
CORRELACION_SEMILLA = 42
# La formula  es exponencial, rho = exp(-L/A). En scikit-gstat el exponencial reporta el rango efectivo r, con A = r/3. Se ajusta el mismo modelo que usa la formula; el Gaussiano se reporta solo como contraste.
CORRELACION_MODELO = "Exponential"
DIVISOR_RANGO_EXPONENCIAL = 3.0
DIVISOR_RANGO_GAUSSIANO = 2.0
ANCHO_CORRELACION_ADOPTADO_M = 53.6
TOLERANCIA_ANCHO_M = 0.1

# Muestreo y pendiente
# Umbral Plano/Ondulado del Manual de Diseño Geometrico de Carreteras (INVIAS, 2008).
UMBRAL_PLANO_PCT = 3.0
# 50 m en plano: en la prueba de pasos la acumulada de los planos baja de 0,72 % (paso 5 m) a 0,42 % (paso 50 m), es decir, en ellos la variacion es ruido. 10 m en pendiente: frente a 5 m, el paso de 50 m pierde mas de 0,5 pp en 16 de 100 segmentos y el de 10 m en 10 de 100 (aux_prueba_pasos.py)
PASO_PLANO_M = 50.0
PASO_PENDIENTE_M = 10.0

# Clasificacion INVIAS sobre |pendiente neta| (contrato): < 3 Plano, [3, 6) Ondulado; [6, 8] Montanoso; > 8 Escarpado
INVIAS_LIMITE_ONDULADO = 3.0
INVIAS_LIMITE_MONTANOSO = 6.0
INVIAS_LIMITE_ESCARPADO = 8.0
ETIQUETAS_INVIAS = ("Plano", "Ondulado", "Montañoso", "Escarpado")

# Distinguible de cero si |neta| > K x error (aprox. 95 % bilateral)
K_SIGMA = 2.0
# Cota: La calle mas empinada verificada tiene 34,8 % (Guinness World Records, 2020). Por encima de 35 % 
UMBRAL_PENDIENTE_EXTREMA_PCT = 35.0

# Sensibilidad (observar si oz fuera otro, cómo cambia los resultados)
# 0,536 el usado, 0,595  si el vertice CD-109A se conserva, 0,900 sin etapan 2 y eliminando solo 3 errores, 1,013 muestra v1 sin depurar.
SENSIBILIDAD_SIGMAS_M = [0.536, 0.595, 0.900, 1.013]
# None = independencia total (rho = 0).
SENSIBILIDAD_ANCHOS_M = [None, 50.0, 53.6, 75.3, 94.5, 150.0]
