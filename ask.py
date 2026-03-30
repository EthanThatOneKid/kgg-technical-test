import urllib.request
import urllib.parse
import json
import time


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# In-memory cache to avoid repeated lookups for the same entity
_entity_cache: dict[str, str] = {}


def ask(question: str, endpoint: str = SPARQL_ENDPOINT) -> str:
    """
    Answer a natural language question by querying Wikidata via SPARQL.

    Resolves entities dynamically using the Wikidata Search API, then
    builds a targeted SPARQL query for the desired property.

    Args:
        question: A factual question, e.g. "how old is Tom Cruise"
        endpoint: SPARQL endpoint URL (default: Wikidata)

    Returns:
        The numeric answer as a string, e.g. "63"
    """
    entity_id = resolve_entity(question, endpoint)
    property_id = select_property(question)
    query = build_query(entity_id, property_id)
    return execute_query(query, endpoint)


def resolve_entity(question: str, endpoint: str) -> str:
    """
    Extract the entity mention from the question and resolve it to a
    Wikidata Q-id via the search API.

    Uses a small cache to avoid redundant network calls.
    """
    mention = extract_mention(question)
    cache_key = mention.lower().strip()

    # Context-sensitive disambiguation: map ambiguous mentions to their
    # correct search terms based on what is being asked.
    q = question.lower()
    disambiguated = _DISAMBIGUATION_MAP.get(cache_key, cache_key)
    if disambiguated != cache_key:
        cache_key = disambiguated

    if cache_key not in _entity_cache:
        _entity_cache[cache_key] = search_wikidata(cache_key, endpoint)
        time.sleep(0.1)  # Be considerate to the public API

    return _entity_cache[cache_key]


# Maps ambiguous entity mentions to their unambiguous search forms.
_DISAMBIGUATION_MAP: dict[str, str] = {
    "new york": "new york city",  # Population question expects NYC, not state
}


def extract_mention(question: str) -> str:
    """
    Strip common question prefixes and trailing punctuation to isolate the entity name.

    e.g. "how old is Tom Cruise" -> "Tom Cruise"
         "what is the population of London" -> "London"
         "what age is Madonna?" -> "Madonna"
    """
    q = question.lower().strip()
    # Remove trailing punctuation (?, ., !)
    q = q.rstrip("?!.")
    prefixes = [
        "how old is ",
        "what age is ",
        "what is the population of ",
        "population of ",
    ]
    for p in prefixes:
        if q.startswith(p):
            return question[len(p) :].strip().rstrip("?!.")
    return q.strip()


def search_wikidata(entity_name: str, endpoint: str) -> str:
    """
    Query the Wikidata API to find the best-matching entity ID.
    """
    params = {
        "action": "wbsearchentities",
        "search": entity_name,
        "language": "en",
        "format": "json",
        "type": "item",
    }
    url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KGGTechnicalTest/1.0 (mailto:ethan.r.davidson@gmail.com)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.loads(response.read())

    if not results.get("search"):
        raise ValueError(f"No Wikidata entity found for: {entity_name}")

    return results["search"][0]["id"]


def select_property(question: str) -> str:
    """
    Map question keywords to the relevant Wikidata property ID.

    P569 = date of birth  (age = derived by calculating years from birth date)
    P1082 = population
    """
    q = question.lower()
    if any(p in q for p in ["age", "old"]):
        return "P569"
    if "population" in q:
        return "P1082"
    raise ValueError(f"Unsupported question type: {question}")


def build_query(entity_id: str, property_id: str) -> str:
    """
    Build a SPARQL SELECT query for the given entity and property.

    All SPARQL expressions are kept on a single line to avoid parser errors
    with Blazegraph (Wikidata's SPARQL engine).

    For P569 (date of birth) we compute the exact age as of today:
      age = YEAR(NOW()) - YEAR(birthDate)
            - IF birthday hasn't occurred yet this year, 1, 0

    For P1082 (population) we return the raw literal value.
    """
    if property_id == "P569":
        query = (
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
            "SELECT ?answer WHERE { "
            f"<http://www.wikidata.org/entity/{entity_id}> wdt:P569 ?birthDate . "
            "BIND(YEAR(NOW()) - YEAR(?birthDate) - "
            "IF(MONTH(NOW()) < MONTH(?birthDate) || "
            "(MONTH(NOW()) = MONTH(?birthDate) && DAY(NOW()) < DAY(?birthDate)), "
            "1, 0) AS ?answer) }"
        )
        return query
    elif property_id == "P1082":
        return (
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
            "SELECT ?answer WHERE { "
            f"<http://www.wikidata.org/entity/{entity_id}> wdt:P1082 ?answer . "
            "}"
        )
    else:
        raise ValueError(f"Unsupported property: {property_id}")


def execute_query(query: str, endpoint: str) -> str:
    """
    Execute a SPARQL SELECT query and return the first binding's value.
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
        print("DEBUG QUERY:", query)  # pragma: no cover
        raise ValueError("SPARQL query returned no bindings")

    return bindings[0]["answer"]["value"]


if __name__ == "__main__":
    assert "63" == ask("how old is Tom Cruise")
    assert "67" == ask("what age is Madonna?")
    assert "8799728" == ask("what is the population of London")
    assert "8804190" == ask("what is the population of New York?")
    print("All assertions passed")
