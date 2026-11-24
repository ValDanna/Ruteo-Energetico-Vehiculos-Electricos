"""Constantes, rutas y utilidades compartidas por toda la tesis.

El módulo se puede importar desde cualquier notebook de cualquier bloque.
Todas las rutas se calculan desde la ubicación de este archivo, no desde la
carpeta de trabajo activa del notebook.
"""

from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import pandas as pd
import json

# ============================================================================
# Rutas del proyecto
# ============================================================================

RUTA_PROYECTO = Path(__file__).resolve().parent.parent

RUTAS_BLOQUES = {
    letra: RUTA_PROYECTO / f"Bloque {letra}"
    for letra in ("A", "B", "C", "D")
}

RUTAS_ENTREGABLES = {
    "A1": RUTAS_BLOQUES["A"] / "Entregable A1",
    "A2": RUTAS_BLOQUES["A"] / "Entregable A2",
    "A3": RUTAS_BLOQUES["A"] / "Entregable A3",
    "A4": RUTAS_BLOQUES["A"] / "Entregable A4",
    "B1": RUTAS_BLOQUES["B"] / "Entregable B1",
    "B2": RUTAS_BLOQUES["B"] / "Entregable B2",
    "B2.1": RUTAS_BLOQUES["B"] / "Entregable B2.1",
    "B3": RUTAS_BLOQUES["B"] / "Entregable B3",
    "B3.1": RUTAS_BLOQUES["B"] / "Entregable B3.1",
    "B4": RUTAS_BLOQUES["B"] / "Entregable B4",
    "C1": RUTAS_BLOQUES["C"] / "Entregable C1",
    "C2": RUTAS_BLOQUES["C"] / "Entregable C2",
    "C3": RUTAS_BLOQUES["C"] / "Entregable C3",
    "D1": RUTAS_BLOQUES["D"] / "Entregable D1",
}

RUTAS_DATOS_BASE = {
    # Vigente: capa nacional de municipios del IGAC, usada por A2 y A3
    "municipios_igac": RUTAS_BLOQUES["A"] / "Municipios_Junio_2026.gpkg",

    # Sustituidos. Se conservan declarados, fuera del circuito de análisis,
    # para poder reproducir los resultados anteriores al cambio de límite.
    "muni": RUTAS_BLOQUES["A"] / "muni.gpkg",
    "medellin": RUTAS_BLOQUES["A"] / "medellin.gpkg",
}


def ruta_archivo(*partes):
    """Devuelve la ruta absoluta de un archivo relativo al proyecto."""

    return RUTA_PROYECTO.joinpath(*partes)


def ruta_entregable(entregable, archivo=None):
    """Devuelve la carpeta de un entregable o uno de sus archivos.

    Ejemplos:
        ruta_entregable("A4", "A4_resultado_final_OCM_OSM.csv")
        ruta_entregable("B2", "resultado.csv")
    """

    clave = str(entregable).strip().upper()
    if clave.startswith("ENTREGABLE "):
        clave = clave.removeprefix("ENTREGABLE ")

    try:
        carpeta = RUTAS_ENTREGABLES[clave]
    except KeyError as error:
        disponibles = ", ".join(sorted(RUTAS_ENTREGABLES))
        raise KeyError(
            f"Entregable desconocido: {entregable}. "
            f"Disponibles: {disponibles}"
        ) from error

    return carpeta if archivo is None else carpeta / archivo


def archivos_existentes():
    """Devuelve un catálogo actualizado de archivos del proyecto."""

    return {
        archivo.relative_to(RUTA_PROYECTO).as_posix(): archivo
        for archivo in RUTA_PROYECTO.rglob("*")
        if archivo.is_file() and "__pycache__" not in archivo.parts
    }


def exigir_archivo(ruta):
    """Valida que un insumo exista y devuelve su ruta absoluta."""

    ruta = Path(ruta)
    if not ruta.is_absolute():
        ruta = ruta_archivo(ruta)

    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")

    return ruta

