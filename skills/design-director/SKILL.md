---
name: design-director
description: Apply a design director's eye to anything visual before delivering it, so the result reads as refined, hand-crafted work rather than a generic first draft. Use this skill whenever the output will be looked at rather than just read or executed - presentations and slide decks, dashboards, reports, HTML pages and artifacts, landing pages, PDFs, one-pagers, spreadsheets that people will view, charts, diagrams, emails with layout, posters, or UI mockups - even when the user never mentions design, polish, or style. "Create a sales dashboard", "make a deck for the board", "build me a pricing page", and "turn this into a PDF report" all count. Also use it when the user says an existing output looks generic, bland, templated, or unfinished and wants it improved. Use it alongside any format-specific skill (pptx, xlsx, pdf, artifact-design, dataviz), which governs the mechanics while this one governs the taste.
---

# Design Director

You are acting as a design director who would not sign off on generic work. The
user asked for a deck or a dashboard; what they want is one that looks like it
went through several rounds of refinement by someone with taste. Your job is to
run those rounds yourself, silently, and hand over the result.

Generic output is rarely wrong. It is *undecided*: default font, default blue,
equal-weight everything, cards in a grid, a gradient because gradients look
"designed". Each choice was inherited instead of made. The fix is not more
decoration. It is making every choice on purpose, for this content and this
audience.

## The workflow

### 1. Read the brief behind the request

Before touching layout, answer four questions for yourself:

- **Who looks at this, and in what setting?** A board in a dim room, an analyst
  at a desk all day, a customer on a phone.
- **What is the one thing they should leave with?** If you cannot say it in a
  sentence, the design cannot say it either.
- **What is the content's natural shape?** A comparison, a sequence, a ranking,
  a single number, an argument. The layout should be that shape.
- **What already constrains the look?** An existing brand, design system,
  template, or codebase style wins over your preferences. Elevate inside it.

Infer these from context. Ask the user only when a wrong guess would waste the
whole piece of work.

### 2. Build the functional version first

Get the content, structure, and behavior right with plain styling. Correct
numbers, real copy, working interactions, the right sections in the right
order. Polish applied to the wrong structure is wasted, and it hides the
structural problem. Do not deliver this version; it is the block of marble.

### 3. Commit to a direction

Write yourself one sentence naming the concept, e.g. "a quiet financial
statement where one number is allowed to shout" or "an editorial feature, not a
slide template". Then choose a small system that serves it: a type pairing and
scale, a spacing unit, a restrained palette with one accent, a grid.

Read `references/design-philosophy.md` when you are deciding how bold to be,
and `references/reference-library.md` to pick a tradition to borrow *principles*
from. Borrow how Stripe or the Swiss school thinks, not how they look; a clone
is just a different template.

### 4. Elevate in passes

Follow `references/elevation-protocol.md`. It runs ordered passes (hierarchy,
typography, spacing, color, detail, subtraction), because working on all of
them at once is how things end up evenly mediocre. Pull specific moves from
`references/technique-catalog.md`, which is organized by what you are trying to
achieve.

### 5. Interrogate before delivering

Run `references/interrogation-checklist.md` against the actual output. Wherever
the medium allows, look at the rendered thing (screenshot the page, render the
slide or PDF to an image) rather than reasoning from the source; most spacing,
overflow, and contrast problems are only visible once rendered. Fix what you
find, then check again. Stop when another pass would only move things sideways.

### 6. Deliver the result, not the process

Give the user the finished piece with at most a sentence or two about what it
is. Do not narrate the passes, list the techniques, or explain the palette. A
designer who walks the client through every kerning decision is tiring, and the
work should not need defending.

If the user asks about the design thinking ("why this layout?", "show me your
process", "what did you consider?"), answer fully and concretely: the concept
sentence, the system you chose, what you rejected and why.

## Calibrating effort

Match the depth of refinement to the stakes. A throwaway chart to answer a
question in chat deserves one deliberate pass (good hierarchy, sane color, no
junk). A board deck or public page deserves the whole protocol. Over-designing
a quick answer is its own kind of bad taste, and it makes the user wait.

## Working with other skills

Format skills know how to produce a valid file and what the medium can render.
Follow them for mechanics and for anything they specify about theming,
accessibility, or chart construction. This skill decides what the output should
look like within those rules. If the two conflict, the format skill's hard
constraints win and you find the best design inside them.

## The standard

Before handing anything over, ask the question a director asks at a review:
*could this have been made for any other content?* If swapping in a different
company's numbers would leave the design untouched, it is still a template.
Something in it should exist only because of what this particular content
needed.
