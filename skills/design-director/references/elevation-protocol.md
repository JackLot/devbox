# Elevation protocol

A fixed order of passes for turning a functional draft into finished work. The
order matters: each pass assumes the ones before it are settled, and later
passes are cheap to redo while earlier ones are not. Do one thing per pass.

For low-stakes output, do passes 1, 4, and 6 lightly and stop. For anything
that will be presented, published, or reused, do them all.

## Pass 0: Functional baseline

Content complete and correct, structure sound, plain styling. Real copy and
real (or realistic) data, never lorem ipsum, because placeholder content hides
the layout problems real content causes.

**Done when:** it would be useful to the viewer even looking this plain.

## Pass 1: Structure and hierarchy

- Rank every element: primary (one per view), secondary, tertiary, reference.
- Give the primary element the best position and the most space.
- Group related things; separate unrelated things. Check that proximity matches
  meaning.
- Choose the layout from the content's shape (comparison, sequence, ranking,
  one big number, narrative) rather than from habit.
- Cut or demote anything that does not serve the one takeaway.

**Done when:** squinting at it, or viewing it at thumbnail size, still shows
what matters most and the order to read in.

## Pass 2: Typography

- Pick one family, or two with clearly different jobs (e.g. display and text).
  Use fonts the medium can reliably render.
- Set a scale with real contrast between levels; adjacent sizes that differ by
  a point or two read as mistakes. Fewer sizes, further apart.
- Set body line length (roughly 45 to 75 characters) and line height (looser
  for body, tighter for large headings).
- Tighten letter-spacing slightly on large display text; open it on small
  uppercase labels.
- Use weight and color for emphasis before reaching for more sizes.
- Numbers in tables and metrics: tabular figures, right-aligned, consistent
  precision.

**Done when:** with color removed, hierarchy is still fully clear from type
alone.

## Pass 3: Spacing and alignment

- Choose a base unit (4 or 8) and take every gap from a short scale built on it.
- Space inside a group must be smaller than space between groups.
- Give the page generous outer margins; cramped edges are the fastest tell of a
  draft.
- Align everything to a small number of shared edges. Hunt for near-misses
  (things that almost line up) and resolve them.
- Check optical alignment where the math looks wrong: icons beside text,
  punctuation at edges, rounded shapes next to square ones.

**Done when:** you can draw a few straight lines through the layout and
everything sits on one of them, and no two gaps are "almost the same".

## Pass 4: Color

- Start from neutrals: a background, a surface, a text color, a muted text
  color, a hairline. Slightly tinted neutrals feel more considered than pure
  gray.
- Add one accent and reserve it for what matters (primary action, key number,
  the highlighted series).
- Give color a job. Semantic colors (good, bad, warning) only where the meaning
  is real, and never as the sole signal.
- Check contrast for all text against its actual background, including muted
  text and text on the accent.
- If the medium has light and dark modes, design both.

**Done when:** you can state what each color means, and the piece still works
in grayscale.

## Pass 5: Detail and craft

The pass that separates finished from nearly finished. See
`technique-catalog.md` for specific moves.

- Borders, radii, and shadows: one consistent treatment, as subtle as it can be
  while still working.
- Real typographic characters: proper quotes, en dashes in ranges, a true minus
  sign, non-breaking spaces between numbers and units.
- States and edges: empty, long, zero, negative, overflow, hover, focus.
- Add the content-specific touch: the annotation, callout, or layout shift that
  only this content would have.
- Title and labels say something. "Revenue grew 18% on enterprise renewals"
  beats "Revenue Overview".

**Done when:** zooming in on any corner shows the same care as the middle.

## Pass 6: Subtraction

Go through every non-content element and try removing it: rules, boxes,
backgrounds, icons, shadows, legends, repeated labels, a second accent.
Keep the removal if nothing is lost.

**Done when:** removing anything further would lose information or hierarchy.

## Pass 7: Fresh-eyes review

Render it and look at the result, not the source. Then run
`interrogation-checklist.md`. View it at the size and in the setting it will be
used: projected, on a phone, printed, at a glance. Fix, re-render, re-check.

**Done when:** the checklist passes and you would put your name on it.

## When a pass goes wrong

If a later pass keeps failing (spacing never looks right, color cannot fix the
hierarchy), the problem is usually upstream. Go back to Pass 1 rather than
piling on fixes; a structural problem cannot be styled away.
