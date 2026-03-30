# KGG Technical Test — Knowledge Graph Engineer

A SPARQL-based Wikidata question-answering system written in pure Python (no external graph libraries).

## Run

```bash
python ask.py
```

## CLI

```bash
python ask.py "how old is Tom Cruise"        # → 63
python ask.py "what is the population of London"  # → 8799728
python ask.py "who is the spouse of Elon Musk"   # → Talulah Riley
python ask.py "what is the capital of France"    # → Paris
python ask.py "when did Shakespeare die"          # → 1616-04-23

python ask.py --help
```

## Architecture

```
Question
  → TextBlob POS tagging          Extract entity noun phrase + property hint words
  → Regex question patterns       Fallback for "how old", "when did" patterns
  → Wikidata Search API           Resolve entity name → Q-id
  → Wikidata Property Search API  Resolve property hint → P-id
  → SPARQL query                 Fetch the answer from Wikidata
  → Label resolution             Convert Q-id answers → human-readable names
  → Return string
```

## Design Decisions

| Decision | Rationale |
|---|---|
| TextBlob POS tagging | Identifies entity noun phrases and property-describing words from any question, without hardcoding question templates |
| Regex fallbacks for "how old"/"when did" | POS tags for "old" (JJ) and "die" (VB) are excluded by the NN/NNP/NNS filter — explicit patterns fill the gap |
| Full IRIs in SPARQL | Wikidata's SPARQL endpoint rejects `wd:Q-id` prefixed names in POST requests; full `<http://...>` IRIs are reliable |
| Wikidata Search API for entities *and* properties | Eliminates hardcoding — any entity or property Wikidata knows, the system can answer |
| Q-id → label resolution | Wikidata stores relations as Q-ids; resolving to names makes answers human-readable |

## Setup

```bash
pip install -r requirements.txt
```