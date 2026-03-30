# KGG Technical Test — Knowledge Graph Engineer

A SPARQL-based Wikidata question-answering system written in Python. No external graph libraries — pure stdlib + TextBlob.

## Architecture

```
Question
  ├─ parse_question()          — TextBlob POS tagging + regex patterns → (entity, property_hint)
  ├─ resolve_entity()           — Wikidata Search API → Q-id
  ├─ search_property()          — Wikidata Property Search API → P-id
  ├─ build_query()             — SPARQL SELECT for the Q/P pair
  └─ execute_query()            — POST to Wikidata Query Service → answer
```

## Key design decisions

- **Dynamic entity resolution** — no hardcoded Q-ids. Any named entity works (Tom Cruise, Madonna, London, New York, etc.) via the Wikidata Search API.
- **Dynamic property discovery** — no hardcoded P-ids. Property hints like "date of birth", "population", "spouse", "capital" are resolved at runtime via the Wikidata Property Search API.
- **TextBlob-powered parsing** — POS tagging identifies the entity noun phrase and the property-describing words in any question, with regex fallbacks for ambiguous patterns like "how old is X" (where "old" is adjective, not noun).
- **SPARQL age computation** — for P569 (date of birth), age is computed in the query using `YEAR(NOW()) - YEAR(?bd)` minus a birthday check, so the result is always current.
- **Full IRIs in SPARQL** — uses `<http://www.wikidata.org/entity/Q37079>` form instead of `wd:Q37079` prefix, which is required for POST-formatted queries to the Wikidata Query Service.
- **In-memory caching** — both entity and property lookups are cached per-run to avoid redundant HTTP calls.

## Extensibility

Adding a new question type only requires registering a new regex pattern (or relying on TextBlob fallback) that maps to the property hint string — e.g. "capital of X" → Wikidata searches "capital" → finds P36 → SPARQL queries it.

## Run

```bash
pip install textblob
python ask.py
# All assertions passed
```