def sha256_archivo(ruta, bloque=1 << 20):
    """SHA-256 de un archivo, leído por trozos.

    Se usa en la celda de procedencia con que abre cada cuaderno: encadena
    los insumos derivados a los crudos congelados de A2 y A3.
    """

    import hashlib

    ruta = exigir_archivo(ruta)
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


ARCHIVOS = archivos_existentes()

def cargar_fuentes_estaciones():
    """Carga los inventarios de estaciones de A2 (OSM) y A3 (OCM).

    Devuelve ``osm`` y ``ocm`` con columnas ciudad, id, nombre, operador,
    lat y lon. Lee únicamente insumos congelados, de modo que puede
    llamarse antes de que cualquier bloque B haya corrido.

    Los identificadores se fijan como texto: son etiquetas, no cantidades,
    y con nulos presentes pandas los infiere como float y los escribe
    '475409.0', lo que rompe las uniones entre archivos.
    """

    osm_filas, ocm_filas = [], []

    for ciudad in ("Bogota", "Medellin"):
        ruta_osm = exigir_archivo(
            ruta_entregable("A2", f"A2_estaciones_OSM_{ciudad}.geojson")
        )
        with open(ruta_osm, encoding="utf-8") as archivo:
            for feature in json.load(archivo)["features"]:
                propiedades = feature["properties"]
                osm_filas.append({
                    "ciudad": ciudad,
                    "id": str(propiedades["osm_uid"]),
                    "nombre": propiedades.get("nombre"),
                    "operador": (
                        propiedades.get("operador")
                        or propiedades.get("marca")
                        or propiedades.get("red")
                    ),
                    "lat": propiedades["latitud"],
                    "lon": propiedades["longitud"],
                })

        ruta_ocm = exigir_archivo(
            ruta_entregable("A3", f"A3_OpenChargeMap_{ciudad}_estaciones.csv")
        )
        datos = pd.read_csv(ruta_ocm, encoding="utf-8-sig")

        if datos["ocm_id"].isna().any():
            raise ValueError(
                f"{ciudad}: hay registros de OpenChargeMap sin ocm_id en "
                f"{ruta_ocm.name}. El identificador es obligatorio."
            )

        ocm_filas.extend({
            "ciudad": ciudad,
            "id": str(fila.ocm_id).strip().removesuffix(".0"),
            "nombre": fila.nombre,
            "operador": fila.operador,
            "lat": fila.latitud,
            "lon": fila.longitud,
        } for fila in datos.itertuples())

    osm = pd.DataFrame(osm_filas)
    ocm = pd.DataFrame(ocm_filas)

    for tabla in (osm, ocm):
        tabla["id"] = tabla["id"].astype("string")

    return osm, ocm

def cargar_resultados_b1():
    """Carga desde disco los insumos y resultados necesarios de B1.

    Devuelve ``osm``, ``ocm``, ``pares`` y ``casos`` para que otros bloques
    puedan reutilizar B1 sin depender del estado de otro notebook.

    Requiere que B1 ya haya corrido: lee sus salidas. Los bloques que solo
    necesiten los inventarios de estaciones deben llamar a
    ``cargar_fuentes_estaciones``, que no depende de ningún resultado.
    """

    osm, ocm = cargar_fuentes_estaciones()

    archivo_pares = exigir_archivo(
        ruta_entregable("B1", "B1_pares_primarios.csv")
    )
    pares = pd.read_csv(
        archivo_pares,
        encoding="utf-8-sig",
        dtype={"ocm_id": "string", "osm_uid": "string"},
    )
    # Defensa por si el archivo se generó antes de fijar el tipo: '475409.0'
    # y '475409' deben unir contra el mismo registro.
    pares["ocm_id"] = pares["ocm_id"].str.replace(
        r"\.0$", "", regex=True
    )

    archivo_b1 = exigir_archivo(
        ruta_entregable("B1", "B1_clasificacion_cuatro_categorias.csv")
    )
    resultados_b1 = pd.read_csv(
        archivo_b1,
        encoding="utf-8-sig",
        dtype={"ocm_id": "string", "osm_uid": "string"},
    )
    resultados_b1["ocm_id"] = resultados_b1["ocm_id"].str.replace(
        r"\.0$", "", regex=True
    )
    resultados_b1 = resultados_b1[
        resultados_b1["distancia_m"].notna()
    ].copy()

    casos = {
        fila.caso: (fila.ocm_id, fila.osm_uid)
        for fila in resultados_b1.itertuples()
        if hasattr(fila, "caso") and pd.notna(fila.caso)
    }

    return osm, ocm, pares, casos

