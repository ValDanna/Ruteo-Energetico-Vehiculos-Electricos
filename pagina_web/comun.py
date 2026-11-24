"""
comun.py — Estilo visual y datos compartidos por todas las secciones.
Solo presentación: la carga y las verificaciones siguen en carga.py.
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import carga

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
FONDO = "#14212B"
SUPERFICIE = "#1C2D39"
TEXTO = "#E6EDF1"
TENUE = "#8FA3B0"
ACENTO = "#4FD1C5"
RUTA_CORTA = "#F2A65A"

MAPA_BASE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"

# Escala continua de |pendiente| en %: de plano (azul petróleo) a extremo (magenta).
RAMPA = [
    (0.0,  (43, 111, 143)),
    (3.0,  (86, 179, 164)),
    (8.0,  (242, 209, 107)),
    (15.0, (238, 138, 60)),
    (25.0, (214, 51, 108)),
]
COLOR_NO_CONFIABLE = (95, 110, 120)


def color_pendiente(pct: np.ndarray) -> np.ndarray:
    x = np.clip(np.nan_to_num(np.abs(pct), nan=0.0), 0, RAMPA[-1][0])
    stops = np.array([s for s, _ in RAMPA])
    cols = np.array([c for _, c in RAMPA], dtype=float)
    return np.stack([np.interp(x, stops, cols[:, i]) for i in range(3)], axis=1).astype(int)


def hex_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def gradiente_css():
    paradas = ", ".join(f"rgb{c} {100 * s / RAMPA[-1][0]:.0f}%" for s, c in RAMPA)
    return f"linear-gradient(90deg, {paradas})"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
def aplicar_estilo():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&display=swap');
    html, body, [class*="css"], .stMarkdown, .stText, button, input, label {{
        font-family: 'Figtree', system-ui, sans-serif !important;
    }}
    .block-container {{ padding-top: 4.2rem; max-width: 1280px; }}
    #MainMenu, footer, [data-testid="stSidebar"], [data-testid="collapsedControl"] {{ display: none; }}
    h1, h2, h3 {{ letter-spacing: -0.01em; }}

    .titular {{ font-size: 2.6rem; line-height: 1.1; font-weight: 700; margin: 0.2rem 0 0.6rem; max-width: 22ch; }}
    .bajada {{ color: {TENUE}; font-size: 1.08rem; max-width: 62ch; line-height: 1.55; }}

    .cifra {{ padding: 0.9rem 0 0.9rem 1rem; border-left: 2px solid {ACENTO}; }}
    .cifra .n {{ font-size: 2rem; font-weight: 700; line-height: 1; }}
    .cifra .t {{ color: {TENUE}; font-size: 0.9rem; margin-top: 0.35rem; }}
    .cifra.tenue {{ border-left-color: #3A4D5A; }}

    .panel {{ background: {SUPERFICIE}; border-radius: 10px; padding: 1.1rem 1.2rem; }}
    .panel h4 {{ margin: 0 0 0.6rem; font-size: 1rem; font-weight: 600; }}
    .fila {{ display: flex; justify-content: space-between; padding: 0.35rem 0;
             border-bottom: 1px solid #263A47; font-size: 0.93rem; }}
    .fila span:first-child {{ color: {TENUE}; }}
    .fila:last-child {{ border-bottom: none; }}

    .rampa {{ height: 8px; border-radius: 4px; background: {gradiente_css()}; margin: 0.4rem 0 0.25rem; }}
    .rampa-et {{ display: flex; justify-content: space-between; color: {TENUE}; font-size: 0.78rem; }}

    .aviso-sint {{ background: rgba(214, 51, 108, 0.14); border: 1px solid rgba(214, 51, 108, 0.55);
                   color: #F4C3D3; border-radius: 8px; padding: 0.6rem 0.9rem; font-size: 0.92rem;
                   margin-bottom: 1rem; }}
    .fase {{ padding: 0.8rem 0; border-top: 1px solid #263A47; }}
    .fase b {{ font-weight: 600; }}
    .fase .e {{ float: right; font-size: 0.85rem; color: {TENUE}; }}
    .fase .e.ok {{ color: {ACENTO}; }}
    </style>
    """, unsafe_allow_html=True)


