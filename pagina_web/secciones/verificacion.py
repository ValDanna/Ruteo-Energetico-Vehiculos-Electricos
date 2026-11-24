from pathlib import Path

import pandas as pd
import streamlit as st

import carga
import comun

d = comun.cargar_o_detener()

st.markdown("<div class='titular' style='font-size:2rem'>Qué se comprobó antes de mostrar esto</div>",
            unsafe_allow_html=True)
st.markdown("<p class='bajada'>Cada vez que se abre la página, los datos se leen de los archivos "
            "entregados y se someten a estas pruebas. Si una falla, la página no muestra nada.</p>",
            unsafe_allow_html=True)

todas = pd.DataFrame([{"Conjunto": "Estaciones", **p} for p in d["pruebas_est"]]
                     + [{"Conjunto": "Red vial", **p} for p in d["pruebas_grafo"]])
n_ok = int(todas["pasa"].sum())

c1, c2, c3 = st.columns(3)
c1.markdown(comun.cifra(f"{n_ok} de {len(todas)}", "pruebas superadas"), unsafe_allow_html=True)
c2.markdown(comun.cifra(len(d["pruebas_est"]), "sobre el inventario de estaciones", tenue=True),
            unsafe_allow_html=True)
c3.markdown(comun.cifra(len(d["pruebas_grafo"]), "sobre la red vial", tenue=True),
            unsafe_allow_html=True)

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
tabla = todas.rename(columns={"prueba": "Prueba", "detalle": "Detalle"})
tabla["Resultado"] = tabla.pop("pasa").map({True: "✓ Pasa", False: "✗ Falla"})
st.dataframe(tabla[["Conjunto", "Prueba", "Resultado", "Detalle"]], hide_index=True, height=620)

st.caption("Archivos leídos: " + ", ".join(Path(p).name for p in carga.RUTAS.values()))
