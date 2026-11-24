# Módulo de inventario de estaciones de carga

Este módulo arma el inventario de estaciones de carga de Bogotá y Medellín a partir de dos fuentes abiertas, OpenStreetMap (OSM) y OpenChargeMap (OCM). Cruza las dos fuentes para saber cuáles registros son la misma estación y mide qué datos de cada estación sirven para rutear. El módulo del grafo usa este inventario para ubicar las estaciones en la red y medir la accesibilidad.

Se hace en dos bloques:

- **Bloque A**: descarga cada fuente con una fecha de corte (29 de agosto de 2026), la congela con su huella SHA256 y la recorta con el límite municipal del IGAC.
- **Bloque B**: cruza las dos fuentes, verifica los casos dudosos contra las manzanas de Catastro, compara el cruce por distancia con un puntaje que suma distancia y nombre, y mide qué tan completos están los datos.

Resultado: 71 estaciones físicas, 52 en Bogotá y 19 en Medellín.

## Estructura

```
modulo_inventario_estaciones/
├── Bloque A/
│   ├── constantes.py              convenciones compartidas (fecha de corte, límites, umbrales, rutas)
│   ├── requirements.txt
│   ├── LEEME.txt                  instrucciones de ejecución paso a paso
│   ├── Entregable A2/A2.ipynb     descarga de OSM (Overpass) por ciudad
│   ├── Entregable A3/A3.ipynb     descarga de OCM (Colombia) y recorte por ciudad
│   └── Entregable A4/A4.ipynb     contraste en un solo sentido, OCM contra OSM (queda como registro)
└── Bloque B/
    ├── Entregable B1/B1.ipynb     cruce en los dos sentidos y deduplicación
    ├── Entregable B2/B2.ipynb     verificación de casos dudosos con las manzanas de Catastro
    ├── Entregable B2.1/B2.1.ipynb aplica los veredictos de B2: inventario verificado
    ├── Entregable B3/B3.ipynb     puntaje combinado (distancia, nombre, operador) y umbral
    ├── Entregable B3.1/B3_1.ipynb contraste del puntaje con la evidencia catastral
    └── Entregable B4/B4.ipynb     completitud y concordancia de los atributos para rutear
```

Los nombres de las carpetas (`Bloque A`, `Entregable A2`…) se conservan porque los cuadernos los usan para encontrar `constantes.py` y las salidas de los bloques anteriores.

## Cómo se ejecuta

El orden es A2 → A3 → B1 → B2 → B2.1 → B3 → B3.1 → B4. A4 no lo usa ningún paso posterior. El LEEME.txt tiene los pasos completos. En resumen:

1. Instalar el entorno: `pip install -r "Bloque A/requirements.txt"`
2. Poner en `Bloque A` el límite municipal del IGAC (`Municipios_Junio_2026.gpkg`).
3. Poner en cada entregable el crudo congelado de su fuente: los de A2 y A3 y, para B2, las manzanas de Catastro. Si están, los cuadernos no se conectan a internet.
4. Correr cada cuaderno de arriba abajo, en el orden de arriba.

Cada cuaderno abre comprobando la huella SHA256 de lo que lee, encadenada hasta los crudos congelados, y escribe su propio manifiesto. Si un insumo cambió, falla en vez de dar otro resultado sin avisar.

## Parámetros adoptados

| | Valor |
|---|---|
| Fecha de corte | 2026-08-29 (OSM con consulta histórica; OCM descargado el 2026-09-02 y verificado contra el corte) |
| Límite de cada ciudad | IGAC, capa nacional de municipios (DANE 11001 y 05001) |
| Sistema de coordenadas para distancias | EPSG:9377 |
| Coincidencia confirmada | hasta 25 m |
| Coincidencia posible | hasta 100 m (escala de manzana medida en B2: mediana del lado largo 101,7 m) |
| Umbral del puntaje combinado (B3) | 0,50 (60 % distancia, 40 % nombre) |
| Estaciones | 71 físicas: Bogotá 52, Medellín 19 |

## Salidas oficiales

| Archivo | SHA256 |
|---|---|
| A2_osm_crudo_Bogota_2026-08-29.json (crudo) | 883195e669b34f105e3a75ec31eddccd9124bcd73b6871384636ff172a9b1724 |
| A2_osm_crudo_Medellin_2026-08-29.json (crudo) | 109443ae81cdfbc7b69f6889a19026ea0f13ea6c1829e75a8830a95fc4989d1c |
| A3_ocm_crudo_Colombia_estado-al-2026-08-29_bajado-2026-09-02.json (crudo) | c281a19abe3fdc10a8910d18ce420517e4bdd23b50f14b3973c5587230a209db |
| manz.shp.07.26.zip (manzanas de Catastro, crudo de B2) | 04be5ad368d471cdfc40093306c709c962ea0fd90d4e0a61a150aa0c24f5b6d3 |
| A2_estaciones_OSM_Bogota.geojson | 99f132a15e2a87e96f2e6f2482ff7756928b5ddcafbe233e6366ebf71cfe83f9 |
| A2_estaciones_OSM_Medellin.geojson | 69a8c0bafbf86fce86b81eb4c1b13dc37af2927a61bf00f1148c9b1a8d1cb54c |
| A3_OpenChargeMap_Bogota_estaciones.csv | cb12e624d5aa1856b3c2422ac9f67908365d0409ac89721553841702ddc80172 |
| A3_OpenChargeMap_Medellin_estaciones.csv | 02767749ab5e1857c41d27485bd1841824cb3e280a2d6910113f90218c68fcad |
| B1_fusiones_internas.csv | e8544de7dff500aa3864cbf6e3962b8456ec4aba0c43ee10fd44699ebd3a2c10 |
| B2_1_clasificacion_verificada.csv | b0a2e926cf09b73c3273bc0b10e35ed5ee9d2b9f7f2798607d4780fde6253337 |
| B3_pares_puntaje_combinado.csv | 6c288bede04300c068adf9b4a8c4498da1c0632cda83e0b8d780026ed107e470 |
| B4_inventario_atributos_ruteo.csv | d2032c3f5899d5e49fcca4771a468199404377ccf201b7221fca1f915772625d |

El módulo del grafo lee `B2_1_clasificacion_verificada.csv`, `B1_fusiones_internas.csv` y las estaciones de A2 y A3, y comprueba sus huellas contra `B3_manifiesto_insumos.json`.

## Datos y licencias

Los datos no están en este repositorio, solo el código. Los archivos se identifican por su huella SHA256.

- OpenStreetMap: © colaboradores de OpenStreetMap, ODbL 1.0.
- OpenChargeMap: datos de openchargemap.org, con atribución a OCM y a los proveedores de cada registro.
- Manzanas de Bogotá: UAECD / IDECA, CC BY 4.0.
- Límites municipales: IGAC, capa nacional de municipios.

La llave de la API de OCM no está en el código: A3 la lee de la variable de entorno `OCM_API_KEY`, y solo hace falta si no existe el crudo congelado.
