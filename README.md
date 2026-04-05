GNOSIA en castellano
====================

Proyecto de extracción, parcheo y reempaquetado del texto estructurado de GNOSIA para mantener una traducción **FAN** al castellano.
El workflow y buena parte de la curación editorial se han ido construyendo con ayuda de Codex, pero la traducción se revisa manualmente y el repo está pensado para usarse con una copia legalmente obtenida del juego.

English summary
---------------

This repository contains tooling and Spanish **FAN** translation patches for GNOSIA.
It does not redistribute the original game assets and must be used with a legally obtained copy of the game.

Aviso legal
-----------

- La licencia MIT de este repo aplica solo al código, documentación, glosario y parches incluidos aquí.
- No concede derechos sobre GNOSIA, sus textos originales, assets, marcas ni ficheros extraídos.
- `out/`, `work/`, `tmp/` y cualquier `.assets` local son artefactos de trabajo y no forman parte del contenido público del proyecto.

Qué contiene este repo
----------------------

- extracción del corpus textual estructurado desde `sharedassets0.assets`
- generación de un snapshot técnico local para trabajo y validación
- aplicación de parches ES sin guardar texto original del juego en Git
- reconstrucción de blobs y reempaquetado de un asset listo para probar
- auditoría técnica y editorial de la traducción actual
- extracción de imágenes localizadas a PNG para revisión manual
- build no-op estricto de bundles `help/pre/systm/title` por copia o reemplazo explícito

Estado actual
-------------

- El corpus editable vive en `Gnosia_Data/sharedassets0.assets`, dentro de 22 `MonoBehaviour` `Entity_*Text`.
- El orden de idiomas detectado es fijo: `jp`, `en`, `zh`.
- Se han identificado 22 entidades, 197 `sheets`, 9.563 `params` y 28.689 strings localizados.
- Los bundles `help_*`, `pre_*`, `systm_*` y `title_*` no contienen strings editables; solo `Sprite` y `Texture2D`.
- La fuente versionada de la traducción ya no vive en Python: ahora está en `parches/*.parche`.

Repositorio público
-------------------

Este repo está preparado para publicarse como proyecto de tooling/traducción.
La fuente de verdad versionada es `parches/`.
Los snapshots extraídos y el corpus materializado de trabajo permanecen fuera de Git:

- `out/`: snapshot técnico local extraído del juego
- `work/`: corpus local materializado para editar
- `tmp/`: auditorías, reconstrucciones y assets de prueba
- `parches/`: traducciones versionadas sin texto original del juego

Formato de parches
------------------

Cada entidad traducida tiene su propio fichero:

- `parches/OthersText.parche`
- `parches/ScreenText.parche`
- `parches/ScenarioBaseText.parche`
- `parches/ScenarioTutorialText.parche`

Formato de línea:

```text
<hash>:<id>:<traduccion>
```

- `hash` es `md5(jp + zh)` en UTF-8
- `id` es el índice `0`-based dentro de las entradas de esa entidad que comparten el mismo hash
- `traduccion` es el texto ES serializado en una sola línea, con escapes como `\n`, `\r`, `\t`, `\\` y `\"`

Esto permite versionar solo la traducción sin incluir `jp`, `en` ni `zh` en el repositorio.

Scripts principales
-------------------

- `extractor.py`
  Extrae el snapshot técnico local desde `sharedassets0.assets` a `out/`.
- `preparar_trabajo.py`
  Crea una copia limpia de `out/` en `work/`.
- `aplicar_parches.py`
  Regenera `work/` desde `out/` y aplica `parches/*.parche`.
- `exportar_parches.py`
  Compara `work/` contra `out/` y actualiza `parches/*.parche`.
- `auditar_traduccion.py`
  Revisa placeholders, saltos de línea, presupuesto de longitud y señales editoriales.
- `reconstructor.py`
  Reconstruye blobs binarios desde el corpus materializado.
- `reempacador.py`
  Reempaqueta un asset de prueba sin tocar la instalación original.
- `validar.py`
  Comprueba integridad estructural del pipeline.
- `extraer_imagenes_localizadas.py`
  Extrae previews PNG y genera un catálogo de los bundles localizados por imagen.
