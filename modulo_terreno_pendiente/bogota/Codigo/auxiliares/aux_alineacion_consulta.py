"""
aux_alineacion_consulta.py
Documenta el defecto de la consulta multipunto que motivo pasar a consultas
punto a punto.

Prueba A: lote de 5 puntos con uno sin dato en el medio (vertice 1-CM-17,
Sumapaz). Resultado: 5 enviados, 2 recibidos; los puntos
validos posteriores al punto sin dato quedaron sin valor.
Prueba B: re-consulta punto a punto una muestra de la cache y compara.
Resultado: 694 de 700 identicos, 6 con diferencias de 2 a 7 cm
(borde de pixel); ninguna elevacion asignada al punto equivocado.

Uso: python auxiliares/aux_alineacion_consulta.py
Salida: datos_salida/auxiliares/alineacion_consulta.csv
"""
import numpy as np
import pandas as pd

from _comun import C, CARPETA_AUX, z2020, z2020_multipunto

lote = [(-74.0800, 4.6500), (-74.0820, 4.6500), (-74.26791584, 4.08030618), (-74.0840, 4.6500), (-74.0860, 4.6500)]
res = z2020_multipunto(lote).get("results", [])
print(f"Prueba A: {len(lote)} puntos enviados, {len(res)} resultados recibidos")
print("  punto a punto:", [z2020(lo, la) for lo, la in lote])

ck = pd.read_csv(C.ARCHIVO_CACHE, float_precision="round_trip")
muestra = ck[ck["elevacion_m"].notna()].sample(700, random_state=42)
muestra["z_punto_a_punto"] = [z2020(lo, la) for lo, la in zip(muestra["lon"], muestra["lat"])]
muestra["diferencia_m"] = muestra["elevacion_m"] - muestra["z_punto_a_punto"]
ok = muestra["diferencia_m"].abs() <= 0.01
print(f"Prueba B: {int(ok.sum())} de {len(muestra)} coinciden; maximo |dif| {muestra['diferencia_m'].abs().max():.3f} m")
muestra.to_csv(CARPETA_AUX / "alineacion_consulta.csv", index=False)
