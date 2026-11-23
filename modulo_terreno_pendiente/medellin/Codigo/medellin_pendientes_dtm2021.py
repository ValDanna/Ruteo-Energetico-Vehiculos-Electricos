"""
Pendiente de cada segmento del grafo vial de Medellin sobre el DTM-LiDAR 2021.

Uso:
    python medellin_pendientes_dtm2021.py

Bloques:
    1. Procedencia de las entradas del grafo (huella del gpkg, SHA del contrato).
    2. Parametros frente al contrato (sigma_z, ancho, CRS, columnas).
    3. Perfiles: muestreo adaptativo sobre el MDT.
    4. Tuneles (es_tunel y pendiente de boca a boca).
    5. Columnas.
    6. Sensibilidad.
    7. Validaciones.
    8. Exportacion, huellas y manifiesto.

Si una etapa falla no se escribe ninguna salida, salvo la bitacora.
"""
import hashlib
import io
import json
import logging
import os
import platform
import sys
from datetime import datetime, timedelta, timezone
from importlib import metadata

import geopandas as gpd
import numpy as np
import pandas as pd

import medellin_pendientes_config as C
# Define la zona horaria de Bogotá (UTC-5) y el registrador que se utilizará para guardar los eventos y mensajes del proceso.
ZONA_BOGOTA = timezone(timedelta(hours=-5))
log = logging.getLogger("medellin_pendientes")
# Define las columnas que debe contener la tabla de perfiles
COLUMNAS_PERFIL = ["segmento_id", "pendiente_neta_pct", "pendiente_acumulada_pct",
                   "ganancia_elevacion_m", "perdida_elevacion_m", "z_inicio_m", "z_fin_m",
                   "n_puntos_muestreados", "paso_muestreo_m", "fuera_cobertura_mdt"]
DEPENDIENTES = ["pendiente_neta_pct", "pendiente_acumulada_pct", "ganancia_elevacion_m",
                "perdida_elevacion_m", "clasificacion_invias", "error_pendiente_pct",
                "distinta_de_cero_2sigma", "ruido_acumulada_pct", "pendiente_extrema",
                "rho_correlacion"]

# Define una excepción específica para identificar errores  durante las distintas etapas 

class ErrorDeEtapa(Exception):
    pass

# Configura la bitácora para registrar los eventos tanto en un archivo como en la salida de la terminal
def configurar_bitacora(ruta):
    # Crea la carpeta de salidas si no existe
    C.CARPETA_SALIDAS.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
     # Establece el formato de los mensajes con fecha, hora y contenido
    formato = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    # Configura los dos destinos: un archivo nuevo y la salida estándar del sistema.
    for manejador in (logging.FileHandler(ruta, mode="w", encoding="utf-8"),
                      logging.StreamHandler(sys.stdout)):
        manejador.setFormatter(formato)
        log.addHandler(manejador)
# Calcula el hash SHA-256 
def sha256_archivo(ruta):
    h = hashlib.sha256()
    # Lee el archivo en bloques de 1 MB para calcular la huella sin tener que cargar todo su contenido en memoria
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()
# Genera una huella digital del conjunto de segmentos 
def huella_segmentos(gdf, col_id="segmento_id"):
    """Copia exacta de d2_medellin.huella_segmentos (modulo del grafo de Medellin).
    No es la funcion de Bogota: separa con 0x00 y 0x01."""
    h = hashlib.sha256()
    # Ordena los segmentos por identificador y combina el ID con la representación binaria de su geometría    
    for sid, geom in sorted(zip(gdf[col_id], gdf.geometry), key=lambda t: t[0]):
        h.update(str(sid).encode("utf-8") + b"\x00" + geom.wkb + b"\x01")
    return h.hexdigest()

# Devuelve la fecha y hora actual en la zona horaria de Bogotá
def ahora():
    return datetime.now(timezone.utc).astimezone(ZONA_BOGOTA).isoformat(timespec="seconds")

# Convierte los valores booleanos de una serie, incluidos los textos "True" y "False"
def a_booleano(serie):
    return serie.map({True: True, False: False, "True": True, "False": False})

# Clasifica las pendientes según los límites INVIAS
# Recibe los valores absolutos de pendiente y devuelve la etiqueta  a cada valor, conservando el orden de los datos de entrada

def clasificar_invias(a):
    return np.where(a < C.INVIAS_LIMITE_ONDULADO, C.ETIQUETAS_INVIAS[0],
           np.where(a < C.INVIAS_LIMITE_MONTANOSO, C.ETIQUETAS_INVIAS[1],
           np.where(a <= C.INVIAS_LIMITE_ESCARPADO, C.ETIQUETAS_INVIAS[2], C.ETIQUETAS_INVIAS[3])))


# 1. Procedencia
# Verifica la integridad y la procedencia de los archivos de entrada 

