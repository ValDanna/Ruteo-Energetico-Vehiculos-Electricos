"""
Etapa de terreno y pendiente del pipeline de ruteo energetico de Bogotá

Entrada: Los segmentos dirigidos de la Malla Vial, MDT 2020 de
Catastro Bogota consultado por identify y vertices de nivelacion del IGAC.
Salida: Es una fila por segmento con pendiente neta y acumulada, su
incertidumbre y  D2_contrato_intercambio.json,
la tabla de exactitud vertical, el ancho de correlacion, la sensibilidad, las
huellas digitales, el manifiesto y la bitacora.

Bloques:
  1. Procedencia de las entradas
  2. Consulta al MDT con cache
  3. Exactitud vertical (sigma_z)
  4. Ancho de correlacion
  5. Muestreo adaptativo y perfiles
  6. Columnas del contrato fomrrado para unificar con el intercambio de datos con el grafo 
  7. Sensibilidad
  8. Validaciones
  9. Exportacion, huellas, manifiesto

Uso:
    python bogota_pendientes_mdt2020.py
    python bogota_pendientes_mdt2020.py solo-cache   (no consulta el servicio, no se conecta a internet, usa solo las elevaciones que ya están)

Todos los parametros estan en bogota_pendientes_config.py.
"""
# Permite manejar las anotaciones de tipos de forma diferida.
from __future__ import annotations
# Librerías para manejar argumentos, archivos, registros de ejecución, información del sistema y medición de tiempos.
import argparse
import hashlib
import json
import logging
import platform
import sys
import time
# Funciones para trabajar con fechas, horas y diferencias de tiempo
from datetime import datetime, timedelta, timezone
# Consultar información de los paquetes instalados, como sus versiones
from importlib import metadata
from pathlib import Path
#Cálculos numéricos y con tablas de datos
import numpy as np
import pandas as pd
# Importa la configuración del proyecto, donde están definidos los parámetros
import bogota_pendientes_config as C
# Define la hora de Bogotá (UTC-5) 
ZONA_BOGOTA = timezone(timedelta(hours=-5))
# Permite registrar mensajes sobre lo que ocurre durante la ejecución del código
log = logging.getLogger("bogota_pendientes")


class ErrorDeEtapa(RuntimeError):
    """Falla que detiene la corrida antes de producir un archivo dudoso."""



# Utilidades

