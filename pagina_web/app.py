"""
app.py — Entrada de la página. Ejecutar desde F:\\Tesis\\App:
    streamlit run app.py
"""

import streamlit as st

import comun

st.set_page_config(page_title="Ruteo energético en ladera", page_icon="⚡",
                   layout="wide", initial_sidebar_state="collapsed")
comun.aplicar_estilo()

paginas = [
    st.Page("secciones/inicio.py", title="Proyecto", default=True),
    st.Page("secciones/red_vial.py", title="Red vial"),
    st.Page("secciones/rutas.py", title="Rutas"),
    st.Page("secciones/verificacion.py", title="Verificación"),
]
st.navigation(paginas, position="top").run()
