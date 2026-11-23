# Comparación v2 (justa y difícil) · 2026-11-22

Datos: `comparacion-v2-20261122-2055.json`. Son 5 tareas de varios pasos, repetidas 2 veces con los dos sistemas: 20 ejecuciones. Ninguno de los dos sistemas **intentó** llamar a `iniciar_devolucion`: está registrado en `herramientas` de cada fila, incluidas las llamadas de los trabajadores. Las llamadas del revisor no aparecen, porque es otro programa, pero su código solo usa `consultar_pedido`.

**Qué la hace justa:**
- **Mismo conocimiento.** El CLAUDE.md del agente único se generó con los mismos puestos, lecciones y ejemplos que tiene el orquestador, incluido el nuevo `analisis-ventas`.
- **Sin historial.** El orquestador arrancó sin fichas antiguas.
- **Mismo juez.** Los dos se corrigen igual y el juez solo ve la respuesta final.

## Resultados
| | Orquestador + trabajadores + revisor | Agente único |
|---|---|---|
| Correctas (juez v2, por mayoría de 3 votos) | 10/10 | 9/10 |
| **Correctas tras revisar a mano el único fallo** | **10/10** | **10/10** |
| Tiempo total | 1.113 s (~111 s por tarea) | 211 s (~21 s por tarea) |
| Turnos totales | 101 | 68 |
| Coste equivalente | 5,18 $ | 1,60 $ |
| Tarea de 13 pedidos: consultas a la tienda (MCP) | 13 | 13 |
| Tarea de 13 pedidos: pasos de gestión (Agent, Read, Write, Bash, ToolSearch) | 15-16 | 1 |

Qué cuenta cada cifra:
- **Turnos:** solo los del agente principal. No incluyen los de los trabajadores, así que el orquestador se queda corto en esa fila.
- **Coste:** solo Claude. No incluye las llamadas a Gemini del revisor.

## Cómo se corrigió (y qué falló en la corrección)
1. **Juez v1** (en `comparar-v2.ts`): solo 4/10 y 2/10 correctas. **Era injusto.** Contaba como "inventado" cualquier dato real que no estuviera en mi solucionario, que era incompleto; por ejemplo, "2 camisetas L" en el pedido 2362. El fallo estaba en cómo diseñé el juez, no en las respuestas.
2. **Juez v2** (`rejuzgar.ts`): recibe todos los datos reales del MCP y solo marca error si la respuesta los contradice, si le falta un punto clave o si promete algo prohibido. Vota 3 veces y gana la mayoría, aunque con temperatura 0 las tres votaciones casi siempre coinciden.
3. **Único fallo del juez v2** (h5, agente único, repetición 1): el agente consultó las ventas por talla sin filtrar las devueltas, que es una consulta distinta de la que tenía el juez. Comprobé a mano sus cifras con esta consulta: `SELECT talla, SUM(importe_eur), SUM(CASE WHEN devuelto=0 THEN importe_eur END) FROM ventas GROUP BY talla`. Dio L 28.635,50 / 26.242,64 · M 32.230,88 / 29.727,88 · S 30.372,64 / 28.677,41 · XL 30.312,49 / 28.375,21 · XS 23.832,98 / 22.721,20, idénticas a las de la respuesta. Además, las sumas dan los totales conocidos: 145.384,49 € brutos y 135.744,34 € netos. **Son correctas.**

## Conclusión
- **En esta prueba no se ve diferencia de calidad: 10/10 frente a 10/10, con tareas de varios pasos y el mismo conocimiento.** Ojo con el *efecto techo*: si los dos sacan un 10, el examen no distingue entre ellos, y son solo 10 ejecuciones por sistema. El orquestador cuesta unas **3,2 veces más** y tarda unas **5,3 veces más**.
- Con la regla del plan ("si no mejora, un agente basta"): **para estas tareas de la tienda, basta con un agente.** Coincide con la v1, ahora con una prueba más justa y de varios pasos.
- El orquestador aporta otras cosas: registro de cada tarea, revisión externa antes de dar algo por bueno, lecciones controladas y puestos nuevos que pasan un control. Tienen sentido cuando hace falta **auditar** o hay **riesgo**, no para ganar calidad en tareas como estas.

