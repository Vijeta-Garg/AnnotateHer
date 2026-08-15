import requests
import time
import json

from flair.data import Sentence
from flair.nn import Classifier


# ============================================================
# CONFIGURATION
# ============================================================

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

HEADERS = {
    "User-Agent": "AnnotateHer/1.0 (educational research project)",
    "Accept": "application/json"
}

ENTITY_CACHE = {}
SEARCH_CACHE = {}


# ============================================================
# WIKIDATA API
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

            print(f"Wikidata request failed: {e}")
            print(f"Retrying in {wait} seconds...")

            time.sleep(wait)

    return None


# ============================================================
# GET MULTIPLE ENTITIES
# ============================================================

def get_entities(qids):

    qids = list(dict.fromkeys(qids))

    if not qids:
        return {}

    entities = {}

    missing = [
        qid
        for qid in qids
        if qid not in ENTITY_CACHE
    ]

    for i in range(0, len(missing), 50):

        batch = missing[i:i + 50]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "format": "json",
            "languages": "en",
            "props": "claims|labels|descriptions"
        }

        data = api_request(params)

        if data:

            batch_entities = data.get(
                "entities",
                {}
            )

            for qid, entity in batch_entities.items():

                ENTITY_CACHE[qid] = entity

        if i + 50 < len(missing):
            time.sleep(0.5)

    for qid in qids:

        if qid in ENTITY_CACHE:
            entities[qid] = ENTITY_CACHE[qid]

    return entities


# ============================================================
# GET ONE ENTITY
# ============================================================

def get_entity(qid):

    if qid in ENTITY_CACHE:
        return ENTITY_CACHE[qid]

    entities = get_entities([qid])

    return entities.get(qid)


# ============================================================
# LABEL
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
# DESCRIPTION
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
# CLAIM QIDS
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
# SEARCH WIKIDATA
# ============================================================

def search_wikidata(name):

    if name in SEARCH_CACHE:
        return SEARCH_CACHE[name]

    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "format": "json",
        "limit": 5
    }

    data = api_request(params)

    results = data.get(
        "search",
        []
    ) if data else []

    for result in results:

        qid = result.get("id")

        if not qid:
            continue

        entity = get_entity(qid)

        if not entity:
            continue

        instance_of = get_claim_qids(
            entity,
            "P31"
        )

        if "Q5" in instance_of:

            SEARCH_CACHE[name] = qid

            return qid

    SEARCH_CACHE[name] = None

    return None


# ============================================================
# CUSTOM TAG: DISCOVERY
# ============================================================

def extract_discoveries(person_qid):

    person = get_entity(person_qid)

    if not person:
        return []

    discovery_qids = get_claim_qids(
        person,
        "P61"
    )

    entities = get_entities(
        discovery_qids
    )

    results = []

    for qid in discovery_qids:

        entity = entities.get(qid)

        if not entity:
            continue

        label = get_label(entity)

        if label:

            results.append({
                "qid": qid,
                "label": label
            })

    return results


# ============================================================
# CUSTOM TAG: PEOPLE ASSOCIATED
# ============================================================

PEOPLE_ASSOCIATED_PROPERTIES = {

    "P802": "student",

    "P1066": "student of",

    "P184": "doctoral advisor",

    "P737": "influenced by",

}


def extract_people_associated(person_qid):

    person = get_entity(person_qid)

    if not person:
        return []

    relationships = []

    qids = []

    for property_id in PEOPLE_ASSOCIATED_PROPERTIES:

        target_qids = get_claim_qids(
            person,
            property_id
        )

        for qid in target_qids:

            relationships.append(
                (
                    property_id,
                    qid
                )
            )

            qids.append(qid)

    entities = get_entities(qids)

    results = []

    for property_id, qid in relationships:

        entity = entities.get(qid)

        if not entity:
            continue

        instance_of = get_claim_qids(
            entity,
            "P31"
        )

        if "Q5" not in instance_of:
            continue

        label = get_label(entity)

        if not label:
            continue

        results.append({
            "property": property_id,
            "relationship":
                PEOPLE_ASSOCIATED_PROPERTIES[
                    property_id
                ],
            "qid": qid,
            "label": label
        })

    return results


# ============================================================
# CUSTOM TAG: AWARD / HONORED
# ============================================================

AWARD_PROPERTIES = {

    "P166": "award/honor received",

    "P1411": "nominated for",

}


