"""
constantes_d1.py — Convenciones del proyecto para el Bloque D (grafo vial con pendiente).

Este modulo NO hace calculos. Solo declara las convenciones compartidas por todos
los cuadernos del proyecto.

Regla: ningun cuaderno define rutas, CRS ni URLs por su cuenta. Todo sale de aqui.
"""

from pathlib import Path
import os

# ---------------------------------------------------------------------------
# 1. RUTAS
# ---------------------------------------------------------------------------
# RUTA_PROYECTO se resuelve en este orden:
#   1. variable de entorno RUTA_PROYECTO_TESIS (util en servidores/colab)
#   2. carpeta que contiene a este archivo
# Nunca se escriben rutas absolutas dentro de los cuadernos.

RUTA_PROYECTO = Path(
    os.environ.get("RUTA_PROYECTO_TESIS", Path(__file__).resolve().parent)
)

RUTA_DATOS_CRUDOS = RUTA_PROYECTO / "datos_crudos"
RUTA_ENTREGABLES = RUTA_PROYECTO / "entregables"
RUTA_FIGURAS = RUTA_PROYECTO / "figuras"


def ruta_entregable(bloque: str, nombre_archivo: str = "") -> Path:
    """Devuelve la ruta de un entregable, creando la carpeta si hace falta.

    Ejemplo: ruta_entregable("D1", "grafo_chapinero.gpkg")
    """
    carpeta = RUTA_ENTREGABLES / bloque
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / nombre_archivo if nombre_archivo else carpeta


def ruta_cruda(nombre_archivo: str = "") -> Path:
    RUTA_DATOS_CRUDOS.mkdir(parents=True, exist_ok=True)
    return RUTA_DATOS_CRUDOS / nombre_archivo if nombre_archivo else RUTA_DATOS_CRUDOS


def ruta_figura(nombre_archivo: str = "") -> Path:
    RUTA_FIGURAS.mkdir(parents=True, exist_ok=True)
    return RUTA_FIGURAS / nombre_archivo if nombre_archivo else RUTA_FIGURAS


# ---------------------------------------------------------------------------
# 2. SISTEMAS DE COORDENADAS
# ---------------------------------------------------------------------------
# CRS_METRICO es el unico sistema en el que se calculan distancias, longitudes
# y pendientes.
#
# Muestrear en 9377 no evita reproyectar el raster: la via de getSamples
# devuelve 403 y no se usa. En la via actual (teselas por WMS) hay DOS
# reproyecciones: la tesela se pide en CRS:84 porque el WMS solo anuncia
# 4326, y luego cada punto se lleva de 9377 al CRS del raster para muestrear.
# El efecto de ese remuestreo no esta cuantificado y queda declarado como
# limitacion.
CRS_METRICO = "EPSG:9377"      # MAGNA-SIRGAS / Origen Unico Nacional
CRS_GEOGRAFICO = "EPSG:4326"   # WGS84. Descarga e intercambio.

# Nota historica (MDT 2025, sin fuente): epoca IGAC 2018.0 y alturas ortometricas
# sobre GEOCOL2004. No aplica a la produccion. Para el informe: codigo EPSG vertical
# no declarado en las fuentes; las alturas del MDT 2020 son ortometricas, del mismo
# sistema que la red de nivelacion del IGAC (sesgo de -0,12 m).

# ---------------------------------------------------------------------------
# 3. FUENTES DE DATOS
# ---------------------------------------------------------------------------
FECHA_VERIFICACION_FUENTES = "2026-09-18"

# --- Fuentes de produccion del Bloque D --------------------------------------
#   MDT        : 2020 (valores decimales). Lo muestrea el modulo de pendiente.
#   Malla Vial : Catastro, Mapa_Referencia/MapServer/13, version 2024.
#   Vertices   : 496 de 504 del IGAC con coordenada calculada; se excluyen 8 con evidencia en el propio vertice (ASPRS).
#
# Flujo: el grafo termina en segmentos y nodos, y los exporta. La pendiente la
# calcula el modulo de pendiente y vuelve unida por segmento_id. El consumo lo
# calcula el modulo de consumo.
#
# Las constantes del MDT 2025 que siguen se CONSERVAN solo porque d1_mdt.py y
# las corridas historicas de D1/D2 las importan. NO son la fuente de
# produccion. No borrar: romperia la reproduccion de corridas anteriores.
MDT_PRODUCCION_ANIO = 2020
MDT_PRODUCCION_RESPONSABLE = "modulo de terreno y pendiente"
MALLA_PRODUCCION_VERSION = "2024"

# --- Modelo Digital de Terreno de Bogota -----------------------------------
MDT_IMAGESERVER = (
    "https://serviciosgis.catastrobogota.gov.co/image/services/Imagenes/"
    "modelodigitalterreno2025funcion/ImageServer"
)
MDT_WMS = f"{MDT_IMAGESERVER}/WMSServer"

# [VERIFICADO] WMS GetCapabilities, campo <AccessConstraints>.
# OJO: esta licencia es la del servicio MDT 2025. La fuente de PRODUCCION es el
# MDT 2020, cuya licencia
# segun la ficha de IDECA es CC BY-NC-SA 4.0 (no comercial; consulta a IDECA sin
# respuesta). Los derivados de Bogota heredan esa licencia. MDT_LICENCIA se deja
# con el valor del 2025 porque lo usan las corridas historicas de D1/D2.
MDT_LICENCIA = "CC BY 4.0"
MDT_PRODUCCION_LICENCIA = "CC BY-NC-SA 4.0 (ficha IDECA, MDT 2020)"
MDT_LICENCIA_FUENTE = "WMS GetCapabilities, <AccessConstraints>"

# La pendiente OFICIAL
# (rama sigma0536_v1_1) sale del MDT 2020 de la zona urbana a 50 cm, cuya ficha en
# Datos Abiertos Bogota declara CC BY-NC-SA 4.0. Esa es la licencia que manda.
# Consecuencia para publicar: todo dato DERIVADO de el (pendientes, grafo con
# pendiente, alturas de esquina, energias y rutas) va con atribucion a IDECA/UAECD,
# solo uso no comercial y con la misma licencia. El codigo no es dato derivado y
# se publica aparte. Medellin: CC BY-SA 4.0 (respuesta de Catastro, 2026-10-27; ver MDT_MED_LICENCIA).
MDT2020_PRODUCTO = "Modelo Digital de Terreno de la zona urbana de Bogota 2020, 50 cm (IDECA/UAECD)"
MDT2020_LICENCIA = "CC BY-NC-SA 4.0"
MDT2020_LICENCIA_FUENTE = ("datosabiertos.bogota.gov.co, ficha del recurso "
                           "'Modelo Digital de Terreno de la zona urbana de Bogota' (consultada 2026-10-26)")
LICENCIA_DATOS_DERIVADOS_BOGOTA = "CC BY-NC-SA 4.0"

# [VERIFICADO] Titulo y <Abstract> del GetCapabilities.
MDT_TITULO = ("Mosaico de Modelos Digitales de Terreno (MDT) de "
              "Bogota D.C. 2025")
MDT_PRODUCTOR = "SIGLA S.A.S."
MDT_CONTRATOS = ("SDP 1047/2024 (DEM urbano y Cerros Orientales); "
                 "UAECD 369-2025 (DEM rural)")

