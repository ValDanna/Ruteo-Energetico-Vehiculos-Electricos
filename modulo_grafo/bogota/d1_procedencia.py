"""
d1_procedencia.py — Congelamiento y trazabilidad de las descargas del Bloque D.

Mismo patron que A2/A3: cada descarga produce tres archivos —el crudo tal como
llego, su sha256 y su metadata— y si el crudo existe NO se vuelve a consultar
el servicio.

Motivo: la capa Malla Vial de IDECA se actualiza trimestralmente y NO declara
fecha de actualizacion en sus metadatos (editingInfo ausente, verificado el
2026-09-18). Tampoco admite consulta historica, a diferencia de Overpass. El
archivo congelado ES el dato; sin el, el cuaderno no es reproducible.

El crudo es un INSUMO, no una salida: nunca se borra al limpiar regenerables.
"""

from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from constantes_d1 import ruta_cruda

ZONA_BOGOTA = timezone(timedelta(hours=-5))


def sha256_bytes(contenido: bytes) -> str:
    """Hash completo, 64 caracteres. Nunca truncado."""
    return hashlib.sha256(contenido).hexdigest()


def sha256_archivo(ruta) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _rutas(nombre: str, carpeta: Path, extension: str):
    return (carpeta / f"{nombre}{extension}",
            carpeta / f"{nombre}{extension}.sha256",
            carpeta / f"{nombre}.meta.json")


def congelar_get(nombre: str, url: str, params: dict, sesion,
                 extension: str = ".json", carpeta=None,
                 tiempo_espera: int = 180, verboso: bool = True) -> dict:
    """Descarga una vez y congela. En corridas siguientes lee de disco.

    Devuelve {"contenido": bytes, "meta": dict, "desde_disco": bool}.

    Si el crudo ya existe, verifica su hash ANTES de devolverlo: un archivo
    alterado falla en voz alta en vez de cambiar resultados en silencio.

    Guarda r.content (bytes crudos), nunca r.text: el hash debe ser del
    documento tal como lo sirvio el servidor, y ademas requests decodifica
    mal el XML de IDECA (declara UTF-8 y llega interpretado como latin-1).
    """
    carpeta = Path(carpeta) if carpeta else ruta_cruda() / "congelados"
    carpeta.mkdir(parents=True, exist_ok=True)
    r_crudo, r_sha, r_meta = _rutas(nombre, carpeta, extension)

    if r_crudo.exists() and r_sha.exists() and r_meta.exists():
        contenido = r_crudo.read_bytes()
        esperado = r_sha.read_text(encoding="utf-8").split()[0].strip()
        obtenido = sha256_bytes(contenido)
        if obtenido != esperado:
            raise RuntimeError(
                f"El crudo congelado {r_crudo.name} NO coincide con su hash.\n"
                f"  esperado: {esperado}\n  obtenido: {obtenido}\n"
                "El archivo se modifico o se corrompio. No se usa."
            )
        meta = json.loads(r_meta.read_text(encoding="utf-8"))
        if verboso:
            print(f"  [congelado] {r_crudo.name}  "
                  f"bajado {meta.get('fecha_descarga_bogota')}  "
                  f"sha {obtenido[:12]}...")
        return {"contenido": contenido, "meta": meta, "desde_disco": True}

    t0 = datetime.now(timezone.utc)
    r = sesion.get(url, params=params, timeout=tiempo_espera)
    r.raise_for_status()
    contenido = r.content

    meta = {
        "nombre": nombre,
        "url": url,
        "parametros_enviados": params,
        "url_efectiva": r.url,
        "estado_http": r.status_code,
        "content_type": r.headers.get("Content-Type"),
        "bytes": len(contenido),
        "sha256": sha256_bytes(contenido),
        "fecha_descarga_utc": t0.isoformat(timespec="seconds"),
        "fecha_descarga_bogota": t0.astimezone(ZONA_BOGOTA)
                                   .isoformat(timespec="seconds"),
    }

    r_crudo.write_bytes(contenido)
    r_sha.write_text(f"{meta['sha256']}  {r_crudo.name}\n", encoding="utf-8")
    r_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                      encoding="utf-8")

    if verboso:
        print(f"  [descargado] {r_crudo.name}  {len(contenido)/1e6:.2f} MB  "
              f"sha {meta['sha256'][:12]}...")
    return {"contenido": contenido, "meta": meta, "desde_disco": False}


def congelar_metadatos_fuentes(sesion, verboso: bool = True) -> list[dict]:
    """Congela la ficha de procedencia de las dos fuentes del Bloque D.

    Son los dos documentos que sustentan licencia, productor y metodo. Se
    corren una vez; despues se leen de disco.
    """
    import constantes_d1 as K

    metas = []

    # GetCapabilities del MDT: trae licencia (AccessConstraints), productor,
    # contratos y metodo por zona. Es la evidencia de la licencia CC BY 4.0.
    res = congelar_get(
        "MDT_getcapabilities", f"{K.MDT_IMAGESERVER}/WMSServer",
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"},
        sesion, extension=".xml", verboso=verboso)
    metas.append(res["meta"])

    # Metadatos de la capa Malla Vial: copyrightText y esquema de campos.
    res = congelar_get(
        "malla_vial_capa13_metadatos", K.MALLA_SERVICIO, {"f": "json"},
        sesion, extension=".json", verboso=verboso)
    metas.append(res["meta"])

    return metas



def huella_segmentos(gdf, columna_id: str = "segmento_id") -> str:
    """Huella de CONTENIDO de una capa de segmentos.

    Por que no basta el sha256 del archivo: GeoPackage guarda la hora de
    escritura en sus tablas internas, asi que el hash del .gpkg cambia en cada
    corrida aunque el contenido sea identico. Un hash que cambia siempre no
    verifica nada.

    Esta huella ordena por id y hashea (id, geometria en WKB). No depende del
    formato ni de la hora. Quien recibe el archivo la recalcula con esta misma
    funcion: si coincide, tiene exactamente los mismos segmentos con las
    mismas geometrias.

    byte_order=1 y output_dimension=2 fijan el WKB: mismo resultado en
    cualquier maquina, y una Z eventual no altera la huella.
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