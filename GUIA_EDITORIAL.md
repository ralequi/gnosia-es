Guia editorial v1
=================

Objetivo
--------

Esta fase prioriza una traduccion usable y segura para UI, sistema y tutorial temprano, sobreescribiendo la variante `en`.

Reglas principales
------------------

- Mantener nombres propios y `Gnosia` sin traducir.
- Mantener placeholders como `{0}`, `{1}` y los saltos de linea.
- Para cadenas cortas de UI, intentar no superar la longitud del original.
- Para ayudas y textos de pantalla, aceptar algo mas de longitud solo si la frase gana claridad real.
- En caso de duda, priorizar una frase breve y natural en castellano de Espana.

Tono
----

- Castellano de Espana, directo y sin florituras.
- Tuteo cuando el original lo permita.
- Verbos cortos en etiquetas y acciones.
- Evitar formulaciones excesivamente literales si suenan torpes o largas.

Abreviacion
-----------

Cuando la UI no da espacio suficiente:

- Reducir articulos y muletillas.
- Preferir verbos directos.
- Usar abreviacion moderada en elementos de sistema si mejora claramente el ajuste.
- No abreviar nombres propios.

Convenciones
------------

- `cold sleep` se traduce como `sueno frio` en mensajes de sistema.
- `Crew Member Data` pasa a `Datos tripul.` en labels cortas.
- `Reference Data` pasa a `Datos ref.` en labels cortas.
- `AC Follower` pasa a `Seguidor AC`.
- Las cadenas puramente estructurales como `, `, `\n`, `.` o `...` se conservan.

Alcance de esta fase
--------------------

- Traducir primero `OthersText`, la UI corta y mensajes visibles de `ScreenText`, y el sistema comun de `ScenarioBaseText`.
- En `ScenarioTutorialText`, priorizar labels, prompts y nodos visibles al inicio.
- El resto del dialogo largo del tutorial y del guion completo se revisara despues, de forma manual y contextual.
