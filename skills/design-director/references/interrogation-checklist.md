# Design interrogation checklist

Questions to ask of the rendered output before delivering. A "no" or "not
sure" is something to fix, not to note. Run the quick gate always; run the full
list for anything presented, published, or reused.

## Quick gate (always)

1. Can I say in one sentence what the viewer should take away, and is that the
   most prominent thing on the page?
2. At thumbnail size, is the hierarchy still obvious?
3. Did I choose the typeface, palette, and layout, or inherit them?
4. Is there anything here that exists only because of this specific content?
5. Is all text comfortably readable, with sufficient contrast?
6. Is anything clipped, overflowing, overlapping, or misaligned when rendered?

## Purpose and content

- Does the layout match the content's shape (comparison, sequence, ranking,
  single figure, argument)?
- Do titles and headings state findings rather than topics?
- Is every element earning its place? What happens if I delete it?
- Is the copy tight? Any filler, repetition, or placeholder text left?
- Would the intended audience, in their actual setting, get it in the time they
  have?

## Hierarchy and layout

- Is there exactly one primary element per view?
- Are there at most three or four clear levels of importance?
- Does the reading order follow the intended order of understanding?
- Is space distributed by importance, or is everything the same size?
- Is there a real grid, and does everything sit on it?
- Are related things close together and unrelated things apart?

## Typography

- How many families, sizes, and weights are in use? Could it be fewer?
- Are the size steps clearly different from each other?
- Are line lengths and line heights comfortable for the amount of text?
- Are numbers tabular and aligned where they are compared?
- Any orphans, awkward wraps, or headings stranded from their content?
- Are quotes, dashes, minus signs, and units typographically correct?

## Color

- Can I state the job of every color in use?
- Is the accent reserved for what matters, and used sparingly?
- Does all text meet contrast requirements on its real background?
- Does meaning survive without color (grayscale, color-blind viewers)?
- Are the neutrals consistent, rather than several near-identical grays?
- If there are light and dark modes, do both look designed?

## Spacing and alignment

- Do all gaps come from one scale? Any "almost equal" spacing?
- Are outer margins generous and consistent?
- Is space inside groups smaller than space between them?
- Are there near-miss alignments that should be resolved?
- Do icons, text baselines, and rounded shapes look aligned optically?

## Detail and craft

- Are borders, radii, and shadows one consistent, subtle system?
- Could any box or rule be replaced by whitespace?
- Are edge cases handled: long names, zeros, negatives, empty states, many
  items, few items?
- Are interactive states (hover, focus, disabled) considered, where relevant?
- Do the least glamorous parts (footers, legends, captions, last page) show the
  same care as the hero?

## The generic tells

If any of these are present without a deliberate reason, the piece still looks
like a first draft:

- Default system or library font with default sizes
- Default-blue links, buttons, or chart series
- A purple-to-blue gradient used as "design"
- Everything in rounded cards with a drop shadow, in an even grid
- Center-aligned everything
- An icon or emoji on every heading or bullet
- Slides that are all title plus bullet list
- Topic titles: "Overview", "Key Metrics", "Summary"
- Rainbow chart palette with a detached legend
- Heavy table borders on every cell
- Pure black text on pure white with no softening and no tinted neutrals
- Equal emphasis on every number
- Lorem ipsum or obviously fake data ("John Doe", "Company A")

## Restraint check

- Is there more than one bold move competing for attention?
- Is any decoration drawing the eye away from the content?
- Did I borrow a principle from a reference, or copy its look?
- Does the level of polish fit the stakes, or is this over-built?

## Final question

Would a design director put their name on this, and could it have been made
for any other content? Deliver when the answers are yes and no.