# Prepara el registro de mensajes del proceso, guardando la información tanto en un archivo como en la consola para poder revisar cómo se ejecutó el código
def configurar_bitacora():
    C.CARPETA_SALIDAS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.INFO)
    log.propagate = False   # evita que xdem/geoutils dupliquen cada linea
    log.handlers.clear()
    for h in (logging.FileHandler(C.ARCHIVO_BITACORA, mode="w", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(formato)
        log.addHandler(h)

# Calcula una huella digital del archivo para comprobar su integridad o identificar si su contenido ha cambiado
def ruta_relativa(ruta) -> str:
    """Ruta respecto a la carpeta del codigo, para que el manifiesto no dependa del equipo."""
    try:
        return Path(ruta).resolve().relative_to(C.CARPETA_PROYECTO).as_posix()
    except ValueError:
        return Path(ruta).name

    
def sha256_archivo(ruta) -> str:


    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()

# Genera una huella digital del contenido de los segmentos, teniendo en cuenta sus identificadores y geometrías. Así se puede verificar si la capa mantiene los mismos segmentos, sin depender de cambios internos en el archivo .gpkg.
def huella_segmentos(gdf, columna_id: str = "segmento_id") -> str:
    """Huella de contenido de una capa de segmentos.

    Copia exacta de d1_procedencia.huella_segmentos (grafo). El
    sha256 del .gpkg no sirve porque el formato guarda la hora de escritura
    esta huella ordena por id y resume (id, geometria WKB 2D).
    """
    import shapely

    orden = gdf.sort_values(columna_id)
    h = hashlib.sha256()
    for sid, geom in zip(orden[columna_id].astype(str), orden.geometry):
        h.update(sid.encode("utf-8"))
        h.update(b"|")
        h.update(shapely.to_wkb(geom, byte_order=1, output_dimension=2))
        h.update(b"\n")
    return h.hexdigest()

# Obtiene la fecha y hora actuales y las devuelve en dos formatos: hora universal (UTC) y hora local de Bogotá.
def ahora():
    t = datetime.now(timezone.utc)
    return {"utc": t.isoformat(timespec="seconds"),
            "bogota": t.astimezone(ZONA_BOGOTA).isoformat(timespec="seconds")}

# Comprueba si un valor está vacío, considerando tanto None como NaN. Para evitar que los datos faltantes pasen inadvertidos durante el procesamiento
def es_vacio(valor) -> bool:
    """None y NaN cuentan como vacio. `NaN is None` es False en Python: esa
    comparacion sola dejo pasar 3.949 filas sin elevacion en una version anterior."""
    return valor is None or pd.isna(valor)



# 1. Procedencia de las entradas

# Comprueba que los archivos de entrada sean los esperados y que cumplan las condiciones necesarias antes de continuar con el procesamiento
def verificar_procedencia():
    import geopandas as gpd

    log.info("BLOQUE 1  Procedencia de las entradas")
    for ruta in (C.ARCHIVO_SEGMENTOS, C.ARCHIVO_HUELLAS_ENTRADA, C.ARCHIVO_CONTRATO, C.ARCHIVO_VERTICES):
        if not ruta.exists():
            raise ErrorDeEtapa(f"Falta la entrada {ruta.relative_to(C.CARPETA_PROYECTO)}")
    # Carga el registro de huellas de la etapa anterior y prepara una lista para guardar la información de los archivos que se van verificando
    registro = json.loads(C.ARCHIVO_HUELLAS_ENTRADA.read_text(encoding="utf-8"))
    entradas = []
    # Lee la capa vial y calcula su huella de contenido para comprobar que los identificadores y las geometrías coincidan con los registrados
    gdf = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)
    huella = huella_segmentos(gdf)
    esperada = registro.get("contenido", {}).get(C.ARCHIVO_SEGMENTOS.name)
    if huella != esperada:
        raise ErrorDeEtapa(f"La huella de contenido de {C.ARCHIVO_SEGMENTOS.name} no coincide.\n"
                           f"  registrada: {esperada}\n  calculada:  {huella}")
    entradas.append({"archivo": C.ARCHIVO_SEGMENTOS.name, "tipo": "huella_contenido",
                     "valor": huella, "verificada": True})
    log.info(f"  {C.ARCHIVO_SEGMENTOS.name}: huella de contenido coincide ({huella[:12]}...)")
    # Calcula el SHA-256 de los archivos definidos en la configuración y lo compara con el registro anterior para detectar posibles cambios.
    for nombre in C.ARCHIVOS_CON_HUELLA_DE_ARCHIVO:
        ruta = C.CARPETA_ENTRADAS / nombre
        calculada = sha256_archivo(ruta)
        esperada = registro.get("archivos", {}).get(nombre)
        if calculada != esperada:
            raise ErrorDeEtapa(f"El sha256 de {nombre} no coincide con el registro de la etapa anterior.\n"
                               f"  registrado: {esperada}\n  calculado:  {calculada}")
        entradas.append({"archivo": nombre, "tipo": "sha256", "valor": calculada, "verificada": True})
        log.info(f"  {nombre}: sha256 coincide ({calculada[:12]}...)")

    # Como los vértices del IGAC se generan en esta etapa, registra su huella para dejar constancia del archivo, sin compararla con un registro anterior.
    # Los vertices del IGAC los produce esta etapa:Se registra su huella, no se compara
    entradas.append({"archivo": C.ARCHIVO_VERTICES.name, "tipo": "sha256",
                     "valor": sha256_archivo(C.ARCHIVO_VERTICES), "verificada": None})
    # Lee el contrato del grafo para obtener las columnas requeridas y el número esperado de segmentos, y después comprueba que la capa cumpla esas condiciones.
    contrato = json.loads(C.ARCHIVO_CONTRATO.read_text(encoding="utf-8"))
    columnas = contrato["retorno_esperado"]["columnas"]
    n_esperado = contrato["segmentos"]["n_segmentos"]
    if len(gdf) != n_esperado:
        raise ErrorDeEtapa(f"El gpkg tiene {len(gdf):,} segmentos y el contrato declara {n_esperado:,}")
    if gdf["segmento_id"].duplicated().any():
        raise ErrorDeEtapa("Hay segmento_id repetidos en el gpkg")
    if gdf.crs is None or gdf.crs.to_string() != C.CRS_METRICO:
        raise ErrorDeEtapa(f"El gpkg no esta en {C.CRS_METRICO} (trae {gdf.crs})")
    log.info(f"  {len(gdf):,} segmentos, {len(columnas)} columnas exigidas por el contrato")
    return gdf, columnas, entradas
#Verifica que los archivos necesarios existan, que su contenido coincida con los registros de referencia y que la capa vial tenga la cantidad de segmentos, los identificadores únicos y el sistema de coordenadas esperados


# 2. Consulta al MDT con cache

# Se encarga de consultar las elevaciones del MDT para las coordenadas que se van a usar y guardar los resultados para no repetir consultas
class ConsultorMDT:
    """Consulta el MDT 2020 punto a punto y guarda cada respuesta en cache.
    Un punto sin dato se guarda como vacio y no se vuelve a pedir: la cache
    distingue "consultado sin dato" de "nunca consultado".
    """
    # Inicializa el consultor y carga las coordenadas que ya se habían consultado, junto con sus elevaciones, desde el archivo de caché
    def __init__(self, solo_cache: bool):
        import requests

        self.solo_cache = solo_cache
        self.sesion = requests.Session()
        self.valores: dict[tuple, float] = {}
        self.nuevos = 0
        C.CARPETA_CACHE.mkdir(parents=True, exist_ok=True)
        if C.ARCHIVO_CACHE.exists():
            ck = pd.read_csv(C.ARCHIVO_CACHE, float_precision="round_trip")
            claves = zip(ck["lon"].round(C.DECIMALES_CLAVE_CACHE), ck["lat"].round(C.DECIMALES_CLAVE_CACHE))
            self.valores = dict(zip(claves, ck["elevacion_m"]))
        log.info(f"  cache: {len(self.valores):,} coordenadas ya consultadas")
    # Crea una clave para identificar cada punto usando sus coordenadas, redondeadas para que pequeñas diferencias decimales no generen duplicados
    @staticmethod
    def clave(lon, lat):
        return (round(float(lon), C.DECIMALES_CLAVE_CACHE), round(float(lat), C.DECIMALES_CLAVE_CACHE))
    # Consulta el servicio del MDT para obtener la elevación de una coordenada.
    # Si no hay un dato disponible, devuelve NaN, si falla la consulta, vuelve a intentarlo antes de detener el proceso
    def _pedir(self, lon, lat):
        params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": "4326",
                  "layers": "all", "tolerance": 1,
                  "mapExtent": f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001}",
                  "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"}
        for intento in range(1, C.MDT_REINTENTOS + 1):
            try:
                r = self.sesion.get(C.MDT_URL, params=params, timeout=C.MDT_TIEMPO_ESPERA_S)
                r.raise_for_status()
                resultados = r.json().get("results", [])
                if not resultados:
                    return np.nan
                v = resultados[0].get("attributes", {}).get(C.MDT_CAMPO_VALOR)
                return np.nan if v in (None, "NoData", "") else float(v)
            except Exception:
                if intento == C.MDT_REINTENTOS:
                    raise ErrorDeEtapa(f"El servicio del MDT no respondio para ({lon}, {lat}) "
                                       f"despues de {C.MDT_REINTENTOS} intentos. La cache conserva lo avanzado.")
                time.sleep(0.5 * intento)
    # Recibe una lista de coordenadas y obtiene las elevaciones. Primero revisa cuáles ya están guardadas y consulta únicamente las que todavía faltan
    def elevaciones(self, puntos_lonlat, etiqueta=""):
        """Devuelve la elevacion de cada (lon, lat); consulta solo lo que falta."""
        faltan = []
        vistos = set()
        for lon, lat in puntos_lonlat:
            k = self.clave(lon, lat)
            if k not in self.valores and k not in vistos:
                faltan.append(k)
                vistos.add(k)
        if faltan:
            # Si se solicitó trabajar solo con la caché, detiene el proceso cuando encuentra coordenadas que todavía no tienen registro         
            if self.solo_cache:
                raise ErrorDeEtapa(f"{len(faltan):,} coordenadas de '{etiqueta}' no estan en cache y se pidio --solo-cache")
            log.info(f"  {etiqueta}: {len(faltan):,} coordenadas nuevas por consultar")
            for i, (lon, lat) in enumerate(faltan, 1):
                self.valores[(lon, lat)] = self._pedir(lon, lat)
                self.nuevos += 1
                time.sleep(C.MDT_PAUSA_S)
                if i % 2000 == 0:
                    self.guardar()
                    log.info(f"    {i:,}/{len(faltan):,}")
            self.guardar()
        return np.array([self.valores[self.clave(lon, lat)] for lon, lat in puntos_lonlat], dtype=float)
    # Guarda en un archivo CSV todas las coordenadas consultadas y sus elevaciones, incluidos los puntos sin dato, para poder reutilizar la información después
    def guardar(self):
        filas = [(k[0], k[1], v) for k, v in self.valores.items()]
        # %.17g garantiza que el valor leido de la cache sea identico al consultado.
        pd.DataFrame(filas, columns=["lon", "lat", "elevacion_m"]).to_csv(C.ARCHIVO_CACHE, index=False,
                                                                          float_format="%.17g")



