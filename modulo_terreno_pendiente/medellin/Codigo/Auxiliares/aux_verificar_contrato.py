"""
Verificacion independiente del archivo de pendientes contra el contrato D2M.

Que hace: lee el CSV como texto y comprueba cada regla del contrato con el gpkg y el JSON del contrato: columnas y orden, una fila por segmento, etiquetas INVIAS exactas,
booleanos escritos True/False, formulas de neta, acumulada, rho, error, 2 sigma,
ruido y pendiente extrema, celdas vacias fuera de cobertura, valores unicos de
sigma_z y ancho iguales a los del contrato, y la regla de tuneles.

Lee:      el CSV, D2M_contrato_intercambio.json y el gpkg.
Escribe:  aux_verificar_contrato.csv

Resultado: 18 de 18 reglas cumplidas.
"""
import csv
import json
import math
import sys

import pandas as pd

from _comun import C, SALIDA_OFICIAL, carpeta_salida, leer_segmentos

TOL = 1e-9


def num(s):
    return float(s) if s != "" else None


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else SALIDA_OFICIAL
    contrato = json.loads(C.ARCHIVO_CONTRATO.read_text(encoding="utf-8"))
    sigma, ancho = contrato["sigma_z_m"], contrato["ancho_correlacion_m"]
    longitud = dict(zip(*leer_segmentos(geometria=False)[["segmento_id", "longitud_m"]].T.values))

    with open(ruta, newline="", encoding="utf-8") as f:
        lector = csv.reader(f)
        encabezado = next(lector)
        filas = [dict(zip(encabezado, r)) for r in lector]

    fallas = {}

    def falla(regla, sid):
        fallas.setdefault(regla, []).append(sid)

    reglas = ["columnas y orden", "una fila por segmento", "booleanos True/False", "etiquetas INVIAS",
              "vacios fuera de cobertura", "neta", "acumulada", "ganancia y perdida no negativas", "rho",
              "error", "2 sigma", "ruido acumulada", "pendiente extrema", "clasificacion INVIAS",
              "sigma_z y ancho del contrato", "tuneles: 2 puntos y acumulada = |neta|",
              "es_tunel igual en FT y TF", "signo FT/TF"]
    if encabezado != contrato["columnas_retorno"]:
        falla("columnas y orden", "encabezado")
    ids = [r["segmento_id"] for r in filas]
    if len(ids) != contrato["n_segmentos"] or len(set(ids)) != len(ids) or set(ids) != set(longitud):
        falla("una fila por segmento", "conjunto")

    tunel_por_base, neta_por_base = {}, {}
    for r in filas:
        sid = r["segmento_id"]
        L = float(longitud[sid])
        for b in ["distinta_de_cero_2sigma", "pendiente_extrema", "fuera_cobertura_mdt", "es_tunel"]:
            if r[b] not in ("True", "False", ""):
                falla("booleanos True/False", sid)
        if num(r["sigma_z_m"]) != sigma or num(r["ancho_correlacion_m"]) != ancho:
            falla("sigma_z y ancho del contrato", sid)
        base, sentido = sid.rsplit("_", 1)
        tunel_por_base.setdefault(base, set()).add(r["es_tunel"])
        if r["fuera_cobertura_mdt"] == "True":
            vacias = ["pendiente_neta_pct", "pendiente_acumulada_pct", "clasificacion_invias",
                      "error_pendiente_pct", "distinta_de_cero_2sigma"]
            if any(r[c] != "" for c in vacias):
                falla("vacios fuera de cobertura", sid)
            continue
        neta, acum = num(r["pendiente_neta_pct"]), num(r["pendiente_acumulada_pct"])
        gan, per = num(r["ganancia_elevacion_m"]), num(r["perdida_elevacion_m"])
        zi, zf, n = num(r["z_inicio_m"]), num(r["z_fin_m"]), int(r["n_puntos_muestreados"])
        neta_por_base.setdefault(base, {})[sentido] = (neta, zi, zf)
        if r["clasificacion_invias"] not in ("Plano", "Ondulado", "Montañoso", "Escarpado"):
            falla("etiquetas INVIAS", sid)
        if abs(neta - 100 * (zf - zi) / L) > TOL:
            falla("neta", sid)
        if abs(acum - 100 * (gan + per) / L) > TOL:
            falla("acumulada", sid)
        if gan < 0 or per < 0:
            falla("ganancia y perdida no negativas", sid)
        rho = math.exp(-L / ancho)
        if abs(num(r["rho_correlacion"]) - rho) > 1e-12:
            falla("rho", sid)
        err = 100 * math.sqrt(2 * sigma ** 2 * (1 - rho)) / L
        if abs(num(r["error_pendiente_pct"]) - err) > 1e-12:
            falla("error", sid)
        if (abs(neta) > 2 * err) != (r["distinta_de_cero_2sigma"] == "True"):
            falla("2 sigma", sid)
        p = L / (n - 1)
        sd = sigma * math.sqrt(2 * (1 - math.exp(-p / ancho)))
        if abs(num(r["ruido_acumulada_pct"]) - 100 * math.sqrt(2 / math.pi) * sd / p) > 1e-12:
            falla("ruido acumulada", sid)
        if (max(abs(neta), abs(acum)) > 35.0) != (r["pendiente_extrema"] == "True"):
            falla("pendiente extrema", sid)
        a = abs(neta)
        esperada = "Plano" if a < 3 else "Ondulado" if a < 6 else "Montañoso" if a <= 8 else "Escarpado"
        if r["clasificacion_invias"] != esperada:
            falla("clasificacion INVIAS", sid)
        if r["es_tunel"] == "True" and (n != 2 or abs(acum - abs(neta)) > TOL):
            falla("tuneles: 2 puntos y acumulada = |neta|", sid)

    for base, valores in tunel_por_base.items():
        if len(valores) > 1:
            falla("es_tunel igual en FT y TF", base)
    for base, d in neta_por_base.items():
        if "FT" in d and "TF" in d:
            (n1, zi1, zf1), (n2, zi2, zf2) = d["FT"], d["TF"]
            if abs(n1 + n2) > TOL or zi1 != zf2:
                falla("signo FT/TF", base)

    tabla = pd.DataFrame([{"regla": r, "pasa": r not in fallas, "casos": len(fallas.get(r, [])),
                           "ejemplos": ", ".join(map(str, fallas.get(r, [])[:5]))} for r in reglas])
    tabla.to_csv(carpeta_salida() / "aux_verificar_contrato.csv", index=False, encoding="utf-8-sig")
    print(f"Archivo: {ruta}")
    print(tabla.to_string(index=False))
    print(f"\n{int(tabla['pasa'].sum())} de {len(tabla)} reglas cumplidas")
    if not tabla["pasa"].all():
        sys.exit(1)


if __name__ == "__main__":
    main()
