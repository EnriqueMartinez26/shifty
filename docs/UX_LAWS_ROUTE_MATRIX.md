# Matriz UX por ruta

Esta matriz organiza la aplicación gradual de 25 leyes de UX como criterios de revisión. Son heurísticas, no reglas universales: cada decisión depende de la tarea, la evidencia y los contratos del sistema. Las pruebas automatizadas no certifican por sí solas la experiencia visual ni la accesibilidad.

## Criterios de revisión

| Grupo | Leyes y pregunta práctica |
| --- | --- |
| Comprensión | **Chunking**, **Cognitive Load**, **Prägnanz**, **Mental Model**, **Miller**, **Occam**, **Active User**. ¿La persona entiende qué hacer sin memorizar detalles ni consultar el manual? |
| Jerarquía visual | **Aesthetic-Usability**, **Common Region**, **Proximity**, **Similarity**, **Uniform Connectedness**, **Von Restorff**, **Selective Attention**. ¿Relaciones, prioridades y avisos críticos se distinguen cerca de la tarea? |
| Interacción | **Doherty Threshold**, **Fitts**, **Flow**, **Hick**, **Jakob**, **Postel**. ¿La respuesta es clara y oportuna, los controles son alcanzables y las entradas se normalizan de forma segura? |
| Progreso y experiencia | **Goal-Gradient**, **Peak-End**. ¿Se ve cuánto falta y termina el flujo con un resultado comprensible? |
| Decisiones de producto | **Cognitive Bias**, **Pareto**, **Tesler**. ¿Las decisiones son transparentes, priorizamos tareas frecuentes y el sistema absorbe la complejidad que puede resolver? |

Las agrupaciones son prácticas para la revisión, no se imponen cuando entran en conflicto. Por ejemplo, Hick no justifica quitar opciones necesarias y Postel no flexibiliza validaciones de seguridad.

## Cómo usarla

1. Elegí una ruta y anotá la tarea principal de la persona.
2. Registrá la fricción observada y el criterio UX antes de cambiar la interfaz.
3. Anotá por separado evidencia automatizada, revisión manual y E2E; son controles distintos.
4. Si hace falta cambiar API o BD, abrí una línea backend independiente.
5. Mantené la ruta en progreso hasta completar los controles que le correspondan; una PR abierta o CI verde no la cierra.

## Estado por ruta — 18 de octubre de 2026