# [SIN FUENTE] El servicio declara "2025" en su titulo y nombre, pero NO
# declara fecha de captura ni de publicacion exacta. El "2025-08-31" que
# figuraba antes aqui no tiene respaldo localizado y se retira.
# Para el informe: "MDT publicado por IDECA en 2025, elaborado por SIGLA S.A.S.
# bajo contratos SDP 1047/2024 y UAECD 369-2025. La fecha de captura no consta
# en los metadatos del servicio."
MDT_ANIO_PRODUCTO = 2025
MDT_FECHA_CAPTURA = None   # no declarada por la fuente

# [VERIFICADO] El WMS entrega el raster como uint32 con alturas redondeadas a
# metro entero. Comprobado el 2026-09-18 sobre una ventana de 256x256 px en
# ladera de los Cerros Orientales (centro -74.0400, 4.6500): 179 valores
# distintos en un rango de 178 m, cero valores con parte decimal. Se probaron
# los formatos image/tiff e image/bil; ninguno entrega decimales.
#
# CONSECUENCIA: hay un error de cuantizacion de paso/sqrt(12) = 0,289 m que es
# INDEPENDIENTE entre pixeles y por tanto NO se cancela al restar alturas de
# dos puntos cercanos. Es el piso irreducible del error de pendiente.
MDT_DTYPE_SERVICIO = "uint32"
MDT_PASO_CUANTIZACION_M = 1.0
SIGMA_CUANTIZACION_M = MDT_PASO_CUANTIZACION_M / (12 ** 0.5)   # 0.2887 m

# [VERIFICADO] <Abstract> del GetCapabilities. Son tres DEM distintos, y el
# rural NO es LiDAR: son imagenes estereoscopicas del satelite ZY3, tecnica
# de exactitud vertical mucho menor. No son comparables entre si.
MDT_COMPOSICION = {
    "urbano": {"escala": "1:1.000", "gsd": "10 cm",
               "metodo": "LiDAR aerotransportado"},
    "cerros_orientales": {"escala": "1:5.000", "pixel": "5 m",
                          "metodo": "LiDAR aerotransportado"},
    "rural": {"escala": "1:10.000", "pixel": "10 m",
              "metodo": "imagenes estereoscopicas ZY3"},
}

# [SIN FUENTE] Exactitud vertical por zona. GetCapabilities NO declara RMSE Z.
# Estos valores estaban declarados en el proyecto sin respaldo localizado.
# NO deben citarse en el informe hasta resolver su origen (tarea C2).
#
# Valores historicos. La medicion contra vertices del IGAC dio 0,54 m (sin 2
# atipicos) / 1,01 m (con todos) sobre 84 vertices, ~5 veces el 0,114 declarado
# aqui. El valor adoptado es SIGMA_Z_ADOPTADO_M (mas abajo).
MDT_RMSE_Z_DECLARADO_SIN_FUENTE = {
    "urbano": 0.100, "cerros_orientales": 0.114, "rural": 3.000,
}
MDT_RMSE_Z_MEDIDO_IGAC = {
    "sin_atipicos": 0.54, "con_todos": 1.01,
    "n_vertices": 84, "fuente": "medicion del modulo de pendiente contra vertices IGAC",
    "estado": "valor historico; el adoptado excluye 8 vertices con evidencia",
}

# sigma_z = 0,536 m, archivo de pendientes v1_1 (solo cambian las columnas de
# incertidumbre; pendientes y alturas identicas, verificado). Motivo: se amplio
# la validacion de 84 a 496 vertices del IGAC con coordenada calculada (496 de 504;
# 8 excluidos con evidencia en el vertice, guia ASPRS Flood 2004 sec. 2.6.1).
# Los 73 vertices comunes con la medicion anterior dan 0,534 m.
SIGMA_Z_ADOPTADO_M = 0.536

# RAMAS DE PENDIENTE. Cada archivo del frente de pendiente se une al grafo en su
# carpeta (entregables/D3/rama_<nombre>). Ninguna se borra. La oficial es
# RAMA_OFICIAL (sigma0536_v1_1); las demas quedan como
# registro. Todas comparten elevaciones y pendientes; solo cambia el error y la
# marca de 2 sigma.
RAMAS_PENDIENTE = {
    "sigma0538": {
        "archivo": "pendiente_sigma0538_20260920_175844.csv",
        "sigma_z_m": 0.538,
        "ancho_correlacion_m": 94.5,
        "descripcion": "RMSEz SIN los 2 puntos atipicos del IGAC",
    },
    "sigma101": {
        "archivo": "pendiente_sigma101_20260920_182450.csv",
        "sigma_z_m": 1.01,
        "ancho_correlacion_m": 94.5,
        "descripcion": "RMSEz CON todos los puntos del IGAC (atipicos incluidos)",
    },
    "sigma0533_v1": {
        "archivo": "bogota_pendientes_segmentos_mdt2020_v1.csv",
        "sha256": "796efe21eb7f49eeab6dec74d81445ecc899f0f448177d6c930e565f824594e7",
        "sigma_z_m": 0.533,
        "ancho_correlacion_m": 53.6,
        "descripcion": "Archivo final de pendientes: 77 vertices IGAC "
                       "(criterio ASPRS), ancho exponencial corregido "
                       "(160,9 / 3), 2.596 segmentos recuperados",
    },
    "sigma0536_v1_1": {
        "archivo": "bogota_pendientes_segmentos_mdt2020_v1_1.csv",
        "sha256": "445009d19b07c61d7e0e789c5ab0adf3a56a794dec8640baf54e61c4ea560c4b",
        "sigma_z_m": 0.536,
        "ancho_correlacion_m": 53.6,
        "descripcion": "Archivo de pendientes v1_1: sigma_z 0,536; solo "
                       "cambian error, ruido acumulada y marca 2 sigma",
    },
}

RAMA_OFICIAL = "sigma0536_v1_1"
# [SIN FUENTE] Epoca y datum vertical. No aparecen en GetCapabilities.
MDT_EPOCA_SIN_FUENTE = "IGAC 2018.0"
MDT_DATUM_VERTICAL_SIN_FUENTE = "ortometrico sobre GEOCOL2004"

# Rango de elevacion plausible para Bogota D.C. Fuera de el se considera
# ausencia de dato: necesario porque el uint32 codifica el NoData como 0.
# Es un umbral elegido, no medido; se reporta el conteo de descartes.
RANGO_ELEVACION_M = (2000.0, 4000.0)

# --- Malla Vial Integral de Bogota -----------------------------------------
MALLA_SERVICIO = (
    "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/"
    "Mapa_Referencia/Mapa_Referencia/MapServer/13"
)
# [VERIFICADO] campo copyrightText de los metadatos de la capa.
MALLA_FUENTE = ("Secretaria Distrital de Movilidad - SDM, Instituto de "
                "Desarrollo Urbano - IDU, Unidad Administrativa Especial de "
                "Catastro Distrital - UAECD, Secretaria Distrital de "
                "Planeacion - SDP")
MALLA_LICENCIA = "Licencia de Uso Abierta (IDECA)"

# [VERIFICADO] La capa NO declara fecha de actualizacion: editingInfo viene
# nulo. Se actualiza trimestralmente y el servicio no admite consulta
# historica. Por eso la descarga se CONGELA y la fecha de referencia es la de
# descarga, registrada con el hash del crudo. Ver d1_procedencia.py.
MALLA_DECLARA_FECHA = False
MALLA_CRS_ORIGEN = "EPSG:4326"    # sourceSpatialReference
MALLA_MAX_REGISTROS = 1000        # obliga a paginar con resultOffset

