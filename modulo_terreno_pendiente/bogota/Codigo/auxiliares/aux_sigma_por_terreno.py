"""

Rama de sensibilidad: error de la pendiente con un sigma_z distinto para cada
tipo de terreno, en lugar del valor unico adoptado (0,536 m).

El error vertical del MDT es mayor en ladera. Este script recalcula el error de
la pendiente de cada segmento con el sigma_z del terreno que le corresponde y
cuenta cuantas pendientes siguen siendo distinguibles de cero (|neta| > 2 x error).

  - sigma_z por terreno: RMSEz de los vertices del conjunto adoptado (496) en
    cada zona, tomado de exactitud_ampliada_resumen.csv y redondeado a 2
    decimales, como se reporta en el documento (plano 0,44; inclinado 0,56;
    ladera 0,75 m).
  - Correspondencia con la clase INVIAS del segmento: Plano -> plano (< 3 %);
    Ondulado y Montanoso -> inclinado (3-8 %); Escarpado -> ladera (> 8 %).
    Son los mismos cortes de pendiente.
  - El error de la pendiente es proporcional a sigma_z, asi que el error con
    el sigma del terreno es error_pendiente_pct x sigma_terreno / 0,536.

No modifica el archivo oficial, la pendiente, la clasificacion INVIAS y la marca de pendiente extrema no dependen de sigma_z.

Uso:   aux_sigma_por_terreno.py
Entra: exactitud_ampliada_resumen.csv
Sale:  sigma_por_terreno_segmentos.csv (error de cada segmento con los dos sigma)
       sigma_por_terreno_resumen.csv   (distinguibles y error mediano por clase)
"""
import hashlib
import sys

import pandas as pd

from _comun import C, CARPETA_AUX

RESUMEN_EXACTITUD = CARPETA_AUX / "exactitud_ampliada_resumen.csv"
ZONA_DE_CLASE = {"Plano": "plano (<3 %)", "Ondulado": "inclinado (3-8 %)",
                 "Montañoso": "inclinado (3-8 %)", "Escarpado": "ladera (>8 %)"}
SALIDA_SEGMENTOS = CARPETA_AUX / "sigma_por_terreno_segmentos.csv"
SALIDA_RESUMEN = CARPETA_AUX / "sigma_por_terreno_resumen.csv"


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def main():
    if not RESUMEN_EXACTITUD.exists():
        sys.exit("Falta exactitud_ampliada_resumen.csv: corra antes aux_exactitud_ampliada.py.")
    ex = pd.read_csv(RESUMEN_EXACTITUD)
    sigma_zona = {}
    for zona in sorted(set(ZONA_DE_CLASE.values())):
        fila = ex[ex["conjunto"] == f"adoptado (oficial) - {zona}"]
        if fila.empty:
            sys.exit(f"No esta el conjunto 'adoptado (oficial) - {zona}' en {RESUMEN_EXACTITUD.name}.\n"
                     f"Conjuntos que tiene el archivo: {list(ex['conjunto'])}\n"
                     "Vuelva a correr aux_exactitud_ampliada.py para regenerarlo con los nombres actuales.")
        sigma_zona[zona] = round(float(fila["rmse_z_m"].iloc[0]), 2)
        print(f"sigma_z {zona}: {float(fila['rmse_z_m'].iloc[0]):.4f} m -> se usa {sigma_zona[zona]:.2f} m "
              f"({int(fila['n'].iloc[0])} vertices)")
    sigma_oficial = C.SIGMA_Z_ADOPTADO_M
    print(f"sigma_z oficial (unico): {sigma_oficial} m")

    df = pd.read_csv(C.ARCHIVO_PENDIENTES, dtype={"segmento_id": str}, float_precision="round_trip")
    con = df[~df["fuera_cobertura_mdt"].astype(str).str.lower().eq("true")].copy()
    con["zona_sigma"] = con["clasificacion_invias"].map(ZONA_DE_CLASE)
    if con["zona_sigma"].isna().any():
        sys.exit("Hay segmentos con una clase INVIAS sin zona asignada.")
    con["sigma_terreno_m"] = con["zona_sigma"].map(sigma_zona)
    con["neta_abs"] = con["pendiente_neta_pct"].abs()
    con["error_oficial_pct"] = con["error_pendiente_pct"]
    con["error_terreno_pct"] = con["error_pendiente_pct"] * con["sigma_terreno_m"] / sigma_oficial
    con["distinguible_oficial"] = con["neta_abs"] > 2 * con["error_oficial_pct"]
    con["distinguible_terreno"] = con["neta_abs"] > 2 * con["error_terreno_pct"]

    comprobacion = (con["distinguible_oficial"] == con["distinta_de_cero_2sigma"].astype(str).str.lower().eq("true")).mean()
    print(f"Coincidencia con la columna distinta_de_cero_2sigma del archivo: {100 * comprobacion:.2f} %")

    filas = []
    grupos = [(clase, con["clasificacion_invias"] == clase) for clase in C.ETIQUETAS_INVIAS]
    grupos.append(("toda la red", pd.Series(True, index=con.index)))
    for nombre, m in grupos:
        g = con[m]
        filas.append({"clase_invias": nombre, "segmentos": len(g),
                      "sigma_terreno_m": sigma_zona.get(ZONA_DE_CLASE.get(nombre)),
                      "distinguibles_oficial_pct": 100 * g["distinguible_oficial"].mean(),
                      "distinguibles_terreno_pct": 100 * g["distinguible_terreno"].mean(),
                      "error_mediano_oficial_pp": g["error_oficial_pct"].median(),
                      "error_mediano_terreno_pp": g["error_terreno_pct"].median()})
    resumen = pd.DataFrame(filas)

    pd.set_option("display.width", 200)
    print("\nPendientes distinguibles de cero y error mediano, con sigma unico y con sigma por terreno:")
    print(resumen.round(2).to_string(index=False))

    cols = ["segmento_id", "clasificacion_invias", "zona_sigma", "sigma_terreno_m", "pendiente_neta_pct",
            "error_oficial_pct", "error_terreno_pct", "distinguible_oficial", "distinguible_terreno"]
    con[cols].to_csv(SALIDA_SEGMENTOS, index=False, encoding="utf-8-sig")
    resumen.to_csv(SALIDA_RESUMEN, index=False, encoding="utf-8-sig")
    print(f"\nGuardado: {SALIDA_SEGMENTOS.name}  SHA256 {sha256(SALIDA_SEGMENTOS)}")
    print(f"Guardado: {SALIDA_RESUMEN.name}  SHA256 {sha256(SALIDA_RESUMEN)}")


if __name__ == "__main__":
    main()