def verificar_procedencia():
    log.info("BLOQUE 1  Procedencia de las entradas del grafo")
    # Comprueba que existan todos los archivos necesarios    
    for ruta in (C.ARCHIVO_SEGMENTOS, C.ARCHIVO_HUELLAS_ENTRADA, C.ARCHIVO_CONTRATO):
        if not ruta.exists():
            raise ErrorDeEtapa(f"Falta la entrada {ruta.name} en {relativa(ruta.parent)}")
    # Carga el registro de huellas de los archivos de entrada        
    huellas = json.loads(C.ARCHIVO_HUELLAS_ENTRADA.read_text(encoding="utf-8"))
    contrato_bytes = C.ARCHIVO_CONTRATO.read_bytes()
    contrato = json.loads(contrato_bytes.decode("utf-8"))
    # Calcula el SHA-256 del contrato y lo compara con el valor registrado en las huellas de entrada. Si no coinciden, detiene el proceso 
    sha_contrato = hashlib.sha256(contrato_bytes).hexdigest()
    esperado = huellas.get("sha256_archivos", {}).get(C.NOMBRE_CONTRATO_EN_HUELLAS)
    if sha_contrato != esperado:
        raise ErrorDeEtapa(f"SHA-256 del contrato {sha_contrato} distinto del registrado "
                           f"en las huellas ({esperado}). Pida al modulo del grafo que regenere "
                           f"D2M_huellas_salidas.json o el contrato correcto.")
    log.info(f"  contrato verificado: {sha_contrato}")
    # Lee la capa de segmentos del GeoPackage y genera una huella a partir de sus identificadores y geometrías para comprobar que no haya cambiado
    gdf = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)
    huella = huella_segmentos(gdf)

    # Compara la huella calculada con la registrada tanto en el archivo de huellas como en el contrato. 
    if huella != huellas["huella_segmentos_gpkg"] or huella != contrato["huella_segmentos"]:
        raise ErrorDeEtapa(f"Huella del gpkg {huella} distinta de la registrada "
                           f"({huellas['huella_segmentos_gpkg']}). El grafo cambio.")
    # Comprueba que la cantidad de segmentos del GeoPackage coincida con la cantidad declarada    
    if len(gdf) != contrato["n_segmentos"]:
        raise ErrorDeEtapa(f"El gpkg tiene {len(gdf):,} segmentos y el contrato dice {contrato['n_segmentos']:,}")
    # Registra la verificación satisfactoria y devuelve los segmentos
    log.info(f"  gpkg verificado: huella {huella}, {len(gdf):,} segmentos")
    return gdf, contrato, {"huella_gpkg": huella, "sha256_contrato": sha_contrato}


# 2. Parametros frente al contrato
# Comprueba que los parámetros de configuración coincidan con el contrato y devuelve las columnas 
def verificar_parametros(contrato):
    log.info("BLOQUE 2  Parametros frente al contrato")

    # Agrupa cada parámetro que se debe verificar con su valor de configuración y el valor correspondiente en el contrato 
    pares = [("sigma_z_m", C.SIGMA_Z_M, contrato.get("sigma_z_m")),
             ("ancho_correlacion_m", C.ANCHO_CORRELACION_M, contrato.get("ancho_correlacion_m")),
             ("mdt_crs", C.CRS_MDT, contrato.get("mdt_crs")),
             ("red_crs", C.CRS_RED, contrato.get("red_crs"))]
    # Compara los valores uno por uno. Si alguno no coincide, detiene el proceso   
    for nombre, config, en_contrato in pares:
        if config != en_contrato:
            raise ErrorDeEtapa(f"{nombre}: configuracion {config} y contrato {en_contrato} no coinciden")
        log.info(f"  {nombre}: {config} (coincide con el contrato)")
    # Obtiene el orden de las columnas y registra la cantidad de columnas y el nombre de la última        
    columnas = contrato["columnas_retorno"]
    log.info(f"  columnas del contrato: {len(columnas)} (ultima: {columnas[-1]})")

    log.info(f"  sigma_z {C.SIGMA_Z_ORIGEN}; ancho medido con el metodo de terreno estable")
    return columnas


# 3. Perfiles

def consultar_elevacion(raster, x, y):
    # Consulta la elevacion del MDT en una coordenada    
    try:
# Convierte las coordenadas geograficas del punto a indices de fila y columna del raster        
        fila, columna = raster.index(x, y)
        # Comprueba que el punto se encuentre dentro de los limites del raster        
        if fila < 0 or columna < 0 or fila >= raster.height or columna >= raster.width:
            return None
        # Lee el valor de elevacion de una sola celda del raster
        valor = raster.read(1, window=((fila, fila + 1), (columna, columna + 1)))[0, 0]
       # Si la celda contiene el valor definido como NoData, no se considera una elevacion valida    
        if raster.nodata is not None and valor == raster.nodata:
            return None
        # Devuelve la elevacion como un numero decimal
        return float(valor)
    except Exception:
        return None