# 3. Exactitud vertical (sigma_z)

# Calcula estadísticas para evaluar qué tan diferentes son las elevaciones del MDT respecto a las elevaciones de referencia, usando los residuos disponibles
def estadisticos(residuos: pd.Series) -> dict:
    r = residuos.dropna()
    rmse = float(np.sqrt((r ** 2).mean()))
    return {"n": int(len(r)), "rmse_z_m": rmse, "media_m": float(r.mean()),
            "mediana_m": float(r.median()), "desv_estandar_m": float(r.std()),
            "nmad_m": float(1.4826 * np.median(np.abs(r - r.median()))),
            "abs_p68_3_m": float(r.abs().quantile(0.683)), "abs_p95_m": float(r.abs().quantile(0.95)),
            "exactitud_nssda_95_m": C.FACTOR_NSSDA_95 * rmse}

# Evalúa la exactitud vertical del MDT comparando sus elevaciones con las de los vértices del IGAC y verifica que el sigma_z obtenido sea el esperado.

def medir_exactitud_vertical(mdt: ConsultorMDT):
    """RMSEz del MDT contra los vertices del IGAC (NSSDA).

    La depuracion no se decide aqui: cada exclusion esta escrita en el CSV de
    vertices (columna motivo_exclusion) con su evidencia. Este bloque solo
    aplica esas exclusiones, calcula los conjuntos y verifica el valor adoptado.
    """
    log.info("BLOQUE 3  Exactitud vertical")
    # Carga los vértices de referencia, identifica cuáles están marcados para excluir y consulta en el MDT la elevación correspondiente a cada coordenada
    v = pd.read_csv(C.ARCHIVO_VERTICES)
    v["excluir"] = v["excluir"].astype(str).str.lower().eq("true")
    v["elevacion_mdt_m"] = mdt.elevaciones(list(zip(v["lon"], v["lat"])), "vertices IGAC")
    v["residuo_m"] = v["elevacion_mdt_m"] - v["altitud_igac_m"]
    con_dato = v["residuo_m"].notna()
    # Define un umbral de investigación para identificar diferencias de elevación inusualmente grandes. 
    # Se calcula primero con los vértices materializados y luego se recalcula sin los valores que superan el primer umbral, para evitar que las diferencias extremas oculten otras diferencias importantes.
    # Superar el umbral no excluye automáticamente un vértice: Ya que debe existir un motivo de exclusión registrado.
    # Umbral (ASPRS, 3 desviaciones), calculado sobre los vertices candidatos: Con dato y materializados. 
    # Los destruidos ya salen por un filtro que no depende del residuo, asi que no deben influir en el
    # umbral. 
    # Etapa 1: todos los candidatos. 
    # Etapa 2: sin los que superan la etapa 1, porque los errores grandes inflan la desviacion y enmascaran a los moderados. 
    # El umbral solo decide a quienes investigar: ningun vertice sale sin motivo escrito
    candidatos = con_dato & v["estado_geovisor"].str.lower().eq("materializado")
    umbral = C.DESVIACIONES_INVESTIGACION * v.loc[candidatos, "residuo_m"].std()
    bajo_1 = candidatos & (v["residuo_m"].abs() <= umbral)
    umbral_2 = C.DESVIACIONES_INVESTIGACION * v.loc[bajo_1, "residuo_m"].std()
    v["supera_umbral_investigacion"] = candidatos & (v["residuo_m"].abs() > umbral_2)
    sin_investigar = v[v["supera_umbral_investigacion"] & ~v["excluir"]
                       & v["motivo_exclusion"].fillna("").eq("")]
    if len(sin_investigar):
        log.warning(f"  vertices sobre el umbral sin motivo registrado: {list(sin_investigar['vertice'])}")
    # Define tres grupos de vértices para comparar los resultados:
    # Todos los que tienen datos, los materializados con datos y los adoptados, es decir, los que tienen datos y no están marcados para excluir
    materializados = con_dato & v["estado_geovisor"].str.lower().eq("materializado")
    adoptado = con_dato & ~v["excluir"]
    conjuntos = {
        "todos_con_dato": con_dato,
        "materializados": materializados,
        "adoptado": adoptado,
    }
    # Calcula las estadísticas de cada grupo y reúne los resultados en una tabla para facilitar su comparación
    tabla = []
    for nombre, mascara in conjuntos.items():
        fila = {"conjunto": nombre}
        fila.update(estadisticos(v.loc[mascara, "residuo_m"]))
        tabla.append(fila)
    tabla = pd.DataFrame(tabla)

    # Registra los vértices excluidos y sus motivos, junto con los resultados de los umbrales de investigación y las estadísticas de cada grupo
    for _, f in v[v["excluir"]].iterrows():
        log.info(f"  excluido {f['vertice']}: {str(f['motivo_exclusion'])[:90]}")
    sigma = float(tabla.loc[tabla["conjunto"] == "adoptado", "rmse_z_m"].iloc[0])
    log.info(f"  vertices: {len(v)}  con dato: {int(con_dato.sum())}  adoptados: {int(adoptado.sum())}")
    log.info(f"  umbral de investigacion etapa 1 (3 desv, materializados): {umbral:.2f} m; superan: "
             f"{list(v.loc[candidatos & (v['residuo_m'].abs() > umbral), 'vertice'])}")
    log.info(f"  umbral de investigacion etapa 2 (3 desv, sin groseros): {umbral_2:.2f} m; superan: "
             f"{list(v.loc[v['supera_umbral_investigacion'], 'vertice'])}")
    for _, f in tabla.iterrows():
        log.info(f"  {f['conjunto']:15s} n={f['n']:3d}  RMSEz={f['rmse_z_m']:.3f}  "
                 f"mediana={f['mediana_m']:+.3f}  NMAD={f['nmad_m']:.3f}")
    # Comprueba que el RMSEz calculado para los vértices adoptados coincida con el sigma_z definido, dentro de la tolerancia permitida
    if abs(sigma - C.SIGMA_Z_ADOPTADO_M) > C.TOLERANCIA_SIGMA_Z_M:
        raise ErrorDeEtapa(f"sigma_z recalculado ({sigma:.4f} m) no coincide con el adoptado en la "
                           f"configuracion ({C.SIGMA_Z_ADOPTADO_M} m). Revise vertices o configuracion.")
    # Guarda los resultados de cada vértice y una tabla resumen con las estadísticas calculadas para los tres grupos
    columnas = ["vertice", "lat", "lon", "altitud_igac_m", "estado_geovisor", "elevacion_mdt_m",
                "residuo_m", "supera_umbral_investigacion", "excluir", "motivo_exclusion"]
    v[columnas].to_csv(C.ARCHIVO_EXACTITUD, index=False)
    tabla.to_csv(C.ARCHIVO_EXACTITUD.with_name(C.ARCHIVO_EXACTITUD.stem + "_resumen.csv"), index=False)
    # Devuelve el sigma_z adoptado, la tabla con las estadísticas y el segundo umbral de investigación para utilizarlos en las siguientes etapas
    return C.SIGMA_Z_ADOPTADO_M, tabla, float(umbral_2)