- `reempacar_bundles_localizados.py`
  Materializa bundles localizados por copia exacta o por reemplazo explícito.
- `GUIA_EDITORIAL.md`
  Criterio de estilo para la traducción ES.
- `glosario_v1.json`
  Glosario base y términos fijados.

Preparación
-----------

Los ejemplos siguientes asumen que estás dentro de `traductor_es/`.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Flujo recomendado
-----------------

1. Extraer snapshot técnico local desde el juego:

```bash
python extractor.py
```

2. Preparar una copia limpia del corpus:

```bash
python preparar_trabajo.py --force
```

3. Materializar la traducción actual desde `parches/`:

```bash
python aplicar_parches.py
```

4. Editar localmente `work/entities/*.json`.

5. Exportar los cambios a `parches/`:

```bash
python exportar_parches.py
```

6. Auditar la traducción:

```bash
python auditar_traduccion.py --work-manifest work/manifest.json
```

7. Reconstruir blobs:

```bash
python reconstructor.py \
  --manifest work/manifest.json \
  --out-dir tmp/work_reconstructed
```

8. Reempaquetar el asset de prueba:

```bash
python reempacador.py \
  --manifest work/manifest.json \
  --replacements-manifest tmp/work_reconstructed/replacements.json \
  --output-asset tmp/sharedassets0.phase1_es.assets
```

9. Validar la build editada:

```bash
python validar.py \
  --mode edited \
  --manifest work/manifest.json \
  --replacements-manifest tmp/work_reconstructed/replacements.json \
  --repacked-asset tmp/sharedassets0.phase1_es.assets
```

Imágenes localizadas
--------------------

Para revisar qué imágenes dependen del idioma:

```bash
python extraer_imagenes_localizadas.py
```

Esto deja un catálogo en `tmp/imagenes_localizadas/catalog.json` y previews PNG en `tmp/imagenes_localizadas/previews/`.

Para materializar un build no-op de los bundles localizados:

```bash
python reempacar_bundles_localizados.py
```

Esto copia los 12 bundles `help/pre/systm/title` a `tmp/localized_bundles/build/` y deja un manifiesto con SHA-256 por fichero.
Si en el futuro quieres modificar imágenes, el script solo permitirá diferencias en los bundles declarados explícitamente en `--replacements-json`.

Qué valida el auditor
---------------------

`auditar_traduccion.py` clasifica por niveles:

- `Tier A`: UI corta y microtextos sensibles
- `Tier B`: mensajes y pantallas de sistema
- `Tier C`: tutorial y texto más largo

Además de la integridad estructural, añade señales editoriales no bloqueantes:

- `glossary_mismatch`
- `ascii_fallback`
- `english_leftover`
- `stylization_review`
- `unchanged_translatable`

Lo importante para una build utilizable es mantener `hard_fail=0`.

Dónde se traduce
----------------

La edición real se hace en `work/entities/*.json`, siempre sobre `texts[1]`.

Reglas básicas:

- no cambiar la estructura del JSON
- no añadir ni eliminar elementos en `texts`
- conservar `{0}`, `{1}`, etc.
- conservar el estilo de saltos y escapes que usa el corpus original
- usar `exportar_parches.py` para persistir cambios en Git

Prueba dentro del juego
-----------------------

Para probar la build traducida dentro de GNOSIA, sustituye temporalmente el asset real solo después de hacer copia de seguridad.

Desde la raíz del juego:

```bash
cp Gnosia_Data/sharedassets0.assets Gnosia_Data/sharedassets0.assets.bak
cp traductor_es/tmp/sharedassets0.phase1_es.assets Gnosia_Data/sharedassets0.assets
```

Lanza el juego y revisa, como mínimo:

- pantalla de título
- carga/guardado
- menú principal
- labels cortas de sistema
- arranque del tutorial

Cuando termines, restaura el original:

```bash
mv Gnosia_Data/sharedassets0.assets.bak Gnosia_Data/sharedassets0.assets
```

Notas
-----

- `aplicar_parches.py` trata `parches/` como fuente de verdad y regenera `work/`.
- `exportar_parches.py` exporta solo entradas donde `es != en`.
- El repo no usa una librería de traducción automática para generar el castellano publicado.
- La traducción sigue en progreso; el tutorial largo aún no está completo.