def perfiles_desde_mdt(gdf):
    """Muestreo adaptativo: preliminar con los extremos, paso de 50 m si la pendiente
    es menor que el umbral plano y de 10 m si no, pixel mas cercano."""
    import rasterio
    from pyproj import Transformer

    log.info("BLOQUE 3  Perfiles sobre el MDT")
    # Verifica que el archivo del Modelo Digital del Terreno exista     
    if not C.ARCHIVO_MDT.exists():
        raise ErrorDeEtapa(f"No esta el MDT en {relativa(C.ARCHIVO_MDT)}. Ver LEEME.txt, paso 3.")
   # Calcula la huella SHA-256 del MDT para registrar e identificar   
    sha_mdt = sha256_archivo(C.ARCHIVO_MDT)
    log.info(f"  SHA-256 del MDT: {sha_mdt}")
    # Si existe un hash esperado en la configuracion, comprueba que corresponda al archivo utilizado    
    if C.SHA256_MDT is not None and sha_mdt != C.SHA256_MDT:
        raise ErrorDeEtapa(f"El MDT no es el registrado ({C.SHA256_MDT})")
        # Si no se ha configurado el hash esperado, deja constancia para que pueda registrarse posteriormente
    if C.SHA256_MDT is None:
        log.info("  [AVISO] SHA256_MDT no esta fijado en la configuracion: copie el valor de arriba")
    # Crea el transformador para convertir coordenadas desde el sistema de referencia de la red vial al sistema de coordenadas del MDT
    transformador = Transformer.from_crs(C.CRS_RED, C.CRS_MDT, always_xy=True)
    filas = [] # Esta lista almacena un registro con los resultados del perfil de cada segmento vial
    # Abre el MDT para consultar las elevaciones de los puntos de cada segmento
    with rasterio.open(C.ARCHIVO_MDT) as raster:
        # Obtiene la definicion del sistema de coordenadas del raster en formato WKT
        wkt = raster.crs.to_wkt() if raster.crs else ""
        # Registra las dimensiones, la resolucion y una comprobacion del identificador 6257 dentro de la definicion del sistema de coordenadas
        log.info(f"  raster {raster.width} x {raster.height}, resolucion {raster.res}, "
                 f"declara 6257: {'6257' in wkt}")
         # Procesa cada segmento de la red vial y lleva un conteo
        for i, (_, eje) in enumerate(gdf.iterrows(), start=1):
            # Recupera la geometria y la longitud del segmento
            geom = eje.geometry
            longitud_m = eje["longitud_m"]
            # Obtiene los puntos inicial y final de la geometria, normalized=True expresa la posicion como una fraccion entre 0 y 1            
            p_ini = geom.interpolate(0, normalized=True)
            p_fin = geom.interpolate(1, normalized=True)
            #Transforma las coordenadas de ambos extremos al sistema del MDT y consulta sus elevaciones en el raster
            z_inicio = consultar_elevacion(raster, *transformador.transform(p_ini.x, p_ini.y))
            # Inicializa el registro del segmento con los valores de los extremos.
            # Las metricas del perfil quedan vacias hasta comprobar que los datos sean validos. 
            z_fin = consultar_elevacion(raster, *transformador.transform(p_fin.x, p_fin.y))
            fila = {"segmento_id": eje["segmento_id"], "z_inicio_m": z_inicio, "z_fin_m": z_fin,
                    "pendiente_neta_pct": None, "pendiente_acumulada_pct": None,
                    "ganancia_elevacion_m": None, "perdida_elevacion_m": None,
                    "n_puntos_muestreados": None, "paso_muestreo_m": None,
                    "fuera_cobertura_mdt": True}

            # Si falta la elevacion de alguno de los extremos o la longitud no es valida, guarda el registro incompleto y pasa al siguiente segmento            
            if z_inicio is None or z_fin is None or not longitud_m:
                filas.append(fila)
                continue
            # Calcula una pendiente preliminar con la diferencia de elevacion entre los extremos. Esta estimacion permite decidir la densidad de muestreo
            pendiente_preliminar = (z_fin - z_inicio) / longitud_m * 100
             # Selecciona el paso de muestreo segun la pendiente preliminar: los segmentos con pendiente inferior al umbral usan el paso para terreno plano, los demas usan el paso definido para segmentos con mayor pendiente
            paso_m = C.PASO_PLANO_M if abs(pendiente_preliminar) < C.UMBRAL_PLANO_PCT else C.PASO_PENDIENTE_M
           # Estima la cantidad de puntos del perfil a partir de la longitud y el paso seleccionado, minimo de dos puntos para representar el segmento
            n_puntos = max(2, int(longitud_m / paso_m) + 1)
            elevaciones = [] # Almacenara las elevaciones obtenidas a lo largo del segmento
             # Genera posiciones distribuidas uniformemente entre el inicio y el final. En cada posicion interpola un punto sobre la geometria y consulta su elevacion en el MDT
            for f in np.linspace(0, 1, n_puntos):
                p = geom.interpolate(f, normalized=True)
                elevaciones.append(consultar_elevacion(raster, *transformador.transform(p.x, p.y)))
            # Si al menos uno de los puntos no tiene una elevacion valida, conserva el registro incompleto                
            if any(e is None for e in elevaciones):
                filas.append(fila)
                continue
            # Obtiene el numero efectivo de elevaciones validas
            n = len(elevaciones)
            # Suma los incrementos positivos entre puntos consecutivos para estimar la ganancia acumulada
            ganancia = sum(max(0, elevaciones[j + 1] - elevaciones[j]) for j in range(n - 1))
            # Suma los descensos entre puntos consecutivos para estimar la perdida acumulada
            perdida = sum(max(0, elevaciones[j] - elevaciones[j + 1]) for j in range(n - 1))
            # Actualiza el registro con las metricas calculadas:
            # - Pendiente neta: diferencia entre elevaciones extremas respecto a la longitud.
            # - Pendiente acumulada: suma de ganancias y perdidas respecto a la longitud.
            # - Ganancia y perdida: cambios verticales acumulados a lo largo del perfil.
            # - Numero de puntos y paso utilizado: informacion sobre el muestreo realizado.
            # Marca el segmento como cubierto si todas las elevaciones fueron validas            
            fila.update({"pendiente_neta_pct": (z_fin - z_inicio) / longitud_m * 100,
                         "pendiente_acumulada_pct": (ganancia + perdida) / longitud_m * 100,
                         "ganancia_elevacion_m": ganancia, "perdida_elevacion_m": perdida,
                         "n_puntos_muestreados": n, "paso_muestreo_m": paso_m,
                         "fuera_cobertura_mdt": False})
             #Agrega el perfil calculado a la lista de resultados
            filas.append(fila)
            # Cada 5000 segmentos registra el avance para facilitar
            if i % 5000 == 0:
                log.info(f"  {i:,}/{len(gdf):,} segmentos")

    # Convierte los registros recopilados en un DataFrame y organiza las columnas segun el orden establecido en COLUMNAS_PERFIL
    perfiles = pd.DataFrame(filas)[COLUMNAS_PERFIL]
    # Convierte las columnas intermedias del perfil a valores numericos decimales
    for col in COLUMNAS_PERFIL[1:-1]:
        perfiles[col] = pd.to_numeric(perfiles[col], errors="coerce").astype(float)
    # Devuelve la tabla de perfiles y el hash del MDT    
    return perfiles, {"sha256_mdt": sha_mdt}


