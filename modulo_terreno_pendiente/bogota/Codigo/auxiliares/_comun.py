"""Rutas compartidas por los scripts auxiliares. Todo sale de la configuracion
de la etapa; los auxiliares escriben en datos_salida/auxiliares/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bogota_pendientes_config as C  # noqa: E402

CARPETA_AUX = C.CARPETA_SALIDAS / "auxiliares"
CARPETA_AUX.mkdir(parents=True, exist_ok=True)

import json
import time

import requests

MDT2025_URL = ("https://serviciosgis.catastrobogota.gov.co/image/rest/services/"
               "Imagenes/modelodigitalterreno2025funcion/ImageServer/identify")
_sesion = requests.Session()


def z2020(lon, lat):
    """Elevacion del MDT 2020 en un punto (misma consulta que la etapa)."""
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": "4326",
              "layers": "all", "tolerance": 1,
              "mapExtent": f"{lon-0.001},{lat-0.001},{lon+0.001},{lat+0.001}",
              "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"}
    for intento in range(1, C.MDT_REINTENTOS + 1):
        try:
            r = _sesion.get(C.MDT_URL, params=params, timeout=C.MDT_TIEMPO_ESPERA_S).json().get("results", [])
            if not r:
                return None
            v = r[0]["attributes"].get(C.MDT_CAMPO_VALOR)
            return None if v in (None, "NoData") else float(v)
        except Exception:
            time.sleep(0.5 * intento)
    return None


def z2020_multipunto(puntos):
    """Consulta multipunto, la que uso la primera version de la etapa."""
    lons, lats = [p[0] for p in puntos], [p[1] for p in puntos]
    params = {"geometry": json.dumps({"points": [list(p) for p in puntos], "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryMultipoint", "sr": "4326", "layers": "all", "tolerance": 1,
              "mapExtent": f"{min(lons)-0.001},{min(lats)-0.001},{max(lons)+0.001},{max(lats)+0.001}",
              "imageDisplay": "800,800,96", "returnGeometry": "true", "f": "json"}
    return _sesion.get(C.MDT_URL, params=params, timeout=60).json()


def z2025(lon, lat):
    """Elevacion del MDT 2025 (ImageServer). Devuelve metros enteros; 0 es sin dato."""
    params = {"geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryPoint", "sr": 4326, "returnGeometry": "false",
              "returnCatalogItems": "false", "f": "json"}
    for intento in range(1, 4):
        try:
            v = _sesion.get(MDT2025_URL, params=params, timeout=20).json().get("value")
            if v in (None, "NoData", ""):
                return None
            v = float(v)
            return None if v <= 0 else v
        except Exception:
            time.sleep(0.5 * intento)
    return None