#evalúa las diferencias entre las elevaciones del MDT y las del IGAC, calcula estadísticas de exactitud vertical, identifica vértices con diferencias que requieren revisión y comprueba que el valor de sigma_z coincida con el configurado

# 4. Ancho de correlacion

# Estima qué tan lejos se extiende la relación entre los errores de elevación del MDT, usando una zona de terreno para analizar su comportamiento espacial.
def estimar_ancho_correlacion(mdt: ConsultorMDT):
    """Ancho de correlacion del error del MDT por terreno estable.

    Grilla de puntos consultados al MDT en una zona plana, se resta un plano
    de tendencia y se ajusta un variograma con xDEM. La escala que entra en
    rho = exp(-L/A) es el rango efectivo exponencial dividido por 3.
    """
    import xdem

    log.info("BLOQUE 4  Ancho de correlacion")
    # Construye una grilla de coordenadas alrededor del punto definido, usando el espaciado entre sus puntos.    
    n = int(2 * C.CORRELACION_MEDIO_LADO_M / C.CORRELACION_ESPACIADO_M) + 1
    lat0 = C.CORRELACION_CENTRO_LAT
    dlat = C.CORRELACION_ESPACIADO_M / 111_320
    dlon = C.CORRELACION_ESPACIADO_M / (111_320 * np.cos(np.radians(lat0)))
    lats = lat0 + dlat * (np.arange(n) - n // 2)
    lons = C.CORRELACION_CENTRO_LON + dlon * (np.arange(n) - n // 2)
    puntos = [(lo, la) for la in lats for lo in lons]
    # Consulta las elevaciones de todos los puntos de la grilla y guarda los resultados para poder revisarlos
    z = mdt.elevaciones(puntos, "grilla de correlacion").reshape(n, n)
    pd.DataFrame(z).to_csv(C.ARCHIVO_GRILLA, index=False)
    # Comprueba que al menos el 80 % de los puntos tenga elevación disponible. Si faltan demasiados datos, detiene el proceso para evitar una estimación poco confiable
    validos = ~np.isnan(z)
    if validos.sum() < 0.8 * z.size:
        raise ErrorDeEtapa(f"La grilla de correlacion tiene solo {int(validos.sum())} de {z.size} puntos con dato")
    # Ajusta un plano a las elevaciones para separar la tendencia general del terreno.
    # Después calcula los residuos, que son las diferencias entre las elevaciones observadas y las estimadas por ese plano
    
    yy, xx = np.mgrid[0:n, 0:n]
    A = np.column_stack([xx[validos], yy[validos], np.ones(int(validos.sum()))])
    coef, *_ = np.linalg.lstsq(A, z[validos], rcond=None)
    residuo = z - (coef[0] * xx + coef[1] * yy + coef[2])
    # Calcula el variograma empírico de los residuos para analizar cómo cambia su relación espacial según la distancia entre los puntos
    vario = xdem.spatialstats.sample_empirical_variogram(
        values=residuo, gsd=C.CORRELACION_ESPACIADO_M,
        subsample=C.CORRELACION_SUBMUESTRA, random_state=C.CORRELACION_SEMILLA)

    # Ajusta dos modelos de variograma y calcula, para cada uno, su rango efectivo y el parámetro de distancia utilizado para representar la correlación espacial    
    filas = []
    for modelo, divisor in (("Exponential", C.DIVISOR_RANGO_EXPONENCIAL), ("Gaussian", C.DIVISOR_RANGO_GAUSSIANO)):
        _, par = xdem.spatialstats.fit_sum_model_variogram(list_models=[modelo], empirical_variogram=vario)
        r = float(par["range"].iloc[0])
        filas.append({"modelo": modelo, "rango_efectivo_m": r, "parametro_a_m": r / divisor,
                      "ventana_m": 2 * C.CORRELACION_MEDIO_LADO_M, "espaciado_m": C.CORRELACION_ESPACIADO_M,
                      "puntos_validos": int(validos.sum()), "desv_residuo_m": float(np.nanstd(residuo))})
    tabla = pd.DataFrame(filas)
    tabla.to_csv(C.ARCHIVO_CORRELACION, index=False)

    # Selecciona el ancho correspondiente al modelo configurado y muestra los resultados de ambos modelos en el registro de ejecución    

    ancho = float(tabla.loc[tabla["modelo"] == C.CORRELACION_MODELO, "parametro_a_m"].iloc[0])
    for _, f in tabla.iterrows():
        log.info(f"  {f['modelo']:11s} rango efectivo {f['rango_efectivo_m']:.1f} m  ->  a = {f['parametro_a_m']:.1f} m")
    # Comprueba que el ancho calculado coincida con el valor adoptado en la configuración, dentro de la tolerancia permitida        
        
    if abs(ancho - C.ANCHO_CORRELACION_ADOPTADO_M) > C.TOLERANCIA_ANCHO_M:
        raise ErrorDeEtapa(f"Ancho recalculado ({ancho:.2f} m) no coincide con el adoptado "
                           f"({C.ANCHO_CORRELACION_ADOPTADO_M} m). Revise la grilla o la configuracion.")
    # Devuelve el ancho de correlación adoptado y la tabla con los resultados de los dos modelos evaluados    
    return C.ANCHO_CORRELACION_ADOPTADO_M, tabla

# Consulta las elevaciones del MDT en una grilla de terreno estable, elimina la tendencia general del terreno y analiza cómo se relacionan espacialmente los errores restantes

# 5. Muestreo adaptativo y perfiles

# Obtiene las elevaciones a lo largo de cada segmento vial, ajustando la cantidad de puntos de muestreo según la pendiente preliminar del segmento
def muestrear_perfiles(gdf, mdt: ConsultorMDT):
    """Dos etapas por segmento.

    Etapa 1: elevacion en los extremos (fraccion 0 y 1 de la geometria) y
    pendiente preliminar. Etapa 2: remuestreo con 50 m si |preliminar| < 3 %
    y 10 m en otro caso. Las fracciones 0 y 1 se repiten en la etapa 2, asi
    que los extremos son las mismas coordenadas y la misma elevacion
    """
    log.info("BLOQUE 5  Muestreo adaptativo")
    # Transforma las geometrías al sistema de coordenadas usado para consultar el MDT y obtiene las longitudes e identificadores de los segmentos    
    geo = gdf.to_crs(C.CRS_CONSULTA).geometry.values
    largo = gdf["longitud_m"].to_numpy(dtype=float)
    ids = gdf["segmento_id"].to_numpy()
    # Consulta las elevaciones al inicio y al final de cada segmento para calcular una primera aproximación de su pendiente
    ini = [g.interpolate(0, normalized=True) for g in geo]
    fin = [g.interpolate(1, normalized=True) for g in geo]
    z_ini = mdt.elevaciones([(p.x, p.y) for p in ini], "extremos (inicio)")
    z_fin = mdt.elevaciones([(p.x, p.y) for p in fin], "extremos (fin)")
    # Identifica los segmentos que no tienen elevación en alguno de sus extremos o cuya longitud no es válida. 
    # Para los demás, calcula la pendiente preliminar y define el espaciado de muestreo según el umbral establecido
    extremo_vacio = np.isnan(z_ini) | np.isnan(z_fin) | ~(largo > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        preliminar = 100 * (z_fin - z_ini) / largo
    paso = np.where(~extremo_vacio & (np.abs(preliminar) < C.UMBRAL_PLANO_PCT), C.PASO_PLANO_M, C.PASO_PENDIENTE_M)
    log.info(f"  extremos sin dato: {int(extremo_vacio.sum()):,}")
    # Genera los puntos de cada perfil según el espaciado elegido.
    # Los segmentos con extremos sin datos se omiten y los demás se preparan para consultar sus elevaciones en una sola operación
    perfiles = []
    todos = []
    for i in range(len(gdf)):
        if extremo_vacio[i]:
            perfiles.append(None)
            continue
        n_puntos = max(2, int(largo[i] / paso[i]) + 1)
        pts = [geo[i].interpolate(f, normalized=True) for f in np.linspace(0, 1, n_puntos)]
        coords = [(p.x, p.y) for p in pts]
        perfiles.append(coords)
        todos.extend(coords)
    zz = mdt.elevaciones(todos, "remuestreo")
    # Organiza los resultados por segmento, asociando sus elevaciones inicial y final, el número de puntos, el espaciado utilizado y las elevaciones de todo. 
    # Si un segmento no pudo muestrearse, deja vacío
    resultado = []
    cursor = 0
    for i in range(len(gdf)):
        if perfiles[i] is None:
            resultado.append((ids[i], z_ini[i], z_fin[i], 2, paso[i], None))
            continue
        k = len(perfiles[i])
        resultado.append((ids[i], z_ini[i], z_fin[i], k, paso[i], zz[cursor:cursor + k]))
        cursor += k
    return resultado



# 6. Columnas del contrato (Conexión con el grafo)
# Clasifica el segmento vial según el valor absoluto de su pendiente neta, utilizando los límites y las etiquetas definidos para la clasificación INVIAS.

def clasificar_invias(pendiente_abs: float) -> str:
    if pendiente_abs < C.INVIAS_LIMITE_ONDULADO:
        return C.ETIQUETAS_INVIAS[0]
    if pendiente_abs < C.INVIAS_LIMITE_MONTANOSO:
        return C.ETIQUETAS_INVIAS[1]
    if pendiente_abs <= C.INVIAS_LIMITE_ESCARPADO:
        return C.ETIQUETAS_INVIAS[2]
    return C.ETIQUETAS_INVIAS[3]
# Calcula las variables de pendiente y sus indicadores de incertidumbre para cada segmento, respetando las columnas y el orden definidos para agrupar

def calcular_columnas(gdf, perfiles, sigma_z, ancho, columnas_contrato):
    """Una fila por segmento con las formulas del contrato.

    Si falta un extremo o cualquier punto intermedio, el segmento queda con
    fuera_cobertura_mdt = True y sus columnas de pendiente vacias. Ningun
    segmento se elimina.
    """
    log.info("BLOQUE 6  Columnas del contrato")
    # Crea una correspondencia entre cada identificador de segmento y su longitud, para consultar la longitud sin recorrer nuevamente el GeoDataFrame   
    largo = dict(zip(gdf["segmento_id"], gdf["longitud_m"].astype(float)))
    # Define las columnas que quedarán vacías cuando no se disponga de todas las elevaciones necesarias para calcular las métricas del segmento    
    vacias = {c: None for c in ["pendiente_neta_pct", "pendiente_acumulada_pct", "ganancia_elevacion_m",
                                "perdida_elevacion_m", "clasificacion_invias", "error_pendiente_pct",
                                "distinta_de_cero_2sigma", "ruido_acumulada_pct", "pendiente_extrema",
                                "rho_correlacion"]}
    filas = []
    # Procesa los perfiles uno por uno y prepara los datos básicos de cada segmento
    for sid, z_ini, z_fin, n, paso, z in perfiles:
        L = largo[sid]
        fila = {"segmento_id": sid, "z_inicio_m": None if es_vacio(z_ini) else z_ini,
                "z_fin_m": None if es_vacio(z_fin) else z_fin, "n_puntos_muestreados": n,
                "paso_muestreo_m": paso, "ancho_correlacion_m": ancho, "sigma_z_m": sigma_z}
        # Si falta alguna elevación del perfil, marca el segmento como fuera de cobertura y conserva el registro sin calcular las métricas de pendiente        
        if z is None or any(es_vacio(e) for e in z):
            fila.update(vacias)
            fila["fuera_cobertura_mdt"] = True
            filas.append(fila)
            continue
        # Calcula los cambios de elevación entre puntos consecutivos del perfil. Los incrementos positivos representan ganancia y los negativos, pérdida
        dz = np.diff(z)
        ganancia = float(dz[dz > 0].sum()) + 0.0
        perdida = float(-dz[dz < 0].sum()) + 0.0   # + 0.0 evita escribir -0.0
        # Calcula la pendiente neta entre los extremos y la pendiente acumulada a partir de las ganancias y pérdidas de elevación a lo largo del segmento
        neta = 100 * (z_fin - z_ini) / L
        acumulada = 100 * (ganancia + perdida) / L
        # Estima la correlación entre los errores de elevación de los extremos y, con ella, el error asociado al cálculo de la pendiente neta
    
        rho = float(np.exp(-L / ancho))
        error = 100 * np.sqrt(2 * sigma_z ** 2 * (1 - rho)) / L
# Estima la separación entre puntos consecutivos y el nivel de ruido que puede introducir la incertidumbre del MDT en la pendiente acumulada   
        p = L / (n - 1)
        sd = sigma_z * np.sqrt(2 * (1 - np.exp(-p / ancho)))
        ruido = 100 * np.sqrt(2 / np.pi) * sd / p
        # Guarda las métricas calculadas y los indicadores que permiten identificar pendientes estadísticamente distintas de cero o valores extremos        

        fila.update({
            "pendiente_neta_pct": neta, "pendiente_acumulada_pct": acumulada,
            "ganancia_elevacion_m": ganancia, "perdida_elevacion_m": perdida,
            "clasificacion_invias": clasificar_invias(abs(neta)),
            "error_pendiente_pct": error,
            "distinta_de_cero_2sigma": bool(abs(neta) > C.K_SIGMA * error),
            "ruido_acumulada_pct": ruido,
            "pendiente_extrema": bool(max(abs(neta), abs(acumulada)) > C.UMBRAL_PENDIENTE_EXTREMA_PCT),
            "fuera_cobertura_mdt": False, "rho_correlacion": rho,
        })
        filas.append(fila)
# Convierte los registros en un DataFrame y selecciona únicamente las columnas del contrato, conservando el orden establecido para la conexión con el grafo      

    df = pd.DataFrame(filas)
    return df[columnas_contrato]



# 7. Sensibilidad

# Evalúa cómo cambia la proporción de segmentos con pendiente estadísticamente distinta de cero al modificar la incertidumbre vertical y el ancho de correlación
def sensibilidad(df, gdf):
    """Porcentaje de segmentos distintos de cero bajo otros sigma_z y anchos."""
    log.info("BLOQUE 7  Sensibilidad")
    # Conserva los segmentos que tienen cobertura del MDT y añade sus longitudes, necesarias para recalcular el error de la pendiente en cada escenario    
    con = df[~df["fuera_cobertura_mdt"]].merge(gdf[["segmento_id", "longitud_m"]], on="segmento_id")
    L = con["longitud_m"].to_numpy(float)
    neta = con["pendiente_neta_pct"].abs().to_numpy(float)
    filas = []

    # Repite el cálculo para cada combinación de incertidumbre vertical y ancho de correlación definidos 
    for s in C.SENSIBILIDAD_SIGMAS_M:
        for a in C.SENSIBILIDAD_ANCHOS_M:
            # Si el escenario supone independencia entre los errores, fija rho en cero.
            # En los demás casos, calcula la correlación según la longitud del segmento y el ancho de correlación establecido           
            rho = 0.0 if a is None else np.exp(-L / a)
            err = 100 * np.sqrt(2 * s ** 2 * (1 - rho)) / L
            dist = neta > C.K_SIGMA * err
            # Registra el número y porcentaje de segmentos distintos de cero, junto con el error mediano de la pendiente para cada escenario           
            filas.append({"sigma_z_m": s, "ancho_m": "independencia" if a is None else a,
                          "distintos_de_cero": int(dist.sum()), "pct": round(100 * dist.mean(), 2),
                          "error_mediano_pp": round(float(np.median(err)), 2)})
    # Organiza los resultados en una tabla, la guarda en CSV 
    tabla = pd.DataFrame(filas)
    tabla.to_csv(C.ARCHIVO_SENSIBILIDAD, index=False)
    return tabla



# 8. Validaciones

# Comprueba que los resultados cumplan las reglas de integridad, consistencia matemática y coherencia con las fórmulas definidas
def validar(df, gdf, columnas_contrato, sigma_z, ancho):
    """Cada regla se recalcula por un camino distinto al que produjo el dato."""
    log.info("BLOQUE 8  Validaciones")
    res = []
    # Registra el resultado de cada validación y lo escribe en la bitácora para identificar fácilmente las reglas que se cumplen o presentan fallas
    def regla(nombre, ok, detalle=""):
        res.append({"regla": nombre, "pasa": bool(ok), "detalle": detalle})
        log.info(f"  [{'OK' if ok else 'FALLA'}] {nombre} {detalle}")
    # Verifica que el archivo conserve la cantidad de segmentos, sus identificadores únicos y las columnas en el mismo orden para pegar con el grafo
    regla("misma cantidad de filas que el gpkg", len(df) == len(gdf), f"{len(df):,}")
    regla("mismos segmento_id que el gpkg", set(df["segmento_id"]) == set(gdf["segmento_id"]))
    regla("segmento_id sin repetidos", not df["segmento_id"].duplicated().any())
    regla("columnas y orden del contrato", list(df.columns) == list(columnas_contrato))
   
    # Separa los segmentos con cobertura válida del MDT y recupera sus longitudes para recalcular las métricas que dependen de ellas
    fuera = df["fuera_cobertura_mdt"].astype(bool)
    con = df[~fuera].merge(gdf[["segmento_id", "longitud_m"]], on="segmento_id")
    L = con["longitud_m"].to_numpy(float)
    neta = con["pendiente_neta_pct"].to_numpy(float)
    acum = con["pendiente_acumulada_pct"].to_numpy(float)
    # Comprueba que los segmentos con datos tengan todas las métricas necesarias y que los segmentos sin cobertura conserven vacías las columnas dependientes
    dependientes = ["pendiente_neta_pct", "pendiente_acumulada_pct", "ganancia_elevacion_m",
                    "perdida_elevacion_m", "clasificacion_invias", "error_pendiente_pct",
                    "distinta_de_cero_2sigma", "ruido_acumulada_pct", "pendiente_extrema", "rho_correlacion"]
    regla("sin vacios inesperados en segmentos con dato", not con[dependientes].isna().any().any())
    regla("segmentos sin cobertura con columnas vacias", df.loc[fuera, dependientes].isna().all().all(),
          f"{int(fuera.sum()):,} fuera de cobertura")
    # Recalcula la pendiente neta directamente a partir de las elevaciones de los extremos y verifica que la ganancia menos la pérdida corresponda al desnivel
    d = np.abs(neta - 100 * (con["z_fin_m"] - con["z_inicio_m"]).to_numpy() / L)
    regla("neta = 100 (z_fin - z_inicio) / L", np.nanmax(d) < 1e-9, f"max {np.nanmax(d):.1e}")
    d = np.abs((con["ganancia_elevacion_m"] - con["perdida_elevacion_m"]) - (con["z_fin_m"] - con["z_inicio_m"]))
    regla("ganancia - perdida = desnivel", np.nanmax(d) < 1e-6, f"max {np.nanmax(d):.1e}")
    # Comprueba las relaciones esperadas entre las pendientes y que la ganancia y la pérdida de elevación no tengan valores negativos    
    regla("acumulada >= |neta|", bool(np.all(acum >= np.abs(neta) - 1e-9)))
    regla("ganancia y perdida no negativas",
          bool((con["ganancia_elevacion_m"] >= 0).all() and (con["perdida_elevacion_m"] >= 0).all()))
    # Vuelve a calcular el error de la pendiente neta usando la incertidumbre vertical y el ancho de correlación, y contrasta los resultados con el archivo
    rho = np.exp(-L / ancho)
    err = 100 * np.sqrt(2 * sigma_z ** 2 * (1 - rho)) / L
    regla("error_pendiente_pct segun contrato", np.max(np.abs(err - con["error_pendiente_pct"])) < 1e-9)
    # Verifica que la identificación de pendientes distintas de cero y de pendientes extremas coincida con los umbrales establecidos en la configuración
    regla("distinta_de_cero_2sigma segun contrato",
          bool(((np.abs(neta) > C.K_SIGMA * err) == con["distinta_de_cero_2sigma"].astype(bool)).all()))
    extrema = np.maximum(np.abs(neta), acum) > C.UMBRAL_PENDIENTE_EXTREMA_PCT
    regla("pendiente_extrema segun contrato", bool((extrema == con["pendiente_extrema"].astype(bool)).all()))
    # Reconstruye la clasificación INVIAS y el paso de muestreo esperado a partir de la pendiente neta para comprobar que ambas columnas sean coherentes    
    a = np.abs(neta)
    inv = np.where(a < 3, "Plano", np.where(a < 6, "Ondulado", np.where(a <= 8, "Montañoso", "Escarpado")))
    regla("clasificacion INVIAS segun contrato", bool((inv == con["clasificacion_invias"]).all()))
    paso = np.where(a < C.UMBRAL_PLANO_PCT, C.PASO_PLANO_M, C.PASO_PENDIENTE_M)
    regla("paso adaptativo coherente con la neta", bool((paso == con["paso_muestreo_m"]).all()))
    # Confirma que todos los segmentos del archivo utilicen los mismos valores de incertidumbre vertical y ancho de correlación    
    regla("un solo sigma_z y un solo ancho en el archivo",
          df["sigma_z_m"].nunique() == 1 and df["ancho_correlacion_m"].nunique() == 1)
    # Separa el identificador base y el sentido de circulación para comparar los segmentos equivalentes en las direcciones FT y TF
    base = df["segmento_id"].str.rsplit("_", n=1)
    piv = df.assign(base=base.str[0], sentido=base.str[1]).pivot_table(
        index="base", columns="sentido", values=["pendiente_neta_pct", "z_inicio_m", "z_fin_m"])
    # Si existen ambas direcciones, comprueba que sus pendientes tengan igual magnitud y signo contrario, y que sus elevaciones de extremos coincidan    
    if ("pendiente_neta_pct", "FT") in piv and ("pendiente_neta_pct", "TF") in piv:
        p = piv.dropna(subset=[("pendiente_neta_pct", "FT"), ("pendiente_neta_pct", "TF")])
        s = (p[("pendiente_neta_pct", "FT")] + p[("pendiente_neta_pct", "TF")]).abs()
        z = (p[("z_inicio_m", "FT")] - p[("z_fin_m", "TF")]).abs()
        regla("FT y TF simetricos", s.max() < 1e-9 and z.max() == 0, f"{len(p):,} pares")
    # Si alguna regla falla, detiene el proceso para evitar exportar un archivo que no haya superado las validaciones. Si todas pasan, devuelve sus resultados
    fallas = [r for r in res if not r["pasa"]]
    if fallas:
        raise ErrorDeEtapa(f"{len(fallas)} validaciones fallaron; no se exporta el archivo: "
                           f"{[f['regla'] for f in fallas]}")
    return res



# 9. Exportacion, huellas, manifiesto

# Recopila las versiones de Python y de las bibliotecas utilizadas durante el proceso para dejar registrado el entorno en el que se generaron los resultados
def versiones():
    paquetes = ["numpy", "pandas", "geopandas", "shapely", "pyproj", "pyogrio",
                "requests", "xdem", "scikit-gstat"]
    salida = {"python": platform.python_version(), "sistema": platform.platform()}
    # Consulta la versión instalada de cada paquete. Si alguno no está instalado, registra esa condición en lugar de interrumpir la ejecución    
    for p in paquetes:
        try:
            salida[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            salida[p] = "no instalado"
    return salida
# Exporta los resultados, calcula las huellas digitales de los archivos generados 

def exportar(df, entradas, tabla_sigma, umbral, tabla_corr, tabla_sens, validaciones, inicio, mdt):
    log.info("BLOQUE 9  Exportacion")
    # Guarda la tabla principal de pendientes en formato CSV    
    df.to_csv(C.ARCHIVO_PENDIENTES, index=False, encoding="utf-8")
    # Calcula el hash SHA-256 de cada archivo de salida existente para poder verificar posteriormente su integridad    
    salidas = {}
    for ruta in (C.ARCHIVO_PENDIENTES, C.ARCHIVO_EXACTITUD, C.ARCHIVO_CORRELACION,
                 C.ARCHIVO_GRILLA, C.ARCHIVO_SENSIBILIDAD):
        if ruta.exists():
            salidas[ruta.name] = sha256_archivo(ruta)
    # Guarda la huella del archivo principal en un archivo auxiliar y registra las huellas de todos los archivos de salida en un JSON            
    sha_principal = salidas[C.ARCHIVO_PENDIENTES.name]
    C.ARCHIVO_PENDIENTES.with_suffix(".csv.sha256").write_text(
        f"{sha_principal}  {C.ARCHIVO_PENDIENTES.name}\n", encoding="utf-8")
    C.ARCHIVO_HUELLAS_SALIDA.write_text(json.dumps(
        {"archivos": salidas,
         "nota": "SHA-256 de cada archivo producido por la etapa de terreno y pendiente."},
        indent=2, ensure_ascii=False), encoding="utf-8")
    # Separa los segmentos con datos válidos de aquellos que quedaron fuera de la cobertura del MDT para resumir los principales resultados del proceso    
    

    fuera = df["fuera_cobertura_mdt"].astype(bool)
    con = df[~fuera]
    resultados = {
        "segmentos": int(len(df)), "con_dato": int(len(con)), "fuera_cobertura": int(fuera.sum()),
        "clasificacion_invias": con["clasificacion_invias"].value_counts().to_dict(),
        "distinta_de_cero_2sigma": int(con["distinta_de_cero_2sigma"].astype(bool).sum()),
        "pendiente_extrema": int(con["pendiente_extrema"].astype(bool).sum()),
        "acumulada_bajo_piso_de_ruido": int((con["pendiente_acumulada_pct"] < con["ruido_acumulada_pct"]).sum()),
        "error_pendiente_mediano_pp": float(con["error_pendiente_pct"].median()),
    }
    # Recopila los parámetros definidos en el módulo de configuración.
    # Convierte a texto los valores que no corresponden a tipos simples para facilitar su almacenamiento en el manifiesto JSON    
    parametros = {k: ruta_relativa(v) if isinstance(v, Path)
                  else (str(v) if not isinstance(v, (int, float, str, list, tuple, type(None))) else v)
                  for k, v in vars(C).items() if k.isupper()}
    # Construye el manifiesto de ejecución con la identificación del código, las huellas de los archivos de entrada y salida, las versiones utilizadas, los parámetros, las validaciones y los principales resultados    
    manifiesto = {
        "etapa": "terreno y pendiente, Bogota",
        "codigo": {"archivo": "bogota_pendientes_mdt2020.py",
                   "sha256": sha256_archivo(__file__),
                   "configuracion_sha256": sha256_archivo(C.__file__)},
        "ejecucion": {"inicio": inicio, "fin": ahora(), "consultas_nuevas_al_mdt": mdt.nuevos},
        "entorno": versiones(),
        "parametros": parametros,
        "entradas": entradas,
        "salidas": salidas,
        "exactitud_vertical": tabla_sigma.to_dict(orient="records"),
        "umbral_investigacion_m": umbral,
        "ancho_correlacion": tabla_corr.to_dict(orient="records"),
        "sensibilidad": tabla_sens.to_dict(orient="records"),
        "validaciones": validaciones,
        "resultados": resultados,
    }
    # Escribe el manifiesto en formato JSON, conservando los caracteres originales y convirtiendo a texto los valores que no sean serializables    
    C.ARCHIVO_MANIFIESTO.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False, default=str),
                                    encoding="utf-8")
    # Registra en la bitácora el nombre y la huella abreviada del archivo principal, además de los valores del resumen final    
    log.info(f"  {C.ARCHIVO_PENDIENTES.name}  sha256 {sha_principal[:12]}...")
    for k, v in resultados.items():
        log.info(f"  {k}: {v}")


# Coordina la ejecución completa del proceso, desde la verificación de los datos de entrada hasta la validación y exportación de los resultados

def main():
    # Configura los argumentos que se pueden recibir al ejecutar el script desde la terminal, incluida la opción de trabajar únicamente con la caché    
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--solo-cache", action="store_true",
                        help="no consulta el servicio; falla si falta una coordenada en cache")
    args = parser.parse_args()
    # Configura el registro de eventos, guarda la hora de inicio y la registra en la bitácora usando la hora local de Bogotá
    configurar_bitacora()
    inicio = ahora()
    log.info(f"Inicio {inicio['bogota']}")
    try:
        # Verifica la procedencia de los archivos de entrada y obtiene los segmentos, las columnas del contrato y sus huellas
        gdf, columnas, entradas = verificar_procedencia()
        # Inicializa el consultor del MDT, que recupera las elevaciones desde la caché o consulta el servicio       
        log.info("BLOQUE 2  Cache de elevaciones")
        mdt = ConsultorMDT(args.solo_cache)
        # Evalúa la exactitud vertical del MDT y estima el ancho de correlación espacial de los errores de elevación        
        sigma_z, tabla_sigma, umbral = medir_exactitud_vertical(mdt)
        ancho, tabla_corr = estimar_ancho_correlacion(mdt)
        # Muestrea las elevaciones a lo largo de los segmentos y calcula las columnas de pendiente, incertidumbre y clasificación        
        perfiles = muestrear_perfiles(gdf, mdt)
        df = calcular_columnas(gdf, perfiles, sigma_z, ancho, columnas)
        # Evalúa la sensibilidad de los resultados ante distintos parámetros y ejecuta las validaciones de consistencia del archivo final        
        tabla_sens = sensibilidad(df, gdf)
        validaciones = validar(df, gdf, columnas, sigma_z, ancho)
        # Exporta el archivo principal y genera las huellas digitales y el manifiesto con los parámetros, las validaciones y los resultados        
        exportar(df, entradas, tabla_sigma, umbral, tabla_corr, tabla_sens, validaciones, inicio, mdt)
    # Si ocurre un error durante alguna etapa, registra el motivo, informa que la ejecución se detuvo y finaliza con un código de error        
    except ErrorDeEtapa as e:
        log.error(str(e))
        log.error("Corrida detenida. No se produjo el archivo de pendientes.")
        sys.exit(1)
    log.info(f"Fin {ahora()['bogota']}")
# Ejecuta la función principal únicamente cuando este archivo se ejecuta directamente, y no cuando se importa como módulo desde otro script

if __name__ == "__main__":
    main()
