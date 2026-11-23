"""
Compara dos versiones del archivo de pendientes fila por fila ( por segmento_id).

Que hace: Comprueba que tengan las mismas filas y columnas, que las columnas de
categoria (INVIAS, booleanos, es_tunel) sean identicas y que la diferencia
maxima en cada columna numerica no supere la tolerancia de la configuracion
(1e-10).Solo documenta que cambia entre versiones, pro si se requiere algun cambio.

Lee:      los dos CSV.
Escribe:  aux_comparar_versiones.csv

Resultado, se realizo unos cambios entre versiones y se comparo v1 (f7f5551e...) contra v2 (96bfac06...): categorias
identicas en las 39.160 filas. Difieren en el ultimo digito: neta 7.742 filas
(max 7,1e-15 pp), acumulada 7.580 (1,1e-13 pp), alturas 313 (2,3e-13 m),
ganancia y perdida 2, error 626, ruido 1.643 y rho 2.030 (max 1,1e-15). Causa:
la v1 se armo leyendo los perfiles con el lector rapido de pandas, que
cambio el ultimo digito, rho, error y ruido difieren ademas porque exp y sqrt de
Linux (v1) y Windows (v2) no redondean igual.

v2 (96bfac06...) contra v3 (2aaba723..., sigma_z 0,10 -> 0,539): neta, acumulada, alturas, puntos, paso, INVIAS, extremas, cobertura, rho, ancho y tuneles identicos en las 39.160 filas. 
Cambian, error y ruido (39.158 filas), sigma_z_m (39.160) y distinta_de_cero_2sigma (9.246 segmentos dejan de ser distinguibles de cero). Por eso el resultado dice "NO COINCIDEN".
"""
import sys

import numpy as np
import pandas as pd

from _comun import C, carpeta_salida, sha256_archivo

# Identifica las columnas que deben compararse como categorías o estados, en lugar de tratar sus valores como cantidades numéricas
CATEGORIAS = ["clasificacion_invias", "distinta_de_cero_2sigma", "pendiente_extrema",
              "fuera_cobertura_mdt", "es_tunel"]


def main():
     # Verifica que se hayan proporcionado las rutas de los dos archivos CSV que se comparan
    if len(sys.argv) < 3:
        raise SystemExit("Uso: python auxiliares/aux_comparar_versiones.py <anterior.csv> <nueva.csv>")
    # Identifica las versiones anterior y nueva, e imprime sus huellas SHA para la trazabilidad de los archivos evaluados.
    a, b = sys.argv[1], sys.argv[2]
    print(f"A: {a}\n   SHA {sha256_archivo(a)}\nB: {b}\n   SHA {sha256_archivo(b)}")
    # Lee ambos archivos como texto y utiliza segmento_id como índice
    x = pd.read_csv(a, dtype=str, keep_default_na=False).set_index("segmento_id")
    y = pd.read_csv(b, dtype=str, keep_default_na=False).set_index("segmento_id")
    # Comprueba que ambas versiones tengan las mismas columnas y los mismos identificadores de segmentos antes de
    if list(x.columns) != list(y.columns) or set(x.index) != set(y.index):
        raise SystemExit("Columnas o filas distintas: no se pueden comparar")
    # Reordena la nueva versión para comparar cada segmento en la misma posición que ocupa en el archivo anterior
    y = y.loc[x.index]
    filas = []
    #Revisa cada columna y registra el resultado de su comparación
    for col in x.columns:
        iguales_texto = int((x[col] == y[col]).sum())
        # Para las columnas categóricas exige coincidencia exacta
        if col in CATEGORIAS:
            ok = iguales_texto == len(x)
            filas.append({"columna": col, "tipo": "categoria", "filas_distintas": len(x) - iguales_texto,
                          "dif_max": "", "pasa": ok})
            continue
        # Convierte las demás columnas a valores numéricos para medir sus diferencias
        # float() de Python es exacto; pd.to_numeric puede cambiar el ultimo digito
        vx = x[col].map(lambda t: float(t) if t != "" else np.nan)
        vy = y[col].map(lambda t: float(t) if t != "" else np.nan)
         # Comprueba que los valores faltantes coincidan y calcula la diferencia absoluta máxima entre ambas versiones para la columna evaluada
        mismos_vacios = bool((vx.isna() == vy.isna()).all())
        dif = (vx - vy).abs().max()
        dif = 0.0 if pd.isna(dif) else float(dif)
        # Una columna numérica pasa si mantiene los mismos valores faltantes y sus diferencias no superan la tolerancia
        filas.append({"columna": col, "tipo": "numerica", "filas_distintas": len(x) - iguales_texto,
                      "dif_max": f"{dif:.1e}", "pasa": mismos_vacios and dif <= C.TOLERANCIA_COMPARACION})
    # Consolida los resultados de todas las columnas en una tabla    
    tabla = pd.DataFrame(filas)
    tabla.to_csv(carpeta_salida() / "aux_comparar_versiones.csv", index=False, encoding="utf-8-sig")
    print(tabla.to_string(index=False))
    # Emite un veredicto global: todas las columnas deben cumplir sus criterios para considerar equivalentes las dos versiones dentro de la tolerancia
    veredicto = "COINCIDEN dentro de la tolerancia" if tabla["pasa"].all() else "NO COINCIDEN: revisar antes de entregar"
    print(f"\n{veredicto} (tolerancia {C.TOLERANCIA_COMPARACION})")
    if not tabla["pasa"].all():
        sys.exit(1)


if __name__ == "__main__":
    main()