# Fecha de corte del Bloque D. Es la fecha de la descarga congelada de la
# Malla Vial, no una fecha declarada por la fuente.
FECHA_CORTE_MALLA = "2026-09-19"   # se fija al congelar; queda en el .meta.json

# Prefijo de los crudos congelados de la malla. Mismo patron que A3: la
# etiqueta dice la version de la fuente y la fecha de descarga va aparte,
# en el nombre de cada pagina y en su .meta.json.
PREFIJO_CRUDO_MALLA = "D_malla_vial_capa13_v2024"

# [VERIFICADO] Identificadores oficiales, ambos enteros. MVICODIGO se declara
# como "Identificador unico del eje vial" y es la base del segmento_id estable.
# Se cargan como pandas "string": con nulos presentes pandas infiere float y
# escribe "475409.0" (mismo defecto que aparecio en B1).
MALLA_CAMPO_ID_EJE = "MVICODIGO"
MALLA_CAMPO_CIV = "MVICIV"

# --- OpenStreetMap: SOLO para el contraste independiente -------------------
# La red vial del Bloque D sale de la Malla Vial de IDECA. OSM se usa
# unicamente en d1_malla.comparar_con_osm como verificacion independiente.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# --- Sigma vertical por zona del mosaico -----------------------------------
# El mosaico son tres DEM de calidad muy distinta (ver MDT_COMPOSICION). El
# codigo venia aplicando un solo sigma a todo el grafo, lo que subestima el
# error en zona rural por un factor cercano a diez: alli el DEM es ZY3
# estereoscopico a 10 m y no LiDAR.
#
# LIMITACION DE PROCEDENCIA: para saber que segmento cae en que DEM haria
# falta el catalogo del ImageServer, que devuelve HTTP 403 (verificado
# 2026-09-18, registrado en la bitacora). La asignacion se hace por un PROXY
# declarado: la clasificacion POT rural y las localidades con territorio
# rural. No es exacta y va deliberadamente del lado conservador.
SIGMA_Z_POR_ZONA = {
    # LiDAR. El valor es [SIN FUENTE] y esta en conflicto con la medicion
    # contra vertices del IGAC; la tabla de sensibilidad recorre las alternativas.
    "lidar": 0.114,
    # ZY3 estereoscopico a 10 m.
    "zy3_rural": 3.000,
}

# Localidades con territorio rural significativo. Proxy para la zona ZY3.
LOCALIDADES_CON_RURAL = {"USME", "CIUDAD BOLIVAR", "SANTA FE",
                         "SAN CRISTOBAL", "CHAPINERO", "USAQUEN", "SUBA"}

# Candidatos de sigma_z LiDAR para la tabla de sensibilidad. Las dos ultimas
# son la medicion empirica contra 84 vertices del IGAC.
SIGMA_Z_CANDIDATOS = {
    "declarado_sin_fuente": 0.114,
    "igac_sin_atipicos": 0.540,
    "igac_con_todos": 1.010,
}

# Ancho de correlacion espacial del error del MDT, en metros.
# Valor historico de 94,5 m del modulo de pendiente: suponer independencia
# (rho = 0) infla el error de mas. Modelo exponencial: rho(d) = exp(-d / ancho).
#
# LIMITACION DECLARADA: 94,5 m sale de una grilla SIMULADA, no de una medicion
# sobre el raster real: el MDT 2020 nunca se pudo descargar completo. Se
# reporta la sensibilidad del resultado a este valor (sin correlacion, 50 m,
# 94,5 m y 150 m).
#
# Sustituye el valor anterior (None = independencia), que se usaba en el
# calculo de pendiente con el MDT 2025, hoy en el cuaderno historico.
# El ancho vigente es 53,6 m (94,5 era el rango
# de un modelo gaussiano; el exponencial es 160,9 / 3). El valor vigente viaja en
# RAMAS_PENDIENTE[RAMA_OFICIAL]["ancho_correlacion_m"]. Esta constante se conserva
# en 94,5 solo para reproducir corridas historicas de D1/D3; D4 no la usa.
ANCHO_CORRELACION_M = 94.5

# ---------------------------------------------------------------------------
# 4. PARAMETROS DEL BLOQUE D
# ---------------------------------------------------------------------------

# Longitud minima para que un segmento no se considere lazo degenerado.
# Se decide por geometria y no por identidad de nodos, para que el conjunto
# de segmentos no dependa de la tolerancia de la rejilla. El valor es la
# tolerancia de nodo tipica: por debajo de eso los dos extremos son el mismo
# punto a efectos practicos.
LONGITUD_MINIMA_LAZO_M = 2.0

# Rejilla para identificar nodos: dos extremos en la misma celda de 2 m son
# el mismo nodo. Acordado en el documento de parametros compartidos.
# id_nodo(x, y) = f"{round(x/2.0)}_{round(y/2.0)}", en EPSG:9377.
TOLERANCIA_NODO_M = 2.0

# Clases POT (campo MVITCLA) que admite un vehiculo particular.
# Excluidas: 4 peatonal, 7 proyectada.
CLASES_VEHICULO = {1, 2, 3, 5, 6}

# Formato del identificador de segmento (convencion comun a todos los modulos):
#   <MVICODIGO>_<parte>_<FT|TF>
# FT = recorre el eje en el sentido en que esta digitalizado; TF = al reves.
# SIGNO DE LA PENDIENTE: positiva = sube en el sentido de recorrido de ESA
# fila. Por eso el inverso de un tramo tiene la pendiente con signo opuesto.
FORMATO_SEGMENTO_ID = "<MVICODIGO>_<parte>_<FT|TF>"

# Cota de plausibilidad: la calle mas empinada registrada (Baldwin Street, Guinness) tiene 34,8 %. Por
# encima de 35 % la pendiente es poco plausible pero NO necesariamente falsa
# (en la franja 35-50 % el 62 % son calles reales). Marca valores de baja
# confianza: calles reales, vias no visibles, escaleras o errores del MDT
# (puente, deprimido, talud). NO detecta todos los puentes.
UMBRAL_PENDIENTE_EXTREMA_PCT = 35.0

COLUMNAS_RETORNO_PENDIENTE = [
    "segmento_id",
    "pendiente_neta_pct", "pendiente_acumulada_pct",
    "ganancia_elevacion_m", "perdida_elevacion_m",
    "z_inicio_m", "z_fin_m",
    "n_puntos_muestreados", "paso_muestreo_m",
    "clasificacion_invias",
    "error_pendiente_pct", "distinta_de_cero_2sigma", "ruido_acumulada_pct",
    "pendiente_extrema", "fuera_cobertura_mdt",
    "rho_correlacion", "ancho_correlacion_m", "sigma_z_m",
]

# Distancia entre puntos de muestreo de elevacion a lo largo de cada segmento.
# 10 m es un compromiso: mas fino que la resolucion del DEM de cerros (5 m) seria
# muestrear ruido de interpolacion; mas grueso perderia la forma del perfil.
PASO_MUESTREO_M = 10.0

# Numero maximo de puntos por peticion a getSamples. El servicio acepta mas,
# pero lotes grandes producen timeouts.
LOTE_MUESTREO = 400

