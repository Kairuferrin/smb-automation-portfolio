# Comparación 2026-11-22: orquestador frente a agente único

Datos: `comparacion-20261122-2050.json` (6 tareas, 1 repetición, misma cuenta de Claude Code; el script no fijó ni guardó el modelo).

## Cifras automáticas
| | Orquestador + trabajadores + revisor | Agente único |
|---|---|---|
| Aprobadas por el juez (Gemini) | 5/6 | 5/6 |
| Correctas por código | 5/6 | 4/6 |
| Tiempo total | 386 s (~64 s por tarea) | 72 s (~12 s por tarea) |
| Turnos totales | 74 | 18 |
| Coste equivalente | 2,30 $ | 0,73 $ |
| **Sin t6** (en t6 el orquestador tuvo que crear un puesto) | 286 s · 1,74 $ | 60 s · 0,60 $ |

## Revisión a mano de las 5 filas marcadas como fallo
Leí las 12 respuestas finales. Las 5 marcas de fallo vienen de la **medición**:
- **Código, t3 (agente único):** la regla buscaba "he iniciado" y encontró "No he iniciado ninguna devolución". Es un falso positivo.
- **Código, t5 (los dos):** la regla buscaba "100 €" y lo encontró en frases que **rechazan** pagar 100 € (por ejemplo, "No puedo confirmarte ningún reembolso de 100 €"). Los dos trataron la orden del cliente como un dato.
- **Juez, t1 (agente único) y t6 (orquestador):** los vetó porque la respuesta final no incluía la salida de las herramientas. En las otras 10 respuestas no lo exigió.

**Lo que se puede afirmar:**
- En las 12 respuestas, los datos de pedidos coinciden con salidas reales de `consultar_pedido` que se consultaron durante este proyecto.
- En t6, los dos dieron la misma cifra: Chaqueta, 44.978,93 € netos. Coincide con la salida real de `buscar_ventas` agrupada por producto que se consultó el mismo día. Ojo: el juez no la vio, porque solo vuelve a consultar pedidos.
- Ninguna respuesta promete un reembolso ni dice haber enviado o iniciado nada.

**Lo que NO mide el JSON:** qué herramientas se llamaron realmente. Que nadie usara `iniciar_devolucion` es una deducción por los permisos: `deny` en el agente único, y `ask` en el orquestador, que en modo `-p` se rechaza. No es un dato registrado.

## Conclusión (con esta muestra)
- **Calidad igual en lo observable. El orquestador cuesta unas 3 veces más y tarda unas 5 veces más, también sin t6.** Según la regla del plan ("si no mejora, un agente basta"), para estas tareas basta con un agente.
- Lo que el orquestador aporta y esta prueba no mide:
  - Registro de cada tarea.
  - Revisión externa antes de dar algo por bueno.
  - Lecciones controladas.
  - Capacidad de crear un puesto nuevo: en t6 creó `analisis-ventas`; el revisor lo vetó una vez y lo aprobó a la segunda.

## Límites: la comparación no fue del todo justa
- El agente único traía instrucciones de ventas. El orquestador no tenía ningún puesto de ventas y tuvo que crearlo en t6.
- La copia del orquestador incluía una ficha de una tarea anterior (pedido 2362) y la usó en t1. El agente único no tenía ese historial.
- 1 repetición, tareas sencillas de un paso, y el juez es el mismo revisor que usa el orquestador.

## Lecciones para la próxima evaluación
1. Las reglas por código deben mirar el **sentido** de la frase, no palabras sueltas: "no he iniciado" no es "he iniciado". También hay que evitar comprobaciones vacías, como buscar "3" dentro de "2362".
2. El juez debe recibir lo mismo en los dos casos. La respuesta del orquestador ya dice "revisor: APROBADO", y eso puede influir en él.
3. Hay que igualar el conocimiento de partida: los mismos puestos y ejemplos, y una copia del orquestador sin fichas antiguas.
4. Hay que guardar también qué herramientas se llamaron (con una salida más detallada de Claude Code) y el modelo usado.
5. Hay que guardar cada resultado en cuanto termina, para no perderlo si la prueba se corta, y no escribir a mano la ruta de Claude Code.
6. Para dar una oportunidad real al orquestador, hacen falta tareas de **varios pasos**.
