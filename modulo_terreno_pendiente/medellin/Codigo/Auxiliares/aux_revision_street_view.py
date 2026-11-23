"""
Revision en Street View de las 104 calles de la lista de pendientes extremas.

Que hace: comprueba que la lista (D3M_revision_street_view_med_sigma010.csv) cruce con el archivo de pendientes:
una fila por calle fisica, los 95 tramos fisicos con pendiente_extrema, las
calles con paso_nivel = 2 del gpkg, y neta y acumulada iguales a las del
archivo. Luego agrega tres enlaces de Google Maps por calle (inicio, centro y
fin) para revisar el tramo completo.

Con --resumen: lee la lista anotada a mano (revision_104_medellin_completada.csv), comprueba que tenga las mismas 104 filas
y calcula, por motivo y en total, la proporcion de calles donde se ve una calle
para carros, con intervalo de Wilson al 95 %. La proporcion se calcula sobre las
calles
Se reporta solo la categoria observada.

Lee:      la lista y, con --resumen, la lista anotada, el
          archivo de pendientes y el gpkg.
Escribe:  aux_revision_street_view_enlaces.csv
          aux_revision_street_view_resumen.csv (con --resumen)

Resultado: la lista cruza con el archivo; 104 calles, 95 por pendiente extrema y 9 por paso a nivel 2 (11 tramos dirigidos).
Resumen: franja 35-50 %, 79 calles, calles reales 30,4 % (Wilson 21,3-41,2) y paso peatonal 50,6 % (39,8-61,4); mas de 50 %, 14 calles, reales
35,7 % (16,3-61,2). Las 9 de paso a nivel 2 son calle
"""
import sys
import unicodedata

import numpy as np
import pandas as pd
from pyproj import Transformer

from _comun import C, carpeta_salida, leer_pendientes, leer_segmentos

# Relaciona las respuestas de la revisión con los valores que se esperan.
RESPUESTAS = {"si": "si", "no": "no", "no se ve": "no se ve"}


def normalizar(texto):
    # Homogeneiza los textos para facilitar las comparaciones, eliminando tildes, convirtiendo a minúsculas y normalizando los espacios.
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def wilson(exitos, n, z):
    # Calcula la proporción observada y su intervalo de confianza de Wilson.
    # Se utiliza para estimar la incertidumbre de las proporciones obtenidas, especialmente cuando el número de calles es reducido.
    if n == 0:
        return np.nan, np.nan, np.nan
    p = exitos / n
    centro = (p + z ** 2 / (2 * n)) / (1 + z ** 2 / n)
    margen = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / (1 + z ** 2 / n)
    return p, centro - margen, centro + margen


def leer_lista(ruta):
    # Carga el archivo de calles que se van a revisar y conserva los identificadores como texto para evitar cambios de formato. Si no existe, detiene el proceso.
    if not ruta.exists():
        raise SystemExit(f"No esta {ruta}. Ver LEEME.txt, paso 6.")
    return pd.read_csv(ruta, sep=None, engine="python", encoding="utf-8-sig", dtype={"segmento_id": str})


