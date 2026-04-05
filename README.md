GNOSIA en Castellano
====================

Este directorio contiene el pipeline de extracción y reconstrucción del texto estructurado de GNOSIA.
El corpus editable vive en `Gnosia_Data/sharedassets0.assets`, dentro de 22 `MonoBehaviour` `Entity_*Text`.

Estado actual
-------------

- Se extraen 22 entidades, 197 `sheets`, 9.563 `params` y 28.689 strings localizados.
- El orden de idiomas detectado es fijo: `jp`, `en`, `zh`.
- Los bundles `help_*`, `pre_*`, `systm_*` y `title_*` no contienen strings editables; solo `Sprite` y `Texture2D`.
- El reempaquetado no-op se ha validado byte a byte contra el `sharedassets0.assets` original.

Estructura
----------

- `extractor.py`
  Extrae el corpus desde `sharedassets0.assets` y genera `out/manifest.json`, `out/entities/*.json` e `out/image_inventory.json`.
- `reconstructor.py`
  Lee los JSON exportados y reconstruye los blobs binarios por entidad en `tmp/reconstructed/blobs/*.bin`.
- `reempacador.py`
  Aplica los blobs reconstruidos a una copia temporal del asset y genera `tmp/sharedassets0.repacked.assets`.
- `validar.py`
  Ejecuta comprobaciones automáticas sobre el pipeline.
- `gnosia_common.py`
  Lógica compartida: parser binario, serializador, inventario de bundles y helpers de validación.

Los directorios `out/` y `tmp/` están ignorados por git a propósito.

Preparación
-----------

Los ejemplos de este README asumen que estás dentro de `traductor_es/`.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Si prefieres ejecutar desde la raíz del juego, usa `python traductor_es/extractor.py`, etc.

Flujo base
----------

1. Extraer el corpus:

```bash
python extractor.py
```

2. Validar el caso base no-op:

```bash
python validar.py
```

Eso confirma que:

- El parser binario reserializa exactamente las 22 entidades.
- El corpus exportado coincide con el original.
- El writer de `UnityPy` queda normalizado correctamente.
- El reempaquetado no-op genera un asset idéntico al original.

Archivos generados
------------------

- `out/manifest.json`
  Índice general del corpus, checksum del asset fuente y lista de entidades.
- `out/entities/*.json`
  Texto editable. Aquí es donde se traduce.
- `out/image_inventory.json`
  Inventario de bundles localizados por imagen.
- `tmp/reconstructed/replacements.json`
  Índice de blobs reconstruidos.
- `tmp/sharedassets0.repacked.assets`
  Asset reempaquetado listo para pruebas.

Qué se puede editar y qué no
----------------------------

Edita solo los strings dentro de `out/entities/*.json`.

Conviene respetar estas reglas:

- No cambies la estructura del JSON.
- No añadas ni elimines elementos en `texts`.
- Si vas a sustituir el inglés por español, normalmente tocarás `texts[1]`.
- Conserva placeholders como `{0}`, `{1}`, etc.
- Conserva secuencias como `\n` cuando formen parte del texto.
- No edites `manifest.json` a mano salvo que sepas exactamente por qué.

Prueba mínima de cambio
-----------------------

La forma más segura de hacer una prueba es trabajar sobre una copia del corpus exportado.

1. Crear una copia de trabajo:

```bash
rm -rf tmp/demo_out tmp/demo_reconstructed tmp/demo.sharedassets0.assets
cp -r out tmp/demo_out
```

2. Localizar un texto de prueba:

```bash
rg -n '"Starting Point"' tmp/demo_out/entities
```

En la extracción actual aparece en `tmp/demo_out/entities/0275_OthersText.json`.

3. Editar ese JSON y sustituir el inglés por algo visible, por ejemplo:

- Antes: `Starting Point`
- Después: `Punto de Inicio [PRUEBA]`

Si quieres hacerlo con un script rápido:

```bash
python - <<'PY'
import json
from pathlib import Path

path = Path("tmp/demo_out/entities/0275_OthersText.json")
data = json.loads(path.read_text(encoding="utf-8"))

for sheet in data["sheets"]:
    for param in sheet["params"]:
        texts = param["texts"]
        if len(texts) >= 2 and texts[1] == "Starting Point":
            texts[1] = "Punto de Inicio [PRUEBA]"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(0)

raise SystemExit("No se encontró el string objetivo")
PY
```

4. Reconstruir los blobs:

```bash
python reconstructor.py \
  --manifest tmp/demo_out/manifest.json \
  --out-dir tmp/demo_reconstructed
```

Importante:

- No uses `--verify-source-match` cuando hayas editado textos.
- Esa opción es solo para el caso no-op exacto contra el original.

5. Reempaquetar el asset modificado:

```bash
python reempacador.py \
  --manifest tmp/demo_out/manifest.json \
  --replacements-manifest tmp/demo_reconstructed/replacements.json \
  --output-asset tmp/demo.sharedassets0.assets
```

6. Validar la edición sin exigir igualdad byte a byte con el original:

```bash
python validar.py \
  --mode edited \
  --manifest tmp/demo_out/manifest.json \
  --replacements-manifest tmp/demo_reconstructed/replacements.json \
  --repacked-asset tmp/demo.sharedassets0.assets
```

Ese modo comprueba que:

- El corpus sigue teniendo la misma forma lógica.
- Los blobs reconstruidos son aplicables.
- El asset reempaquetado contiene exactamente los blobs nuevos.
- Los bundles localizados por imagen siguen siendo solo raster.

Prueba dentro del juego
-----------------------

Para ver el cambio dentro de GNOSIA necesitas sustituir temporalmente el asset real del juego.
Hazlo siempre con copia de seguridad.

Desde la raíz del juego:

```bash
cp Gnosia_Data/sharedassets0.assets Gnosia_Data/sharedassets0.assets.bak
cp traductor_es/tmp/demo.sharedassets0.assets Gnosia_Data/sharedassets0.assets
```

Lanza el juego, busca el texto que has modificado y comprueba que aparece el cambio.

Cuando termines, restaura el original:

```bash
mv Gnosia_Data/sharedassets0.assets.bak Gnosia_Data/sharedassets0.assets
```

Si quieres conservar también el asset de prueba por separado:

```bash
cp traductor_es/tmp/demo.sharedassets0.assets traductor_es/tmp/sharedassets0.prueba.assets
```

Modo de trabajo recomendado
---------------------------

Para una traducción real, el flujo habitual sería:

1. `python extractor.py`
2. Editar `out/entities/*.json`
3. `python reconstructor.py`
4. `python reempacador.py`
5. `python validar.py --mode edited`
6. Probar temporalmente el asset dentro del juego

Notas
-----

- `validar.py` sin argumentos es una prueba de integridad del pipeline base, no de una traducción editada.
- `validar.py --mode edited` es el modo adecuado después de cambiar textos.
- Si el juego se rompe tras una edición, lo primero que conviene revisar es que no se haya modificado la estructura de `texts`, o que no se hayan roto placeholders como `{0}` o saltos de línea.
- El pipeline actual está pensado para sustituir una de las variantes existentes, normalmente `en`, no para añadir un cuarto idioma al selector del juego.
