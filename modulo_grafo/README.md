# Módulo del grafo y ruteo

Este módulo arma la red vial dirigida de Bogotá y de Medellín y se la entrega al módulo de terreno, que calcula la pendiente de cada segmento. Después une esas pendientes con la red, les pone el consumo que da el módulo de consumo y compara, para una muestra de viajes, la ruta más corta contra la ruta de mínimo consumo. También mide cuánta batería hace falta para llegar a una estación de carga desde cada esquina.

Se trabaja en tres pasos por ciudad:

- **D2**: red dirigida de toda la ciudad, partida en segmentos con un identificador estable. Es el archivo de segmentos y huellas que recibe el módulo de terreno.
- **D3**: recibe el archivo de pendientes del módulo de terreno, revisa que cumpla lo acordado y lo une a la red.
- **D4**: deja la red lista para rutear y calcula las rutas, el consumo de cada viaje y la accesibilidad a las estaciones de carga.

D1 fue la prueba del método en Chapinero y no hace parte de los resultados.

El identificador de cada segmento es `<código de la vía>_<parte>_<FT|TF>`. Cada segmento va en un solo sentido, y la pendiente es positiva cuando sube en ese sentido. Es la misma convención del módulo de terreno.

## Estructura

```
modulo_grafo/
├── README.md
├── bogota/
│   └── Codigo/
│       ├── constantes_d1.py           parámetros de las dos ciudades (rutas, fuentes, decisiones)
│       ├── d1_procedencia.py          huellas de archivos y de segmentos
│       ├── d1_malla.py                descarga y congela la Malla Vial
│       ├── d1_grafo.py, d1_red.py, d1_bogota.py   funciones para armar la red
│       ├── D2_grafo_bogota.ipynb      red dirigida y archivo para el módulo de terreno
│       ├── D3_union_pendiente.ipynb   revisa y une las pendientes
│       ├── D4_grafo_ruteo.ipynb       ruteo, consumo y accesibilidad
│       ├── LEEME.txt                  instrucciones de ejecución paso a paso
│       └── requirements.txt
└── medellin/
    └── Codigo/
        ├── d2_medellin.py
        ├── D2_grafo_medellin.ipynb
        ├── D3_union_pendiente_medellin.ipynb
        ├── D4_ruteo_medellin.ipynb
        ├── LEEME.txt
        └── requirements.txt
```

Los cuadernos de Medellín usan el mismo `constantes_d1.py` y el mismo `d1_procedencia.py` de Bogotá, porque el método es el mismo y solo cambia lo propio de cada ciudad. Para correrlos, todo va en una sola carpeta de trabajo, como explica el LEEME.txt.

## Cómo se ejecuta

Cada ciudad se corre por separado, en orden D2 → D3 → D4. El LEEME.txt de cada carpeta tiene los pasos completos. En resumen:

1. Instalar el entorno: `pip install -r requirements.txt`
2. Correr D2. Si la red ya está congelada en `datos_crudos`, la lee de ahí y no se conecta a internet.
3. Copiar en `datos_crudos/recibidos/` el archivo de pendientes del módulo de terreno, tal como llega.
4. Correr D3. Si el archivo no cumple lo acordado, el cuaderno se detiene y no une nada.
5. Poner la carpeta del modelo de consumo (`modelo_consumo/`, y `modelo_consumo_v2/` para Medellín) junto a `constantes_d1.py` y correr D4.

Cada cuaderno revisa al empezar las huellas SHA256 de todo lo que lee: si un insumo cambió, falla en vez de dar otro resultado sin avisar. Ningún cuaderno sobrescribe un resultado que ya existe; si lo encuentra, comprueba que sea idéntico. Cada corrida escribe una bitácora, y la última celda de D4 deja la versión oficial con sus huellas.

## Parámetros adoptados

| | Bogotá | Medellín |
|---|---|---|
| Red vial | Malla Vial de Catastro, versión 2024 | Capa «Sentido vial» de la Secretaría de Movilidad, depurada con OpenStreetMap |
| Fecha de corte de la red | 2026-09-19 | 2026-09-21 |
| Límite de la ciudad | IGAC, código DANE 11001 | IGAC, código DANE 05001 |
| Sistema de coordenadas de la red | EPSG:9377 | EPSG:9377 |
| Unión de esquinas cercanas | 2 m | 2 m |
| Segmentos dirigidos | 225.704 | 39.160 |
| Esquinas | 94.795 | 16.396 |
| Pendientes usadas (módulo de terreno) | σz 0,536 m | σz 0,539 m |
| Estaciones de carga | 52 | 18 |
| Muestra de viajes | 5.250 (3 terrenos × 5 distancias × 350) | 4.200 (3 terrenos × 4 distancias × 350) |
| Semilla de la muestra | 20261026 | 20261026 |
| Castigo a tramos de más de 35 % | k = 50 | k = 50 (la regla da k = 1, que queda como sensibilidad) |

