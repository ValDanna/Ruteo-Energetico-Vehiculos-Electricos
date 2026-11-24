# Módulo de terreno y pendiente

Este módulo calcula la pendiente de cada segmento de la red vial de Bogotá y de Medellín a partir de los modelos digitales de terreno LiDAR de cada ciudad. Cada pendiente se entrega con su error. El archivo resultante lo usa el módulo del grafo para construir la red y rutear, y el módulo de consumo para calcular la energía de cada tramo.

Para cada segmento dirigido se calculan:

- la pendiente neta, entre los extremos del segmento
- la pendiente acumulada, a partir de las subidas y bajadas del perfil
- el error de la pendiente y si se distingue de cero
- la clase de terreno INVIAS
- la marca de pendiente extrema (más de 35 %)

La pendiente no se calcula por celda del raster, sino con las alturas muestreadas a lo largo del segmento y en el sentido del recorrido.

## Estructura

```
modulo_terreno_pendiente/
├── bogota/
│   ├── bogota_eda.ipynb                 análisis exploratorio que respalda el documento
│   └── Codigo/
│       ├── bogota_pendientes_config.py  parámetros del programa principal
│       ├── bogota_pendientes_mdt2020.py programa principal
│       ├── LEEME.txt                    instrucciones de ejecución paso a paso
│       ├── requirements.txt
│       └── auxiliares/                  validaciones y análisis complementarios
└── medellin/
    ├── medellin_eda_respaldo_documento.ipynb   
    └── Codigo/
        ├── medellin_pendientes_config.py
        ├── medellin_pendientes_dtm2021.py
        ├── LEEME.txt
        ├── requirements.txt
        └── Auxiliares/
```

## Cómo se ejecuta

Cada ciudad se corre por separado y tiene su propio LEEME.txt con los pasos completos. En resumen:

1. Instalar el entorno: `pip install -r requirements.txt`
2. Copiar en `datos_entrada` los archivos que entrega el módulo del grafo (segmentos y huellas) y los vértices del IGAC.
3. Correr el programa principal (`python bogota_pendientes_mdt2020.py` o `python medellin_pendientes_dtm2021.py`).
4. Correr los auxiliares después del principal, desde la carpeta `Codigo`: `python auxiliares/<nombre>.py`.

El programa principal escribe una bitácora con cada etapa. Si algo falla, no escribe salidas parciales.

## Parámetros adoptados

| | Bogotá | Medellín |
|---|---|---|
| Modelo de terreno | MDT 2020, zona urbana, 0,5 m (IDECA/UAECD) | DTM-LiDAR 2021, 1 m (Subsecretaría de Catastro) |
| Sistema de coordenadas del modelo | EPSG:9377 | EPSG:6257 |
| Error vertical σz | 0,536 m (496 vértices del IGAC) | 0,539 m (9 vértices del IGAC) |
| Ancho de correlación del error | 53,6 m | 59,2 m |
| Umbral de pendiente extrema | 35 % | 35 % |

En Medellín, el 0,10 m que declara la ficha del modelo se conserva como sensibilidad.

## Salidas oficiales

| Archivo | Ciudad | SHA256 |
|---|---|---|
| bogota_pendientes_segmentos_mdt2020_v1_1.csv | Bogotá | 445009d19b07c61d7e0e789c5ab0adf3a56a794dec8640baf54e61c4ea560c4b |
| medellin_pendientes_segmentos_dtm2021_v3.csv | Medellín | 2aaba7230df0845116775e5100d3bc9292f67c4041a33aed1082d28d69f68e5e |
| ascenso_linea_recta_bogota.csv | Bogotá | 37c82cf6aa068bfae0df6afc9b2b41c1a0dcf928ccc7981db9fa385f8f98ba35 |
| ascenso_linea_recta_medellin.csv | Medellín | 3ce2a9822cd66a276762ac224216c97b78976dcfc364d0085c17a20f660c225b |
| revision_52_extremas_bogota.csv | Bogotá | 7a451b1bdbf0217a97e887eb683cb022e1b603c0a6ce7019f30ed04a4b9973a4 |
| revision_104_medellin_completada.csv | Medellín | f10b110c78652820f08e4d0f9e7914795ac8580c45bdbad275a4ddf4dd42d59e |
| sigma_por_terreno_segmentos.csv | Bogotá | 5eabaf693a2f1ac96440e700fa667d971dc605a4e78109e36ff7b74c1d99af82 |
| sigma_por_terreno_resumen.csv | Bogotá | 8e3d0875ad2cbb4c8a8010207b4c9035321b2bcf310f271ca8c5f7e56fea5eee |
| copernicus_dem_N04_00_W075_00.tif (insumo) | Bogotá | 01434300ecd2be4a226fb863b9a88df15e01e42c07ba02bf8aed2125049d1da8 |