# Longitud minima de segmento para que su pendiente sea reportable.
#
# LA JUSTIFICACION ANTERIOR QUEDO VACIA. Decia: "con RMSE Z de 0,10 m, para
# L = 20 m el error estandar de la pendiente es 0,7 %". Pero 0,10 m es el
# valor [SIN FUENTE] de zona urbana. Con los valores reales:
#     sigma(L=20 m) = sqrt(2)*sigma_z/20
#       sigma_z = 0,100 m  ->  0,7 %   (el del comentario viejo)
#       sigma_z = 0,310 m  ->  2,2 %   (cuantizacion + LiDAR cerros)
#       sigma_z = 0,540 m  ->  3,8 %   (medicion contra vertices IGAC)
#
# El umbral se mantiene en 20 m por continuidad con D1. Con el sigma_z adoptado
# (0,536 m) el error a 20 m es 3,8 %; el umbral sigue sin justificacion propia
# (LONGITUD_MINIMA_JUSTIFICADA = False). Se reporta la sensibilidad
# (cuantos segmentos quedan confiables con cada sigma), igual que se hizo con
# el umbral textual del B3.
LONGITUD_MINIMA_PENDIENTE_M = 20.0
LONGITUD_MINIMA_JUSTIFICADA = False
# Tipos de via de OSM que admite un vehiculo particular.
FILTRO_OSM_VEHICULO = (
    '["highway"]["area"!~"yes"]'
    '["highway"!~"cycleway|footway|path|pedestrian|steps|track|corridor|'
    'elevator|escalator|proposed|construction|bridleway|abandoned|platform|raceway"]'
    '["motor_vehicle"!~"no"]["motorcar"!~"no"]'
    '["service"!~"parking|parking_aisle|driveway|private|emergency_access"]'
)

# ---------------------------------------------------------------- D2 Medellín
URL_SENTIDO_VIAL_MED = "https://www.medellin.gov.co/servidormapas/rest/services/mapas_nacionales/VC_Transporte/MapServer/3"
URL_MDT_MED_SERVICIO = "https://www.medellin.gov.co/servidormapas/rest/services/ServiciosImagen/Modelo_digital_de_elevacion_medellin_2024/ImageServer"
FECHA_CORTE_SVIAL_MED = "2026-09-21"
PREFIJO_CRUDO_SVIAL_MED = "sentido_vial_med"
LOTE_SVIAL_MED = 500

# nombre del archivo congelado -> URL (se congelan con sha256 en la celda 2)
URLS_METADATOS_MED = {
    "sentido_vial_capa.json": URL_SENTIDO_VIAL_MED + "?f=pjson",
    "sentido_vial_ficha.xml": "https://www.medellin.gov.co/giscatalogacion/srv/api/records/b571f498-75c4-4554-b278-cf72c05498a2/formatters/xml",
    "mdt_2021_ficha.xml": "https://www.medellin.gov.co/giscatalogacion/srv/api/records/440571dd-7f89-40aa-bcf9-0b99b311ca1d/formatters/xml?output=xml",    "mdt_servicio_2024.json": URL_MDT_MED_SERVICIO + "?f=pjson",
    "licencia_banco_imagenes_abierta.pdf": "https://www.medellin.gov.co/servicios/metadatos_gis/BancoImagenes/Terminos/Abierta.pdf",
}
URLS_METADATOS_MED_LEGIBLES = {
    "mdt_2021_ficha": "https://www.medellin.gov.co/giscatalogacion/srv/api/records/440571dd-7f89-40aa-bcf9-0b99b311ca1d",
    "sentido_vial_ficha": "https://www.medellin.gov.co/giscatalogacion/srv/api/records/b571f498-75c4-4554-b278-cf72c05498a2",
}

RUTA_EXCLUSION_OSM_MED = RUTA_PROYECTO / "salidas_medellin_prueba_osm" / "20260925_011846" / "D2M_exclusion_no_vehicular_osm.csv"
SHA256_EXCLUSION_OSM_MED = "3cb1c8c8662c5b69486d70f0e462c3b2deee9630277843c71ecbca7a219d64ff"


# ---------------------------------------------------------------- D4 estaciones
# Insumos de estaciones de carga para D4. No se escriben rutas: D4 los busca por
# nombre bajo las carpetas de los bloques A y B y usa SOLO la copia cuyo sha256
# coincide con el registrado. Los hashes se copiaron de B3_manifiesto_insumos.json
# (B3 los registro al consumir estos archivos); D4 comprueba ademas que ese
# manifiesto en disco diga lo mismo.


# ---------------------------------------------------------------- D3/D4 Medellín
# MDT de Medellin. El .TIF del DTM-LiDAR 2021 declara EPSG:6257 (MAGNA-SIRGAS /
# Medellin urban grid), NO EPSG:9377 como decia el contrato D2M. La red esta en
# 9377: el muestreo lleva cada punto al CRS del raster antes de leer la altura.
# Alineacion verificada.
MDT_MED_PRODUCTO = "DTM-LiDAR Medellín 2021, 1 m (Subsecretaría de Catastro)"
MDT_MED_CRS = "EPSG:6257"
# LICENCIA (respuesta de Catastro Medellin, radicado 202630563893 del 2026-10-27, a la
# peticion 202610353641 del 2026-09-25): CC BY-SA 4.0 (Circular Conjunta 202660000054 de
# 2026). Permite derivados, incluso comerciales, con atribucion y misma licencia. La
# aceptacion de terminos al descargar es la autorizacion; no requiere convenio.
MDT_MED_LICENCIA = "CC BY-SA 4.0"
MDT_MED_LICENCIA_FUENTE = "Respuesta Catastro Medellin, radicado 202630563893 (2026-10-27)"
LICENCIA_DATOS_DERIVADOS_MEDELLIN = "CC BY-SA 4.0"
ATRIBUCION_MDT_MED = "Medellín (Colombia). Recuperado el {fecha}, de https://www.medellin.gov.co/mapgis9/mapa.jsp?aplicacion=49"

# Tuneles (Tunel de Occidente y tramos del Tunel de Oriente): el MDT mide la
# montana, no la via. Regla: pendiente de boca a
# boca, solo dos puntos (entrada y salida): n_puntos_muestreados = 2 y
# acumulada = |neta|. Se marcan con la columna es_tunel, que solo existe en
# Medellin; por eso el contrato de Medellin tiene una columna mas que el de
# Bogota (la lista de Bogota NO se toca).
COLUMNAS_RETORNO_PENDIENTE_MED = COLUMNAS_RETORNO_PENDIENTE + ["es_tunel"]

