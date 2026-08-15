import requests
import time
import json

from flair.data import Sentence
from flair.nn import Classifier


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
# WIKIDATA API REQUEST
# ============================================================

def api_request(params, retries=5):

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

    params = {
        "action": "wbsearchentities",
        "search": search_term,
        "language": "en",
        "format": "json",
        "limit": limit
    }

    data = api_request(params)

    results = []

    if not data:
        return results

    for result in data.get("search", []):

        results.append({
            "qid": result.get("id"),
            "label": result.get("label"),
            "description": result.get(
                "description",
                ""
            )
        })

    return results


# ============================================================
# GET MULTIPLE ENTITIES
# ============================================================

def get_entities(qids):

    if not qids:
        return {}

    qids = list(dict.fromkeys(qids))

    entities = {}

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
                data.get(
                    "entities",
                    {}
                )
            )

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
        .get(
            "value",
            ""
        )
    )


# ============================================================
# EXTRACT QIDS FROM PROPERTY
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

    return qids


# ============================================================
# TAG 1: DISCOVERY
# ============================================================

def extract_discoveries(person_qid):

    query = f"""
    SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {{

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

        description = (
            result
            .get("itemDescription", {})
            .get("value", "")
        )

        if item_url.startswith(
            "http://www.wikidata.org/entity/"
        ):

            qid = item_url.split("/")[-1]

            discoveries.append({
                "qid": qid,
                "label": label,
                "description": description
            })

    return discoveries


# ============================================================
# TAG 2: PEOPLE ASSOCIATED
# ============================================================

PEOPLE_ASSOCIATED_PROPERTIES = {

    "P802": "student",

    "P1066": "student of",

    "P184": "doctoral advisor",

    "P737": "influenced by"

}


def extract_people_associated(person_qid):

    person = get_entity(person_qid)

    if not person:
        return []

    relationships = []

    qids_to_fetch = []

    for property_id in PEOPLE_ASSOCIATED_PROPERTIES:

        qids = get_claim_qids(
            person,
            property_id
        )

        for qid in qids:

            relationships.append(
                (
                    property_id,
                    qid
                )
            )

            qids_to_fetch.append(qid)

    entities = get_entities(
        qids_to_fetch
    )

    results = []

    for property_id, qid in relationships:

        entity = entities.get(qid)

        if not entity:
            continue

        label = get_label(entity)

        description = get_description(
            entity
        )

        instance_of = get_claim_qids(
            entity,
            "P31"
        )

        # Only humans
        if "Q5" not in instance_of:
            continue

        if not label:
            continue

        results.append({
            "qid": qid,
            "label": label,
            "description": description,
            "property": property_id,
            "relationship":
                PEOPLE_ASSOCIATED_PROPERTIES[
                    property_id
                ]
        })

    return results


# ============================================================
# TAG 3: AWARD / HONORED
# ============================================================

AWARD_PROPERTIES = {

    "P166": "award/honor received",

    "P1411": "nominated for"

}


def extract_awards(person_qid):

    person = get_entity(person_qid)

    if not person:
        return []

    awards = []

    qids_to_fetch = []

    for property_id in AWARD_PROPERTIES:

        qids = get_claim_qids(
            person,
            property_id
        )

        for qid in qids:

            awards.append(
                (
                    property_id,
                    qid
                )
            )

            qids_to_fetch.append(qid)

    entities = get_entities(
        qids_to_fetch
    )

    results = []

    for property_id, qid in awards:

        entity = entities.get(qid)

        if not entity:
            continue

        label = get_label(entity)

        description = get_description(
            entity
        )

        if not label:
            continue

        results.append({
            "qid": qid,
            "label": label,
            "description": description,
            "property": property_id,
            "relationship":
                AWARD_PROPERTIES[
                    property_id
                ]
        })

    return results


# ============================================================
# TEXT MATCHING HELPERS
# ============================================================

def normalize_text(text):

    return (
        text
        .lower()
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
    )


def phrase_in_text(phrase, text):

    if not phrase:
        return False

    phrase = normalize_text(
        phrase
    )

    text = normalize_text(
        text
    )

    return phrase in text


# ============================================================
# DETERMINE WHETHER A DISCOVERY IS ACTUALLY IN TEXT
# ============================================================

def discovery_in_context(
    discovery,
    text
):

    label = discovery.get(
        "label",
        ""
    )

    description = discovery.get(
        "description",
        ""
    )

    # Exact discovery name
    if phrase_in_text(
        label,
        text
    ):
        return True

    # Check meaningful words from the label.
    # This prevents very generic words from matching.
    label_words = [
        word.strip(
            ".,!?;:()[]{}\"'"
        ).lower()
        for word in label.split()
    ]

    label_words = [
        word
        for word in label_words
        if len(word) >= 5
    ]

    if label_words:

        matches = sum(
            1
            for word in label_words
            if word in normalize_text(text)
        )

        if matches >= max(
            1,
            len(label_words) // 2
        ):
            return True

    # Sometimes the Wikidata description contains the
    # actual concept even when the exact label does not.
    description_words = [
        word.strip(
            ".,!?;:()[]{}\"'"
        ).lower()
        for word in description.split()
    ]

    description_words = [
        word
        for word in description_words
        if len(word) >= 6
    ]

    if description_words:

        matches = sum(
            1
            for word in description_words
            if word in normalize_text(text)
        )

        if matches >= 2:
            return True

    return False


# ============================================================
# DETERMINE WHETHER AN AWARD IS ACTUALLY IN TEXT
# ============================================================

def award_in_context(
    award,
    text
):

    label = award.get(
        "label",
        ""
    )

    description = award.get(
        "description",
        ""
    )

    # Exact award name
    if phrase_in_text(
        label,
        text
    ):
        return True

    # Check meaningful words.
    label_words = [
        word.strip(
            ".,!?;:()[]{}\"'"
        ).lower()
        for word in label.split()
    ]

    label_words = [
        word
        for word in label_words
        if len(word) >= 5
    ]

    if len(label_words) >= 2:

        matches = sum(
            1
            for word in label_words
            if word in normalize_text(text)
        )

        if matches >= 2:
            return True

    return False


# ============================================================
# BUILD CLEAN CUSTOM TAGS
# ============================================================

def build_custom_tags(
    text,
    person,
    all_people
):

    name = person["name"]

    person_qid = person["qid"]

    # --------------------------------------------------------
    # Get Wikidata information internally
    # --------------------------------------------------------

    discoveries = extract_discoveries(
        person_qid
    )

    people_associated = extract_people_associated(
        person_qid
    )

    awards = extract_awards(
        person_qid
    )

    # --------------------------------------------------------
    # CLEAN DISCOVERY TAGS
    # --------------------------------------------------------

    clean_discoveries = []

    seen = set()

    for discovery in discoveries:

        if not discovery_in_context(
            discovery,
            text
        ):
            continue

        label = discovery.get(
            "label"
        )

        if not label:
            continue

        if label.lower() in seen:
            continue

        seen.add(
            label.lower()
        )

        clean_discoveries.append({
            "label": label
        })

    # --------------------------------------------------------
    # CLEAN PEOPLE ASSOCIATED TAGS
    # --------------------------------------------------------

    clean_people = []

    seen = set()

    # Names of people actually detected in THIS text
    detected_names = {
        p["name"].lower()
        for p in all_people
    }

    for relationship in people_associated:

        label = relationship.get(
            "label"
        )

        if not label:
            continue

        # The associated person must actually appear
        # in the input text.
        if label.lower() not in detected_names:
            continue

        # Don't associate a person with themselves.
        if label.lower() == name.lower():
            continue

        if label.lower() in seen:
            continue

        seen.add(
            label.lower()
        )

        clean_people.append({
            "label": label
        })

    # --------------------------------------------------------
    # CLEAN AWARD / HONORED TAGS
    # --------------------------------------------------------

    clean_awards = []

    seen = set()

    for award in awards:

        if not award_in_context(
            award,
            text
        ):
            continue

        label = award.get(
            "label"
        )

        if not label:
            continue

        if label.lower() in seen:
            continue

        seen.add(
            label.lower()
        )

        clean_awards.append({
            "label": label
        })

    # --------------------------------------------------------
    # FINAL CLEAN STRUCTURE
    # --------------------------------------------------------

    return {
        "discovery": clean_discoveries,
        "people_associated": clean_people,
        "award_honored": clean_awards
    }


# ============================================================
# FLAIR NER
# ============================================================

def detect_people(text):

    tagger = Classifier.load(
        "ner"
    )

    sentence = Sentence(
        str(text)
    )

    tagger.predict(
        sentence
    )

    people = []

    for label in sentence.get_labels(
        "ner"
    ):

        if label.value != "PER":
            continue

        person_name = (
            label.data_point.text
        )

        people.append(
            person_name
        )

    # Remove duplicate names while preserving order
    unique_people = []

    seen = set()

    for name in people:

        key = name.lower()

        if key not in seen:

            seen.add(key)

            unique_people.append(
                name
            )

    return unique_people


# ============================================================
# RESOLVE PEOPLE TO WIKIDATA
# ============================================================

def resolve_people(
    names
):

    resolved = []

    for name in names:

        print(
            f"Detected person: {name}"
        )

        results = search_wikidata(
            name,
            limit=5
        )

        if not results:

            print(
                f"  Could not find {name} "
                f"on Wikidata."
            )

            continue

        # ----------------------------------------------------
        # Pick the first result for now.
        # ----------------------------------------------------

        best = results[0]

        qid = best.get(
            "qid"
        )

        label = best.get(
            "label"
        )

        print(
            f"  Wikidata QID: {qid}"
        )

        if not qid:
            continue

        resolved.append({
            "name": label or name,
            "qid": qid
        })

        # Avoid hammering Wikidata
        time.sleep(0.5)

    return resolved


# ============================================================
# PROCESS TEXT
# ============================================================

def annotate_text(text):

    print(
        "\nDetecting people..."
    )

    names = detect_people(
        text
    )

    if not names:

        return []

    resolved_people = resolve_people(
        names
    )

    results = []

    for person in resolved_people:

        print(
            f"\nProcessing {person['name']}..."
        )

        tags = build_custom_tags(
            text,
            person,
            resolved_people
        )

        results.append({
            "name": person["name"],
            "qid": person["qid"],
            "context": text,
            "tags": tags
        })

    return results


# ============================================================
# PRINT RESULT
# ============================================================

def print_result(
    text,
    results
):

    print(
        "\n"
        + "=" * 70
    )

    print(
        "ANNOTATEHER RESULT"
    )

    print(
        "=" * 70
    )

    print(
        "\nTEXT:"
    )

    print(text)

    print(
        "\n"
        + "-" * 70
    )

    for person in results:

        print(
            f"PERSON: "
            f"{person['name']}"
        )

        print(
            f"QID: "
            f"{person['qid']}"
        )

        tags = person["tags"]

        print(
            "\nDISCOVERY:"
        )

        if tags["discovery"]:

            for item in tags[
                "discovery"
            ]:

                print(
                    f"  {item['label']}"
                )

        else:

            print(
                "  None found"
            )

        print(
            "\nPEOPLE_ASSOCIATED:"
        )

        if tags[
            "people_associated"
        ]:

            for item in tags[
                "people_associated"
            ]:

                print(
                    f"  {item['label']}"
                )

        else:

            print(
                "  None found"
            )

        print(
            "\nAWARD_HONORED:"
        )

        if tags[
            "award_honored"
        ]:

            for item in tags[
                "award_honored"
            ]:

                print(
                    f"  {item['label']}"
                )

        else:

            print(
                "  None found"
            )

        print(
            "\n"
            + "-" * 70
        )


# ============================================================
# SAVE JSON
# ============================================================

def save_json(
    results,
    filename="annotateher_result.json"
):

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            results,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(
        f"\nStructured result saved to "
        f"{filename}"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # TEST TEXT
    #
    # Replace this with any text you want AnnotateHer to
    # analyze.
    # --------------------------------------------------------

    text = (
        "Ada Lovelace worked with Charles Babbage "
        "and developed an algorithm for computing "
        "Bernoulli numbers."
    )

    # --------------------------------------------------------
    # Run AnnotateHer
    # --------------------------------------------------------

    results = annotate_text(
        text
    )

    # --------------------------------------------------------
    # Display results
    # --------------------------------------------------------

    print_result(
        text,
        results
    )

    # --------------------------------------------------------
    # Save clean structured JSON
    # --------------------------------------------------------

    save_json(
        results
    )

    print(
        "\nDone."
    )