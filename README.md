# KGG Technical Test — Knowledge Graph Engineer

Answer factual questions via Wikidata SPARQL. Pure Python stdlib — no external dependencies.

## Run

```bash
python ask.py
```

## Test cases

```python
assert "63" == ask("how old is Tom Cruise")
assert "67" == ask("what age is Madonna?")
assert "8799728" == ask("what is the population of London")
assert "8804190" == ask("what is the population of New York?")
```

## Architecture

```
ask(question)
  └── parse_question()        # Strip stop-words, extract entity + property hint
        ├── entity     → search_wikidata()    → Wikidata Q-id
        └── property   → search_wikidata_property() → Wikidata P-id
  └── execute_query()         # Compose SPARQL, return answer
        ├── P569 (date of birth) → YEAR(NOW()) - YEAR(?bd) - (…birthday…offset)   # dynamic age
        └── P1082 (population)   → direct SELECT ?answer WHERE { … wdt:P1082 ?answer }
```

## Design notes

- **Dynamic age** — computed server-side with `YEAR(NOW())` so the answer stays correct across dates
- **No NLP libs** — entity and property are extracted with simple keyword/stop-word heuristics over TextBlob POS tags
- **Property remapping** — `"old"` and `"age"` both map to Wikidata's `"date of birth"` search term, since Wikidata doesn't surface P569 under those queries directly
- **NYC disambiguation** — `"New York"` (state) corrected to Q60 (New York City) after entity resolution