# Pendiente de Medellin: dos ramas; la oficial es RAMA_OFICIAL_MED.
#   sigma_z 0,539 m (oficial): medido contra los 9 vertices utiles del IGAC en
#   Medellin. El 0,10 m es el RMSEz declarado en la ficha del DTM-LiDAR 2021 y
#   queda como sensibilidad (rama med_sigma010).
#   ancho 59,2 m: medido con el mismo metodo de Bogota.
RAMAS_PENDIENTE_MED = {
    "med_sigma010": {
        "archivo": "medellin_pendientes_segmentos_dtm2021_v2.csv",
        "sha256": "96bfac06f66020792d1cd923d48faca688aceb4bb997ca10ccddc946a2ea490d",
        "sigma_z_m": 0.10,
        "ancho_correlacion_m": 59.2,
        "descripcion": "sigma_z de la ficha oficial (RMSEz "
                       "0,1 m), solo sensibilidad; ancho 59,2 m medido",
    },
    "med_sigma054": {
        "archivo": "medellin_pendientes_segmentos_dtm2021_v3.csv",
        "sha256": "2aaba7230df0845116775e5100d3bc9292f67c4041a33aed1082d28d69f68e5e",
        "sigma_z_m": 0.539,
        "ancho_correlacion_m": 59.2,
        "descripcion": "sigma_z 0,539 m; ancho 59,2 m; v3, "
                       "misma pendiente que v2, solo cambian error, marca 2 sigma y ruido",
    },
}
RAMA_OFICIAL_MED = "med_sigma054"
SIGMA_Z_ADOPTADO_MED_M = 0.539
RUTA_TESIS = RUTA_PROYECTO.parent
CARPETAS_BLOQUES_AB = [RUTA_TESIS / "Bloque A", RUTA_TESIS / "Bloque B"]
MANIFIESTO_REFERENCIA_ESTACIONES = "B3_manifiesto_insumos.json"
INSUMOS_ESTACIONES_D4 = {
    "B2_1_clasificacion_verificada.csv":
        "b0a2e926cf09b73c3273bc0b10e35ed5ee9d2b9f7f2798607d4780fde6253337",
    "A2_estaciones_OSM_Bogota.geojson":
        "99f132a15e2a87e96f2e6f2482ff7756928b5ddcafbe233e6366ebf71cfe83f9",
    "A3_OpenChargeMap_Bogota_estaciones.csv":
        "cb12e624d5aa1856b3c2422ac9f67908365d0409ac89721553841702ddc80172",
    "B1_fusiones_internas.csv":
        "e8544de7dff500aa3864cbf6e3962b8456ec4aba0c43ee10fd44699ebd3a2c10",
}


# ---------------------------------------------------------------- D4 escenarios
# Escenarios de la RED (que aristas se usan). Se corren todos; el oficial es
# ESCENARIO_OFICIAL_D4 y los demas son sensibilidad. Ninguno se borra.
#   bloquear_extremas        : excluir aristas con pendiente_extrema (> 35 %)
#   tratamiento_sin_altura   : "E" = excluir las sin altura con highway rural,
#                              las demas con pendiente 0 marcada;
#                              "A" = todas las sin altura con pendiente 0
#   incluir_sentido_supuesto : conservar las aristas SD/N (doble sentido supuesto)
# Orden fijo: excluir -> recalcular componente fuerte -> (despues) estaciones.

ESCENARIOS_D4 = {
    "base": {
        "rol": "base",
        "bloquear_extremas": False, "tratamiento_sin_altura": "E",
        "incluir_sentido_supuesto": True,
        "descripcion": "sin bloquear >35 %, sin altura E, con SD/N"},
    "sens_bloquear_extremas": {
        "rol": "sensibilidad",
        "bloquear_extremas": True, "tratamiento_sin_altura": "E",
        "incluir_sentido_supuesto": True,
        "descripcion": "bloquea >35 %"},
    # RED OFICIAL (ESCENARIO_OFICIAL_D4). Las calles sin altura usan la altura
    # ESTIMADA de sus esquinas, no pendiente 0. "rol" y "descripcion" son las
    # etiquetas con que se creo el escenario; quedan asi porque las copia D4 Medellin.
    "sens_sin_altura_A": {
        "rol": "sensibilidad",
        "bloquear_extremas": False, "tratamiento_sin_altura": "A",
        "incluir_sentido_supuesto": True,
        "descripcion": "todas las sin altura con pendiente 0"},
    "sens_sin_SDN": {
        "rol": "sensibilidad",
        "bloquear_extremas": False, "tratamiento_sin_altura": "E",
        "incluir_sentido_supuesto": False,
        "descripcion": "quita las aristas de sentido supuesto SD/N"},
    "sens_bloquear_y_sin_SDN": {          # cruce de las dos sensibilidades
        "rol": "sensibilidad",
        "bloquear_extremas": True, "tratamiento_sin_altura": "E",
        "incluir_sentido_supuesto": False,
        "descripcion": "bloquea >35 % y quita SD/N (las dos cortan ladera)"},
}
# Red oficial: no bloquear > 35 %, altura estimada en las esquinas sin dato, SD/N en
# doble sentido, y castigo k a los tramos > 35 %. Todas las celdas de D4 calculan con
# esta constante. Los otros 4 escenarios quedan como sensibilidad.
ESCENARIO_OFICIAL_D4 = "sens_sin_altura_A"
CRITERIO_RURAL_SIN_ALTURA = ("highway", "rural")   # regla de la opcion E

# Muestra uniforme v1 (la oficial es la estratificada, mas abajo). Se conservan
# porque son la semilla de otras validaciones (celdas 8b, 11, 19, 21).
N_PARES_OD_D4 = 5000
SEMILLA_OD_D4 = 20260926


# ---------------------------------------------------------------- D4 consumo
# Modelo de consumo. Sin zip original: los hashes se registran sobre los archivos
# tal como estan en la carpeta al integrar (limitacion anotada en la bitacora).
# Nadie edita esta carpeta.
CARPETA_MODELO_CONSUMO = RUTA_PROYECTO / "modelo_consumo"
ARCHIVOS_MODELO_CONSUMO = {          # registrados al integrar
    "interfaz_grafo.py":   "6b8b9d54f23a29342da04561201acf417fd2d4706a9e407cc87265610e44828d",  
    "modelo.py":           "30bc8dc7c4aec48131ebd84154f1ce671578baba0fd07f97f9b101609dbe9a41",
    "parametros.py":       "41d8d5cc490f904d91c8a954f64983c328450a75eab34349131b6a35b21050ca",
    "vehiculos_flota.py":  "2c20c77b402938ccd881d56ffdd4607270e1724d8c7c66cbfb8a23e0453c2cd5",
    "franjas_horarias.py": "58269c0a7f594f9129a829ddc9b36efe93c398de6d968949e14a305c86f93b0f",
    # Capa 2 (arrancar y frenar)
    "capa2_paradas/capa_paradas.py":             "619138cd7bd5af82f9b78559a60ac6e0cbd86765ec79195eeed597ce48ce6912",
    "capa2_paradas/_capa1.py":                   "d913cac8bbc8e100e2cca379cad6c6510c3dd7601f7134cf7186703a65c829e4",
    "capa2_paradas/capa_paradas_tabla_pke.csv":  "e89e182e1a6101d26f26dc5f34204ed26519460ff8dc4974ef5528bcfc92f19d",
    "capa2_paradas/capa_paradas_coef_flota.csv": "3fbae331d01f7e2ddddebc9bb0ae6524120114da7f148f67c2afb6c474b7e73e",
}

# Capa 2: a cada tramo se le suma el gasto extra de arrancar y frenar,
#   extra = k_vehiculo * PKE(velocidad de la zona) * longitud_inclinada_km / 1000.
# Calibrada con velocidades reales de Ann Arbor (eVED) y su modelo completo; NO con
# baterias medidas ni con datos de Bogota; terreno plano. True = principal; la
# celda 12 corre ademas una vez la otra opcion como sensibilidad.
CAPA_PARADAS_D4 = True

# Carro base, franjas y forma de la pendiente
VEHICULO_BASE_D4 = "byd_dolphin_449"
VEHICULOS_VALIDADOS_D4 = {"byd_dolphin_449", "chevrolet_spark_euv", "kia_ev5_light",
                          "mg4_electric_urban", "kia_ev9_gtline"}   # criterio A del modelo de consumo
HORA_BASE_D4 = 12.0                                  # valle de dia
HORAS_POR_FRANJA_D4 = {"pico_manana": 7.0, "valle_dia": 12.0, "pico_tarde": 17.5,
                       "valle_noche": 21.5, "madrugada": 2.0}
