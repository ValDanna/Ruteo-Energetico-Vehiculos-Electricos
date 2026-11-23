"""
aux_comparar_versiones.py
Compara dos versiones del archivo de pendientes (por ejemplo, la entregada y
una regenerada). Confirma que las pendientes de los segmentos con dato en
ambas no cambiaron y cuenta los segmentos que ganaron o perdieron cobertura.

Uso: python auxiliares/aux_comparar_versiones.py anterior.csv nueva.csv
"""
import sys

import pandas as pd

if len(sys.argv) != 3:
    sys.exit("Uso: python auxiliares/aux_comparar_versiones.py anterior.csv nueva.csv")

viejo = pd.read_csv(sys.argv[1], float_precision="round_trip").set_index("segmento_id")
nuevo = pd.read_csv(sys.argv[2], float_precision="round_trip").set_index("segmento_id")
print(f"Filas: {len(viejo):,} / {len(nuevo):,}  mismos ids: {set(viejo.index) == set(nuevo.index)}")
nuevo = nuevo.loc[viejo.index]
fv, fn = viejo["fuera_cobertura_mdt"].astype(bool), nuevo["fuera_cobertura_mdt"].astype(bool)
print(f"Fuera de cobertura: {int(fv.sum()):,} -> {int(fn.sum()):,}")
print(f"  recuperados: {int((fv & ~fn).sum()):,}   perdidos: {int((~fv & fn).sum()):,} (debe ser 0)")
ambos = ~fv & ~fn
for col in ["pendiente_neta_pct", "pendiente_acumulada_pct", "z_inicio_m", "z_fin_m",
            "ganancia_elevacion_m", "perdida_elevacion_m", "n_puntos_muestreados", "paso_muestreo_m",
            "error_pendiente_pct", "ruido_acumulada_pct", "rho_correlacion"]:
    d = (viejo.loc[ambos, col] - nuevo.loc[ambos, col]).abs().max()
    print(f"  {col:26s} diferencia maxima {d:.2e}")
for col in ["clasificacion_invias", "pendiente_extrema", "distinta_de_cero_2sigma"]:
    n = (viejo.loc[ambos, col].astype(str) != nuevo.loc[ambos, col].astype(str)).sum()
    print(f"  {col:26s} filas distintas {n}")