def cargar_veredictos_b2():
    """Carga los veredictos de contención producidos por B2.

    Devuelve (veredictos, ficha). ``veredictos`` es un dict caso -> True /
    False / None, donde None significa que B2 no adoptó conclusión: o el
    punto quedó fuera de toda manzana dentro de la banda de tolerancia, o el
    polígono era demasiado grande para discriminar, o el veredicto cambiaba
    dentro de la banda. ``ficha`` trae el método, la tolerancia y los motivos.

    None NO equivale a 'no son la misma estación'. Un bloque que lo trate
    como False estaría afirmando algo que B2 explícitamente no concluyó.
    """

    archivo = exigir_archivo(ruta_entregable("B2", "B2_veredictos.json"))

    with open(archivo, encoding="utf-8") as fh:
        ficha = json.load(fh)

    veredictos = {
        caso: (None if valor is None else bool(valor))
        for caso, valor in ficha["veredictos"].items()
    }

    return veredictos, ficha


def cargar_resultados_b3():
    """Carga los resultados del emparejamiento por puntaje combinado de B3.

    Devuelve (pares, candidatos, parametros). ``pares`` son los aceptados;
    ``candidatos`` son TODOS los evaluados dentro del radio de búsqueda, con
    su puntaje y sus componentes, aceptados o no —es la materia prima de
    cualquier análisis de sensibilidad posterior, que así no tiene que
    reevaluar nada—. ``parametros`` es B3_parametros.json tal como lo
    escribió B3.

    LOS PARÁMETROS DEL PUNTAJE NO SE DECLARAN EN ESTE MÓDULO. Viven en B3 y
    salen a B3_parametros.json. Copiarlos aquí crearía dos versiones del
    mismo umbral que divergen en cuanto alguien corrija una sola, que es
    justamente lo que este módulo existe para evitar. Quien los necesite los
    lee del diccionario que devuelve esta función.

    Los identificadores se fijan como texto y se les quita el sufijo '.0'
    por si el archivo se generó antes de fijar el tipo: '475409.0' y
    '475409' deben unir contra el mismo registro.
    """

    tipos = {"ocm_id": "string", "osm_uid": "string"}

    def _leer(nombre):
        tabla = pd.read_csv(
            exigir_archivo(ruta_entregable("B3", nombre)),
            encoding="utf-8-sig",
            dtype=tipos,
        )
        for columna in tipos:
            if columna in tabla.columns:
                tabla[columna] = tabla[columna].str.replace(
                    r"\.0$", "", regex=True
                )
        return tabla

    pares = _leer("B3_pares_puntaje_combinado.csv")
    candidatos = _leer("B3_candidatos_evaluados.csv")

    archivo = exigir_archivo(ruta_entregable("B3", "B3_parametros.json"))
    with open(archivo, encoding="utf-8") as fh:
        parametros = json.load(fh)

    declarados = parametros.get("decision_umbral", {}).get("pares_resultantes")
    if declarados is not None and declarados != len(pares):
        raise ValueError(
            f"B3_parametros.json declara {declarados} pares y "
            f"B3_pares_puntaje_combinado.csv trae {len(pares)}. Los dos "
            "archivos vienen de corridas distintas de B3: hay que "
            "reejecutarlo completo antes de seguir."
        )

    return pares, candidatos, parametros