PENDIENTE_CONSUMO_D4 = "extremos"    # "extremos" (principal) | "acumulada" (sensibilidad,
                                     # celda 12)
LONGITUD_CONSUMO_D4 = "inclinada"    # la formula usa la longitud a lo largo de la
                                     # pendiente; corrige los 4
                                     # terminos (rodadura, aire, gravedad, auxiliares)
CIUDAD_CONSUMO_D4 = "bogota"
LOCALIDADES_SIN_TABLA_VELOCIDAD = {"sumapaz"}   # sin sensores Bitcarrier


# ---------------------------------------------------------------- D4 decisiones
# Tramos > 35 %: revision visual en Street View (los 52 mas empinados, uno por
# calle). Se guarda intacto en datos_crudos/recibidos.
ARCHIVO_REVISION_EXTREMAS = "revision_52_extremas_bogota.csv"

# Estaciones: coordenada elegida cuando la estacion esta en OCM y OSM y las
# dos caen en esquinas distintas (revision visual en satelite).
# Clave = ocm_id; se verifica contra la fila y el osm_uid (la fila sola es
# posicional y podria moverse). "desempate" = no se distingue en satelite;
# se usa el punto mas cercano a la red base (medido en la celda 3b).
VEREDICTOS_COORDENADA_D4 = {
    #  ocm_id : (fila, osm_uid, fuente, motivo)
    "302194": (3, "node/13009697994", "osm",
               "OSM al borde del parqueadero abierto; OCM contra la pared, en la esquina"),
    "472671": (4, "node/13009961999", "ocm",
               "desempate: no se distingue (enganche OCM 70.0 m vs OSM 82.8 m)"),
    "132440": (8, "node/6876729187", "ocm",
               "desempate: no se distingue (enganche OCM 41.0 m vs OSM 54.9 m); OCM en el frente del concesionario"),
    "311258": (9, "node/13015491671", "ocm",
               "OCM en el parqueadero grande; OSM sobre el techo, enganche de 124 m a la Av. 68"),
    "475122": (10, "node/13009418551", "osm",
               "desempate: no se ve la gasolinera en ninguno (enganche OSM 17.9 m vs OCM 49.6 m); par no sostenido por B3"),
    "470940": (11, "node/13010048854", "ocm",
               "OSM en la mitad de una cancha sintetica; par marcado como invertido en B1 y no sostenido por B3"),
    "302193": (12, "node/13009696528", "ocm",
               "OCM al final de un parqueadero, a 7 m de su esquina; OSM dentro de un parque junto a canchas"),
}
# C5 (puntos secundarios): un punto por estacion, el principal. Los
# secundarios no se usan para rutear (observacion visual en la celda Markdown).
USAR_PUNTOS_SECUNDARIOS_C5 = False
# Enganche: esquina mas cercana de la red de cada escenario. El umbral solo
# MARCA enganches lejanos; es la escala de manzana medida en B2 (~101.7 m).
UMBRAL_ENGANCHE_LEJANO_M = 100.0


# ---------------------------------------------------------------- D4 alcanzabilidad
# Pregunta: desde cada esquina de la red, energia minima para llegar a ALGUNA
# estacion de carga; alcanzable si cabe en la bateria disponible sobre la reserva.
NIVELES_BATERIA_D4 = (0.20, 0.50, 0.80)   # fraccion de bateria al salir
RESERVA_BATERIA_D4 = 0.10                 # nadie maneja hasta 0 %
# SOLO sensibilidad pesimista (columnas _pesimista): a velocidad constante el
# modelo subestimaba el consumo 25-40 % en una ruta real de montana (bitacora
# del modelo, sec. 22-25). La capa 2 ya corrige eso, asi que el escenario oficial
# va SIN este factor. Se aplica (x1,4) sobre el consumo de cada tramo que gasta;
# lo que recuperan las bajadas no se multiplica (celda 15).
FACTOR_SUBESTIMACION_D4 = 1.40
CURVA_BATERIA_PCT_D4 = tuple(range(0, 31))  # % de bateria disponible para la curva
N_ESQUINAS_VERIFICACION_D4 = 20
SHA256_REVISION_EXTREMAS = "7a451b1bdbf0217a97e887eb683cb022e1b603c0a6ce7019f30ed04a4b9973a4"
# Ascenso acumulado por km en linea recta origen -> destino (5.250 viajes, paso 50 m),
# para la segunda estratificacion de terreno. En datos_crudos/recibidos/.
SHA256_ASCENSO_BOG = "37c82cf6aa068bfae0df6afc9b2b41c1a0dcf928ccc7981db9fa385f8f98ba35"
# Lo mismo para Medellin (4.200 viajes, paso 50 m, sigma_z 0,539, rama med_sigma054).
ARCHIVO_ASCENSO_MED = "ascenso_linea_recta_medellin.csv"
SHA256_ASCENSO_MED = "3ce2a9822cd66a276762ac224216c97b78976dcfc364d0085c17a20f660c225b"
# Segunda estratificacion por ascenso (regla fijada ANTES de cruzar con el
# ahorro; ver regla_cortes_ascenso.md). Cortes = terciles de la distribucion
# ponderada de las dos ciudades juntas (cada ciudad pesa lo mismo), valores EXACTOS; en el
# texto se escriben 7,6 y 30,3 m/km. Los mismos cortes en las dos ciudades.
CORTES_ASCENSO_M_KM = (7.585675172081233, 30.303668922427057)
NOMBRES_GRUPO_ASCENSO = ("bajo", "medio", "alto")
MAX_FRACCION_SIN_DATO_ASCENSO = 0.10   # sale el viaje si mas del 10 % de sus puntos no tiene dato
# Reparto que quedo escrito en la regla (viajes por grupo); la celda 20e lo comprueba.
REPARTO_ASCENSO_MED = {"bajo": 465, "medio": 1281, "alto": 2451}
REPARTO_ASCENSO_BOG = {"bajo": 1760, "medio": 1626, "alto": 1794}

# ---------------------------------------------------------------- D4 pendientes extremas: castigo k
# Los tramos con pendiente_extrema NO se quitan: su peso de RUTEO se multiplica por k,
#   peso = k * max(consumo SIN recuperar en la bajada, consumo del mismo tramo en plano)
#   (nunca negativo). La regla da k = 50.
# La energia que se REPORTA es siempre la real. k = 0 significa SIN castigo: es la
# comparacion principal (ruta de minimo consumo); k = 50 es la restriccion de pendiente.
# k se elige con datos en la celda 12: 500 pares (semilla 42), candidatos de abajo,
# y el menor k desde el cual el % de rutas con tramo extremo baja menos de 1 punto
# frente al k siguiente (y asi hasta el final).
FACTORES_EXTREMAS_CANDIDATOS_D4 = (1, 2, 5, 10, 20, 50, 100)
N_PARES_ELEGIR_K_D4 = 500
SEMILLA_ELEGIR_K_D4 = 42
UMBRAL_CAMBIO_K_PUNTOS_D4 = 1.0
FACTOR_EXTREMAS_D4 = 50.0               # el valor que da la regla; la celda 12 lo comprueba
CASTIGO_EXTREMAS_PRINCIPAL_D4 = True    # True = las corridas de 12 carros, franjas y alcanzabilidad usan k = 50
EXTREMAS_POR_ALTURA_ESTIMADA_D4 = True  # incluir tramos SIN dato del MDT con |pendiente estimada| > 35 %
                                        # (solo 68395_0), en columna aparte

