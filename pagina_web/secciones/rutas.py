import altair as alt
import networkx as nx
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import comun
import consumo_sintetico as consumo

d = comun.cargar_o_detener()
tramos, contorno, est_df, (lat0, lon0) = comun.capas_base()
seg = d["segmentos"]


@st.cache_resource(show_spinner=False)
def estructura():
    rutas_geo = dict(zip(tramos["segmento_id"], tramos["path"]))
    pos = {}
    for u, v, p in zip(seg["u"], seg["v"], tramos["path"]):
        pos.setdefault(u, p[0])
        pos.setdefault(v, p[-1])
    G0 = nx.MultiDiGraph()
    G0.add_edges_from(zip(seg["u"], seg["v"]))
    mayor = max(nx.strongly_connected_components(G0), key=len)
    en_sector = set(seg.loc[seg["en_sector"], "u"]) | set(seg.loc[seg["en_sector"], "v"])
    return rutas_geo, pos, sorted(mayor & en_sector, key=str)


rutas_geo, pos, candidatos = estructura()

st.markdown("<div class='titular' style='font-size:2rem'>Ruta más corta frente a ruta de menor consumo</div>",
            unsafe_allow_html=True)
if consumo.ES_SINTETICO:
    comun.aviso_sintetico("El grafo, las pendientes y la ruta más corta son reales. "
                          "Los carros y el consumo son de prueba mientras se termina el modelo.")

# --- controles --------------------------------------------------------------
a, b, c, e = st.columns([2.2, 2, 1.2, 1])
nombre_carro = a.selectbox("Vehículo", list(consumo.VEHICULOS))
velocidad = b.slider("Velocidad (km/h)", 10, 60, 30)
semilla = c.number_input("Par de puntos", min_value=0, value=7, step=1)
with e.popover("Ajustes", width="stretch"):
    no_conf_cero = st.toggle("Tramos sin pendiente confiable como planos", value=True)
    excluir_extremos = st.toggle("Excluir tramos de más del 25 %", value=False)
carro = consumo.VEHICULOS[nombre_carro]

# --- grafo ponderado --------------------------------------------------------
pend = seg["pendiente_neta"].fillna(0.0).to_numpy()
if no_conf_cero:
    pend = np.where(seg["pendiente_confiable"].to_numpy(), pend, 0.0)
mascara = np.abs(pend) <= 0.25 if excluir_extremos else np.ones(len(seg), bool)
s = seg[mascara]
energia = consumo.energia_tramo_kwh(carro, s["longitud_m"].to_numpy(), pend[mascara], velocidad)

G = nx.MultiDiGraph()
for sid, u, v, L, en, p in zip(s["segmento_id"], s["u"], s["v"], s["longitud_m"], energia, pend[mascara]):
    G.add_edge(u, v, key=sid, longitud=float(L), energia=float(en), pendiente=float(p))

rng = np.random.default_rng(int(semilla))
cand = [n for n in candidatos if n in G]
origen = destino = None
for _ in range(50):
    i, j = rng.choice(len(cand), size=2, replace=False)
    if nx.has_path(G, cand[i], cand[j]):
        origen, destino = cand[i], cand[j]
        break
if origen is None:
    st.warning("No hay un par conectado con estos ajustes. Pruebe otro número.")
    st.stop()


def peso(attr):
    return lambda u, v, datos: min(x[attr] for x in datos.values())


def resumir(camino, attr):
    filas, dist, z = [], 0.0, 0.0
    for u, v in zip(camino[:-1], camino[1:]):
        k, x = min(G[u][v].items(), key=lambda kx: kx[1][attr])
        dist += x["longitud"]
        z += x["pendiente"] * x["longitud"]
        filas.append({"segmento_id": k, "longitud": x["longitud"], "energia": x["energia"],
                      "pendiente": x["pendiente"], "km": dist / 1000, "altura": z})
    return pd.DataFrame(filas)


corta = nx.shortest_path(G, origen, destino, weight=peso("longitud"))
aviso_ciclo = False
try:
    eficiente = nx.bellman_ford_path(G, origen, destino, weight=peso("energia"))
except nx.NetworkXUnbounded:
    aviso_ciclo = True
    for _, _, x in G.edges(data=True):
        x["energia"] = max(x["energia"], 0.0)
    eficiente = nx.shortest_path(G, origen, destino, weight=peso("energia"))

rc, re_ = resumir(corta, "longitud"), resumir(eficiente, "energia")

# Verificación independiente
for r in (rc, re_):
    recalculo = consumo.energia_tramo_kwh(carro, r["longitud"], r["pendiente"], velocidad).sum()
    assert abs(recalculo - r["energia"].sum()) < 1e-9, "La energía de la ruta no cuadra"
assert re_["energia"].sum() <= rc["energia"].sum() + 1e-9, "Ruteo por energía incorrecto"
assert rc["longitud"].sum() <= re_["longitud"].sum() + 1e-9, "Ruteo por distancia incorrecto"
if aviso_ciclo:
    st.warning("Pendientes incoherentes entre tramos: para esta consulta la regeneración se truncó a cero.")

