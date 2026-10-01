# Design philosophy

Principles for deciding how far to push and when to stop. Read this when you
are choosing a direction or when a design feels either timid or overworked.

## 1. Content is the design

Design is the arrangement of meaning, not a layer on top of it. Start from what
the content is saying and let form follow. A deck whose argument is "we have
one problem" should not have twelve equally loud slides. If the content is
weak, vague, or padded, fix that first; no typography rescues a slide with
nothing to say.

## 2. Decide, don't default

A default is a decision someone else made for a different problem. Every
visible property (typeface, size, color, radius, gap, alignment, chart type)
should survive the question "why this one?". "It's what the library gives you"
is not an answer. You may well land on the default; land on it knowingly.

## 3. Hierarchy is most of the job

A viewer should know in two seconds what matters most, what comes second, and
what is reference material. Most generic output fails here: everything is the
same size, weight, and color, so nothing leads. Solve hierarchy with the
fewest tools possible, in this order: position, size, weight, color. If you
need all four on one element, the levels below it are too loud.

## 4. One bold move, everything else quiet

Boldness and restraint are not opposites; restraint is what makes boldness
legible. Give each piece a small budget: one confident gesture (an oversized
number, a single saturated accent, a dramatic crop, an unusual grid) and let
the rest recede to support it. Two bold moves compete. Zero reads as timid.
When unsure which element earns the move, pick the one tied to the single thing
the viewer should leave with.

## 5. Build a system, then obey it

Define the type scale, spacing unit, palette, and grid once, and derive
everything from them. Consistency is what the eye reads as "professional":
five slightly different grays or gaps look accidental even when no one can say
why. Break the system only deliberately and only once, since a single exception
reads as emphasis and several read as mess.

## 6. Specificity is what "hand-crafted" means

Template work fits any content. Crafted work has details that exist only
because of this content: a column widened because these labels are long, an
annotation on the one data point that matters, a layout that changes on the
slide where the argument turns. Look for the moment in the content that
deserves special treatment and give it some.

## 7. Borrow principles, not skins

References (see `reference-library.md`) teach ways of thinking: the Swiss grid,
Stripe's layering, Linear's density. Copying their surface (the gradient, the
dark theme, the typeface) produces a knock-off and trades one template for
another. Ask what problem the reference was solving and whether you have the
same problem.

## 8. Respect the medium

A spreadsheet is a working tool, not a web page; its craft is in number
formats, alignment, frozen headers, and restraint. A slide is seen from across
a room for a few seconds. A PDF may be printed in grayscale. A dashboard is
read daily, so calm beats spectacle. Excellence looks different in each, and
importing one medium's flourishes into another is a common way to look amateur.

## 9. Legibility and access are part of taste

Low-contrast gray text, tiny labels, color as the only signal, and motion with
no purpose are not sophisticated; they are failures that happen to be
fashionable. If someone cannot read it, it is not well designed. Meeting
contrast and size minimums never made a good design worse.

## 10. Subtract last

After the design works, remove things: borders that a gap could replace,
labels that repeat the title, a third color, a decorative icon, a drop shadow.
Each removal should make what remains clearer. If removing something changes
nothing, it was noise.

## 11. The user's context outranks your taste

An existing brand, design system, house template, or stated preference is a
constraint to do excellent work within, not an obstacle. So is the user's
purpose: an internal ops tool should be efficient before it is beautiful. A
director's taste shows in how well the work serves its setting.

## 12. Know when to stop

Refinement has diminishing returns, then negative ones. Signs you are past the
peak: you are changing things back, adjustments are matters of mood rather than
clarity, or new detail is drawing attention to itself. Ship.
