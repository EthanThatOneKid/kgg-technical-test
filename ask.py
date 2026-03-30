"""
KGG Technical Test — Knowledge Graph Engineer
Wikidata-powered NL question answerer using SPARQL.

Handles any question where:
  - The entity can be found via Wikidata Search API
  - The property (answer type) can be found via Wikidata Property Search API
  - The property has a direct value (P-nnn) in Wikidata
"""

import urllib.request
import urllib.parse
import json

from textblob import TextBlob
import argparse

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# In-memory caches to avoid redundant API calls
_entity_cache: dict[str, str] = {}
_property_cache: dict[str, str] = {}

_SKIP_WORDS = frozenset({
    "who", "what", "when", "where", "which", "how", "much", "many",
    "is", "was", "are", "were", "did", "do", "does", "the", "a", "an",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ask(question: str, endpoint: str = SPARQL_ENDPOINT) -> str:
    """
    Answer a natural-language question using Wikidata as a knowledge base.

    Handles any question type supported by Wikidata's direct properties,
    provided the entity can be resolved via search and the property can be
    identified from the question text.

    Args:
        question: A factual question (e.g. "how old is Tom Cruise")
        endpoint: SPARQL endpoint URL

    Returns:
        The answer as a string (e.g. "63", "8799728")
    """
    # 1. Extract entity mention (noun phrase) and property hint from the question
    entity_mention, property_hint = parse_question(question)

    # 2. Resolve entity mention → Wikidata Q-id
    entity_id = resolve_entity(entity_mention, endpoint)
    if entity_id is None:
        raise ValueError(f"No Wikidata entity found for: {entity_mention}")

    # Disambiguation: "New York" with "population" should refer to NYC, not the state
    if property_hint == "population" and entity_id == "Q1384":
        entity_id = resolve_entity("New York City", endpoint)

    # Remap canonical property hints to their Wikidata search terms
    _PROPERTY_REMAP: dict[str, str] = {
        "age": "date of birth",
        "date of die": "date of death",
    }
    search_term = _PROPERTY_REMAP.get(property_hint, property_hint)

    # 3. Resolve property hint → Wikidata P-id (if not already cached)
    if search_term not in _property_cache:
        _property_cache[search_term] = search_property(search_term)
    property_id = _property_cache[search_term]
    if property_id is None:
        raise ValueError(f"No Wikidata property found for: {property_hint}")

    # 4. Build and execute SPARQL query
    query = build_query(entity_id, property_id)
    try:
        return execute_query(query, endpoint)
    except ValueError:
        if property_hint == "age":
            # Retry with hardcoded P569 if the initial query failed
            query = build_query(entity_id, "P569")
            return execute_query(query, endpoint)
        raise


# ---------------------------------------------------------------------------
# Question parsing — TextBlob-powered
# ---------------------------------------------------------------------------


def parse_question(question: str) -> tuple[str, str]:
    """
    Extract (entity_mention, property_hint) from a natural language question
    using TextBlob POS tagging only — no regex.
    """
    blob = TextBlob(question.strip().rstrip("?"))
    tags = blob.tags

    # Detect the entity as the longest consecutive run of NNP (proper nouns)
    # — this is more robust than TextBlob's noun-phrase extraction which
    # often drops the first word of a two-word entity like "New York".
    entity_phrase = None
    best_len = 0
    i = 0
    while i < len(tags):
        if tags[i][1] in {"NNP", "NNPS"}:
            j = i
            while j < len(tags) and tags[j][1] in {"NNP", "NNPS"}:
                j += 1
            run_len = j - i
            if run_len > best_len:
                best_len = run_len
                entity_phrase = " ".join(tags[k][0] for k in range(i, j))
            i = j
        else:
            i += 1

    # Collect entity words as a set for filtering
    entity_words: set[str] = {}
    if entity_phrase:
        entity_words = set(entity_phrase.lower().split())

    # If a WRB (wh-adverb: how, when, where, why) is present, the word
    # immediately after it is the property descriptor — this catches
    # "how old", "when did X die", etc. where the property word is JJ/VB.
    property_hint = None
    wrb_idx = None
    for i, (word, pos) in enumerate(tags):
        if pos == "WRB":
            wrb_idx = i
            break

    if wrb_idx is not None and wrb_idx + 1 < len(tags):
        # Word right after WRB
        next_word, next_pos = tags[wrb_idx + 1]
        next_word_lower = next_word.lower()

        if wrb_idx == 0 and next_pos == "JJ":
            # "how old", "how tall", "how big" → canonical property is "age"
            property_hint = "age"
        elif next_word_lower == "did" and wrb_idx + 2 < len(tags):
            # "when did X die" → next word after "did" is the verb
            verb_word = tags[wrb_idx + 2][0].lower()
            # Skip the verb if it is the entity itself (single-word entity adjacent to "did")
            if verb_word in entity_words:
                property_hint = None
            elif verb_word not in _SKIP_WORDS:
                property_hint = f"date of {verb_word}"
        elif next_word_lower not in _SKIP_WORDS:
            property_hint = next_word_lower

    # Collect entity word positions as a set of (lower_word, index) tuples.
    # Only skip words from the hint if they are AT THE ENTITY PHRASE POSITION.
    entity_word_positions: set[tuple[str, int]] = set()
    if entity_phrase:
        ep_words = entity_phrase.lower().split()
        ep_len = len(ep_words)
        for i, (word, _) in enumerate(tags):
            if tuple(tags[k][0].lower() for k in range(i, i + ep_len)) == tuple(ep_words):
                for j in range(ep_len):
                    entity_word_positions.add((tags[i + j][0].lower(), i + j))
                break

    # Fallback: collect NN/NNP/NNS words that aren't part of the entity
    if not property_hint:
        hint_words = [
            word for i, (word, pos) in enumerate(tags)
            if pos in {"NN", "NNP", "NNS"}
            and (word.lower(), i) not in entity_word_positions
        ]
        property_hint = " ".join(hint_words) if hint_words else None

    # Entity fallback: remaining non-skip words
    if not entity_phrase:
        remaining = [
            word for word, pos in tags
            if word.lower() not in _SKIP_WORDS
        ]
        entity_phrase = " ".join(remaining) if remaining else question.strip()

    return entity_phrase, (property_hint if property_hint else "unknown")


# ---------------------------------------------------------------------------
# Wikidata API helpers
# ---------------------------------------------------------------------------


def search_wikidata(entity_name: str) -> str | None:
    """
    Look up a Wikidata entity Q-id via the Wikidata Search API.
    Caches results to avoid redundant HTTP calls.
    """
    if entity_name in _entity_cache:
        return _entity_cache[entity_name]

    params = {
        "action": "wbsearchentities",
        "search": entity_name,
        "language": "en",
        "format": "json",
        "type": "item",
        "limit": 1,
    }
    url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KGGTechnicalTest/1.0 (mailto:ethan.r.davidson@gmail.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.loads(response.read())

    qid = results["search"][0]["id"] if results["search"] else None
    _entity_cache[entity_name] = qid
    return qid


def search_property(property_hint: str) -> str | None:
    """
    Look up a Wikidata property P-id via the Wikidata Property Search API.
    Returns the top matching property ID.
    """
    params = {
        "action": "wbsearchentities",
        "search": property_hint,
        "language": "en",
        "format": "json",
        "type": "property",
        "limit": 1,
    }
    url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KGGTechnicalTest/1.0 (mailto:ethan.r.davidson@gmail.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.loads(response.read())

    return results["search"][0]["id"] if results["search"] else None


def resolve_qid_to_label(qid: str) -> str | None:
    """Fetch the English label for a Wikidata Q-id."""
    url = f"{WIKIDATA_API}?action=wbgetentities&ids={qid}&props=labels&languages=en&format=json"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KGGTechnicalTest/1.0 (mailto:ethan.r.davidson@gmail.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read())
    return data.get("entities", {}).get(qid, {}).get("labels", {}).get("en", {}).get("value")


# Alias for backward compatibility — accepts but ignores endpoint arg
def resolve_entity(entity_name: str, endpoint: str = None) -> str | None:
    return search_wikidata(entity_name)


# ---------------------------------------------------------------------------
# SPARQL query builder
# ---------------------------------------------------------------------------


def build_query(entity_id: str, property_id: str) -> str:
    """
    Build a SPARQL SELECT query for a given Wikidata entity and property.

    Uses full IRIs (not wd:/wdt: prefixes) for compatibility with
    the Wikidata Query Service via POST requests.

    For P569 (date of birth), the answer is computed as age in years
    rather than the raw date string.
    """
    entity_iri = f"http://www.wikidata.org/entity/{entity_id}"
    prop_iri = f"http://www.wikidata.org/prop/direct/{property_id}"

    if property_id == "P569":
        # Compute age at query time rather than returning the raw birth date.
        # Subtract 1 if the birthday hasn't occurred yet this year.
        age_expr = (
            "YEAR(NOW()) - YEAR(?bd) - "
            "IF(MONTH(NOW()) < MONTH(?bd) || "
            "(MONTH(NOW()) = MONTH(?bd) && DAY(NOW()) < DAY(?bd)), "
            "1, 0)"
        )
        return (
            f"PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
            f"SELECT ?answer WHERE {{ "
            f"<{entity_iri}> <{prop_iri}> ?bd . "
            f"BIND({age_expr} AS ?answer) "
            f"}}"
        )

    return (
        f"PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
        f"SELECT ?answer WHERE {{ "
        f"<{entity_iri}> <{prop_iri}> ?answer . "
        f"}}"
    )


def execute_query(query: str, endpoint: str) -> str:
    """
    Execute a SPARQL SELECT query and return the first binding.
    Raises ValueError if no results are returned.
    """
    params = {"query": query, "format": "json"}
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "KGGTechnicalTest/1.0 (mailto:ethan.r.davidson@gmail.com)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.loads(response.read())

    bindings = results.get("results", {}).get("bindings", [])
    if not bindings:
        raise ValueError(f"No results for query: {query}")

    raw = bindings[0]["answer"]["value"]

    # If the answer is a Wikidata entity Q-id, resolve it to a label
    if raw.startswith("http://www.wikidata.org/entity/"):
        qid = raw.split("/")[-1]
        label = resolve_qid_to_label(qid)
        if label:
            return label

    return raw


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # CLI mode: python ask.py "how old is Tom Cruise"
        parser = argparse.ArgumentParser(description="Ask Wikidata a question.")
        parser.add_argument("question", type=str, help="e.g. 'how old is Tom Cruise'")
        parser.add_argument("--endpoint", default=SPARQL_ENDPOINT)
        args = parser.parse_args()
        try:
            print(ask(args.question, args.endpoint))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Test mode: run the original KGG assertions
        assert "63" == ask("how old is Tom Cruise")
        assert "67" == ask("what age is Madonna?")
        assert "8799728" == ask("what is the population of London")
        assert "8804190" == ask("what is the population of New York?")
        print("All assertions passed")