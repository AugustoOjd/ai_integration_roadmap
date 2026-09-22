# Corpus — Nordix Comercio S.A.

Cinco documentos de política interna de una empresa de e-commerce ficticia.

| Archivo | Documento | Contenido |
|---|---|---|
| [`01_devoluciones.txt`](01_devoluciones.txt) | DEV-004 | Plazos por categoría, condiciones, costos de retorno, reembolsos |
| [`02_envios.txt`](02_envios.txt) | ENV-011 | Modalidades, corte de preparación, visitas fallidas, extravíos |
| [`03_garantias.txt`](03_garantias.txt) | GAR-007 | Plazos por categoría, exclusiones, service, garantía extendida |
| [`04_soporte_sla.txt`](04_soporte_sla.txt) | SOP-002 | Prioridades, escalamiento, autorizaciones por monto, clientes preferentes |
| [`05_facturacion.txt`](05_facturacion.txt) | FAC-009 | Medios de pago, cobros duplicados, facturación, contracargos |

## Por qué este corpus y no otro

**El modelo base no puede saberlo.** Nordix no existe. Cada número —21 días,
4.800 pesos, 200.000 de tope, el código FR3— sólo puede salir del retrieval. Si
la respuesta es correcta, el retrieval funcionó; no hay forma de acertar de
memoria.

**Tiene contradicciones aparentes a propósito.** Un electrodoméstico grande
tiene 24 meses de garantía, pero su batería tiene 6. El tope de autorización son
200.000 pesos, salvo para cobros duplicados, que no tienen tope. Un cliente
preferente no paga el envío de retorno que DEV-004 dice que sí se paga.

Esas no son erratas: son los casos donde el retrieval trae el chunk correcto y
la respuesta igual sale mal. Separan **falla de recuperación** de **falla de
generación**, que es la distinción que el set de preguntas mide.

**Los documentos se referencian entre sí.** FAC-009 apunta a SOP-002 y a
DEV-004; GAR-007 aclara que es independiente de DEV-004. Dos preguntas del set
sólo se contestan bien si el retrieval trae chunks de **dos** documentos.

**Es el mismo dominio que P2 y P3.** Órdenes, reembolsos, envíos, aprobación por
monto. El vocabulario ya lo tenés.

## El set de preguntas

[`../evals/preguntas.json`](../evals/preguntas.json) — 18 preguntas etiquetadas
por tipo:

| Tipo | Cuántas | Qué mide |
|---|---|---|
| `hecho_directo` | 9 | Retrieval puro: el dato está literal en un chunk |
| `razonamiento` | 4 | El chunk correcto no alcanza: hay que inferir o calcular |
| `trampa` | 1 | El chunk trae dos números y hay que elegir el correcto |
| `cruce_documentos` | 2 | Necesita chunks de dos archivos distintos |
| `debe_negarse` | 1 | No está en el corpus: contestar algo es fallar |

El formato (`question`, `expect`, `note`) es el mismo de Project 1, más un campo
`tipo`. `expect` es una lista de grupos: cada grupo es un conjunto de sinónimos
aceptables, y la respuesta tiene que contener al menos uno de cada grupo.