El [issue #163](https://github.com/EnriqueMartinez26/shifty/issues/163) sigue abierto. Este snapshot incluye las PR de UX #196–#202 y #204–#225, abiertas como borradores; #203 corresponde a performance del [issue #152](https://github.com/EnriqueMartinez26/shifty/issues/152) y se mantiene separado. Ninguna representa una ruta integrada o cerrada. El estado «checks verdes» se refiere a las comprobaciones automatizadas remotas de esa PR, no a QA visual, teclado ni E2E.

| Ruta o área | Tarea / fricción atendida | Cambio UX y evidencia disponible |
| --- | --- | --- |
| `/b/:slug`, `/booking/:slug` | Elegir servicios, fecha y horario; completar, revisar y reintentar la reserva. | Responsive y fundamento visual: [#196](https://github.com/EnriqueMartinez26/shifty/pull/196), [#199](https://github.com/EnriqueMartinez26/shifty/pull/199), [#200](https://github.com/EnriqueMartinez26/shifty/pull/200), [#201](https://github.com/EnriqueMartinez26/shifty/pull/201). [#225](https://github.com/EnriqueMartinez26/shifty/pull/225) aclara errores temporales frente a conflictos de horario y conserva datos/clave al reintentar; 82/82 Jest y 2/2 E2E móvil (reserva normal y 503 seguido de éxito), checks remotos verdes. QA visual en 390×844 y 1440×900 sin desborde; foco visible y transición por Enter al encabezado del paso siguiente en [#224](https://github.com/EnriqueMartinez26/shifty/pull/224). En 320 px, la vista local confirmó que el indicador no se superpone y que el nombre “COLOR COMPLETO” envuelve en dos líneas; con el ajuste de ancho de [#196](https://github.com/EnriqueMartinez26/shifty/pull/196), el documento queda en 305 px igual que el área útil y no presenta scroll horizontal. #224 pasó 41/41 pruebas focalizadas y todos sus checks remotos; #198 pasó 10/10 en BookingStepService y todos sus checks remotos. El preview Vercel de #198 sigue respondiendo HTTP 500, pero la vista local de la rama sirvió para la inspección visual. #201 también completó sus checks remotos. Faltan anchos y variantes restantes. |
| `/b/:slug/mis-turnos` y acceso OTP | Consultar y gestionar turnos con acciones legibles en móvil y mantener claro el acceso del cliente. | [#202](https://github.com/EnriqueMartinez26/shifty/pull/202). Checks remotos verdes; PR abierta y encadenada. |
| `/login`, `/reset-password` | Acceder o recuperar la cuenta y alcanzar los controles táctiles. | [#204](https://github.com/EnriqueMartinez26/shifty/pull/204). Checks remotos verdes. La revisión puntual previa de Login a 390 y 1440 px observó foco en Email y sin desborde; no completa QA de recuperación ni teclado. |
| Páginas legales, presentación móvil | Mantener legibles los objetivos táctiles y permitir que enlaces largos de contacto se ajusten al ancho. | [#204](https://github.com/EnriqueMartinez26/shifty/pull/204), [#207](https://github.com/EnriqueMartinez26/shifty/pull/207). Checks remotos verdes. El contenido legal definitivo no forma parte de estos cambios. |
| Navegación del panel en móvil | Abrir y recorrer la navegación del panel desde pantallas pequeñas. | [#205](https://github.com/EnriqueMartinez26/shifty/pull/205). Checks remotos verdes. |
| `/dashboard` | Consultar el panel sin desbordes en pantallas angostas. | [#206](https://github.com/EnriqueMartinez26/shifty/pull/206). Checks remotos verdes. Inspección visual del preview a 390×844 y 1440×900 sin desborde; no cierra revisión de todos los estados ni de teclado. |
| Agenda y acciones de turnos | Avanzar por la agenda y alcanzar controles de fecha, vista, alta y acciones del turno. | [#197](https://github.com/EnriqueMartinez26/shifty/pull/197), [#208](https://github.com/EnriqueMartinez26/shifty/pull/208). Checks remotos verdes; #197 sigue encadenada. Inspección visual a 390×844 y 1440×900 sin desborde. El menú móvil abre con foco en navegación y Escape lo cierra restaurando el foco al botón. |
| Tarjetas de servicios, personal y usuarios | Leer y operar las tarjetas en anchos móviles. | [#198](https://github.com/EnriqueMartinez26/shifty/pull/198). El ajuste a 320 px reduce padding, separación e iconos solo bajo `sm`; mantiene tamaños amplios en pantallas mayores y no altera selección ni datos. `npm run check` pasó localmente y `BookingStepService.test.tsx` pasó 10/10. Todos los checks remotos del head actual están verdes. La tarjeta pública se inspeccionó en preview local; el preview Vercel de esa PR responde HTTP 500. |
| `/dashboard/collections` | Alcanzar acciones de cobranza en móvil sin alterar permisos ni flujo financiero. | [#209](https://github.com/EnriqueMartinez26/shifty/pull/209). Checks remotos verdes. |
| `/dashboard/payments` | Registrar una devolución manual indicando tipo, importe y confirmación externa explícita. | [#210](https://github.com/EnriqueMartinez26/shifty/pull/210). Checks remotos verdes; no envía dinero ni cambia el contrato del backend. |
| Libro de cuenta | Alcanzar las acciones de búsqueda y reversión sin alterar montos ni cálculos. | [#211](https://github.com/EnriqueMartinez26/shifty/pull/211). Checks remotos verdes. |
| Configuración | Identificar la sección activa del panel de configuración. | [#212](https://github.com/EnriqueMartinez26/shifty/pull/212). Checks remotos verdes. |
| Lista de espera | Completar fecha, hora y confirmación en móvil conservando el horario calculado por el servidor. | [#213](https://github.com/EnriqueMartinez26/shifty/pull/213). Checks remotos verdes. |
| Reportes | Distinguir y operar los filtros Desde/Hasta mediante tacto o teclado. | [#214](https://github.com/EnriqueMartinez26/shifty/pull/214). Todos los checks remotos están verdes. |
| Promociones | Comprender y completar los nueve campos; percibir el foco y alcanzar las acciones. | [#215](https://github.com/EnriqueMartinez26/shifty/pull/215). Checks remotos verdes. |
| Servicios | Buscar servicios y distinguir catálogo vacío de búsqueda sin coincidencias. | [#216](https://github.com/EnriqueMartinez26/shifty/pull/216). Checks remotos verdes. |
| Personal | Buscar profesionales y distinguir catálogo vacío de búsqueda sin coincidencias. | [#217](https://github.com/EnriqueMartinez26/shifty/pull/217). Checks remotos verdes. |
| Usuarios | Usar la búsqueda con teclado manteniendo la consulta explícita del servidor. | [#218](https://github.com/EnriqueMartinez26/shifty/pull/218). Checks remotos verdes. |
| Manual | Cambiar entre seis secciones con pestañas y teclado; conservar foco visible, asociar cada pestaña a su panel y alcanzar enlaces legales con 44 px. | [#219](https://github.com/EnriqueMartinez26/shifty/pull/219), draft. Prueba focalizada 4/4 y gates locales verdes; Quality, Security, CodeQL y Vercel remotos en verde. |
| SuperAdmin (`/control-global`) | Identificar los controles de formularios y usar diálogos con foco predecible. | [#220](https://github.com/EnriqueMartinez26/shifty/pull/220) etiqueta 40 controles (4/4 pruebas focalizadas y gates locales verdes; Quality, Security, CodeQL y Vercel remotos en verde). [#221](https://github.com/EnriqueMartinez26/shifty/pull/221) gestiona foco, Escape, restauración del foco y botón de 44 px (5/5 y gates locales verdes; checks remotos en verde). [#222](https://github.com/EnriqueMartinez26/shifty/pull/222) nombra filtros, expone `aria-pressed`, muestra el foco y lleva controles a 44 px (2/2 pruebas; check, build y auditoría locales verdes; checks remotos en verde). QA visual/teclado autenticado sigue pendiente. |

### Revisión manual: parcial

El 18 de octubre se revisaron el flujo de reserva pública, el dashboard y la agenda en el preview local a 390×844 y 1440×900. No hubo desborde horizontal en esas pantallas. En reserva, el foco de teclado es visible y Enter al avanzar lo lleva al encabezado del paso siguiente; en la navegación móvil, Enter abre el menú, Escape lo cierra y restaura foco al disparador. En la reserva a 390 px, Tab muestra un contorno sólido de 3 px en el enlace “Mis turnos”. A 320 px, el preview local de #224 confirmó el resumen “Paso 1 de 3: Servicio” sin superposición. El preview local de #198 confirmó wrapping de “COLOR COMPLETO” en dos líneas, y la base de #196 dejó `documentWidth` igual a `clientWidth` (305 px), sin scroll horizontal. También se comprobó el paso de selección de servicio a 360, 412, 768, 1024 y 1280 px: no presentó desborde horizontal en esos anchos. El preview Vercel de #198 devolvió HTTP 500; eso no impidió la inspección local, pero la causa de ese error remoto sigue sin investigarse.

Queda pendiente revisar los demás pasos de reserva y las otras rutas en esos anchos; además, estados de carga, vacío, error y reintento, contraste, anuncios, diálogos y uso exclusivo de teclado. La sesión autenticada de QA expiró durante la navegación repetida y el rate limit respondió 429, así que no se certifican más pantallas del panel con esta corrida.

### E2E: parcial

La reserva pública pasó 2/2 en Playwright sobre stack Docker descartable con tienda sintética `salon-sentinel`: reserva normal y error temporal 503 seguido de éxito al reintentar. Los casos de clasificación de 409/503 y conservación del pedido también tienen pruebas de comportamiento. No se usaron datos de producción ni se realizaron pagos. Siguen pendientes la reserva multi-servicio, OTP/Mis turnos y recorridos autenticados del panel.

## Trabajo separado de #163

- **Capacidades compartidas** para alinear rutas, navegación y acciones: línea independiente, con issue y alcance propios antes de integrarla.
- **Analítica y consentimiento**: sin issue aprobado para integrarla en este alcance.
- **Texto legal definitivo**: separado de los ajustes visuales de [#204](https://github.com/EnriqueMartinez26/shifty/pull/204) y [#207](https://github.com/EnriqueMartinez26/shifty/pull/207); requiere datos definitivos y revisión profesional.
- **Performance y runner de staging**: [PR #203](https://github.com/EnriqueMartinez26/shifty/pull/203) corresponde al [issue #152](https://github.com/EnriqueMartinez26/shifty/issues/152), no al issue UX #163.

## Límites de arquitectura

La UI representa permisos, disponibilidad, estados y montos; el backend mantiene la autoridad. La entrega UX de #163 no agrega endpoints públicos ni cambios de esquema. Cualquier necesidad de API o BD va en una PR backend independiente, con contrato, migración y validaciones que correspondan.

## Criterios para cerrar una ruta

- [ ] Tarea principal y fricción observada documentadas.
- [ ] Criterio UX aplicado con justificación contextual.
- [ ] Carga, vacío, error y reintento revisados cuando correspondan.
- [ ] Permisos, montos, estados, idempotencia, tienda y horario conservan la autoridad del backend.
- [ ] Pruebas automatizadas de comportamiento pasan.
- [ ] Revisión manual en escritorio, móvil y teclado: foco, contraste, diálogos, anuncios y objetivos táctiles.
- [ ] E2E local o de staging pasa si la ruta completa un flujo autenticado o transaccional.