# 4. Tuneles

def marcar_tuneles(gdf):
    log.info("BLOQUE 4  Tuneles")
    # Busca segmentos cuyo nombre coincide con el patron de tunel, fillna("") permite tratar los nombres nulos como cadenas vacias y evitar los errores
    # case=False hace que la busqueda no distinga entre mayusculas y minusculas   
    por_nombre = gdf["nombre"].fillna("").str.contains(C.PATRON_TUNEL, case=False, regex=True)
    # Obtiene los nodos iniciales y finales de los segmentos como tuneles y se utiliza un conjunto (set) para conservar unicamente los nodos distintos    
    nodos = set(gdf.loc[por_nombre, "u"]) | set(gdf.loc[por_nombre, "v"])
    # Identifica los segmentos que no tienen nombre o cuyo nombre esta compuesto solo por los espacios
    sin_nombre = gdf["nombre"].isna() | (gdf["nombre"].str.strip() == "")
    # Detecta segmentos sin nombre cuyos dos extremos pertenecen al conjunto de nodos que son asociados a tuneles identificados. Estos segmentos pueden completar una cadena de tunel aunque no tengan un nombre 
    hueco = sin_nombre & gdf["u"].isin(nodos) & gdf["v"].isin(nodos)
    # Obtiene el identificador base de cada segmento eliminando el ultimo componente separado por un guion bajo, lo que esto permite agrupar registros que pertenecen a una misma unidad o cadena de segmento
    base = gdf["segmento_id"].str.rsplit("_", n=1).str[0]
    # Marca como tunel todos los registros cuya base aparece en segmentos identificados directamente por nombre o en segmentos sin nombre que completan la cadena    
    es_tunel = base.isin(set(base[por_nombre | hueco]))
    # Registra la cantidad total de filas marcadas y el aporte de cada criterio    
    log.info(f"  es_tunel: {int(es_tunel.sum())} filas ({int(por_nombre.sum())} por nombre, "
             f"{int(hueco.sum())} sin nombre que cierran la cadena)")
    # Devuelve una serie booleana que indica cuales filas se clasifican como tuneles    
    return es_tunel


# 5. Columnas del contrato

