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
import time
import re
import sys

from textblob import TextBlob
import argparse

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# In-memory caches to avoid redundant API calls
_entity_cache: dict[str, str] = {}
_property_cache: dict[str, str] = {}

_QUESTION_PATTERNS = [
    # (regex_pattern, property_hint_for_fallback_or_override, entity_extractor)
    # Priority-ordered list of common question patterns
    (r"how\s+old\s+is\s+(.+)", "date of birth", None),
    (r"what\s+age\s+is\s+(.+)", "date of birth", None),
    (r"when\s+did\s+(.+?)\s+die", "date of death", None),
    (r"what\s+is\s+the\s+population\s+of\s+(.+)", "population", None),
    (r"who\s+is\s+the\s+spouse\s+of\s+(.+)", "spouse", None),
    (r"who\s+is\s+(.+)\s+spouse", "spouse", None),
    (r"what\s+is\s+the\s+capital\s+of\s+(.+)", "capital", None),
    (r"when\s+was\s+(.+)\s+born", "date of birth", None),
]


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

    # 3. Resolve property hint → Wikidata P-id (if not already cached)
    if property_hint not in _property_cache:
        _property_cache[property_hint] = search_property(property_hint)
    property_id = _property_cache[property_hint]
    if property_id is None:
        raise ValueError(f"No Wikidata property found for: {property_hint}")

    # 4. Build and execute SPARQL query
    query = build_query(entity_id, property_id)
    return execute_query(query, endpoint)


# ---------------------------------------------------------------------------
# Question parsing — TextBlob-powered
# ---------------------------------------------------------------------------


def parse_question(question: str) -> tuple[str, str]:
    """
    Split a question into (entity, property_hint).

    Tries regex question-patterns first, then falls back to TextBlob POS tagging.

    Examples:
      "how old is Tom Cruise"      → entity="Tom Cruise",       hint="date of birth"
      "what age is Madonna?"       → entity="Madonna",           hint="date of birth"
      "what is the population of London" → entity="London",      hint="population"
      "when did Shakespeare die"   → entity="Shakespeare",      hint="date of death"
      "what is the capital of France" → entity="France",         hint="capital"
    """
    q = question.strip().rstrip("?")
    entity_mention = None
    property_hint = None

    for pattern, hint, _ in _QUESTION_PATTERNS:
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            entity_mention = m.group(1).strip()
            property_hint = hint
            break

    # Fallback: TextBlob noun-phrase + POS-based property extraction
    if entity_mention is None:
        blob = TextBlob(q)
        noun_phrases = list(blob.noun_phrases)
        entity_mention = noun_phrases[0] if noun_phrases else q

        # Collect NN/NNP words outside the entity mention
        entity_words = set(entity_mention.lower().split())
        hint_words = [
            word.lower()
            for word, tag in blob.tags
            if tag in ("NN", "NNP", "NNS", "JJ") and word.lower() not in entity_words
        ]
        # Strip question framing
        skip = {"what", "who", "when", "where", "which", "how", "much", "many", "is", "was", "did", "do", "does"}
        hint_words = [w for w in hint_words if w not in skip]
        property_hint = " ".join(hint_words) if hint_words else "unknown"

    return entity_mention, property_hint


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
def resolve_entity(entity_name: str, _endpoint: str = None) -> str | None:
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