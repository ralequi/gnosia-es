GNOSIA en Castellano
====================

Este directorio contiene el pipeline de extraccion, trabajo y reempaquetado del texto estructurado de GNOSIA.
El corpus editable vive en `Gnosia_Data/sharedassets0.assets`, dentro de 22 `MonoBehaviour` `Entity_*Text`.

Estado actual
-------------

- Se extraen 22 entidades, 197 `sheets`, 9.563 `params` y 28.689 strings localizados.
- El orden de idiomas detectado es fijo: `jp`, `en`, `zh`.
- Los bundles `help_*`, `pre_*`, `systm_*` y `title_*` no contienen strings editables; solo `Sprite` y `Texture2D`.
- El pipeline no-op sigue validado byte a byte contra el original.
- La primera tanda manual de traduccion vive en `work/` y sobreescribe la ranura `en`.
- Esta tanda cambia 4 entidades: `OthersText`, `ScreenText`, `ScenarioBaseText` y `ScenarioTutorialText`.
- Auditoria actual de la tanda manual: `hard_fail=0`, `review=1396`, `ok=712`.

Estructura
----------

- `extractor.py`
  Extrae el snapshot tecnico desde `sharedassets0.assets` a `out/`.
- `preparar_trabajo.py`
  Crea `work/` como copia versionada del snapshot exportado.
- `aplicar_fase1_manual.py`
  Aplica la tanda manual inicial de traduccion sobre `work/`.
- `auditar_traduccion.py`
  Compara `work/` contra `out/` y revisa longitud, placeholders y saltos de linea.
- `reconstructor.py`
  Reconstruye blobs binarios desde un manifest de trabajo.
- `reempacador.py`
  Reempaqueta una copia del asset con los blobs reconstruidos.
- `validar.py`
  Comprueba integridad estructural del pipeline.
- `GUIA_EDITORIAL.md`
  Criterio de estilo y de compresion.
- `glosario_v1.json`
  Glosario base de la fase inicial.

Directorios
-----------

- `out/`
  Snapshot tecnico generado desde el juego. No se edita a mano.
- `work/`
  Corpus versionado de trabajo. Aqui va la traduccion real.
- `tmp/`
  Artefactos de auditoria, reconstruccion y assets de prueba.

Preparacion
-----------

Los ejemplos siguientes asumen que estas dentro de `traductor_es/`.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Flujo recomendado
-----------------

1. Extraer snapshot tecnico desde el juego:

```bash
python extractor.py
```

2. Crear o refrescar el corpus versionado de trabajo:

```bash
python preparar_trabajo.py --force
```

3. Aplicar la tanda manual inicial ya preparada:

```bash
python aplicar_fase1_manual.py --force-init
```

4. Auditar longitud e integridad textual:

```bash
python auditar_traduccion.py --work-manifest work/manifest.json
```

5. Reconstruir blobs desde `work/`:

```bash
python reconstructor.py \
  --manifest work/manifest.json \
  --out-dir tmp/work_reconstructed
```

6. Reempaquetar el asset de prueba:

```bash
python reempacador.py \
  --manifest work/manifest.json \
  --replacements-manifest tmp/work_reconstructed/replacements.json \
  --output-asset tmp/sharedassets0.phase1_es.assets
```

7. Validar la build editada:

```bash
python validar.py \
  --mode edited \
  --manifest work/manifest.json \
  --replacements-manifest tmp/work_reconstructed/replacements.json \
  --repacked-asset tmp/sharedassets0.phase1_es.assets
```

Qué hace cada validacion
------------------------

- `validar.py`
  Comprueba estructura, blobs reconstruidos, reempaquetado e integridad general.
- `auditar_traduccion.py`
  Comprueba politica de longitud y preservacion de placeholders/saltos de linea.

El auditor clasifica por niveles:

- `Tier A`
  UI muy corta y microtextos sensibles.
- `Tier B`
  Pantallas y mensajes de sistema de longitud media.
- `Tier C`
  Texto mas largo, especialmente tutorial o dialogo.

Para la tanda actual, lo importante es mantener `hard_fail=0`.
Los elementos marcados como `review` son cola de refinado manual, no roturas estructurales.

Dónde traducir
--------------

La traduccion real siempre se hace en `work/entities/*.json`.

Reglas basicas:

- No cambies la estructura del JSON.
- No anadas ni elimines elementos en `texts`.
- La ranura sobreescrita es `texts[1]`.
- Conserva `{0}`, `{1}`, etc.
- Conserva `\n` y cualquier string puramente estructural.
- Usa `out/` solo como referencia tecnica/original.

Prueba dentro del juego
-----------------------

Para probar la build traducida dentro de GNOSIA, sustituye temporalmente el asset real solo despues de hacer copia de seguridad.

Desde la raiz del juego:

```bash
cp Gnosia_Data/sharedassets0.assets Gnosia_Data/sharedassets0.assets.bak
cp traductor_es/tmp/sharedassets0.phase1_es.assets Gnosia_Data/sharedassets0.assets
```

Lanza el juego y revisa, como minimo:

- pantalla de titulo
- carga/guardado
- menu principal
- labels cortas de sistema
- arranque del tutorial

Cuando termines, restaura el original:

```bash
mv Gnosia_Data/sharedassets0.assets.bak Gnosia_Data/sharedassets0.assets
```

Notas
-----

- La tanda actual es deliberadamente conservadora en longitud.
- No se ha usado una libreria de traduccion automatica para generar el castellano; la traduccion aplicada es manual/curada.
- `work/` es el corpus versionado. Si regeneras `out/`, vuelve a copiar a `work/` solo si quieres resetear la traduccion.
- `validar.py` puede pasar aunque aun queden muchos `review` en el auditor; eso significa que la build es estructuralmente valida, no que la fase editorial este terminada.
- El siguiente refinado natural es reducir la cola de `review`, empezando por `ScreenText` y luego por dialogo/tutorial largo.