def cargar_criterio_manzana():
    """Criterio de suficiencia de la etiqueta por manzana catastral.

    Devuelve (banda_m, area_max_m2, origen). La BANDA es la de B2: una
    etiqueta solo se adopta si no cambia en ninguno de sus valores. Un valor
    único de tolerancia es lo que hay que evitar —B2 usó 25 m en una primera
    versión, que es el mismo umbral de confirmación que estaba validando, y
    al corregirlo sus veredictos adoptados bajaron de 4 a 2—.

    La medida canónica vive en la auditoría de B2, no aquí: se lee de allá y
    solo si no aparece se usa la copia declarada, avisándolo en ``origen``.
    Quien la use debe reportar cuál de las dos obtuvo.
    """

    banda_declarada = [2.7, 6.4, 10.8, 21.5]

    for archivo in sorted(Path(ruta_entregable("B2")).glob("*.json")):
        try:
            with open(archivo, encoding="utf-8") as fh:
                contenido = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        for clave, valor in _recorrer_json(contenido):
            if (
                "toleran" in clave.lower()
                and isinstance(valor, list)
                and len(valor) >= 2
                and all(isinstance(v, (int, float)) for v in valor)
            ):
                return (
                    sorted(float(v) for v in valor),
                    AREA_MAX_MANZANA_M2,
                    f"{archivo.name} · {clave}",
                )

    return (
        sorted(banda_declarada),
        AREA_MAX_MANZANA_M2,
        "copia declarada en constantes.py; no se halló la banda en B2",
    )


def _recorrer_json(dato, prefijo=""):
    """Recorre un JSON anidado devolviendo (ruta.de.claves, valor)."""

    if isinstance(dato, dict):
        for clave, valor in dato.items():
            yield from _recorrer_json(
                valor, f"{prefijo}.{clave}" if prefijo else str(clave)
            )
    else:
        yield prefijo, dato

# ============================================================================
# Identificación de la investigación
# ============================================================================

USER_AGENT = (
    "tesis-estaciones-carga-electrica/1.0 "
    "(investigacion-academica)"
)

# ============================================================================
# Configuración geográfica y de zona horaria
# ============================================================================

TIMEZONE = ZoneInfo("America/Bogota")

# WGS84 / Geográfico - estándar para OpenStreetMap y OpenChargeMap
CRS_WGS84 = "EPSG:4326"

# MAGNA-SIRGAS / Origen Nacional - métrico, oficial del IGAC
# Se utiliza para verificaciones independientes en metros
CRS_METRICO = "EPSG:9377"

# ============================================================================
# Corte temporal del inventario
# ============================================================================
# El corte es común a las dos fuentes del Bloque A. La razón no proviene de
# OpenStreetMap sino de OpenChargeMap: OCM no admite consultas históricas, de
# modo que su archivo debe congelarse en disco a una fecha. Para que ambas
# fuentes describan el mismo estado del mundo, OSM se corta en ese mismo
# instante mediante attic query. Cortar cada fuente en una fecha distinta
# haría que el emparejamiento del Bloque B comparara dos momentos diferentes.
#
# El instante se declara como el final del 29/08/2026 en hora de Bogotá.
# Overpass exige UTC y Bogotá es UTC-5, de modo que el mismo instante se
# escribe 2026-08-30T04:59:59Z. Las dos formas se declaran juntas para no
# tener que rehacer la conversión mentalmente.

FECHA_CORTE_LOCAL = "2026-08-29"

FECHA_CORTE_OSM = "2026-08-30T04:59:59Z"