Las demás decisiones son las mismas en las dos ciudades:

- No se quita ninguna calle.
- Las calles sin sentido definido se toman de doble sentido.
- A las esquinas sin altura se les estima la altura con el promedio de las esquinas vecinas.
- La pendiente se toma de esquina a esquina y la longitud es la inclinada.
- Un tramo de más de 35 % que va sobre un puente o un túnel solo se castiga si su pendiente neta también pasa de 35 %.

En Medellín, además, se quitaron 873 tramos que OpenStreetMap marca como escaleras, senderos o peatonales.

La comparación principal es entre la ruta más corta y la **ruta de mínimo consumo** (k = 0). La **ruta de mínimo consumo con restricción de pendiente** usa k = 50. Bloquear los tramos de más de 35 % y el factor pesimista de × 1,40 quedan como sensibilidad.

## Salidas oficiales

| Archivo | Ciudad | SHA256 |
|---|---|---|
| D2_segmentos_para_pendiente.gpkg (huella de segmentos) | Bogotá | dcf865850e8c15196ce7f85306fde17cb16a786f91763b26d8abcd919e4d95c1 |
| Malla Vial congelada (huella del conjunto) | Bogotá | 3d8963916697159423856913110c144661d42abdbc12c67398058dee6a8df75e |
| D2M_segmentos_para_pendiente.gpkg (huella de segmentos) | Medellín | 5baf0bc9b8d2ac59a29b21eafe4d36cd8c2803ce5e966d095fd2ca6db587a590 |
| Capa «Sentido vial» congelada (huella del conjunto) | Medellín | c9d53ebbdffe80e2de23167f82954e8015900c7d06fc5c308826ca043797358c |
| D3_grafo_con_pendiente_sigma0536_v1_1.csv | Bogotá | [completar] |
| D3M_grafo_con_pendiente_med_sigma054.csv | Medellín | [completar: 845158ec00ad…] |
| bitacora_ejecucion_D4_20261119_130812_cierre_192643.json | Bogotá | [completar: 043c671e0d3f…] |
| bitacora_ejecucion_D4M_20261120_092658_cierre_102743.json | Medellín | 59bfabe40322c83abc058461137bd6d9fc85e5c42e4fcebaf7d5f65e7621796f |
| D4_version_oficial.json | Bogotá | [completar] |
| D4M_version_oficial.json | Medellín | [completar] |
| D4_resumen_energia_ponderado_v2.csv | Bogotá | [completar] |
| D4M_resumen_energia_ponderado.csv | Medellín | [completar] |

Los GeoPackage se identifican por la huella de sus segmentos (identificador y geometría, ordenados) y no por el SHA256 del archivo, porque el GeoPackage guarda la hora en que se escribió y su SHA256 cambia en cada corrida aunque el contenido sea el mismo.

Con estas huellas se comprueba que un archivo es el mismo que usaron el ruteo y el documento. Las huellas de las pendientes y de las revisiones en Street View están en el README del módulo de terreno.

## Qué revisa cada cuaderno

Cada cuaderno tiene pruebas que pueden fallar y detienen la corrida.

- **D2**: identificadores únicos, sentidos FT/TF consistentes y lectura de vuelta del archivo exportado.
- **D3**: los identificadores coinciden en los dos sentidos, la pendiente neta y la acumulada cuadran con la longitud, el signo FT/TF es simétrico, la clase INVIAS se recalcula y el σz es el adoptado.
- **D4**: quitar calles nunca acorta una ruta y no hay ciclos que ganen energía. Las energías se comprueban por otro camino (networkx con Bellman-Ford puro), las corridas se reproducen idénticas y la versión oficial coincide con la corrida citada.

## Datos y licencias

Los datos no están en este repositorio, solo el código. Los archivos de resultados se identifican por su huella SHA256.

- Malla Vial de Bogotá: Catastro / IDECA, con atribución a SDM, IDU, UAECD y SDP.
- Red vial de Medellín: capa «Sentido vial» de la Secretaría de Movilidad de Medellín. [completar licencia]
- OpenStreetMap: © colaboradores de OpenStreetMap, ODbL 1.0.
- Límites municipales: IGAC, capa nacional de municipios.
- Las pendientes vienen del módulo de terreno y heredan su licencia, igual que todo lo que se calcula con ellas (alturas de esquina, energías y rutas): Bogotá CC BY-NC-SA 4.0 y Medellín CC BY-SA 4.0. Por eso los resultados de cada ciudad van en archivos separados.