Con estas huellas se comprueba que un archivo es el mismo que usaron el ruteo y el documento.

## Auxiliares de Bogotá

| Script | Qué hace |
|---|---|
| _comun.py | Funciones compartidas por los auxiliares |
| aux_alineacion_consulta.py | Comprueba que las alturas consultadas al servicio coinciden con la posición del punto (prueba de alineación) |
| aux_ascenso_linea_recta.py | Ascenso acumulado por km en línea recta de origen a destino para los viajes del ruteo, con su piso de ruido |
| aux_comparacion_30m.py | Compara la pendiente con modelos globales de 30 m |
| aux_comparar_versiones.py | Compara dos versiones del archivo de pendientes columna por columna |
| aux_conteo_localidades.py | Conteos de segmentos y clases de terreno por localidad |
| aux_exactitud_ampliada.py | Valida el MDT contra los vértices del IGAC con coordenada calculada, da σz por etapa y por tipo de terreno |
| aux_investigar_atipicos.py | Revisa los vértices con diferencias grandes frente al MDT |
| aux_mapa_extremas.py | Mapa de los segmentos con pendiente extrema |
| aux_mdt2025_vs_igac.py | Compara el MDT 2025 contra los vértices del IGAC |
| aux_muestra_extremas_35_50.py | Muestra al azar de 50 tramos entre 35 y 50 % para revisar a mano; con `--resumen` da los porcentajes con su intervalo |
| aux_prueba_pasos.py | Prueba el efecto del paso de muestreo sobre la pendiente |
| aux_puentes_tuneles_osm.py | Cruza la Malla Vial con puentes y túneles de OpenStreetMap |
| aux_referencia_vertical_geoide.py | Compara el sesgo del MDT con la ondulación del geoide para establecer si las alturas son ortométricas |
| aux_regla_puentes_castigo.py | Cuenta los tramos extremos sobre puente o túnel que dejan de castigarse cuando solo se castiga la neta mayor de 35 % |
| aux_resolucion_2020_2025_srtm.py | Pendiente de los mismos segmentos con MDT 2020, MDT 2025, SRTM y Copernicus GLO-30 |
| aux_revision_visual_extremas.py | La revisión en Street View de los tramos más empinados |
| aux_sigma_por_terreno.py | Rama de sensibilidad con un σz por tipo de terreno; no cambia el archivo oficial |
| aux_verificar_contrato.py | Verifica que el archivo de salida cumpla las columnas y reglas acordadas con el módulo del grafo |

## Auxiliares de Medellín

| Script | Qué hace |
|---|---|
| _comun.py | Funciones compartidas por los auxiliares |
| aux_alineacion_mdt.py | Comprueba la alineación entre la red y el modelo de terreno |
| aux_ancho_correlacion.py | Calcula el ancho de correlación espacial del error (59,2 m) |
| aux_ascenso_linea_recta_medellin.py | Ascenso acumulado por km en línea recta de origen a destino para los viajes del ruteo |
| aux_comparacion_30m.py | Compara la pendiente con modelos globales de 30 m en dos sectores (antecedente) |
| aux_comparar_versiones.py | Compara dos versiones del archivo de pendientes |
| aux_crs_mdt.py | Verifica el sistema de coordenadas del modelo (EPSG:6257) |
| aux_paso_muestreo.py | Prueba el efecto del paso de 50 m en los tramos planos |
| aux_pendientes_extremas.py | Analiza los segmentos con pendiente extrema |
| aux_resolucion_srtm.py | Compara la pendiente con SRTM y Copernicus en una muestra de toda la red |
| aux_revision_street_view.py | Prepara la revisión en Street View de las 104 calles (extremas y con paso_nivel = 2) y resume el resultado |
| aux_sigma_por_terreno.py | Calcula el error de los vértices según el tipo de terreno (solo descriptivo) |
| aux_tuneles.py | Lista los túneles y revisa su pendiente de boca a boca |
| aux_verificar_contrato.py | Verifica que el archivo de salida cumpla lo acordado con el módulo del grafo |
| aux_vertices_igac.py | Compara el modelo con los vértices del IGAC en Medellín y da el σz (0,539 m) |


## Datos y licencias

Los datos no están en este repositorio, solo el código. Los modelos de terreno se consultan en los servicios de cada ciudad, y los archivos de resultados se identifican por su huella SHA256.

- Bogotá: MDT 2020 de IDECA/UAECD, CC BY-NC-SA 4.0. Todo dato derivado (pendientes, alturas, rutas) hereda esa licencia: atribución, uso no comercial y misma licencia.
- Medellín: DTM-LiDAR 2021 de la Subsecretaría de Catastro, CC BY-SA 4.0.
- Malla Vial de Bogotá: IDECA, con atribución a las entidades que la producen.
- Copernicus GLO-30: European Space Agency y Airbus (2022), doi:10.5270/ESA-C5D3D65.