def extract_awards(person_qid):

    person = get_entity(person_qid)

    if not person:
        return []

    relationships = []

    qids = []

    for property_id in AWARD_PROPERTIES:

        target_qids = get_claim_qids(
            person,
            property_id
        )

        for qid in target_qids:

            relationships.append(
                (
                    property_id,
                    qid
                )
            )

            qids.append(qid)

    entities = get_entities(qids)

    results = []

    for property_id, qid in relationships:

        entity = entities.get(qid)

        if not entity:
            continue

        label = get_label(entity)

        if not label:
            continue

        results.append({
            "property": property_id,
            "relationship":
                AWARD_PROPERTIES[
                    property_id
                ],
            "qid": qid,
            "label": label
        })

    return results


# ============================================================
# FLAIR NER
# ============================================================

print("Loading Flair NER model...")

tagger = Classifier.load("ner")


# ============================================================
# DETECT PEOPLE
# ============================================================

def detect_people(text):

    sentence = Sentence(text)

    tagger.predict(sentence)

    people = []

    seen = set()

    for label in sentence.get_labels("ner"):

        if label.value != "PER":
            continue

        name = label.data_point.text

        if name in seen:
            continue

        seen.add(name)

        people.append({
            "name": name,
            "start": label.data_point.start_position,
            "end": label.data_point.end_position
        })

    return people


# ============================================================
# FIND SENTENCE CONTEXT
# ============================================================

def get_context(text, start, end):

    # Find the beginning of the sentence
    sentence_start = start

    while (
        sentence_start > 0
        and text[sentence_start - 1]
        not in ".!?\n"
    ):
        sentence_start -= 1

    # Find the end of the sentence
    sentence_end = end

    while (
        sentence_end < len(text)
        and text[sentence_end]
        not in ".!?\n"
    ):
        sentence_end += 1

    return text[
        sentence_start:sentence_end
    ].strip()


# ============================================================
# BUILD PERSON ANNOTATION
# ============================================================

def annotate_person(person, text):

    name = person["name"]

    qid = search_wikidata(name)

    if not qid:

        return {
            "name": name,
            "qid": None,
            "context": get_context(
                text,
                person["start"],
                person["end"]
            ),
            "tags": {}
        }

    context = get_context(
        text,
        person["start"],
        person["end"]
    )

    print(
        f"\nDetected person: {name}"
    )

    print(
        f"  Wikidata QID: {qid}"
    )

    return {

        "name": name,

        "qid": qid,

        "context": context,

        "tags": {

            "discovery":
                extract_discoveries(qid),

            "people_associated":
                extract_people_associated(qid),

            "award_honored":
                extract_awards(qid)

        }

    }


# ============================================================
# ANNOTATE TEXT
# ============================================================

def annotate_text(text):

    people = detect_people(text)

    results = []

    for person in people:

        result = annotate_person(
            person,
            text
        )

        results.append(result)

    return results


# ============================================================
# PRINT RESULTS
# ============================================================

def print_results(text, results):

    print("\n")
    print("=" * 70)
    print("ANNOTATEHER RESULT")
    print("=" * 70)

    print("\nTEXT:")
    print(text)

    for person in results:

        print("\n" + "-" * 70)

        print(
            f"PERSON: {person['name']}"
        )

        print(
            f"QID: {person['qid']}"
        )

        print("\nTEXT CONTEXT:")

        print(
            f"  {person['context']}"
        )

        tags = person["tags"]

        # ----------------------------------------------------
        # DISCOVERY
        # ----------------------------------------------------

        print("\nDISCOVERY:")

        discoveries = tags.get(
            "discovery",
            []
        )

        if discoveries:

            for item in discoveries:

                print(
                    f"  {item['label']} "
                    f"({item['qid']})"
                )

        else:

            print("  None found")

        # ----------------------------------------------------
        # PEOPLE ASSOCIATED
        # ----------------------------------------------------

        print("\nPEOPLE_ASSOCIATED:")

        associated = tags.get(
            "people_associated",
            []
        )

        if associated:

            for item in associated:

                print(
                    f"  {item['relationship']} "
                    f"→ {item['label']} "
                    f"({item['qid']})"
                )

        else:

            print("  None found")

        # ----------------------------------------------------
        # AWARDS
        # ----------------------------------------------------

        print("\nAWARD_HONORED:")

        awards = tags.get(
            "award_honored",
            []
        )

        if awards:

            for item in awards:

                print(
                    f"  {item['relationship']} "
                    f"→ {item['label']} "
                    f"({item['qid']})"
                )

        else:

            print("  None found")


# ============================================================
# SAVE STRUCTURED RESULT
# ============================================================

def save_json(results, filename="annotateher_output.json"):

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

    text = (
        "Ada Lovelace worked with Charles Babbage "
        "and developed an algorithm for computing "
        "Bernoulli numbers."
    )

    results = annotate_text(text)

    print_results(
        text,
        results
    )

    save_json(
        results
    )

    print("\nDone.")