# Prefijo del archivo crudo congelado de OpenChargeMap.
#
# El nombre lleva 'estado-al-<fecha>' —qué contiene el archivo— y
# 'bajado-<fecha>' —cuándo se trajo de la API—, porque OCM no admite
# consultas históricas y la descarga es necesariamente posterior al estado
# que se le atribuye.
#
# A2 mantiene su propia convención de nombres, definida dentro de su
# cuaderno. Pendiente de homogeneizar al publicar las convenciones del
# proyecto; no afecta el funcionamiento de ningún bloque.

PREFIJO_CRUDO_OCM = "A3_ocm_crudo"

# ============================================================================
# OpenStreetMap
# ============================================================================

ETIQUETA_OSM = "amenity=charging_station"

# ============================================================================
# Parámetros compartidos de clasificación B1-B2
# ============================================================================

UMBRAL_CONFIRMADA = 25.0
UMBRAL_PROBABLE = 100.0
RADIO_BUSQUEDA_MAX = 500.0
RADIO_SECUNDARIO = 300.0
RADIO_DUPLICADO = 50.0
UMBRAL_TEXTUAL = 0.45

MEDIDA_ANCLAJE = {
    "fuente": "Manzana. Bogotá D.C. — UAECD / Mapa de Referencia IDECA",
    "ciudad_medida": "Bogota",
    "lado_corto_mediano_m": 50.3,
    "lado_largo_mediano_m": 101.7,
    "separacion_mediana_manzanas_m": 5.4,
    "nota_separacion": (
        "la separación entre manzanas catastrales no equivale al ancho de "
        "vía: cerca de un tercio de las vecinas son contiguas porque la capa "
        "separa por línea de predio y no por eje vial"
    ),
}

# Área por encima de la cual una manzana deja de discriminar. Un polígono de
# cientos de miles de metros cuadrados es un parque, un aeropuerto o un predio
# institucional entero, y decir que dos estaciones «están en la misma manzana»
# de 114 hectáreas no aporta información. Medido sobre la capa de la UAECD:
# deja por debajo el 99,45 % de las manzanas (mediana 2.508 m², p99 65.425 m²).
AREA_MAX_MANZANA_M2 = 100_000.0

# Palabras sin valor discriminante en los nombres de estaciones. Se usan en
# la similitud de tokens desde A4; la lista es común a todos los bloques
# para que las medidas textuales sean comparables entre ellos.
#
# Las tildes las elimina la normalización antes de llegar aquí, así que en
# la práctica solo coinciden las formas sin tilde. Las acentuadas se dejan
# declaradas por legibilidad.

PALABRAS_NO_INFORMATIVAS = {
    "estacion", "estación", "carga", "electrica", "eléctrica",
    "vehiculo", "vehículo", "vehiculos", "vehículos",
    "electrico", "eléctrico", "punto", "para",
    "de", "del", "la", "el", "los", "las", "en", "por", "y", "and",
}

CENTINELAS = {
    "",
    "unknown", "unknown operator",   # OCM: «Unknown», «(Unknown Operator)»
    "unspecified",                   # OCM: «(Unspecified)»
    "application",                   # OCM costo_uso: tarifa según la app, no declarada
    "n a", "na", "none", "null", "nan",
    "sin nombre", "sin datos", "desconocido",
}


def normalizar_texto(t):
    """Minúsculas, sin tildes, sin signos, espacios colapsados.
    Devuelve '' para None y NaN. Es la normalización común a todos los bloques."""
    import re
    import unicodedata

    if t is None or t is pd.NA or (isinstance(t, float) and pd.isna(t)):
        return ""
    s = str(t).lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def es_centinela(v):
    """True si el valor no es un dato: vacío, nulo, diccionario vacío o centinela."""
    if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
        return True
    if isinstance(v, dict):
        return len(v) == 0
    return normalizar_texto(v) in CENTINELAS

# ============================================================================
# Atribuciones de datos
# ============================================================================