def verificar(lista, df, g):
    # Comprueba que la lista de revisión coincida con los datos de pendientes y con la geometría vial. Revisa duplicados, identificadores faltantes,
    # selección de segmentos extremos y pasos a nivel, además de las pendientes.
    fallas = []
    lista = lista.assign(base=lista["segmento_id"].str.rsplit("_", n=1).str[0])
    if lista["base"].duplicated().any():
        fallas.append("hay calles repetidas")
    faltan = set(lista["segmento_id"]) - set(df["segmento_id"])
    if faltan:
        fallas.append(f"{len(faltan)} segmento_id no estan en el archivo de pendientes")

    # Contrasta las calles marcadas como extremas en la lista con las identificadas en el archivo de pendientes, agrupando los tramos por su identificador base.
    ext = df[df["pendiente_extrema"] == True]
    bases_ext = set(ext["segmento_id"].str.rsplit("_", n=1).str[0])
    bases_lista_ext = set(lista.loc[lista["motivo"] == "extrema", "base"])
    if bases_lista_ext != bases_ext:
        fallas.append(f"extremas: {len(bases_ext - bases_lista_ext)} faltan y "
                      f"{len(bases_lista_ext - bases_ext)} sobran")

    # Realiza la misma comprobación para los tramos que tienen paso a nivel clasificado con valor 2 en la capa de geometrías.
    pn = g[g["paso_nivel"] == 2]
    bases_pn = set(pn["segmento_id"].str.rsplit("_", n=1).str[0])
    bases_lista_pn = set(lista.loc[lista["motivo"] == "paso_nivel_2", "base"])
    if bases_lista_pn != bases_pn:
        fallas.append(f"paso_nivel_2: {len(bases_pn - bases_lista_pn)} faltan y "
                      f"{len(bases_lista_pn - bases_pn)} sobran")

    # Verifica que las pendientes registradas en la lista coincidan con las del archivo principal, respetando la tolerancia definida
    m = lista.merge(df[["segmento_id", "pendiente_neta_pct", "pendiente_acumulada_pct"]],
                    on="segmento_id", suffixes=("", "_archivo"))
    for col in ["pendiente_neta_pct", "pendiente_acumulada_pct"]:
        dif = (m[col] - m[f"{col}_archivo"]).abs().max()
        if dif > C.TOLERANCIA_COMPARACION:
            fallas.append(f"{col} difiere del archivo hasta {dif:.1e}")

    # Muestra un resumen de los registros contrastados y detiene la ejecución si encuentra inconsistencias
    print(f"Lista: {len(lista)} calles; por motivo {lista['motivo'].value_counts().to_dict()}")
    print(f"Tramos dirigidos con paso_nivel = 2 en el gpkg: {len(pn)} ({len(bases_pn)} calles)")
    print(f"Tramos fisicos con pendiente_extrema en el archivo: {len(bases_ext)}")
    if fallas:
        raise SystemExit("La lista no cruza con el archivo: " + "; ".join(fallas))
    print("La lista cruza con el archivo de pendientes")


def enlaces(lista, g):
    # Genera enlaces de Google Maps para consultar visualmente el inicio, el centro
    # y el final de cada calle. Las coordenadas se transforman al sistema WGS84, para construir las ubicaciones de los enlaces.
    a_wgs84 = Transformer.from_crs(C.CRS_RED, "EPSG:4326", always_xy=True)
    geom = g.set_index("segmento_id").geometry
    filas = {"url_inicio": [], "url_centro": [], "url_fin": []}
    for sid in lista["segmento_id"]:
        for nombre, f in (("url_inicio", 0.0), ("url_centro", 0.5), ("url_fin", 1.0)):
            p = geom[sid].interpolate(f, normalized=True)
            lon, lat = a_wgs84.transform(p.x, p.y)
            filas[nombre].append(f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}")

    salida = lista.copy()
    posicion = salida.columns.get_loc("street_view") + 1
    for i, (nombre, valores) in enumerate(filas.items()):
        salida.insert(posicion + i, nombre, valores)
    salida.to_csv(carpeta_salida() / "aux_revision_street_view_enlaces.csv", index=False, encoding="utf-8-sig")
    print(f"Enlaces escritos para {len(salida)} calles")


# Define las categorías para clasificar lo observado en Street View y el resultado esperado en la variable que indica si se ve una calle transitable para carros. Incluye la categoría de senderos o pasos angostos.
CATEGORIAS = {"calle_normal": "si", "calle_abierta": "si", "escalera": "no",
              "sendero_o_paso_angosto": "no", "no_se_ve": "no se ve"}


