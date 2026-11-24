import numpy as np
import pydeck as pdk
import streamlit as st

import comun

d = comun.cargar_o_detener()
tramos, contorno, est_df, (lat0, lon0) = comun.capas_base()

izq, der = st.columns([5, 6], gap="large")

with izq:
    st.markdown("<div class='titular'>La ruta más corta no siempre es la que menos batería gasta</div>",
                unsafe_allow_html=True)
    st.markdown(
        "<p class='bajada'>En Bogotá y Medellín, subir una ladera puede costarle a un carro "
        "eléctrico pequeño varias veces lo que cuesta el mismo trayecto en plano. Medimos cuánto "
        "cambia la ruta cuando se optimiza por energía, usando solo datos abiertos.</p>",
        unsafe_allow_html=True)

    sector = tramos[tramos["en_sector"]]
    conf = sector[sector["confiable"]]
    principales = d["estaciones"][~d["estaciones"]["es_secundario"]]
    c1, c2 = st.columns(2)
    c1.markdown(comun.cifra(f"{len(sector):,}".replace(",", "."), "tramos de calle en Chapinero"),
                unsafe_allow_html=True)
    c2.markdown(comun.cifra(f"{np.median(conf['abs_pct']):.1f} %", "pendiente mediana"),
                unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    c3.markdown(comun.cifra(int((principales["ciudad"] == "Bogota").sum()),
                            "estaciones de carga en Bogotá"), unsafe_allow_html=True)
    c4.markdown(comun.cifra(int((principales["ciudad"] == "Medellin").sum()),
                            "estaciones de carga en Medellín"), unsafe_allow_html=True)

    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
    fases = [
        ("Inventario de estaciones", "Verificado", True),
        ("Red vial con pendiente", "Chapinero verificado", True),
        ("Modelo de consumo", "En desarrollo", False),
        ("Comparación de rutas", "Prototipo con consumo de prueba", False),
        ("Alcanzabilidad", "Pendiente", False),
        ("Contraste con Medellín", "Pendiente", False),
    ]
    html = "".join(f"<div class='fase'><b>{i}. {n}</b>"
                   f"<span class='e{' ok' if ok else ''}'>{e}</span></div>"
                   for i, (n, e, ok) in enumerate(fases, 1))
    st.markdown(html, unsafe_allow_html=True)

with der:
    vista = tramos[tramos["en_sector"] & tramos["confiable"]]
    capas = [
        pdk.Layer("PathLayer", data=vista, get_path="path", get_color="color",
                  width_min_pixels=1.6, cap_rounded=True, joint_rounded=True),
        pdk.Layer("PathLayer", data=contorno, get_path="path",
                  get_color=[230, 237, 241, 90], width_min_pixels=1),
    ]
    st.pydeck_chart(comun.deck(capas, lat0, lon0 + 0.01, zoom=12.4, pitch=40), height=600)
    st.markdown(comun.leyenda_pendiente(), unsafe_allow_html=True)
    st.caption("Pendiente de cada tramo en Chapinero, calculada sobre el terreno LiDAR de IDECA 2025.")