ATRIBUCION_ODBL = (
    "Datos de OpenStreetMap, © colaboradores de OpenStreetMap, "
    "disponibles bajo la Open Database License (ODbL). "
    "https://www.openstreetmap.org/copyright"
)

ATRIBUCION_OCM = (
    "Datos de OpenChargeMap (openchargemap.org), contribuidos por "
    "la comunidad. Condiciones de redistribución pendientes de "
    "verificación — tarea C3 del anteproyecto."
)

# ============================================================================
# Delimitación adoptada: capa oficial de municipios del IGAC
# ============================================================================
# Sustituye los límites empleados hasta el 8 de septiembre de 2026 (IDECA para
# Bogotá, OpenStreetMap/Nominatim para Medellín). La sustitución se sustenta en
# la comparación geométrica ejecutada en A2: IoU de 0,976 en Bogotá y 0,984 en
# Medellín frente a los límites anteriores, de modo que el cambio afecta la
# procedencia y la independencia del insumo, no el área de estudio.

LIMITE_IGAC = {

    "archivo": RUTAS_DATOS_BASE["municipios_igac"],

    "capa": "Munpio",

    "columna_codigo": "MpCodigo",

    # Se filtra por código DANE y NO por nombre: en esta capa Bogotá
    # figura como "Bogotá, D.C.", con coma y abreviatura.
    "codigos_dane": {
        "Bogota": "11001",
        "Medellin": "05001",
    },

    # Fuente administrativa nacional, ajena a OpenStreetMap para ambas
    # ciudades. El filtro espacial es verificación externa.
    "independiente_de_osm": True,

    "procedencia": {

        "entidad": "IGAC — Instituto Geográfico Agustín Codazzi",

        "url": "https://www.colombiaenmapas.gov.co/",

        "fecha_descarga": "09/09/2026",

        "crs_origen": "EPSG:9377",

        "obtencion": (
            "Descarga manual desde el portal Colombia en Mapas. "
            "Capa nacional de municipios, versión junio de 2026, "
            "1.105 registros."
        ),

        "restriccion_declarada_por_la_fuente": (
            "No es apropiada su aplicación para la ubicación exacta "
            "de puntos ni para el cálculo de áreas y distancias"
        ),
    },
}


# ============================================================================
# Límites sustituidos
# ============================================================================
# Se conservan declarados, fuera del circuito de análisis, como registro de la
# versión anterior y para poder reproducir la comparación que justificó la
# sustitución.

LIMITES_SUSTITUIDOS = {

    "Bogota": {

        "archivo": RUTAS_DATOS_BASE["muni"],

        "capa": "Muni",

        "independiente_de_osm": True,

        "motivo_sustitucion": (
            "Trazabilidad incompleta: la ficha exacta del recurso no quedó "
            "registrada al momento de la descarga. El límite era "
            "independiente de OpenStreetMap, de modo que la sustitución no "
            "corrige un defecto de independencia sino de documentación."
        ),

        "procedencia": {
            "entidad": (
                "IDECA — Infraestructura de Datos Espaciales "
                "para el Distrito Capital"
            ),
            "url": "https://www.ideca.gov.co/recursos/mapas/municipio-bogota-dc",
            "fecha_descarga": "01/09/2026",
            "obtencion": (
                "Descarga manual desde el portal IDECA. La ficha exacta del "
                "recurso no quedó registrada."
            ),
        },
    },

    "Medellin": {

        "archivo": RUTAS_DATOS_BASE["medellin"],

        "capa": "limite_medellin",

        "independiente_de_osm": False,

        "motivo_sustitucion": (
            "Dependencia circular: el límite provenía de OpenStreetMap, la "
            "misma fuente de la que se extraen las estaciones, de modo que el "
            "filtro espacial no constituía verificación independiente. Es el "
            "defecto que la sustitución corrige."
        ),

        "procedencia": {
            "entidad": (
                "OpenStreetMap — relación administrativa de Medellín, "
                "resuelta mediante Nominatim"
            ),
            "url": "https://nominatim.openstreetmap.org",
            "fecha_descarga": "01/09/2026",
            "obtencion": (
                "Generado con osmnx.geocode_to_gdf('Medellín, Antioquia, "
                "Colombia') y exportado a GPKG. El resultado depende de la "
                "versión de la relación vigente al momento de la consulta, "
                "no registrada."
            ),
        },
    },
}