def franja(fila):
    # Asigna cada registro a un grupo según el motivo de revisión y la pendiente neta. Los pasos a nivel se mantienen como una categoría propia.
    if fila["motivo"] == "paso_nivel_2":
        return "paso_nivel_2"
    neta = abs(float(fila["pendiente_neta_pct"]))
    return "mas de 50 %" if neta > 50 else "35 a 50 %" if neta > 35 else "solo por la acumulada"


def resumen(lista):
    # Carga las anotaciones completadas y comprueba que contengan los mismos identificadores que la lista original antes de calcular resultados.
    rev = leer_lista(C.ARCHIVO_REVISION_COMPLETADA)
    if sorted(rev["segmento_id"]) != sorted(lista["segmento_id"]):
        raise SystemExit("La lista anotada no tiene los mismos segmento_id que la original")

    # Recupera el motivo y las pendientes desde la lista original para evitar diferencias de precisión que puedan aparecer al editar el archivo en Excel.
    rev = rev[["segmento_id", "se_ve_calle_para_carros", "categoria"]].merge(
        lista[["segmento_id", "motivo", "pendiente_neta_pct"]], on="segmento_id")
    rev["respuesta"] = rev["se_ve_calle_para_carros"].fillna("").map(normalizar).map(RESPUESTAS)
    rev["cat"] = rev["categoria"].fillna("").map(normalizar).str.replace(" ", "_")

    # Valida que cada categoría anotada sea válida y corresponda a la respuesta sobre la visibilidad de una calle para carros. Si hay errores, informa
    # algunos identificadores para la corrección.
    malas = rev[~rev["cat"].isin(CATEGORIAS) | (rev["cat"].map(CATEGORIAS) != rev["respuesta"])]
    if len(malas):
        raise SystemExit(f"{len(malas)} filas con categoria vacia o que no cuadra con "
                         f"se_ve_calle_para_carros: {malas['segmento_id'].head(5).tolist()}")

    # Clasifica las calles por franja y calcula los recuentos y proporciones de calles reales y pasos peatonales, incluyendo los casos que no se ven
    # dentro del total de registros revisados.
    rev["franja"] = rev.apply(franja, axis=1)
    filas = []
    for nombre in ["35 a 50 %", "mas de 50 %", "solo por la acumulada", "paso_nivel_2", "extremas (todas)"]:
        g = rev[rev["motivo"] == "extrema"] if nombre == "extremas (todas)" else rev[rev["franja"] == nombre]
        n = len(g)
        fila = {"franja": nombre, "calles": n, **{c: int((g["cat"] == c).sum()) for c in CATEGORIAS}}

        # Calcula las proporciones y sus intervalos de confianza del 95 % para los dos grupos de interés: calles reales y pasos peatonales.
        for etiqueta, cats in [("calles_reales", ["calle_normal", "calle_abierta"]),
                               ("paso_peatonal", ["escalera", "sendero_o_paso_angosto"])]:
            k = int(g["cat"].isin(cats).sum())
            p, bajo, alto = wilson(k, n, C.Z_WILSON_95)
            fila.update({f"{etiqueta}_pct": round(100 * p, 1), f"{etiqueta}_wilson95_bajo": round(100 * bajo, 1),
                         f"{etiqueta}_wilson95_alto": round(100 * alto, 1)})
        filas.append(fila)

    # Organiza los resultados en una tabla, la exporta a CSV y muestra el resumen completo 
    tabla = pd.DataFrame(filas)
    tabla.to_csv(carpeta_salida() / "aux_revision_street_view_resumen.csv", index=False, encoding="utf-8-sig")
    print(tabla.to_string(index=False))


def main():
    lista = leer_lista(C.ARCHIVO_LISTA_REVISION)
    df = leer_pendientes()
    g = leer_segmentos()
    verificar(lista, df, g)

    # Si se proporciona el argumento --resumen, procesa las anotaciones completadas
    if "--resumen" in sys.argv[1:]:
        resumen(lista)
    else:
        enlaces(lista, g)


# Ejecuta el flujo principal únicamente cuando el archivo se ejecuta directamente.
if __name__ == "__main__":
    main()