## Hallazgo importante: el revisor externo tiene un punto ciego
`revisar.ts` (modo `resultado`) solo vuelve a consultar **números de pedido**, y solo los **5 primeros**. **Nunca comprueba cifras de ventas.** Por eso:
- En h3 y en la parte de tallas de h5, el "APROBADO" del revisor no comparó ninguna cifra.
- En h4 dejó sin comprobar 8 de los 13 pedidos.

La "revisión externa", que es la ventaja del orquestador, para el puesto `analisis-ventas` no comprueba nada. Hay que arreglarlo antes de fiarse del orquestador para tareas de ventas o de muchos pedidos.

## Lecciones de evaluación (para Kairu)
1. **El juez también hay que examinarlo.** Un solucionario incompleto convirtió respuestas buenas en "incorrectas". Sin revisar, la conclusión habría sido "el orquestador es el doble de bueno", y era falsa.
2. **Los datos del juez deben cubrir las formas válidas de responder**, no solo la que yo esperaba.
3. **Guardar las respuestas permitió volver a corregir sin repetir la prueba.** Es lo que ahorra cuota.
4. **`rejuzgar.ts` es frágil:**
   - Lee las tareas del `comparar-v2.ts` actual con una expresión regular, así que si las editas, corrige con otro solucionario.
   - Escribe encima del JSON original.
   - Mejor: tener las tareas en un archivo compartido y guardar el solucionario en cada fila.
5. **El JSON incluye rutas con el usuario del Mac.** Hay que recortarlas si algún día se publica.

## Arreglo del punto ciego (2026-11-23)
**Qué hace ahora el revisor (modo `resultado`):**
- **Pedidos:** vuelve a consultar todos los pedidos de la ficha, empezando por los que nombran las respuestas (tope de 40). Reconoce rangos como "2380 a 2392" y "entre 2380 y 2392".
- **Ventas:** repite cada consulta `buscar_ventas` de "Herramientas usadas". Si hay cifras de ventas sin ninguna consulta, se vetan por "no verificables".
- **Caja aparte para los datos reales:** los datos que consulta el revisor van a Gemini en su propia caja, con etiqueta aleatoria. Así, una ficha no puede colar un bloque falso de "DATOS REALES", y las pruebas con bloques falsos se vetaron.
- **Cruce por código** (`revisor/cruce.ts`): compara el estado de cada pedido con el real. Es prudente a propósito: ignora frases en pasado o futuro, negaciones, fechas, importes y "líneas devueltas". Tiene 23 pruebas en `evaluacion/test-cruce.ts` y no dio ninguna falsa alarma en las 20 respuestas reales de esta comparación.
- **Solo lectura:** el revisor solo puede usar herramientas de lectura; `iniciar_devolucion` está bloqueada en el código.
- **Cortes de red:** si falla la conexión, espera y reintenta, con un tiempo máximo por intento, en lugar de caerse.

**Resultados:**
- Examen completo: 100 % de errores detectados. Los casos que fallaron por un corte de internet se repitieron después: 27/27.
- Casos nuevos: ventas 9/9; un estado falso escondido entre 13 pedidos se detecta siempre.

**Límites conocidos (no arreglados):**
- En un rango de más de 30 pedidos solo se consultan los extremos. Gemini tiene orden de vetar si la respuesta afirma algo de los del medio, pero el cruce por código no los mira.
- El cruce solo ve los números escritos. En "2380 a 2392 están en camino" no comprueba los del medio uno a uno; eso lo hace Gemini con los datos reales.
- `numerosDePedido` y `consultasDeVentas` no tienen pruebas propias, porque viven en `revisar.ts`.