def calcular_columnas(gdf, perfiles, es_tunel):
    # Integra los perfiles del MDT con la red vial y calcula las metricas de pendiente, incertidumbre y clasificacion    
    log.info("BLOQUE 5  Columnas del contrato")
    perfiles = perfiles.copy()
    perfiles["fuera_cobertura_mdt"] = a_booleano(perfiles["fuera_cobertura_mdt"])
    base = gdf[["segmento_id", "longitud_m"]].assign(es_tunel=es_tunel.values)
    df = base.merge(perfiles, on="segmento_id", how="left", validate="one_to_one")
    L = df["longitud_m"].astype(float)
    con = df["fuera_cobertura_mdt"] == False
    # Para los tuneles, calcula la ganancia, perdida y pendiente acumulada usando un perfil simplificado entre las dos bocas, sin considerar variaciones internas
    # Tuneles: boca a boca con las dos alturas de los extremos
    t = df["es_tunel"] & con
    dz = df.loc[t, "z_fin_m"] - df.loc[t, "z_inicio_m"]
    df.loc[t, "ganancia_elevacion_m"] = dz.clip(lower=0) + 0.0
    df.loc[t, "perdida_elevacion_m"] = (-dz).clip(lower=0) + 0.0
    df.loc[t, "pendiente_acumulada_pct"] = 100 * dz.abs() / L[t]
    df.loc[t, "n_puntos_muestreados"] = 2
    df.loc[t, "paso_muestreo_m"] = L[t]
    # Estima la correlacion espacial y la incertidumbre de la pendiente a partir de la longitud del segmento, la incertidumbre vertical del MDT y el ancho de correlacion configurado. Tambien calcula el ruido esperado de la pendiente acumulada
    neta = df["pendiente_neta_pct"]
    acum = df["pendiente_acumulada_pct"]
    rho = np.exp(-L / C.ANCHO_CORRELACION_M)
    error = 100 * np.sqrt(2 * C.SIGMA_Z_M ** 2 * (1 - rho)) / L
    p = L / (df["n_puntos_muestreados"] - 1)
    sd = C.SIGMA_Z_M * np.sqrt(2 * (1 - np.exp(-p / C.ANCHO_CORRELACION_M)))
    ruido = 100 * np.sqrt(2 / np.pi) * sd / p
    # Incorpora las metricas calculadas, identifica pendientes estadisticamente distintas de cero y pendientes extremas, y asigna la clasificacion INVIAS.
    # Los segmentos sin cobertura valida del MDT quedan sin estas metricas dependientes
    df.loc[con, "rho_correlacion"] = rho[con]
    df.loc[con, "error_pendiente_pct"] = error[con]
    df.loc[con, "distinta_de_cero_2sigma"] = (neta.abs() > C.K_SIGMA * error)[con]
    df.loc[con, "ruido_acumulada_pct"] = ruido[con]
    df.loc[con, "pendiente_extrema"] = (np.maximum(neta.abs(), acum.abs()) > C.UMBRAL_PENDIENTE_EXTREMA_PCT)[con]
    df.loc[con, "clasificacion_invias"] = clasificar_invias(neta.abs())[con]
    df.loc[~con, DEPENDIENTES] = np.nan
    df["ancho_correlacion_m"] = C.ANCHO_CORRELACION_M
    df["sigma_z_m"] = C.SIGMA_Z_M
    for col in ["distinta_de_cero_2sigma", "pendiente_extrema"]:
        df[col] = df[col].astype(object).where(con, None)
    df["n_puntos_muestreados"] = df["n_puntos_muestreados"].astype("Int64")
    # Resume la cobertura y los principales resultados para el registro 
    log.info(f"  con dato {int(con.sum()):,}; fuera de cobertura {int((~con).sum())}; "
             f"pendiente_extrema {int((df['pendiente_extrema'] == True).sum())}; "
             f"distinta de cero {int((df['distinta_de_cero_2sigma'] == True).sum()):,}")
    return df


# 6. Sensibilidad

def sensibilidad(df):
    # Evalua como cambian los resultados de incertidumbre al modificar la precision vertical del MDT y el ancho de correlacion espacial    
    log.info("BLOQUE 6  Sensibilidad")
    con = df[df["fuera_cobertura_mdt"] == False]
    L = con["longitud_m"].to_numpy(float)
    neta = con["pendiente_neta_pct"].abs().to_numpy(float)
    filas = []
   # Prueba todas las combinaciones de sigma y ancho definidas en la configuracion 
    for s in C.SENSIBILIDAD_SIGMAS_M:
        for a in C.SENSIBILIDAD_ANCHOS_M:
            rho = 0.0 if a is None else np.exp(-L / a)
            err = 100 * np.sqrt(2 * s ** 2 * (1 - rho)) / L
            dist = neta > C.K_SIGMA * err
            filas.append({"sigma_z_m": s, "ancho_m": "independencia" if a is None else a,
                          "distintos_de_cero": int(dist.sum()), "pct": round(100 * dist.mean(), 2),
                          "error_mediano_pp": round(float(np.median(err)), 3)})
    # Organiza los resultados en una tabla y registra el error mediano y la cantidad de pendientes consideradas distintas de cero para cada escenario            
    tabla = pd.DataFrame(filas)
    for _, f in tabla.iterrows():
        log.info(f"  sigma {f['sigma_z_m']}  ancho {f['ancho_m']}: error mediano "
                 f"{f['error_mediano_pp']} pp, distintos de cero {f['distintos_de_cero']:,}")
    return tabla