# ============================================================================
# Áreas de estudio — Ciudades de análisis
# ============================================================================

AREAS_ESTUDIO = {

    "Bogota": {

        "nombre": "Bogotá D.C.",

        "codigo_dane": "11001",

        # Sobre de consulta para Overpass (A2), NO recorte final.
        # Excluye Sumapaz por el sur, pero se desborda por el occidente
        # sobre municipios vecinos; ver 'criterio_espacial'.
        # A3 descarga a escala nacional y no usa este bbox.
        "bbox": {
            "oeste": -74.2235,
            "sur": 4.4711,
            "este": -74.0102,
            "norte": 4.8331,
        },

        "criterio_espacial": (
            "El recorte efectivo es la INTERSECCIÓN del bbox con el límite "
            "municipal, porque ninguno de los dos contiene al otro. El bbox "
            "aporta la exclusión de Sumapaz: 1.010,2 km² del Distrito quedan "
            "fuera del área consultada, coherente con la cobertura del Modelo "
            "Digital de Terreno de IDECA, que es zona urbana. El límite del "
            "IGAC aporta la exclusión de los municipios vecinos que el bbox "
            "alcanza —Soacha, Funza, Cota, Tenjo, Mosquera, Chipaque, Ubaque, "
            "Madrid, La Calera, Chía y Sibaté— y que suman 338,2 km² del área "
            "consultada. El filtro por límite es por tanto recorte vinculante "
            "y no mera validación de consistencia, contra lo que afirmaba la "
            "versión anterior de este criterio."
        ),

        "limite": LIMITE_IGAC,
    },

    "Medellin": {

        "nombre": "Medellín",

        "codigo_dane": "05001",

        # El límite municipal está íntegramente contenido en este bbox,
        # de modo que el recorte vinculante es el límite.
        "bbox": {
            "oeste": -75.7193,
            "sur": 6.1629,
            "este": -75.4718,
            "norte": 6.3748,
        },

        "criterio_espacial": (
            "El límite municipal del IGAC está contenido por completo en el "
            "bbox —0,0 km² del municipio quedan fuera del área consultada—, de "
            "modo que el recorte vinculante es el límite. El bbox alcanza "
            "municipios vecinos del Área Metropolitana —Bello, Copacabana, "
            "Envigado, Itagüí, Sabaneta, entre otros— que suman 268,6 km² y "
            "que el filtro por límite descarta. "
            "SUSTITUCIÓN: el límite empleado antes provenía de OpenStreetMap "
            "vía Nominatim, la misma fuente de la que se extraen las "
            "estaciones, por lo que el filtro espacial no constituía "
            "verificación independiente. Con la capa del IGAC el filtro pasa a "
            "ser verificación externa, en igualdad de condiciones con Bogotá."
        ),

        "limite": LIMITE_IGAC,
    },
}

# ============================================================================
# Funciones auxiliares compartidas
# ============================================================================

