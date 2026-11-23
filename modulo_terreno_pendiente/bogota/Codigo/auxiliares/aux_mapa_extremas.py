"""
aux_mapa_extremas.py
Mapa interactivo (Leaflet) de los tramos fisicos con pendiente extrema,
uno por tramo, en su punto medio y coloreados por severidad (35-50 %,
50-75 %, > 75 %). Usa teselas de OpenStreetMap, con su atribucion.

Uso: python auxiliares/aux_mapa_extremas.py
Salida: datos_salida/auxiliares/mapa_pendientes_extremas_bogota.html
"""
import json

import geopandas as gpd
import pandas as pd

from _comun import C, CARPETA_AUX

df = pd.read_csv(C.ARCHIVO_PENDIENTES)
ext = df[df["pendiente_extrema"].astype(str).eq("True")].copy()
ext["tramo_fisico"] = ext["segmento_id"].str.rsplit("_", n=1).str[0]
ext["magnitud"] = ext[["pendiente_neta_pct", "pendiente_acumulada_pct"]].abs().max(axis=1)
unicos = ext.sort_values("magnitud", ascending=False).drop_duplicates("tramo_fisico")
seg = gpd.read_file(C.ARCHIVO_SEGMENTOS, layer=C.CAPA_SEGMENTOS).to_crs(C.CRS_CONSULTA)
unicos = unicos.merge(seg[["segmento_id", "localidad", "geometry"]], on="segmento_id")
puntos = []
for _, f in unicos.iterrows():
    p = f.geometry.interpolate(0.5, normalized=True)
    puntos.append({"lat": round(p.y, 6), "lon": round(p.x, 6), "p": round(float(f["magnitud"]), 1),
                   "loc": f["localidad"] or "", "id": f["segmento_id"]})

html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Pendientes extremas - Bogota</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>html,body,#m{height:100%;margin:0}#t{position:absolute;z-index:999;top:8px;left:50px;background:#fff;
padding:6px 10px;font:13px sans-serif;border-radius:4px}</style></head><body><div id="m"></div>
<div id="t">Tramos fisicos con pendiente &gt; 35 %: __N__. Rojo &gt; 75 %, naranja 50-75 %, amarillo 35-50 %.</div>
<script>
const P = __DATOS__;
const m = L.map('m').setView([4.60, -74.10], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution: '&copy; colaboradores de OpenStreetMap', maxZoom: 19}).addTo(m);
for (const q of P) {
  const c = q.p > 75 ? '#c0392b' : (q.p > 50 ? '#e67e22' : '#f1c40f');
  L.circleMarker([q.lat, q.lon], {radius: 4, color: c, fillOpacity: .8})
   .bindPopup(q.id + '<br>' + q.loc + '<br>' + q.p + ' %').addTo(m);
}
</script></body></html>"""
html = html.replace("__DATOS__", json.dumps(puntos, ensure_ascii=False)).replace("__N__", str(len(puntos)))
(CARPETA_AUX / "mapa_pendientes_extremas_bogota.html").write_text(html, encoding="utf-8")
print(f"{len(puntos)} tramos fisicos en el mapa")