# 7. Validaciones

def validar(df, gdf, columnas):
    # Comprueba que los resultados cumplan el contrato de union con el grafo, las formulas de pendiente y las condiciones especiales de cobertura, muestreo y tuneles    
    log.info("BLOQUE 7  Validaciones")
    res = []
    # Registra el resultado de cada comprobacion y lo escribe en la bitacora.
    def regla(nombre, ok, detalle=""):
        res.append({"regla": nombre, "pasa": bool(ok), "detalle": detalle})
        log.info(f"  [{'OK' if ok else 'FALLA'}] {nombre} {detalle}")
    # Verifica la integridad de los registros y que esten presentes las columnas exigidas
    regla("misma cantidad de filas que el gpkg", len(df) == len(gdf), f"{len(df):,}")
    regla("mismos segmento_id que el gpkg", set(df["segmento_id"]) == set(gdf["segmento_id"]))
    regla("segmento_id sin repetidos", not df["segmento_id"].duplicated().any())
    regla("columnas y orden del contrato", all(c in df.columns for c in columnas), f"{len(columnas)} columnas")
    # Separa los segmentos con datos validos de aquellos que quedaron fuera de la cobertura del MDT
    fuera = df["fuera_cobertura_mdt"] == True
    c = df[~fuera]
    L = c["longitud_m"].to_numpy(float)
    neta = c["pendiente_neta_pct"].to_numpy(float)
    acum = c["pendiente_acumulada_pct"].to_numpy(float)
    # Comprueba la disponibilidad de datos y la coherencia de las pendientes, la ganancia y la perdida de elevacion    
    regla("sin vacios en segmentos con dato", not c[DEPENDIENTES].isna().any().any())
    regla("segmentos sin cobertura con columnas vacias", df.loc[fuera, DEPENDIENTES].isna().all().all(),
          f"{int(fuera.sum())} fuera de cobertura")
    d = np.abs(neta - 100 * (c["z_fin_m"] - c["z_inicio_m"]).to_numpy() / L)
    regla("neta = 100 (z_fin - z_inicio) / L", d.max() < 1e-9, f"max {d.max():.1e}")
    d = np.abs(acum - 100 * (c["ganancia_elevacion_m"] + c["perdida_elevacion_m"]).to_numpy() / L)
    regla("acumulada = 100 (ganancia + perdida) / L", d.max() < 1e-9, f"max {d.max():.1e}")
    d = np.abs((c["ganancia_elevacion_m"] - c["perdida_elevacion_m"]) - (c["z_fin_m"] - c["z_inicio_m"]))
    regla("ganancia - perdida = desnivel", d.max() < 1e-6, f"max {d.max():.1e}")
    regla("acumulada >= |neta|", bool(np.all(acum >= np.abs(neta) - 1e-9)))
    regla("ganancia y perdida no negativas",
          bool((c["ganancia_elevacion_m"] >= 0).all() and (c["perdida_elevacion_m"] >= 0).all()))
    # Recalcula la correlacion, el error y los indicadores de pendiente para compararlos con los valores generados anteriormente y verificar que siguen las reglas
    rho = np.exp(-L / C.ANCHO_CORRELACION_M)
    err = 100 * np.sqrt(2 * C.SIGMA_Z_M ** 2 * (1 - rho)) / L
    regla("rho y error segun contrato", np.abs(err - c["error_pendiente_pct"]).max() < 1e-12
          and np.abs(rho - c["rho_correlacion"]).max() < 1e-12)
    regla("distinta_de_cero_2sigma segun contrato",
          bool(((np.abs(neta) > C.K_SIGMA * err) == c["distinta_de_cero_2sigma"].astype(bool)).all()))
    regla("pendiente_extrema segun contrato",
          bool(((np.maximum(np.abs(neta), acum) > C.UMBRAL_PENDIENTE_EXTREMA_PCT)
                == c["pendiente_extrema"].astype(bool)).all()))
    regla("clasificacion INVIAS segun contrato",
          bool((clasificar_invias(np.abs(neta)) == c["clasificacion_invias"]).all()))
    # Comprueba que el paso de muestreo corresponda a la regla adaptativa fuera de tuneles y que los parametros de incertidumbre sean uniformes
    nt = ~c["es_tunel"].to_numpy()
    paso = np.where(np.abs(neta) < C.UMBRAL_PLANO_PCT, C.PASO_PLANO_M, C.PASO_PENDIENTE_M)
    regla("paso adaptativo coherente (fuera de tuneles)",
          bool((paso[nt] == c["paso_muestreo_m"].to_numpy()[nt]).all()))
    regla("un solo sigma_z y un solo ancho en todas las filas",
          set(df["sigma_z_m"]) == {C.SIGMA_Z_M} and set(df["ancho_correlacion_m"]) == {C.ANCHO_CORRELACION_M})
    # Verifica el tratamiento especial de los tuneles y registra cuales se clasificaron como segmentos con pendiente extrema
    tu = c[c["es_tunel"]]
    regla("tuneles: 2 puntos, paso = longitud, acumulada = |neta|",
          bool((tu["n_puntos_muestreados"] == 2).all()
               and np.allclose(tu["paso_muestreo_m"], tu["longitud_m"])
               and np.allclose(tu["pendiente_acumulada_pct"], tu["pendiente_neta_pct"].abs())), f"{len(tu)} filas")
    extremos_tunel = tu.loc[tu["pendiente_extrema"] == True, "segmento_id"].tolist()
    log.info(f"  [INFO] tuneles con pendiente_extrema: {extremos_tunel or 'ninguno'}")
    # Agrupa los segmentos por su identificador base y sentido para comprobar que las etiquetas de tunel y las pendientes sean consistentes entre las versiones FT y TF del mismo tramo
    partes = df["segmento_id"].str.rsplit("_", n=1)
    tmp = df.assign(base=partes.str[0], sentido=partes.str[1])
    regla("es_tunel igual en FT y TF", bool((tmp.groupby("base")["es_tunel"].nunique() == 1).all()))
    piv = tmp.pivot_table(index="base", columns="sentido", values=["pendiente_neta_pct", "z_inicio_m", "z_fin_m"])
    pp = piv.dropna(subset=[("pendiente_neta_pct", "FT"), ("pendiente_neta_pct", "TF")])
    s = (pp[("pendiente_neta_pct", "FT")] + pp[("pendiente_neta_pct", "TF")]).abs()
    z = (pp[("z_inicio_m", "FT")] - pp[("z_fin_m", "TF")]).abs()
    regla("FT y TF simetricos", s.max() < 1e-9 and z.max() == 0, f"{len(pp):,} pares")
    # Si alguna validacion falla, detiene el proceso 
    # Si todas pasan, devuelve el registro de validaciones
    fallas = [r["regla"] for r in res if not r["pasa"]]
    if fallas:
        raise ErrorDeEtapa(f"{len(fallas)} validaciones fallaron; no se exporta: {fallas}")
    return res


