import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import comun

d = comun.cargar_o_detener()
tramos, contorno, est_df, (lat0, lon0) = comun.capas_base()

st.markdown("<div class='titular' style='font-size:2rem'>Red vial de Chapinero</div>",
            unsafe_allow_html=True)
st.markdown("<p class='bajada'>Haga clic en cualquier tramo para ver su pendiente. "
            "Arrastre con clic derecho para inclinar el mapa.</p>", unsafe_allow_html=True)

# --- controles en una fila --------------------------------------------------
a, b, c, e = st.columns([2.2, 1.6, 1.6, 1.4])
area = a.segmented_control("Área", ["Chapinero", "Con anillo de 500 m"], default="Chapinero")
ver_no_conf = b.toggle("Tramos sin pendiente confiable", value=False)
ver_est = c.toggle("Estaciones de carga", value=True)
vista_3d = e.toggle("Vista inclinada", value=True)
rango = st.slider("Mostrar pendientes entre (%)", 0, 60, (0, 60), label_visibility="collapsed")

vista = tramos if area == "Con anillo de 500 m" else tramos[tramos["en_sector"]]
if not ver_no_conf:
    vista = vista[vista["confiable"]]
vista = vista[(vista["abs_pct"].fillna(0) >= rango[0]) &
              ((vista["abs_pct"].fillna(0) <= rango[1]) | (rango[1] == 60))]

mapa, panel = st.columns([3, 1.15], gap="medium")

with mapa:
    capas = [
        pdk.Layer("PathLayer", id="tramos", data=vista, get_path="path", get_color="color",
                  width_min_pixels=2, width_max_pixels=6, get_width=4, cap_rounded=True,
                  joint_rounded=True, pickable=True, auto_highlight=True,
                  highlight_color=[255, 255, 255, 200]),
        pdk.Layer("PathLayer", data=contorno, get_path="path",
                  get_color=[230, 237, 241, 110], width_min_pixels=1.2),
    ]
    if ver_est:
        est = est_df[(est_df["ciudad"] == "Bogota")]
        if area == "Chapinero":
            est = est[est["en_chapinero"]]
        capas += [
            pdk.Layer("ScatterplotLayer", data=est, get_position=["lon", "lat"],
                      get_fill_color=comun.hex_rgb(comun.ACENTO) + [60], radius_min_pixels=13),
            pdk.Layer("ScatterplotLayer", id="estaciones", data=est, get_position=["lon", "lat"],
                      get_fill_color=comun.hex_rgb(comun.ACENTO), get_line_color=[20, 33, 43],
                      stroked=True, line_width_min_pixels=2, radius_min_pixels=5, pickable=True),
        ]
    tooltip = {"html": "<b>{via}</b><br/>{pend_txt}",
               "style": {"backgroundColor": comun.SUPERFICIE, "color": comun.TEXTO,
                         "fontFamily": "Figtree", "fontSize": "13px", "borderRadius": "6px"}}
    evento = st.pydeck_chart(
        comun.deck(capas, lat0, lon0, zoom=13.4, pitch=45 if vista_3d else 0, tooltip=tooltip),
        height=640, on_select="rerun", selection_mode="single-object", key="mapa_red")
    st.markdown(comun.leyenda_pendiente(), unsafe_allow_html=True)

# --- panel lateral ----------------------------------------------------------
seleccion = {}
try:
    seleccion = evento.selection.get("objects", {}) or {}
except AttributeError:
    pass

with panel:
    tramo = (seleccion.get("tramos") or [None])[0]
    estacion = (seleccion.get("estaciones") or [None])[0]

    if tramo:
        signo = "Sube" if tramo["pct"] > 0 else "Baja" if tramo["pct"] < 0 else "Plano"
        desnivel = abs(tramo["pct"]) / 100 * tramo["longitud_m"]
        st.markdown(f"""<div class='panel'><h4>{tramo['via']}</h4>
            <div style='font-size:2.2rem;font-weight:700;line-height:1'>{tramo['pend_txt']}</div>
            <div style='color:{comun.TENUE};margin-bottom:.7rem'>{signo} en el sentido de circulación</div>
            <div class='fila'><span>Longitud</span><span>{tramo['longitud_m']:.0f} m</span></div>
            <div class='fila'><span>Desnivel</span><span>{desnivel:.1f} m</span></div>
            <div class='fila'><span>Tipo de vía</span><span>{tramo['tipo']}</span></div>
            <div class='fila'><span>Pendiente confiable</span><span>{'Sí' if tramo['confiable'] else 'No, tramo corto'}</span></div>
            <div class='fila'><span>Identificador</span><span>{tramo['segmento_id']}</span></div>
            </div>""", unsafe_allow_html=True)
    elif estacion:
        st.markdown(f"""<div class='panel'><h4>{estacion['nombre']}</h4>
            <div class='fila'><span>Categoría</span><span>{estacion['categoria']}</span></div>
            <div class='fila'><span>Posición tomada de</span><span>{estacion.get('fuente_posicion', '')}</span></div>
            </div>""", unsafe_allow_html=True)
    else:
        sel = vista[vista["confiable"]]
        st.markdown(f"""<div class='panel'><h4>En esta vista</h4>
            <div class='fila'><span>Tramos</span><span>{len(vista):,}</span></div>
            <div class='fila'><span>Con pendiente confiable</span><span>{len(sel):,}</span></div>
            <div class='fila'><span>Mediana</span><span>{sel['abs_pct'].median():.1f} %</span></div>
            <div class='fila'><span>Más empinado</span><span>{sel['abs_pct'].max():.1f} %</span></div>
            <div class='fila'><span>Por encima del 25 %</span><span>{int((sel['abs_pct'] > 25).sum())}</span></div>
            </div>""".replace(",", "."), unsafe_allow_html=True)

    st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
    sel = vista[vista["confiable"]].copy()
    if len(sel):
        cortes = [0, 3, 8, 15, 25, 1000]
        nombres = ["0–3 %", "3–8 %", "8–15 %", "15–25 %", "+25 %"]
        sel["clase"] = pd.cut(sel["abs_pct"], cortes, labels=nombres, right=False)
        conteo = sel["clase"].value_counts().reindex(nombres).reset_index()
        conteo.columns = ["clase", "tramos"]
        colores = [f"rgb{c}" for _, c in comun.RAMPA]
        grafico = (alt.Chart(conteo)
                   .mark_bar(cornerRadiusEnd=3, height=16)
                   .encode(y=alt.Y("clase:N", sort=nombres, title=None),
                           x=alt.X("tramos:Q", title=None, axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)),
                           color=alt.Color("clase:N", scale=alt.Scale(domain=nombres, range=colores), legend=None),
                           tooltip=["clase", "tramos"])
                   .properties(height=170, background="transparent")
                   .configure_view(strokeWidth=0)
                   .configure_axis(labelColor=comun.TENUE, labelFont="Figtree"))
        st.altair_chart(grafico)
        st.caption("Distribución de tramos confiables por pendiente.")

if (vista["abs_pct"] > 25).any():
    st.caption("Los tramos por encima del 25 % no se ocultan: pueden ser calles reales de ladera "
               "o errores de geometría. Su revisión está pendiente.")