# --- D4: validacion de la altura estimada ("esconder y adivinar") ---------------
N_BLOQUES_VALIDACION_ALTURAS = 1000      # bloques escondidos, con tamanos de huecos reales
K_VECINOS_VALIDACION = (1, 4, 8, 16)     # vecinas mas cercanas en el mapa (KNN)
POTENCIA_IDW = 2                         # peso = 1 / distancia^2

# =============================================================================
# D4 MEDELLIN (D4M) — ruteo con energia. Cuaderno: D4_ruteo_medellin.ipynb
# =============================================================================
# Mismo metodo que D4 de Bogota. Lo que es METODO (pares, semillas, carro base,
# franjas, capa 2, regla de k, bateria, estaciones) se toma de las constantes de
# D4 de Bogota, para que las dos ciudades se corran exactamente igual. Aqui solo
# va lo que es propio de Medellin. Nada de esta seccion cambia a Bogota.
# Salidas: entregables/D4_medellin/

# --- Escenarios de red (mismos 5 de Bogota; la regla "rural" es la de Medellin) ---
# "sin altura": en Medellin solo 2 aristas (1 calle, Antigua via al mar) quedan
# fuera del MDT, asi que los escenarios de altura casi no cambian la red; se
# corren igual para que las tablas de las dos ciudades tengan la misma forma.
ESCENARIOS_D4M = ESCENARIOS_D4
# Rural en Medellin = jerarquia operativa 6 (cabecera de corregimiento) o
# 7 (vias inter-veredales). En Bogota era highway == "rural".
CRITERIO_RURAL_SIN_ALTURA_MED = ("jerarquia_op", (6, 7))
ESCENARIO_OFICIAL_D4M = "sens_sin_altura_A"     # misma red oficial que Bogota

# --- Modelo de consumo (carpeta v2, con el modulo de Medellin) ------------------
# Los 9 archivos de Bogota tienen EXACTAMENTE los mismos hashes que la carpeta
# de Bogota (verificado): es el mismo modelo. Se suman los 3 de Medellin.
CARPETA_MODELO_CONSUMO_MED = RUTA_PROYECTO / "modelo_consumo_v2"
ARCHIVOS_MODELO_CONSUMO_MED = {
    **ARCHIVOS_MODELO_CONSUMO,
    # vehiculos_flota.py de v2 cambia SOLO metadatos de validacion
    # (Tang consumo_wltp 23,8 -> 21,6; Kwid 8,99 -> 11,65 y 298 -> 230 km). Ningun
    # parametro fisico cambia y D4 no usa esos campos: los resultados de D4M no cambian.
    "vehiculos_flota.py": "90b9f579d2fb48a855fe032a3136ca82005265b35a1504c28461cc197ba5080c",
    "medellin/franjas_medellin.py":
        "4ad72a1a55c53c8b63eb435d65dc86c02bd1e500c61d43004de3c72010dbce56",
    "medellin/interfaz_medellin.py":
        "9c7a7af2fdbcb78dc9565d0ee602ff2d36865e7556bcdcdec017792f506ff6e0",
    "medellin/velocidad_medellin_por_tipo_via_franjas_modelo.csv":
        "297a4311c39561a4aafb6901bd2b2ac6cd0b7441efa028344b59f91909e92f29",
}
CIUDAD_CONSUMO_D4M = "medellin"     # densidad del aire a 1.495 m (parametros.py del modelo)

# --- Velocidad: tipo de via (continuo / interrumpido) por NOMBRE de calle --------
# Los datos de velocidad (MEData, 2018-2019) miden 4
# corredores "continuos": Autopista Norte, Autopista Sur, Av. Regional y Av. Las
# Palmas. Aqui van sus calzadas principales tal como se llaman en el grafo; las
# glorietas, salidas, lazos y conectores a la Calle 19 quedan como interrumpidas.
# Todo lo demas es "interrumpido" (supuesto 2 del modelo de consumo).
CORREDORES_CONTINUOS_MED = (
    "AP Norte >(N)", "AP Norte >(S)", "AP Norte (N)",
    "AP Sur / Calz Derecha", "AP Sur / Calz Izquierda",
    "Regional Oriental",
    "Av. Las Palmas >Occidente", "Av. Las Palmas >Oriente",
    "Av, Las Palmas - Occidente", "Vía Las Palmas",
)
# Vias rapidas SIN medicion de velocidad: se tratan como interrumpidas (False).
# True = tratarlas como continuas (sensibilidad; correr en una carpeta nueva).
VIAS_RAPIDAS_SIN_MEDICION_MED = (
    "Conexión vial Guillermo Gaviria Correa", "Tunel De Occidente",
    "Tunel de Oriente", "Tunel de oriente",
)
VIAS_SIN_MEDICION_COMO_CONTINUAS_MED = False
# Madrugada sin dato propio en Medellin: "central" (razon 1,72 de Bogota);
# "baja"/"alta" son la sensibilidad.
MADRUGADA_D4M = "central"

# --- Pendientes extremas: castigo k (misma regla que Bogota, k propio) ----------
FACTOR_EXTREMAS_D4M = 50.0          # mismo k que Bogota en las dos ciudades. La regla en
                                    # Medellin da k = 1; se corre como sensibilidad.
                                    # None = usar el k de la regla.
# k que dio la misma regla en Bogota. Se corre como sensibilidad en
# Medellin para poder comparar las dos ciudades con el mismo castigo.
K_REFERENCIA_BOGOTA_D4M = 50

# --- Estaciones de carga ---------------------------------------------------------
# Inventario de B2.1 (19 estaciones fisicas en Medellin), verificado contra el
# manifiesto de B3. Hashes copiados de B3_manifiesto_insumos.json.
INSUMOS_ESTACIONES_D4M = {
    "B2_1_clasificacion_verificada.csv":
        "b0a2e926cf09b73c3273bc0b10e35ed5ee9d2b9f7f2798607d4780fde6253337",
    "A2_estaciones_OSM_Medellin.geojson":
        "69a8c0bafbf86fce86b81eb4c1b13dc37af2927a61bf00f1148c9b1a8d1cb54c",
    "A3_OpenChargeMap_Medellin_estaciones.csv":
        "02767749ab5e1857c41d27485bd1841824cb3e280a2d6910113f90218c68fcad",
    "B1_fusiones_internas.csv":
        "e8544de7dff500aa3864cbf6e3962b8456ec4aba0c43ee10fd44699ebd3a2c10",
}
# Se quitan SOLO en D4M (B no se toca). Clave = osm_uid u ocm_id.
ESTACIONES_EXCLUIDAS_D4M = {
    "way/770877089": "OSM dice motorcar=no, bicycle=yes: cargador de bicicletas, no de carros",
}
# Coordenada elegida cuando la estacion esta en OCM y OSM y caen en esquinas
# distintas. Misma forma que VEREDICTOS_COORDENADA_D4 de Bogota.
VEREDICTOS_COORDENADA_D4M = {
    #  ocm_id : (fila, osm_uid, fuente, motivo)
    "311395": (56, "node/9902522850", "osm",
               "desempate: no revisado en satelite; se usa el punto mas cercano a la red "
               "base (OSM 22.8 m vs OCM 63.0 m)"),
}
# Voltex Autopista Norte: B la dejo como DOS estaciones (OCM 311396 y OSM
# node/13009470546, a 0,9 km). No se toca B: se usan las dos y se declara.


