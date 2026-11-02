# Excepción de contraste de los controles de marca de Shifty

**Registrada:** 2026-10-29

**Estado:** excepción visual documentada; no conformidad con WCAG 2.1, criterio 1.4.3.

## Decisión y alcance

Por instrucción del usuario, los controles propios de Shifty conservan el
gradiente naranja `#ff8c42` → `#e67e22` y texto `#ffffff`, sin contorno ni halo
alrededor de los caracteres. Esta decisión registra una excepción; no declara
que los controles cumplan AA.

El alcance es la marca de Shifty. Los colores configurados por cada negocio y
los colores semánticos de estado (éxito, advertencia, error e información) se
mantienen independientes.

En la reserva pública, `#000000` es el marcador existente de color de negocio
no configurado: ese caso usa el naranja claro de Shifty (`#ff8c42`) y su
degradado. Los demás colores válidos configurados por el negocio se conservan;
por ejemplo, Salon Sentinel mantiene `#BE185D`. Esta regla ya está cubierta en
`frontend/src/presentation/lib/brandTheme.test.ts`.

## Mediciones

Las etiquetas observadas en los controles tienen aproximadamente 10–12 CSS px
y peso bold. No alcanzan los tamaños de texto grande de WCAG, por lo que aplica
el mínimo de 4.5:1 para texto normal.

| Texto | Fondo inmediato | Contraste | Estado | Resultado |
| --- | --- | ---: | --- | --- |
| `#ffffff` | `#ff8c42` (extremo claro) | 2.31:1 | Normal | No alcanza 4.5:1 |
| `#ffffff` | `#e67e22` (extremo oscuro) | 2.85:1 | Normal | No alcanza 4.5:1 |
| `#ffffff` | Mismo gradiente de marca | 2.31:1–2.85:1 | Hover, pressed y focus | El color del texto y el relleno no cambian; sigue por debajo de 4.5:1 |

El indicador de foco está fuera de los glifos y no aumenta el contraste entre
el texto y su fondo inmediato. Los controles inactivos están exentos del
criterio 1.4.3; no se usa esa exención para afirmar conformidad de los CTA
activos.

## Aclaración sobre G18 y `#2b2b2b`

G18 describe un contorno o halo alrededor de las letras cuando el fondo y el
interior del texto no contrastan lo suficiente. La implementación actual no
usa `#2b2b2b` como halo, trazo ni borde de los glifos. Los valores anteriores
de 6.12:1 y 4.97:1 corresponden únicamente al par hipotético `#2b2b2b` sobre
`#ff8c42` y `#e67e22`; el margen de 0.47:1 es `4.97 − 4.5`, no el contraste
del texto blanco con el naranja. El halo no se implementa porque la instrucción
vigente lo excluye.

Referencias: [W3C G18](https://www.w3.org/WAI/WCAG21/Techniques/general/G18) y
[WCAG 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

## Revisión futura

No presentar estos controles como conformes con AA. Reabrir esta excepción si
cambian el naranja, el texto blanco o la restricción de no usar halo; volver a
medir cada estado antes de retirar la excepción.
