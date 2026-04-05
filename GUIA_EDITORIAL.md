Guía editorial v1
=================

Objetivo
--------

Esta fase prioriza una traducción usable y segura para UI, sistema y tutorial temprano, sobreescribiendo la variante `en`.

Reglas principales
------------------

- Mantener nombres propios y `Gnosia` sin traducir.
- Mantener placeholders como `{0}`, `{1}` y los saltos de línea.
- En UI corta, intentar no alargar el texto sin necesidad, pero priorizar claridad cuando el espacio lo permita.
- En ayudas y textos de pantalla, aceptar algo más de longitud si la frase mejora de forma clara.
- En caso de duda, priorizar una frase breve y natural en castellano de España.

Tono
----

- Castellano de España, directo y sin florituras.
- Tuteo cuando el original lo permita.
- Verbos cortos en etiquetas y acciones.
- Evitar formulaciones excesivamente literales si suenan torpes o largas.

Abreviación
-----------

Cuando la UI no da espacio suficiente:

- Reducir artículos y muletillas.
- Preferir verbos directos.
- Usar abreviación moderada en elementos de sistema si mejora claramente el ajuste.
- No abreviar nombres propios.

Convenciones
------------

- `Cold Sleep` se traduce como `Criogenia` en etiquetas y mensajes de sistema.
- `Data Reference` pasa a `Datos ref.` en labels cortas.
- `Crew Member Data` pasa a `Datos tripul.` en labels cortas.
- `AC Follower` pasa a `Seguidor AC`.
- Las cadenas puramente estructurales como `, `, `\n`, `.` o `...` se conservan.

Alcance de esta fase
--------------------

- Traducir primero `OthersText`, la UI corta y mensajes visibles de `ScreenText`, y el sistema común de `ScenarioBaseText`.
- En `ScenarioTutorialText`, priorizar labels, prompts y nodos visibles al inicio.
- El resto del diálogo largo del tutorial y del guion completo se revisará después, de forma manual y contextual.
