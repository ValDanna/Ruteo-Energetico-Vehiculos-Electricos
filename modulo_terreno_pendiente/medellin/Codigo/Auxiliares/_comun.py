"""
Rutas y funciones compartidas por los auxiliares. 
"""
import hashlib
import sys
from pathlib import Path

import pandas as pd

CARPETA_CODIGO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CARPETA_CODIGO))

import medellin_pendientes_config as C  # noqa: E402

SALIDA_OFICIAL = C.salidas()["pendientes"]


def carpeta_salida():
    # Crea la carpeta de salidas auxiliares si no existe y devuelve su ruta
    C.CARPETA_SALIDAS_AUX.mkdir(parents=True, exist_ok=True)
    return C.CARPETA_SALIDAS_AUX


def sha256_archivo(ruta):
    # Calcula el hash SHA-256 del archivo para verificar su integridad e identificar cambios.
    # Lee el archivo en bloques para evitar cargarlo completo en memoria    
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def a_booleano(serie):
     #Normaliza los valores booleanos que pueden venir como True/False o como texto
    return serie.map({True: True, False: False, "True": True, "False": False})


def leer_pendientes(ruta=None):
    """Archivo de pendientes con booleanos normalizados. Por defecto el oficial."""
    ruta = Path(ruta) if ruta else SALIDA_OFICIAL
    if not ruta.exists():
        raise SystemExit(f"No esta {ruta}. Corra antes el programa principal.")
    # round_trip: el lector rapido de pandas puede cambiar el ultimo digito
    df = pd.read_csv(ruta, low_memory=False, float_precision="round_trip")
    # Normaliza las columnas de indicadores para que sus valores sean booleanos independientemente de como se hayan interpretado al leer el CSV    
    for col in ["distinta_de_cero_2sigma", "pendiente_extrema", "fuera_cobertura_mdt", "es_tunel"]:
        df[col] = a_booleano(df[col])
    return df


def leer_segmentos(geometria=True):
    # Carga la capa de segmentos viales desde el archivo geográfico
    import geopandas as gpd
    if geometria:
        return gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS)
    # Lee únicamente los atributos, sin cargar las geometrías, para reducir el uso de memoria
    return gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS, ignore_geometry=True)


def recorte_olaya():
    """Arreglo del recorte del Olaya Herrera y su transformacion.
    Lo corta del MDT y lo guarda en datos_salida/auxiliares; si ya lo corto una
    corrida anterior de un auxiliar, lo reutiliza. Comprueba su SHA-256."""
    # Importa las herramientas para leer y escribir rásteres, transformar coordenadas y calcular la ventana espacial que delimita el recorte    
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds
    # Define la ruta donde se almacenará el recorte del MDT
    ruta = C.ARCHIVO_RECORTE_OLAYA
    if not ruta.exists():
        if not C.ARCHIVO_MDT.exists():
            raise SystemExit(f"Hace falta el MDT ({C.ARCHIVO_MDT}) o el recorte ({ruta}).")
        # Obtiene los límites geográficos definidos para el área del aeropuerto
        caja = C.CAJA_OLAYA
        with rasterio.open(C.ARCHIVO_MDT) as src:
            # Transforma los límites de EPSG:4326 al sistema de coordenadas del MDT
            t = Transformer.from_crs("EPSG:4326", C.CRS_MDT, always_xy=True)
            x0, y0 = t.transform(caja[0], caja[1])
            x1, y1 = t.transform(caja[2], caja[3])
            # Convierte los límites transformados en una ventana de píxeles del ráster
            ventana = from_bounds(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), src.transform)
            # Lee las elevaciones de la ventana y conserva la configuración original
            datos = src.read(1, window=ventana)
            perfil = src.profile.copy()
        # Actualiza las dimensiones, la transformación espacial y la compresión    
            perfil.update(height=datos.shape[0], width=datos.shape[1],
                          transform=src.window_transform(ventana), compress="deflate", tiled=True)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(ruta, "w", **perfil) as dst:
            dst.write(datos, 1)
    #Calcula el SHA-256 del archivo para comprobar su integridad        
    sha = sha256_archivo(ruta)
    if sha != C.SHA256_RECORTE_OLAYA:
        print(f"  [AVISO] el recorte tiene SHA {sha[:12]}..., distinto del registrado "
              f"({C.SHA256_RECORTE_OLAYA[:12]}...): los resultados pueden no coincidir")
# Abre el recorte, carga las elevaciones como números decimales y obtiene la información espacial necesaria para consultar sus píxeles        
    with rasterio.open(ruta) as r:
        z = r.read(1).astype(float)
        if r.nodata is not None:
            z[z == r.nodata] = float("nan")
        return z, r.transform, r.bounds, sha
