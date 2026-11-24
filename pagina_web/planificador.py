"""Planificador de viaje con recarga: referencia en Python (la página debe dar lo mismo)."""
import networkx as nx


def _camino_y_pico(G, a, b, attr="E"):
    """Ruta de menor energía a→b, su energía total, longitud y pico de consumo acumulado."""
    nodos = nx.bellman_ford_path(G, a, b, weight=lambda u, v, d: min(x[attr] for x in d.values()))
    acum, pico, largo = 0.0, 0.0, 0.0
    for u, v in zip(nodos[:-1], nodos[1:]):
        x = min(G[u][v].values(), key=lambda y: y[attr])
        acum += x["E"]; largo += x["L"]; pico = max(pico, acum)
    return acum, largo, pico


def planear(G, carro, estaciones, origen, destino, soc_salida, espera_min, velocidad_kmh, reglas):
    cap = carro["bateria_kwh"]
    e0, res = soc_salida * cap, reglas.RESERVA_SOC * cap
    E, Ld, pico = _camino_y_pico(G, origen, destino)
    if e0 - pico >= res - 1e-12:
        return {"parada": None, "e_directa": E, "pico_directo": pico}

    mejor = None
    for k, s in enumerate(estaciones):
        if s.get("kw") is None or s["kw"] <= 0 or s.get("acc") == "PRIVADO" or s.get("nodo") is None:
            continue
        if not set(t["t"] for t in s.get("con", [])) & set(carro["conectores"]):
            continue
        n = s["nodo"]
        try:
            E1, L1, p1 = _camino_y_pico(G, origen, n)
            E2, L2, p2 = _camino_y_pico(G, n, destino)
        except nx.NetworkXNoPath:
            continue
        if e0 - p1 < res - 1e-12:
            continue
        llegada = e0 - E1
        objetivo = res + max(0.0, p2) + reglas.MARGEN_SOC * cap
        if objetivo > reglas.SOC_MAX_CARGA * cap + 1e-12:
            continue
        carga = max(0.0, objetivo - llegada)
        dc = s.get("dc") is True or s["kw"] > reglas.UMBRAL_DC_KW
        potencia = min(s["kw"], carro["carga_dc_kw"] if dc else carro["carga_ac_kw"])
        t_carga = 0.0 if carga == 0 else carga / (potencia * reglas.EFICIENCIA_CARGA) * 60
        t_manejo = (L1 + L2) / 1000 / velocidad_kmh * 60
        total = t_manejo + t_carga + espera_min
        if mejor is None or total < mejor["total_min"] - 1e-9:
            mejor = {"estacion": k, "total_min": total, "carga_kwh": carga, "t_carga_min": t_carga,
                     "t_manejo_min": t_manejo, "potencia_kw": potencia, "E1": E1, "E2": E2}
    return {"parada": mejor, "e_directa": E, "pico_directo": pico, "imposible": mejor is None}