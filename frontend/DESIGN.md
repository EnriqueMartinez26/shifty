# Shifty frontend design direction

## Identity and visual language

Shifty keeps its early-smartphone 2000s identity: warm orange, silver-gray
surfaces, compact bevels, restrained highlights, and clear pressed/selected
states. The orange `#ff8c42` to `#e67e22` gradient identifies the brand and
decorative marks. Text and primary actions use the darker accessible orange
tokens from `src/theme/colors.ts`; white text does not sit on the light brand
orange.

The shared token object in `src/theme/colors.ts` is the source of truth for
React styles. The active Tailwind theme in `src/index.css` mirrors the same
semantic roles and is checked against those tokens. Components may use a
service's configured color to identify that service; configured values remain
data and are not replaced with brand orange.

## Baseline findings

The responsive audit found a few concrete inconsistencies in the starting
frontend:

- The active Tailwind theme still declared an indigo primary and a dark Zinc
  surface while Shifty's rendered components used the warm orange and silver
  palette. Status colors were also repeated as unrelated hex values.
- The dashboard hero kept a 280 px minimum content width and clipped its text
  at a 320 px viewport.
- The mobile agenda kept desktop calendar grids, and date/professional strips
  hid their scrollbars without telling customers how to reach the other items.
- Several standalone actions and links fell below the 44 px touch target used
  by this design system.
- Responsive tables could scroll horizontally without a named keyboard-focusable
  region or an on-screen cue.

These are addressed by the theme bridge, semantic status tokens, responsive
calendar mode, explicit scroll regions, and the touch-target rules below. The
browser smoke test saves current-state screenshots for login, booking, and the
dashboard at 320 px. Each run attaches a JSON report with the viewport,
document width, clipped content, and short controls measured by route.

## Visual dials

| Area                                   | Energy | Rhythm | Motion | Reason                                                                                 |
| -------------------------------------- | -----: | -----: | -----: | -------------------------------------------------------------------------------------- |
| Public booking and client self-service |      2 |      2 |      1 | Keep the booking flow warm and legible, with a clear step order and quiet transitions. |
| Store panel and superadmin             |      1 |      2 |      1 | Prioritize scanning, operational density, and stable controls over decoration.         |

Gradients and highlights belong on brand marks, primary actions, and selected
controls where they communicate identity or state. Neutral raised surfaces
separate related sections; inset surfaces are reserved for inputs and dense
data. Shadows, rounded corners, and icons must explain hierarchy, grouping, or
interaction. Avoid applying cards or glow to every element.

## Responsive behavior

The layout follows the content rather than a device label. The current panel
sidebar becomes a keyboard-accessible drawer below its 1024 px desktop
breakpoint. The calendar changes to its existing list view on narrow phones;
day, week, month, and list controls remain available at tablet and desktop
widths. Tables keep their comparison structure and use a labeled, contained
horizontal scroller only when columns cannot reflow without losing meaning.

Review widths at 320, 360, 390, 412, 768, 1024, 1280, and 1440 px, plus
landscape and long-content cases. Do not hide page overflow to mask a layout
defect. Any internal scroller needs a visible cue and reachable controls.

## Interaction and accessibility

- Keep every action connected to real application behavior and real content.
- Give touch controls at least 44 by 44 CSS pixels where the control is a
  standalone target; keep adjacent choices separated enough to avoid misses.
- Use visible keyboard focus, semantic names, and keyboard-operable menus,
  forms, dialogs, and selection controls.
- New text/background combinations must meet WCAG AA contrast (4.5:1 for
  normal text); extend `src/theme/colors.contrast.test.ts` when adding tokens.
- Preserve loading, empty, success, disabled, and error states. Do not invent
  metrics, testimonials, or placeholder actions to fill a layout.
- Respect reduced-motion preferences; movement should communicate a state
  change and remain brief.

## Anti-Slop delivery gate

Anti-Slop is a quality filter, not a replacement for Shifty's established
visual direction. Close each implementation slice with concrete PASS/FAIL
evidence for:

1. **Hard gate:** target viewport reflow, no page-level horizontal overflow,
   readable long content, real content and destinations, working controls,
   keyboard access, focus visibility, touch targets, and AA contrast.
2. **Purpose gate:** explain the role of color, gradients, icons, typography,
   surfaces, and motion in that slice. Remove effects that add no hierarchy or
   feedback.
3. **Liveliness:** retain the area-specific energy, rhythm, and motion dials
   above; do not add motion merely to make a screen feel animated.
4. **Craft and quality locks:** test empty/loading/error states, confirm
   responsive screenshots or browser measurements, and record any local-only
   environment limits. A FAIL blocks delivery of that slice.