def cifra(numero, texto, tenue=False):
    return f"<div class='cifra{' tenue' if tenue else ''}'><div class='n'>{numero}</div><div class='t'>{texto}</div></div>"


def leyenda_pendiente():
    return ("<div class='rampa'></div><div class='rampa-et'>"
            "<span>0 %</span><span>3</span><span>8</span><span>15</span><span>25 % o más</span></div>")


def aviso_sintetico(texto):
    st.markdown(f"<div class='aviso-sint'>🧪 <b>Datos sintéticos, no son resultados.</b> {texto}</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Datos (una sola carga verificada por sesión)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Cargando y verificando datos…")
def datos():
    estaciones, p_est = carga.cargar_estaciones()
    segmentos, grafo, p_graf = carga.cargar_grafo()
    p_lim = carga.verificar_huella(carga.RUTAS["d1_limite"], carga.RUTAS["d1_huellas"])
    if not p_lim["pasa"]:
        raise carga.ErrorCarga(f"{p_lim['prueba']}: {p_lim['detalle']}")
    limite = gpd.read_file(carga.RUTAS["d1_limite"], layer="limite")
    return {"estaciones": estaciones, "segmentos": segmentos.reset_index(drop=True),
            "grafo": grafo, "limite": limite, "pruebas_est": p_est,
            "pruebas_grafo": p_graf + [p_lim]}


@st.cache_resource(show_spinner=False)
def capas_base():
    d = datos()
    seg = d["segmentos"]
    geo = seg.to_crs(carga.CRS_GEOGRAFICO)

    def coords(g):
        partes = g.geoms if g.geom_type == "MultiLineString" else [g]
        return [[round(x, 6), round(y, 6)] for p in partes for x, y in p.coords]

    pct = seg["pendiente_neta"].to_numpy() * 100
    col = color_pendiente(pct)
    no_conf = ~seg["pendiente_confiable"].to_numpy() | np.isnan(pct)
    col[no_conf] = COLOR_NO_CONFIABLE

    nombre = seg["name"] if "name" in seg.columns else pd.Series("", index=seg.index)
    tramos = pd.DataFrame({
        "segmento_id": seg["segmento_id"],
        "path": [coords(g) for g in geo.geometry],
        "color": [list(c) + [235] for c in col],
        "pct": pct,
        "abs_pct": np.abs(pct),
        "confiable": ~no_conf,
        "en_sector": seg["en_sector"].to_numpy(),
        "longitud_m": seg["longitud_m"].round(1),
        "via": nombre.fillna("Sin nombre").astype(str),
        "tipo": seg["highway"].astype(str) if "highway" in seg.columns else "",
        "pend_txt": ["sin dato" if np.isnan(p) else f"{p:+.1f} %" for p in pct],
    })

    lim = d["limite"].to_crs(carga.CRS_GEOGRAFICO)
    poligono = lim.geometry.union_all()
    contorno = [{"path": [list(c) for c in g.exterior.coords]}
                for g in lim.explode(index_parts=False).geometry]

    est = d["estaciones"]
    est = est[~est["es_secundario"]].copy()
    est["en_chapinero"] = est.geometry.within(poligono)
    est_df = pd.DataFrame(est.drop(columns="geometry"))
    est_df["nombre"] = est_df["nombre_osm"].fillna(est_df["nombre_ocm"]).fillna("Estación sin nombre")
    est_df["via"] = est_df["nombre"]
    est_df["pend_txt"] = est_df["categoria"]

    c = poligono.centroid
    return tramos, contorno, est_df, (c.y, c.x)


def deck(capas, lat, lon, zoom=13.2, pitch=0, tooltip=None):
    return pdk.Deck(
        layers=capas, map_provider="carto", map_style=MAPA_BASE,
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom,
                                         pitch=pitch, bearing=-12 if pitch else 0),
        tooltip=tooltip or False,
    )


def cargar_o_detener():
    try:
        return datos()
    except carga.ErrorCarga as e:
        st.error("La página no muestra datos porque una verificación falló.")
        st.code(str(e))
        st.stop()
