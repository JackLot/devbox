# Technique catalog

Specific visual moves, organized by what you are trying to achieve. Find the
goal, pick one or two moves, and apply them consistently. These are options,
not a checklist; using many at once produces the over-designed look.

## Contents

- Establish hierarchy
- Make it feel calm and spacious
- Make it feel dense but orderly
- Direct attention to one thing
- Make numbers easy to read
- Make color carry meaning
- Add depth without clutter
- Separate things without boxes
- Make it feel specific and hand-made
- Make text a pleasure to read
- Medium notes: slides, dashboards, spreadsheets, PDFs and print, web pages

## Establish hierarchy

- **Scale jump.** Make the primary element two to four times the size of the
  secondary, not 20% bigger. Timid differences look accidental.
- **Weight and tone before size.** Bold dark for labels that matter, regular
  muted for supporting text, all at the same size. Keeps the scale short.
- **De-emphasize rather than emphasize.** Quiet the secondary content (smaller,
  lighter, grayer) instead of making the primary louder.
- **Label under value.** For metrics, a large value with a small muted label,
  not a bold label with a same-size value.
- **Position as rank.** Top-left (in left-to-right languages) and the optical
  center carry the most weight; put the answer there, not the logo.

## Make it feel calm and spacious

- **Double the margins** you first reach for, then check whether content still
  fits. Usually it does.
- **Fewer, larger elements** per view. Split one crowded slide or panel in two.
- **Narrow the text column** and let empty space sit beside it.
- **One alignment edge.** Left-align everything to a single strong line.
- **Asymmetric space.** More room above a heading than below it binds the
  heading to its content.

## Make it feel dense but orderly

For tools people use all day, density is a feature.

- **Tight rows, generous columns.** Reduce vertical padding; keep horizontal
  breathing room so columns stay distinct.
- **Smaller type, stronger alignment.** Small text reads fine when edges are
  strict and numbers are tabular.
- **Muted chrome.** Headers, borders, and controls in low-contrast neutrals so
  data is the darkest thing on screen.
- **Progressive disclosure.** Show the summary; reveal detail on hover, expand,
  or drill-down.

## Direct attention to one thing

- **Single accent.** Everything neutral except the one element that matters.
- **Gray out the context.** In a chart, all series in gray, the subject series
  in the accent, labeled directly.
- **Isolation.** Surround the key element with more empty space than anything
  else gets.
- **Break the grid once.** One element that overhangs, bleeds, or spans columns
  reads as intentional emphasis.
- **Annotation.** A short note with a thin leader line on the exact point that
  matters ("Price change, March").

## Make numbers easy to read

- **Tabular, lining figures** so digits align in columns.
- **Right-align numbers, left-align text,** headers aligned with their column.
- **Consistent precision** within a column; round to what the decision needs.
- **Units once,** in the header or a muted suffix, not repeated on every row.
- **Scale the unit** (1.2M, not 1,204,387) unless exactness is the point.
- **Deltas with sign and direction,** plus color as a second cue, never the
  only one.
- **Thousands separators** always; a true minus sign for negatives.
- **Sparkline beside the figure** when the trend matters as much as the level.

## Make color carry meaning

- **Tinted neutrals.** Nudge grays slightly toward the accent hue (cool or
  warm) so the palette feels related.
- **One hue, several lightnesses** for sequential data; two opposed hues through
  a neutral midpoint for diverging data; distinct hues only for categories.
- **Reserve saturation.** Large areas low-saturation; small areas can be vivid.
- **Semantic colors used sparingly** so a red value still alarms.
- **Accent on under 10% of the surface.** More and it stops being an accent.
- **Off-black and off-white.** Slightly softened extremes feel less harsh than
  pure #000 on pure #fff, while keeping strong contrast.

## Add depth without clutter

- **Surface steps.** Background, surface, raised surface, each a small
  lightness step apart, instead of borders everywhere.
- **Soft, layered shadows.** Two low-opacity shadows (one tight, one wide) look
  more natural than one heavy one. Use for things that truly float.
- **Hairlines.** 1px borders at low contrast; a border you notice is too strong.
- **Subtle gradient or tint** on a hero area, held to a narrow range of one
  hue, rather than a rainbow sweep.
- **Consistent radius.** One radius for containers, a smaller related one for
  controls. Nested radii should shrink inward.

## Separate things without boxes

Boxes around everything is the signature of template output.

- **Whitespace first.** A larger gap separates as well as a line.
- **Alignment as grouping.** Items sharing an edge read as a set.
- **A single rule** above a section, rather than a full border around it.
- **Background shift** for one region instead of outlining each item.
- **Zebra or hairline, not both,** in tables, and often neither with enough
  row height.

## Make it feel specific and hand-made

- **Headlines that state the finding,** not the topic.
- **Direct labels** on chart series instead of a detached legend.
- **Layout that follows the content,** e.g. a wider column for the item that
  has more to say, a full-bleed slide where the argument turns.
- **A considered detail in an unexpected place:** footers, empty states, table
  captions, the last slide.
- **Custom, restrained visual motif** drawn from the subject (a line weight, a
  shape, a crop) repeated quietly, in place of stock icons.
- **Real content everywhere.** Plausible names, numbers, and dates; no
  placeholder text.

## Make text a pleasure to read

- **Measure** of roughly 45 to 75 characters per line for body copy.
- **Line height** around 1.5 for body, 1.1 to 1.25 for large headings.
- **Tight tracking on large display type,** slightly open tracking on small
  caps or uppercase labels.
- **Balanced headings.** Avoid a single orphaned word on the last line.
- **Proper punctuation:** curly quotes, en dashes for ranges, real ellipses.
- **Left-aligned, ragged right** for body; avoid justified text without
  hyphenation and centered text beyond a couple of lines.

## Medium notes

### Slides

- One idea per slide; the title is the takeaway sentence.
- Type large enough to read from the back of a room; far less text than feels
  natural.
- Vary the rhythm: a full-bleed statement or single-number slide between
  denser ones. A deck where every slide is title-plus-bullets is the template
  look.
- Consistent margins and title position across slides so nothing jumps on
  advance.
- Replace bullets with structure where possible: three columns, a sequence, a
  before and after.

### Dashboards

- Lead with the handful of numbers that answer "are we okay?", then trends,
  then detail.
- Calm by default; color only where something needs attention.
- Size panels by importance rather than a uniform grid of equal cards.
- Every chart gets a plain-language title and directly labeled series.
- Follow the dataviz skill, if available, for chart form and palette rules.

### Spreadsheets

- Craft here is restraint: one font, consistent number formats, aligned
  columns, sensible widths, frozen header row.
- Header row distinguished by weight and a bottom border, not a loud fill.
- Inputs, calculations, and outputs visually distinguishable and kept
  separate.
- Gridlines off or very light on summary sheets; conditional formatting only
  where it flags something.
- Totals set apart with a top rule and weight.

### PDFs and print

- Real margins, a proper type scale, page numbers, and running heads on long
  documents.
- Check that it survives grayscale and that nothing important sits at the
  trim edge.
- Control page breaks: no heading stranded at the bottom, no table split
  awkwardly.
- A cover or title block with intent, not a centered title in the default font.

### Web pages and HTML artifacts

- Responsive from phone to wide desktop; cap content width so lines stay
  readable.
- Light and dark themes both designed, not one inverted.
- Interactive states (hover, focus, active, disabled) all styled.
- Motion short and purposeful, and respecting reduced-motion preferences.
