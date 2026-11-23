# Malo: suma los pedidos de los grupos y redondea
**Herramienta:** `buscar_ventas {"agrupar_por":"talla"}` → pedidos por talla.
**Respuesta (MAL):** Tuvimos unos 1.400 pedidos sumando todas las tallas y facturamos unos 140.000 €.
**Por qué está mal:** suma pedidos de grupos (un pedido puede estar en varios) y redondea cifras en vez de dar las exactas de `resumen`.
