"""
consumo_sintetico.py — Modelo de consumo DE PRUEBA.

⚠ NADA DE ESTE ARCHIVO ES RESULTADO. Los carros son ficticios y los parámetros
son valores redondos plausibles, sin fuente. Sirve solo para diseñar la página
mientras Emily entrega el modelo real (fase 3).

CONTRATO que debe cumplir el modelo real para reemplazar este archivo sin tocar
la página:
    VEHICULOS: dict  nombre -> dict de parámetros (con clave "fuente")
    energia_tramo_kwh(vehiculo: dict, longitud_m, pendiente, velocidad_kmh) -> kWh
        - pendiente como fracción (0.08 = 8 %), positiva en subida
        - acepta arrays de numpy
        - kWh negativo = energía recuperada en bajada
    ES_SINTETICO: bool
"""

import numpy as np

ES_SINTETICO = True

G = 9.81          # m/s²
RHO_AIRE = 0.95   # kg/m³ aprox. a 2.600 m de altura

VEHICULOS = {
    "Carro prueba A (muy liviano)": {
        "masa_kg": 1000, "crr": 0.010, "cd_a_m2": 0.60,
        "eficiencia_motor": 0.88, "eficiencia_regen": 0.60,
        "bateria_kwh": 27, "carga_ac_kw": 7.4, "carga_dc_kw": 40, "conectores": ["TYPE2", "CCS2"],
        "fuente": "SINTÉTICO — sin fuente",
    },
    "Carro prueba B (compacto)": {
        "masa_kg": 1350, "crr": 0.011, "cd_a_m2": 0.65,
        "eficiencia_motor": 0.90, "eficiencia_regen": 0.65,
        "bateria_kwh": 42, "carga_ac_kw": 11, "carga_dc_kw": 50, "conectores": ["TYPE2", "CCS2", "CHADEMO"],
        "fuente": "SINTÉTICO — sin fuente",
    },
    "Carro prueba C (compacto pesado)": {
        "masa_kg": 1650, "crr": 0.012, "cd_a_m2": 0.72,
        "eficiencia_motor": 0.90, "eficiencia_regen": 0.70,
        "bateria_kwh": 60, "carga_ac_kw": 11, "carga_dc_kw": 100, "conectores": ["TYPE2", "CCS2"],
        "fuente": "SINTÉTICO — sin fuente",
    },
}

# Reglas de recarga (SINTÉTICAS salvo que se indique)
EFICIENCIA_CARGA = 0.90     # energía que entra a la batería / energía entregada por la estación
SOC_MAX_CARGA = 0.80        # no se carga por encima del 80 %
RESERVA_SOC = 0.05          # el carro nunca debe bajar de esta reserva
MARGEN_SOC = 0.02           # margen extra al calcular cuánto cargar
UMBRAL_DC_KW = 22           # sin dato de corriente, más de 22 kW se asume carga DC

def energia_tramo_kwh(vehiculo, longitud_m, pendiente, velocidad_kmh):
    """Dinámica longitudinal a velocidad constante (sin aceleraciones)."""
    L = np.asarray(longitud_m, dtype=float)
    s = np.asarray(pendiente, dtype=float)
    v = np.asarray(velocidad_kmh, dtype=float) / 3.6
    theta = np.arctan(s)

    m = vehiculo["masa_kg"]
    fuerza = (m * G * vehiculo["crr"] * np.cos(theta)       # rodadura
              + m * G * np.sin(theta)                        # gravedad
              + 0.5 * RHO_AIRE * vehiculo["cd_a_m2"] * v**2)  # aire
    trabajo_j = fuerza * L

    en_rueda = np.where(trabajo_j >= 0,
                        trabajo_j / vehiculo["eficiencia_motor"],   # batería gasta más
                        trabajo_j * vehiculo["eficiencia_regen"])   # batería recupera menos
    return en_rueda / 3.6e6
