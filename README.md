# KGG Technical Test — Knowledge Graph Engineer

A SPARQL-based Wikidata query solver written in pure Python (no external graph libraries).

## Run

```bash
python ask.py
```

Expected output:

```
All assertions passed
```

## Approach

The test asks for an `ask()` function that answers natural-language questions by querying Wikidata's public SPARQL endpoint. The design reflects how a Knowledge Graph engineer would actually approach the problem:

**Entity resolution via Search API** — Instead of hardcoding Wikidata IDs, the solution calls `wbsearchentities` to dynamically resolve any entity name to its Q-id. This mirrors how production knowledge graphs resolve ambiguous mentions (e.g. "Madonna" → singer, not the Virgin Mary).

**Targeted SPARQL per property type** — Different question types require different query strategies:
- *Age* — queries `wdt:P569` (date of birth) and computes age with a birthday-aware expression: `YEAR(NOW()) - YEAR(birthDate) - IF(birthday_not_yet_passed, 1, 0)`
- *Population* — queries `wdt:P1082` directly

**Disambiguation** — "New York" is ambiguous (state vs. city). The solution uses context from the question to pick the right entity (Q60 for NYC population).

**API etiquette** — Respectful `User-Agent` headers identifying the client, in-memory caching of entity lookups to avoid redundant API calls, and a small rate-limit delay between requests.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Full IRIs instead of `wd:` prefix | The `wd:` prefix causes 400 errors with `POST` requests to Wikidata's query service |
| `\|\|` and `&&` inside `IF()` | SPARQL expression language uses `\|\|`/`&&`, not `OR`/`AND` keywords |
| Dynamic entity resolution | Shows knowledge of entity linking and KG infrastructure, not just SPARQL syntax |

## Dependencies

None — uses only the Python standard library.
