import requests
import time

# ============================================================
# CONFIGURATION
# ============================================================

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

HEADERS = {
    "User-Agent": "AnnotateHer/1.0 (educational research project)",
    "Accept": "application/json"
}


# ============================================================
# GENERAL WIKIDATA API REQUEST
# ============================================================

def api_request(params, retries=5):
    """
    Make a request to the Wikidata API.

    Includes retry/backoff handling for rate limits.
    """

    for attempt in range(retries):

        try:
            response = requests.get(
                WIKIDATA_API,
                params=params,
                headers=HEADERS,
                timeout=30
            )

            if response.status_code == 429:

                wait = 2 ** attempt

                print(
                    f"Wikidata API rate limited. "
                    f"Waiting {wait} seconds..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:

            if attempt == retries - 1:
                raise

            wait = 2 ** attempt

            print(f"Request failed: {e}")
            print(f"Retrying in {wait} seconds...")

            time.sleep(wait)

    return None


# ============================================================
# SPARQL REQUEST
# ============================================================

def sparql_query(query, retries=5):
    """
    Run a SPARQL query against Wikidata.
    """

    params = {
        "query": query,
        "format": "json"
    }

    for attempt in range(retries):

        try:

            response = requests.get(
                WIKIDATA_SPARQL,
                params=params,
                headers={
                    "User-Agent":
                        "AnnotateHer/1.0 (educational research project)",
                    "Accept":
                        "application/sparql-results+json"
                },
                timeout=60
            )

            if response.status_code == 429:

                wait = 2 ** attempt

                print(
                    f"SPARQL rate limited. "
                    f"Waiting {wait} seconds..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            return response.json()["results"]["bindings"]

        except requests.RequestException as e:

            if attempt == retries - 1:
                raise

            wait = 2 ** attempt

            print(f"SPARQL request failed: {e}")
            print(f"Retrying in {wait} seconds...")

            time.sleep(wait)

    return []


# ============================================================
# SEARCH WIKIDATA
# ============================================================

def search_wikidata(search_term, limit=5):
    """
    Search Wikidata for an entity.
    """

    params = {
        "action": "wbsearchentities",
        "search": search_term,
        "language": "en",
        "format": "json",
        "limit": limit
    }

    data = api_request(params)

    if not data:
        return []

    results = []

    for result in data.get("search", []):

        results.append({
            "qid": result.get("id"),
            "label": result.get("label"),
            "description": result.get("description", "")
        })

    return results


# ============================================================
# GET MULTIPLE ENTITIES
# ============================================================

def get_entities(qids):
    """
    Retrieve multiple Wikidata entities in batches.

    This avoids repeatedly requesting individual QIDs,
    which can trigger Wikidata's rate limits.
    """

    if not qids:
        return {}

    # Remove duplicates
    qids = list(dict.fromkeys(qids))

    entities = {}

    # Wikidata supports batches of up to 50 IDs
    for i in range(0, len(qids), 50):

        batch = qids[i:i + 50]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "format": "json",
            "languages": "en",
            "props": "claims|labels|descriptions"
        }

        data = api_request(params)

        if data:
            entities.update(
                data.get("entities", {})
            )

        # Small delay between batches
        if i + 50 < len(qids):
            time.sleep(0.5)

    return entities


# ============================================================
# GET ONE ENTITY
# ============================================================

def get_entity(qid):

    entities = get_entities([qid])

    return entities.get(qid)


# ============================================================
# ENTITY LABEL
# ============================================================

def get_label(entity):

    if not entity:
        return None

    return (
        entity
        .get("labels", {})
        .get("en", {})
        .get("value")
    )


# ============================================================
# ENTITY DESCRIPTION
# ============================================================

def get_description(entity):

    if not entity:
        return ""

    return (
        entity
        .get("descriptions", {})
        .get("en", {})
        .get("value", "")
    )


# ============================================================
# EXTRACT QIDS FROM A PROPERTY
# ============================================================

def get_claim_qids(entity, property_id):

    if not entity:
        return []

    claims = (
        entity
        .get("claims", {})
        .get(property_id, [])
    )

    qids = []

    for claim in claims:

        try:

            value = (
                claim["mainsnak"]
                ["datavalue"]
                ["value"]
            )

            if isinstance(value, dict):

                qid = value.get("id")

                if qid and qid.startswith("Q"):
                    qids.append(qid)

        except (KeyError, TypeError):

            continue

    return list(dict.fromkeys(qids))


# ============================================================
# TAG 1: DISCOVERY
# ============================================================

def extract_discoveries(person_qid):
    """
    Find things discovered or invented by the person.

    Wikidata:
        P61 = discoverer or inventor

    We search for:
        ?item P61 person
    """

    query = f"""
    SELECT DISTINCT ?item ?itemLabel WHERE {{

        ?item wdt:P61 wd:{person_qid}.

        SERVICE wikibase:label {{
            bd:serviceParam
                wikibase:language "en".
        }}
    }}

    LIMIT 100
    """

    results = sparql_query(query)

    discoveries = []

    for result in results:

        item_url = (
            result
            .get("item", {})
            .get("value", "")
        )

        label = (
            result
            .get("itemLabel", {})
            .get("value", "")
        )

        if item_url.startswith(
            "http://www.wikidata.org/entity/"
        ):

            qid = item_url.split("/")[-1]

            discoveries.append(
                (qid, label)
            )

    # Remove duplicates
    seen = set()
    unique = []

    for item in discoveries:

        if item[0] not in seen:

            seen.add(item[0])
            unique.append(item)

    return unique


# ============================================================
# TAG 2: PEOPLE ASSOCIATED
# ============================================================

PEOPLE_ASSOCIATED_PROPERTIES = {

    # Students
    "P802": "student",

    # Students/advisors
    "P1066": "student of",

    # Doctoral advisor
    "P184": "doctoral advisor",

    # Influences
    "P737": "influenced by",
}


def extract_people_associated(person_qid):
    """
    Extract professional/intellectual people associated
    with the person.

    Only entities classified as humans (Q5) are kept.

    Family relationships are intentionally excluded.
    """

    person = get_entity(person_qid)

    if not person:
        return []

    relationships = []

    qids_to_fetch = []

    # --------------------------------------------------------
    # Get direct professional relationships
    # --------------------------------------------------------

    for property_id in PEOPLE_ASSOCIATED_PROPERTIES:

        qids = get_claim_qids(
            person,
            property_id
        )

        for qid in qids:

            relationships.append(
                (property_id, qid)
            )

            qids_to_fetch.append(qid)

    # --------------------------------------------------------
    # Fetch all related people at once
    # --------------------------------------------------------

    entities = get_entities(qids_to_fetch)

    results = []

    for property_id, qid in relationships:

        entity = entities.get(qid)

        if not entity:
            continue

        # ----------------------------------------------------
        # Require human
        # ----------------------------------------------------

        instance_of = get_claim_qids(
            entity,
            "P31"
        )

        if "Q5" not in instance_of:
            continue

        label = get_label(entity)

        description = get_description(entity)

        if not label:
            label = qid

        results.append(
            (
                property_id,
                qid,
                label,
                description,
                PEOPLE_ASSOCIATED_PROPERTIES[
                    property_id
                ]
            )
        )

    return results


# ============================================================
# PEOPLE ASSOCIATED: CO-AUTHORS
# ============================================================

def extract_collaborators(person_qid):
    """
    Find people who co-authored scholarly works
    with the person.

    Wikidata:
        P50 = author

    This supplements the direct relationship properties.
    """

    query = f"""
    SELECT DISTINCT ?person ?personLabel WHERE {{

        ?work wdt:P50 wd:{person_qid}.
        ?work wdt:P50 ?person.

        ?person wdt:P31 wd:Q5.

        FILTER(?person != wd:{person_qid})

        SERVICE wikibase:label {{
            bd:serviceParam
                wikibase:language "en".
        }}
    }}

    LIMIT 100
    """

    results = sparql_query(query)

    collaborators = []

    for result in results:

        person_url = (
            result
            .get("person", {})
            .get("value", "")
        )

        label = (
            result
            .get("personLabel", {})
            .get("value", "")
        )

        if person_url.startswith(
            "http://www.wikidata.org/entity/"
        ):

            qid = person_url.split("/")[-1]

            collaborators.append(
                (
                    "P50",
                    qid,
                    label,
                    "co-author"
                )
            )

    # Remove duplicates
    unique = []
    seen = set()

    for item in collaborators:

        key = (item[0], item[1])

        if key not in seen:

            seen.add(key)
            unique.append(item)

    return unique


# ============================================================
# TAG 3: AWARD / HONORED
# ============================================================

AWARD_PROPERTIES = {

    # Award or honor received
    "P166": "award/honor received",

    # Nominated for
    "P1411": "nominated for",
}


def extract_awards(person_qid):
    """
    Extract awards and honors received or nominations.
    """

    person = get_entity(person_qid)

    if not person:
        return []

    awards = []

    qids_to_fetch = []

    # --------------------------------------------------------
    # Get award properties
    # --------------------------------------------------------

    for property_id in AWARD_PROPERTIES:

        qids = get_claim_qids(
            person,
            property_id
        )

        for qid in qids:

            awards.append(
                (property_id, qid)
            )

            qids_to_fetch.append(qid)

    # --------------------------------------------------------
    # Fetch all awards at once
    # --------------------------------------------------------

    entities = get_entities(qids_to_fetch)

    results = []

    for property_id, qid in awards:

        entity = entities.get(qid)

        if not entity:
            continue

        label = get_label(entity)

        description = get_description(entity)

        if not label:
            label = qid

        results.append(
            (
                property_id,
                qid,
                label,
                description,
                AWARD_PROPERTIES[
                    property_id
                ]
            )
        )

    return results


# ============================================================
# PRINT DISCOVERY TAG
# ============================================================

def print_discoveries(person_qid):

    print("\nDISCOVERY:")

    discoveries = extract_discoveries(
        person_qid
    )

    if not discoveries:

        print("  None found")
        return

    for qid, label in discoveries:

        print(
            f"  {qid} | {label}"
        )


# ============================================================
# PRINT PEOPLE ASSOCIATED TAG
# ============================================================

def print_people_associated(person_qid):

    print("\nPEOPLE_ASSOCIATED:")

    people = extract_people_associated(
        person_qid
    )

    collaborators = extract_collaborators(
        person_qid
    )

    if not people and not collaborators:

        print("  None found")
        return

    # --------------------------------------------------------
    # Direct professional relationships
    # --------------------------------------------------------

    for (
        property_id,
        qid,
        label,
        description,
        relationship
    ) in people:

        print(
            f"  {property_id} "
            f"({relationship}) "
            f"→ {qid} | {label}"
        )

    # --------------------------------------------------------
    # Co-authors
    # --------------------------------------------------------

    for (
        property_id,
        qid,
        label,
        relationship
    ) in collaborators:

        print(
            f"  {property_id} "
            f"({relationship}) "
            f"→ {qid} | {label}"
        )


# ============================================================
# PRINT AWARD / HONORED TAG
# ============================================================

def print_awards(person_qid):

    print("\nAWARD_HONORED:")

    awards = extract_awards(
        person_qid
    )

    if not awards:

        print("  None found")
        return

    for (
        property_id,
        qid,
        label,
        description,
        relationship
    ) in awards:

        print(
            f"  {property_id} "
            f"({relationship}) "
            f"→ {qid} | {label}"
        )


# ============================================================
# RUN ALL CUSTOM TAGS
# ============================================================

def analyze_person(person_qid):
    """
    Analyze a Wikidata person and return structured custom tags.

    Returns:
        {
            "person": {
                "qid": ...,
                "label": ...,
                "description": ...
            },
            "tags": {
                "DISCOVERY": [...],
                "PEOPLE_ASSOCIATED": [...],
                "AWARD_HONORED": [...]
            }
        }
    """

    person = get_entity(person_qid)

    if not person:
        print(f"Could not retrieve {person_qid}.")
        return None

    person_label = get_label(person)
    person_description = get_description(person)

    # ========================================================
    # DISCOVERY
    # ========================================================

    discoveries = extract_discoveries(person_qid)

    discovery_data = []

    for qid, label in discoveries:

        discovery_data.append({
            "qid": qid,
            "label": label
        })

    # ========================================================
    # PEOPLE ASSOCIATED
    # ========================================================

    people = extract_people_associated(person_qid)
    collaborators = extract_collaborators(person_qid)

    people_data = []

    # Direct professional relationships
    for (
        property_id,
        qid,
        label,
        description,
        relationship
    ) in people:

        people_data.append({
            "qid": qid,
            "label": label,
            "description": description,
            "property": property_id,
            "relationship": relationship
        })

    # Co-authors
    for (
        property_id,
        qid,
        label,
        relationship
    ) in collaborators:

        people_data.append({
            "qid": qid,
            "label": label,
            "description": "",
            "property": property_id,
            "relationship": relationship
        })

    # Remove duplicate people
    unique_people = []
    seen_people = set()

    for person_data in people_data:

        key = person_data["qid"]

        if key not in seen_people:

            seen_people.add(key)
            unique_people.append(person_data)

    # ========================================================
    # AWARDS / HONORS
    # ========================================================

    awards = extract_awards(person_qid)

    award_data = []

    for (
        property_id,
        qid,
        label,
        description,
        relationship
    ) in awards:

        award_data.append({
            "qid": qid,
            "label": label,
            "description": description,
            "property": property_id,
            "relationship": relationship
        })

    # ========================================================
    # STRUCTURED RESULT
    # ========================================================

    result = {

        "person": {
            "qid": person_qid,
            "label": person_label,
            "description": person_description
        },

        "tags": {

            "DISCOVERY": discovery_data,

            "PEOPLE_ASSOCIATED": unique_people,

            "AWARD_HONORED": award_data
        }
    }

    return result


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    person_qid = "Q7259"

    result = analyze_person(person_qid)

    if result:

        print("=" * 60)

        print(
            f"{result['person']['label']} "
            f"({result['person']['qid']})"
        )

        print(
            f"Description: "
            f"{result['person']['description']}"
        )

        print("=" * 60)

        print("\nDISCOVERY:")

        for item in result["tags"]["DISCOVERY"]:

            print(
                f"  {item['qid']} | "
                f"{item['label']}"
            )

        print("\nPEOPLE_ASSOCIATED:")

        for person in result["tags"]["PEOPLE_ASSOCIATED"]:

            print(
                f"  {person['relationship']} → "
                f"{person['qid']} | "
                f"{person['label']}"
            )

        print("\nAWARD_HONORED:")

        for award in result["tags"]["AWARD_HONORED"]:

            print(
                f"  {award['relationship']} → "
                f"{award['qid']} | "
                f"{award['label']}"
            )

        print("\n")
        print("Structured result created successfully.")