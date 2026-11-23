"""
aux_verificar_contrato.py
Verificacion independiente del archivo de pendientes contra el contrato.

No reutiliza el codigo de la etapa: reconstruye la longitud de cada segmento
a partir de error_pendiente_pct y rho_correlacion, y con ella vuelve a
calcular cada regla del contrato. Sirve para revisar un archivo recibido sin
tener el gpkg.

Uso: python auxiliares/aux_verificar_contrato.py [archivo.csv]
"""
import json
import sys

import numpy as np
import pandas as pd

from _comun import C

archivo = sys.argv[1] if len(sys.argv) > 1 else C.ARCHIVO_PENDIENTES
df = pd.read_csv(archivo, float_precision="round_trip")
contrato = json.loads(C.ARCHIVO_CONTRATO.read_text(encoding="utf-8"))
print(f"Archivo: {archivo}  filas: {len(df):,}")
print("Columnas del contrato:", list(df.columns) == contrato["retorno_esperado"]["columnas"])

s = df["sigma_z_m"].unique(); a = df["ancho_correlacion_m"].unique()
print(f"sigma_z: {s}  ancho: {a}")
S, A = float(s[0]), float(a[0])
c = df[~df["fuera_cobertura_mdt"].astype(bool)].copy()
L = 100 * np.sqrt(2 * S ** 2 * (1 - c["rho_correlacion"])) / c["error_pendiente_pct"]
neta = c["pendiente_neta_pct"]; acum = c["pendiente_acumulada_pct"]
p = L / (c["n_puntos_muestreados"] - 1)
ruido = 100 * np.sqrt(2 / np.pi) * S * np.sqrt(2 * (1 - np.exp(-p / A))) / p
an = neta.abs()
inv = np.select([an < 3, an < 6, an <= 8], ["Plano", "Ondulado", "Montañoso"], "Escarpado")
reglas = {
    "rho = exp(-L/A)": np.max(np.abs(c["rho_correlacion"] - np.exp(-L / A))),
    "neta = 100 dz / L": np.max(np.abs(neta - 100 * (c["z_fin_m"] - c["z_inicio_m"]) / L)),
    "acumulada = 100 (g+p) / L": np.max(np.abs(acum - 100 * (c["ganancia_elevacion_m"] + c["perdida_elevacion_m"]) / L)),
    "ruido segun contrato": np.max(np.abs(c["ruido_acumulada_pct"] - ruido)),
}
for k, v in reglas.items():
    print(f"  {k:28s} diferencia maxima {v:.1e}")
print("  INVIAS discrepancias:", int((inv != c["clasificacion_invias"]).sum()))
print("  2 sigma discrepancias:", int(((an > 2 * c["error_pendiente_pct"]) != c["distinta_de_cero_2sigma"].astype(bool)).sum()))
print("  extrema discrepancias:", int(((np.maximum(an, acum) > 35) != c["pendiente_extrema"].astype(bool)).sum()))
print("  paso discrepancias:", int((np.where(an < 3, 50.0, 10.0) != c["paso_muestreo_m"]).sum()))