def cargar_limite_ciudad(
    archivo,
    capa,
    nombre_ciudad,
    procedencia,
    columna_codigo=None,
    codigo=None,
):
    """
    Carga el límite oficial de la ciudad y lo transforma a EPSG:4326.

    El archivo NO se descarga por programa: se aporta junto con el cuaderno.
    Por eso su procedencia se exige de forma explícita y se propaga a los
    metadatos del entregable, como acción manual documentada.

    columna_codigo y codigo permiten seleccionar un municipio dentro de una
    capa nacional. Son obligatorios cuando la capa trae más de un registro: la
    del IGAC tiene 1.105 municipios y sin filtrar se disolverían todos en una
    sola geometría que abarcaría el país entero.

    El límite se disuelve en una sola geometría para que el filtrado espacial
    no genere filas duplicadas.

    Usa: geopandas, CRS_WGS84
    """

    campos_procedencia = {
        "entidad",
        "url",
        "fecha_descarga",
        "obtencion",
    }

    faltantes = campos_procedencia - set(procedencia.keys())

    if faltantes:
        raise ValueError(
            f"{nombre_ciudad}: la procedencia del límite "
            f"está incompleta: {faltantes}"
        )

    sin_completar = [
        campo
        for campo, valor in procedencia.items()
        if str(valor).strip().upper() == "COMPLETAR"
    ]

    if sin_completar:
        raise ValueError(
            f"{nombre_ciudad}: la procedencia del límite tiene campos sin "
            f"diligenciar: {sin_completar}. El archivo se aporta manualmente, "
            "de modo que su origen debe quedar documentado."
        )

    limite = gpd.read_file(archivo, layer=capa)

    if limite.empty:
        raise ValueError(f"El límite de {nombre_ciudad} está vacío.")

    # ------------------------------------------------------------------------
    # Selección del municipio dentro de la capa
    # ------------------------------------------------------------------------
    # Se filtra por código y no por nombre: en la capa del IGAC Bogotá figura
    # como "Bogotá, D.C.", con coma y abreviatura, de modo que la búsqueda por
    # texto es frágil.

    registros_originales = len(limite)

    if columna_codigo is not None and codigo is not None:

        if columna_codigo not in limite.columns:
            raise ValueError(
                f"{nombre_ciudad}: la capa '{capa}' no tiene la columna "
                f"'{columna_codigo}'. Columnas disponibles: "
                f"{list(limite.columns)}"
            )

        limite = limite[limite[columna_codigo] == codigo]

        if limite.empty:
            raise ValueError(
                f"{nombre_ciudad}: no hay registros con "
                f"{columna_codigo} = {codigo!r} en la capa '{capa}'."
            )

        if len(limite) != 1:
            raise ValueError(
                f"{nombre_ciudad}: se esperaba exactamente un registro con "
                f"{columna_codigo} = {codigo!r}, se encontraron {len(limite)}."
            )

    elif registros_originales > 1:

        # Sin filtro, una capa multirregistro se disolvería entera en un
        # solo polígono sin emitir error.

        raise ValueError(
            f"{nombre_ciudad}: la capa '{capa}' tiene {registros_originales} "
            "registros y no se indicó columna_codigo ni codigo. Disolverla "
            "completa produciría un límite incorrecto."
        )

    if limite.crs is None:
        raise ValueError(
            f"El límite de {nombre_ciudad} no tiene CRS definido."
        )

    crs_original = limite.crs.to_string()

    limite = limite.to_crs(CRS_WGS84)

    if not limite.geometry.is_valid.all():
        raise ValueError(
            f"El límite de {nombre_ciudad} contiene geometrías inválidas."
        )

    # Disolver a una sola geometría
    geometria_unica = limite.union_all()

    limite_disuelto = gpd.GeoDataFrame(
        {"codigo_dane_limite": [codigo]},
        geometry=[geometria_unica],
        crs=CRS_WGS84,
    )

    ficha = {
        "ciudad": nombre_ciudad,
        "archivo": str(archivo),
        "capa": capa,
        "crs_original": crs_original,
        "registros_en_la_capa": registros_originales,
        "columna_codigo": columna_codigo,
        "codigo_filtrado": codigo,
        "geometrias_originales": len(limite),
        "entidad": procedencia["entidad"],
        "url": procedencia["url"],
        "fecha_descarga_limite": procedencia["fecha_descarga"],
        "obtencion": procedencia["obtencion"],
    }

    return limite_disuelto, ficha