d_c, d_e = rc["longitud"].sum() / 1000, re_["longitud"].sum() / 1000
e_c, e_e = rc["energia"].sum() * 1000, re_["energia"].sum() * 1000
ahorro = 100 * (e_c - e_e) / e_c if e_c > 0 else 0.0

# --- resultado --------------------------------------------------------------
mapa, panel = st.columns([3, 1.15], gap="medium")

with mapa:
    def trazo(r):
        pts = []
        for sid in r["segmento_id"]:
            pts.extend(rutas_geo[sid])
        return pts

    fondo = tramos[tramos["en_sector"]]
    capas = [
        pdk.Layer("PathLayer", data=fondo, get_path="path", get_color=[143, 163, 176, 45],
                  width_min_pixels=1),
        pdk.Layer("PathLayer", data=[{"path": trazo(rc)}], get_path="path",
                  get_color=comun.hex_rgb(comun.RUTA_CORTA) + [60], width_min_pixels=14,
                  cap_rounded=True, joint_rounded=True),
        pdk.Layer("PathLayer", data=[{"path": trazo(rc), "via": "Ruta más corta", "pend_txt": f"{d_c:.2f} km"}],
                  get_path="path", get_color=comun.hex_rgb(comun.RUTA_CORTA), width_min_pixels=4,
                  cap_rounded=True, joint_rounded=True, pickable=True),
        pdk.Layer("PathLayer", data=[{"path": trazo(re_)}], get_path="path",
                  get_color=comun.hex_rgb(comun.ACENTO) + [60], width_min_pixels=14,
                  cap_rounded=True, joint_rounded=True),
        pdk.Layer("PathLayer", data=[{"path": trazo(re_), "via": "Ruta de menor consumo", "pend_txt": f"{d_e:.2f} km"}],
                  get_path="path", get_color=comun.hex_rgb(comun.ACENTO), width_min_pixels=4,
                  cap_rounded=True, joint_rounded=True, pickable=True),
        pdk.Layer("ScatterplotLayer",
                  data=[{"lon": pos[origen][0], "lat": pos[origen][1], "via": "Origen", "pend_txt": ""},
                        {"lon": pos[destino][0], "lat": pos[destino][1], "via": "Destino", "pend_txt": ""}],
                  get_position=["lon", "lat"], get_fill_color=[230, 237, 241],
                  get_line_color=[20, 33, 43], stroked=True, line_width_min_pixels=3,
                  radius_min_pixels=7, pickable=True),
    ]
    lat_c = (pos[origen][1] + pos[destino][1]) / 2
    lon_c = (pos[origen][0] + pos[destino][0]) / 2
    tooltip = {"html": "<b>{via}</b><br/>{pend_txt}",
               "style": {"backgroundColor": comun.SUPERFICIE, "color": comun.TEXTO, "fontFamily": "Figtree"}}
    st.pydeck_chart(comun.deck(capas, lat_c, lon_c, zoom=14.3, pitch=35, tooltip=tooltip), height=560)

with panel:
    igual = corta == eficiente
    st.markdown(f"""<div class='panel'>
        <div style='color:{comun.TENUE};font-size:.9rem'>Energía ahorrada</div>
        <div style='font-size:2.6rem;font-weight:700;line-height:1.05;color:{comun.ACENTO}'>{ahorro:.1f} %</div>
        <div style='color:{comun.TENUE};margin-bottom:.9rem'>{e_c - e_e:.0f} Wh menos</div>
        <div class='fila'><span style='color:{comun.RUTA_CORTA}'>● Más corta</span><span>{d_c:.2f} km · {e_c:.0f} Wh</span></div>
        <div class='fila'><span style='color:{comun.ACENTO}'>● Menor consumo</span><span>{d_e:.2f} km · {e_e:.0f} Wh</span></div>
        <div class='fila'><span>Distancia extra</span><span>{(d_e - d_c) * 1000:+.0f} m</span></div>
        <div class='fila'><span>Batería usada</span><span>{100 * e_e / 1000 / carro['bateria_kwh']:.2f} %</span></div>
        </div>""", unsafe_allow_html=True)
    if igual:
        st.caption("Para este par, la ruta más corta ya es la de menor consumo.")

    perfil = pd.concat([rc[["km", "altura"]].assign(ruta="Más corta"),
                        re_[["km", "altura"]].assign(ruta="Menor consumo")])
    grafico = (alt.Chart(perfil).mark_line(strokeWidth=2.5, interpolate="monotone")
               .encode(x=alt.X("km:Q", title="km recorridos"),
                       y=alt.Y("altura:Q", title="altura relativa (m)"),
                       color=alt.Color("ruta:N", legend=None,
                                       scale=alt.Scale(domain=["Más corta", "Menor consumo"],
                                                       range=[comun.RUTA_CORTA, comun.ACENTO])))
               .properties(height=220, background="transparent")
               .configure_view(strokeWidth=0)
               .configure_axis(labelColor=comun.TENUE, titleColor=comun.TENUE, gridColor="#263A47",
                               labelFont="Figtree", titleFont="Figtree"))
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    st.altair_chart(grafico)
    st.caption("Perfil de altura de cada ruta desde el origen.")
