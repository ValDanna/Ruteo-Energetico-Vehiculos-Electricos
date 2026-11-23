"""
aux_investigar_atipicos.py
Reune evidencia sobre los vertices que superan el umbral de investigacion de
la ASPRS en la validacion ampliada, para decidir uno por uno si el error esta
en la referencia del IGAC o en el MDT.

Para cada vertice:
  - residuo con el MDT 2025 (si los dos MDT coinciden entre si y no con el
    IGAC, el problema esta en la referencia, como en 10-E-1);
  - variacion del terreno alrededor (MDT 2020 en 8 puntos a 5 m y 8 a 15 m):
    si el terreno cambia varios metros en pocos metros (muro, talud, canal),
    un pequeno corrimiento de la coordenada explica el residuo;
  - enlace de Google Maps para mirar el sitio.

Uso:   python auxiliares/aux_investigar_atipicos.py [VERTICE ...]
Entra: datos_salida/auxiliares/exactitud_ampliada_vertices.csv
Sale:  datos_salida/auxiliares/atipicos_evidencia.csv
"""
import math
import sys
import time

import pandas as pd

from _comun import CARPETA_AUX, z2020, z2025

VERTICES = sys.argv[1:] or ["CD-543", "BOGOTA-19", "CD-840", "CD-109A", "CD-445",
                           "CAR1", "CD-323A", "18-BGT-1", "NP-A63-CD", "NP-B63-CD"]
M_POR_GRADO = 111_320.0

v = pd.read_csv(CARPETA_AUX / "exactitud_ampliada_vertices.csv").set_index("vertice")
filas = []
for nombre in VERTICES:
    f = v.loc[nombre]
    lat, lon, h = f["lat"], f["lon"], f["altitud_igac_m"]
    z25 = z2025(lon, lat)
    anillo = {}
    for radio in (5, 15):
        zs = []
        for k in range(8):
            ang = math.radians(45 * k)
            dla = radio * math.sin(ang) / M_POR_GRADO
            dlo = radio * math.cos(ang) / (M_POR_GRADO * math.cos(math.radians(lat)))
            z = z2020(lon + dlo, lat + dla)
            if z is not None:
                zs.append(z)
            time.sleep(0.05)
        anillo[radio] = (min(zs), max(zs)) if zs else (None, None)
    filas.append({
        "vertice": nombre, "altitud_igac_m": h,
        "mdt2020_m": f["elevacion_mdt2020_m"], "residuo_2020_m": f["residuo_m"],
        "mdt2025_m": z25, "residuo_2025_m": None if z25 is None else z25 - h,
        "terreno_5m_min": anillo[5][0], "terreno_5m_max": anillo[5][1],
        "terreno_15m_min": anillo[15][0], "terreno_15m_max": anillo[15][1],
        "igac_dentro_rango_15m": (anillo[15][0] is not None and anillo[15][0] <= h <= anillo[15][1]),
        "google_maps": f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
    })
    print(f"  {nombre} listo")

t = pd.DataFrame(filas)
t.to_csv(CARPETA_AUX / ("atipicos_evidencia.csv" if not sys.argv[1:] else f"atipicos_evidencia_{'_'.join(VERTICES)}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250)
print(t.drop(columns="google_maps").round(2).to_string(index=False))
print("\nEnlaces:")
for _, r in t.iterrows():
    print(f"  {r['vertice']:10s} {r['google_maps']}")