# 8. Exportacion

def versiones():
    # Recopila las versiones del entorno
    salida = {"python": platform.python_version(), "sistema": platform.platform()}
    for p in ["numpy", "pandas", "geopandas", "shapely", "pyproj", "pyogrio", "rasterio"]:
        try:
            salida[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            salida[p] = "no instalado"
    return salida


def relativa(ruta):
    # Convierte una ruta absoluta en una ruta relativa
    return ruta.relative_to(C.CARPETA_PROYECTO).as_posix()


def escribir_atomico(ruta, contenido):
    # Escribe primero en un archivo temporal y despues lo reemplaza por el definitivo
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_bytes(contenido)
    os.replace(tmp, ruta)


def exportar(df, columnas, rutas, procedencia, tabla_sens, validaciones, inicio):
# Genera los archivos finales, calcula sus huellas y documenta la ejecucion    
    log.info("BLOQUE 8  Exportacion")
    # lineterminator fijo: en Windows pandas usaria CRLF y el SHA cambiaria
    csv_bytes = df[columnas].to_csv(index=False, lineterminator="\n").encode("utf-8")
    sha = hashlib.sha256(csv_bytes).hexdigest()
    log.info(f"  SHA-256 del CSV: {sha}")
    # Comprueba que el CSV generado coincida con el hash esperado
    if C.SHA256_SALIDA_ESPERADO is not None and sha != C.SHA256_SALIDA_ESPERADO:
        raise ErrorDeEtapa(f"El CSV no es el esperado ({C.SHA256_SALIDA_ESPERADO}). Revise entradas y versiones; "
                           f"en otro sistema operativo ponga SHA256_SALIDA_ESPERADO = None y compare con "
                           f"auxiliares/aux_comparar_versiones.py")
    if C.SHA256_SALIDA_ESPERADO is None:
        log.info("  [AVISO] SHA256_SALIDA_ESPERADO no esta fijado en la configuracion: copie el valor de arriba")
    else:
        log.info("  coincide con el SHA esperado de la configuracion")

    # utf-8-sig solo en las salidas de soporte, para que Excel muestre las tildes; el CSV principal va sin BOM porque su SHA-256 es el registrado en el modulo del grafo
    validaciones_bytes = pd.DataFrame(validaciones).to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
    sensibilidad_bytes = tabla_sens.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
    # Construye el registro de huellas de los archivos principales y auxiliares
    nombre = rutas["pendientes"].name
    huellas = {"archivo": nombre, "sha256": sha, "filas": len(df), "columnas": columnas, **procedencia,
               "sha256_salidas": {nombre: sha,
                                  rutas["validaciones"].name: hashlib.sha256(validaciones_bytes).hexdigest(),
                                  rutas["sensibilidad"].name: hashlib.sha256(sensibilidad_bytes).hexdigest()}}
    carpeta = C.CARPETA_PROYECTO
    # Crea el manifiesto con las fechas, versiones, hashes del codigo, parametros, procedencia de los datos, archivos generados, conteos y resultados de validacion    
    manifiesto = {
        "fecha": inicio, "fin": ahora(), "versiones": versiones(),
        "codigo": {"medellin_pendientes_dtm2021.py": sha256_archivo(carpeta / "medellin_pendientes_dtm2021.py"),
                   "medellin_pendientes_config.py": sha256_archivo(carpeta / "medellin_pendientes_config.py")},
        "parametros": {"sigma_z_m": C.SIGMA_Z_M, "sigma_z_origen":  C.SIGMA_Z_ORIGEN,
                       "ancho_correlacion_m": C.ANCHO_CORRELACION_M,
                       "ancho_origen": "metodo de Bogota, 11 ventanas del Olaya Herrera",
                       "crs": f"{C.CRS_RED} -> {C.CRS_MDT}"},
        "entradas": procedencia, "salida": huellas,
        # rutas relativas a la carpeta del codigo, para que el manifiesto no dependa del equipo
        "archivos": {"entradas": [relativa(r) for r in (C.ARCHIVO_SEGMENTOS, C.ARCHIVO_CONTRATO,
                                                        C.ARCHIVO_HUELLAS_ENTRADA, C.ARCHIVO_MDT)],
                     "salidas": {**{k: relativa(v) for k, v in rutas.items()},
                                 "sha256": relativa(rutas["pendientes"].with_name(nombre + ".sha256"))}},
        # Resume las cantidades de segmentos segun cobertura, pendiente y clasificacion                         
        "conteos": {"con_dato": int((df["fuera_cobertura_mdt"] == False).sum()),
                    "fuera_cobertura": int((df["fuera_cobertura_mdt"] == True).sum()),
                    "pendiente_extrema": int((df["pendiente_extrema"] == True).sum()),
                    "distinta_de_cero_2sigma": int((df["distinta_de_cero_2sigma"] == True).sum()),
                    "es_tunel": int(df["es_tunel"].sum())},
        # Registra cuantas validaciones se ejecutaron            
        "validaciones": {"total": len(validaciones), "pasan": sum(v["pasa"] for v in validaciones)},
    }
    escribir_atomico(rutas["pendientes"], csv_bytes)
    escribir_atomico(rutas["pendientes"].with_name(nombre + ".sha256"), f"{sha}  {nombre}\n".encode("utf-8"))
    escribir_atomico(rutas["validaciones"], validaciones_bytes)
    escribir_atomico(rutas["sensibilidad"], sensibilidad_bytes)
    escribir_atomico(rutas["huellas"], json.dumps(huellas, ensure_ascii=False, indent=2).encode("utf-8"))
    escribir_atomico(rutas["manifiesto"], json.dumps(manifiesto, ensure_ascii=False, indent=2).encode("utf-8"))
    # Registra los archivos generados en la bitacora
    for k in ["pendientes", "validaciones", "sensibilidad", "huellas", "manifiesto"]:
        log.info(f"  escrito {rutas[k].name}")
    log.info(f"  escrito {nombre}.sha256")


def main():
    # Coordina las etapas del procesamiento desde la verificacion de entradas hasta la validacion y exportacion    
    rutas = C.salidas()
    configurar_bitacora(rutas["bitacora"])
    inicio = ahora()
    log.info(f"Inicio {inicio}")
    log.info(f"Parametros: sigma_z {C.SIGMA_Z_M} m ({C.SIGMA_Z_ORIGEN}), ancho {C.ANCHO_CORRELACION_M} m, "
             f"CRS {C.CRS_RED} -> {C.CRS_MDT}")
    try:
        gdf, contrato, procedencia = verificar_procedencia()
        columnas = verificar_parametros(contrato)
        perfiles, extra = perfiles_desde_mdt(gdf)
        procedencia.update(extra)
        es_tunel = marcar_tuneles(gdf)
        df = calcular_columnas(gdf, perfiles, es_tunel)
        tabla_sens = sensibilidad(df)
        validaciones = validar(df, gdf, columnas)
        exportar(df, columnas, rutas, procedencia, tabla_sens, validaciones, inicio)
    except ErrorDeEtapa as exc:
        log.error(f"DETENIDO: {exc}")
        log.error("No se escribio ninguna salida (solo esta bitacora).")
        sys.exit(1)
    log.info(f"Fin {ahora()}")


if __name__ == "__main__":
    main()