# ---------------------------------------------------------------- D4 sensibilidad: semaforos y giros
# Sensibilidad pedida para responder "y si el gasto de frenar se concentra en semaforos y
# giros?" (version E3 del modelo de consumo, bitacora 27.16). NO cambia los resultados
# principales. Usa dos archivos de la carpeta v2 del modelo que D4 no usaba (huellas abajo; la celda
# 15d las imprime la primera vez si estan en None).
CARPETA_MODELO_CONSUMO_V2 = RUTA_PROYECTO / "modelo_consumo_v2"
ARCHIVOS_EVENTOS_CONSUMO = {
    "capa2_paradas/paradas.py": "c6f03403a7b1a93c6f34270000a049922e403058aa18b5fadf9e0ec9b156b222",
           "capa2_paradas/datos/red_semaforica_vehicular.geojson": "8f3865489ee1423697bc0c719de68ccc58d6470b9eb7049539306048a6e8a57e",
}
# Supuestos SIN fuente de Bogota (los del modelo de consumo, para que sea comparable con su prueba):
#   umbral_semaforo_m : un semaforo se asigna a la esquina de la red mas cercana a <= 40 m
#   p_min             : probabilidad minima de frenar en un semaforo (p = 1 - v_franja/v_madrugada, recortada)
#   q_giro            : un giro en esquina sin semaforo cuesta esta fraccion de una frenada completa
#   angulo_giro       : desde cuantos grados cuenta como giro
#   vecinas_esquina   : una esquina es interseccion si llegan 3 o mas calles distintas
SENS_EVENTOS_D4 = {"umbral_semaforo_m": 40.0, "p_min": 0.25, "q_giro": 0.5,
                   "angulo_giro": 45.0, "vecinas_esquina": 3}
# Cada supuesto se mueve uno a la vez (Dolphin, hora pico de la tarde)
VARIANTES_EVENTOS_D4 = (("p_min", 0.5), ("p_min", 1.0), ("q_giro", 0.25), ("q_giro", 1.0),
                        ("angulo_giro", 30.0), ("angulo_giro", 60.0))
HORA_VARIANTES_EVENTOS_D4 = 17.5

# La bitacora oficial ya no se escribe a mano: la celda 23 toma la de la ultima
# corrida en entregables/D4, calcula su huella y la deja en D4_version_oficial.json.


# ---------------------------------------------------------------- D4 muestra estratificada
# La muestra uniforme de 5.000 pares (semilla 20260926) tenia solo 249 viajes con
# las dos puntas en ladera y 183 de menos de 2 km. Por eso la muestra oficial es
# ESTRATIFICADA: 3 terrenos x 5 bandas de
# distancia en linea recta, 350 pares por casilla (15 x 350 = 5.250 pares).
#   - terreno: esquina en ladera si su altura MEDIDA > mediana de las esquinas
#     de la ciudad + MARGEN_LADERA_M (Bogota: 2.555,2 + 50 = 2.605,2 m).
#     plano = ninguna punta en ladera; ladera = las dos; cruzado = una.
#   - 350 por casilla: con 350 viajes, un porcentaje cerca de 50 % queda con
#     +/- 5 puntos al 95 %, igual en todas las casillas; y el total cuesta casi
#     lo mismo que los 5.000 de antes.
#   - las cifras de toda la ciudad se ponderan (columna "peso" de la muestra).
# SEMILLA_OD_D4 y N_PARES_OD_D4 se CONSERVAN: son la muestra v1 y la semilla de
# otras validaciones (celdas 8b, 11, 19, 21).
SEMILLA_OD_ESTRAT_D4 = 20261026
N_PARES_POR_CASILLA_D4 = 350
CORTES_BANDA_OD_M = (2000.0, 5000.0, 10000.0, 20000.0)
NOMBRES_BANDA_OD = ("<2 km", "2-5 km", "5-10 km", "10-20 km", ">20 km")
MARGEN_LADERA_M = 50.0
N_SORTEOS_MIN_PESOS_OD = 2_000_000    # sorteos minimos para medir la fraccion de cada casilla
SORTEOS_POR_RONDA_OD = 200_000

# Medellin: 4 bandas propias (con 5 bandas la de > 20 km casi no se llena; la de 5
# bandas va como sensibilidad en la celda 20c). Tope de sorteos: si una casilla no
# llega al cupo, queda con los pares que alcanzo y se declara.
CORTES_BANDA_OD_M_MED = (2000.0, 5000.0, 10000.0)
NOMBRES_BANDA_OD_MED = ("<2 km", "2-5 km", "5-10 km", ">10 km")
N_SORTEOS_MAX_OD = 20_000_000

# ---------------------------------------------------------------- D4M (Medellin)
# Muestra principal de Medellin: 4 bandas propias (CORTES_BANDA_OD_M_MED, definidas mas
# arriba). Sensibilidad (celda 20c): la muestra con las 5 bandas de Bogota. Los viajes de
# mas de 20 km son muy raros en Medellin (en plano, unos 5 de cada 100.000 pares), asi que
# hacen falta mas sorteos para que esa casilla tenga >= 1.000 sorteos y su peso sea estable.
N_SORTEOS_MIN_PESOS_OD_D4M = 30_000_000
N_SORTEOS_MAX_OD_D4M = 300_000_000    # tope de seguridad: si una casilla no se llena, se detiene
# Regla El Tambor: en puentes y tuneles (es_elevado / es_tunel de
# OSM) el modelo de terreno mide el suelo, no el tablero. Ahi un tramo solo cuenta como
# "> 35 %" (se castiga, o se bloquea en los escenarios que bloquean) si su pendiente
# NETA, de extremo a extremo, tambien pasa de 35 %. False = marca de D3M sin cambios.
EXTREMAS_ELEVADOS_SOLO_NETA_D4M = True
# Revision visual en Street View de los 104 tramos de Medellin (95 de mas de 35 % y
# 9 pasos a desnivel). Se guarda tal cual en datos_crudos/recibidos/.
ARCHIVO_REVISION_EXTREMAS_MED = "revision_104_medellin_completada.csv"
SHA256_REVISION_EXTREMAS_MED = "f10b110c78652820f08e4d0f9e7914795ac8580c45bdbad275a4ddf4dd42d59e"
# Sensibilidad: la red oficial NO cambia; aparte se corre sin escaleras ni senderos.
CATEGORIAS_NO_VEHICULARES_MED = ("Escalera", "Sendero_o_paso_angosto")
# Version oficial de D4 Medellin (celda 23): bitacora de la corrida citada y su huella.
BITACORA_OFICIAL_D4M = "bitacora_ejecucion_D4M_20261120_092658_cierre_102743.json"
SHA256_BITACORA_OFICIAL_D4M = "59bfabe40322c83abc058461137bd6d9fc85e5c42e4fcebaf7d5f65e7621796f"

# ---------------------------------------------------------------- D4 regla de puentes
# Mismo criterio que Medellin: una arista extrema sobre puente o tunel (marca de OSM,
# margen 8 m) solo se castiga si la pendiente NETA pasa de 35 %, porque ahi el MDT mide
# el terreno de abajo y la acumulada no representa la via. En Bogota afecta solo a
# 12427_0 (FT y TF): puente, neta 32,3 %, acumulada 36,5 %.
ARCHIVO_REGLA_PUENTES = "regla_puentes_castigo.csv"
SHA256_REGLA_PUENTES = "aaf96937d808ac947fdc2610bb77716101f1c88cbe6534ff69cd4f35e09e3ca6"
REGLA_PUENTES_D4 = True              # False = castigar todas las extremas