# Generate Discovery Queries

You are writing the search-query set that drives discovery for ONE topic in a
personal discovery engine. The queries are executed against a global search
index (Exa) to find genuinely interesting, relevant articles that the
subscribed feeds might miss.

CRITICAL: the queries must be GLOBAL. The reader's interest is not bounded
by the UK or Europe — a policy or market development in Ethiopia, Vietnam,
or Texas counts exactly as much as one in the UK. The current query set's
mistake was anchoring queries to one country ("GB grid connection queue
statistics", "UK CfD allocation round results"). Do not repeat that.

## Input

Topic: {topic.name}
Description: {topic.description}
IN scope: {topic.in}
OUT of scope: {topic.out}

Subareas (the skeleton of the area; "strong" coverage deserves more query
attention than "adequate"):

{subareas}

## Output

Respond with STRICT JSON only. Return EXACTLY ONE query per subarea — same
number of queries as subareas, each explicitly serving one subarea:

{
  "queries": {
    "<subarea name>": "the search query for this subarea",
    ...
  }
}

## Rules

- GLOBAL, NOT LOCAL. No country/region names, no "GB"/"UK"/"European"
  qualifiers, no regulator names tied to one jurisdiction (Ofgem, NESO,
  Elexon). Describe the mechanism, market, or development generically:
  "grid connection queue statistics" not "GB grid connection queue
  statistics".
- MECHANISM-FIRST. Query for the underlying phenomenon: "battery storage
  revenue streams as markets mature", "floating offshore wind auction
  results", "demand-side flexibility market design". A reader anywhere in
  the world should find it.
- COVERAGE. Aim for one query per subarea. Strong subareas may
  get two; group related subareas under one query if you need fewer. The set
  as a whole should span every subarea.
- GROUNDED IN THE SUBAREA NAMES. Each query should carry distinctive words
  from the subarea name it serves (e.g. for a subarea called "AI market
  structure & capital markets" use words like market-structure or capital in
  the query), so coverage can be checked mechanically.
- DIVERSE. Each query targets a different angle (policy, market data,
  technology, economics, geopolitics). No near-duplicates.
- SEARCH-SHAPED. Formulate for a search index: concrete noun phrases a
  good article would contain, 2-6 words each. Not questions.
- Stay inside the IN scope; avoid the OUT scope.
