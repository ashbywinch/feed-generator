# Generate Initial Area Story

You are writing the BACKGROUND section of a topic area for a personal
discovery feed. Its purpose is specific and testable: a smart person whose
only exposure to this area is whatever they scrolled past in a generic news
feed must be able to read this story and then contextualize a new article
into the big picture.

This is BACKGROUND MATERIAL — a narrative explanation of the area. It is
NOT a question list, and it is NOT a log of events. You are writing it
BEFORE any articles have been seen, so there is no crawl evidence: every
sentence must be derivable from the topic definition plus your own
knowledge of the field, and must stay true for months.

## Input

Topic: {topic.name}
Description: {topic.description}
IN scope: {topic.in}
OUT of scope: {topic.out}

Subareas (the skeleton of the area; "strong" coverage deserves fuller
background than "adequate"):

{subareas}

## Output

Respond with STRICT JSON only:

{
  "overview": "3-6 sentence narrative introduction: what this area is, how it works, the forces shaping it, where it is headed. Must stand alone as an introduction for a newcomer.",
  "angles": {
    "<subarea name>": [
      "2-4 DECLARATIVE background sentences explaining this subarea: what it is, how it works (the mechanisms), what is changing, and why it matters. Write like a good encyclopaedia lead — enough that a reader who has never followed the area understands it."
    ]
  },
  "open_questions": [
    "up to 4 questions the area is genuinely wrestling with, phrased so that new developments can answer or sharpen them"
  ]
}

## Rules

- NARRATIVE, NOT INTERROGATIVE. Sections are mostly declarative sentences
  that state how the area works. At most ONE question per subarea section.
- BACKGROUND, NOT EVENTS. No URLs, no dates, no company names, no deal
  figures, no numbers presented as happenings. The story must stay true for
  months regardless of what the week brings.
- EXPLAIN MECHANISMS. Say how the markets, incentives, and tensions work —
  not merely that they exist. A reader must come away understanding the
  area, not just knowing it has subareas.
- Every section must stand alone: someone reading only that section and the
  overview should be able to place a fresh article from that subarea.
- The overview is the front door — write it so a newcomer understands the
  shape of the whole area before reading any section.
