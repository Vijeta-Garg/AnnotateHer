from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv

load_dotenv()

URI = os.environ["NEO4J_URI"]
USERNAME = os.environ["NEO4J_USERNAME"]
PASSWORD = os.environ["NEO4J_PASSWORD"]


driver = GraphDatabase.driver(
    URI,
    auth=(USERNAME, PASSWORD)
)


# ============================================================
# EMBEDDING MODEL
# ============================================================

model = SentenceTransformer("all-MiniLM-L6-v2")


# ============================================================
# DISCOVERY SEARCH
# ============================================================

def search_discoveries(query, limit=10):

    # Convert the query into the same 384-dimensional
    # embedding space used by the Discovery nodes.
    embedding = model.encode(query).tolist()

    cypher = """
    MATCH (d:discovery)
    SEARCH d IN (
        VECTOR INDEX discovery_embedding_index
        FOR $embedding
        LIMIT $limit
    )
    SCORE AS score

    RETURN
        d.discoveryID AS id,
        d.name AS discovery,
        d.description AS description,
        score

    ORDER BY score DESC
    """

    records, summary, keys = driver.execute_query(
        cypher,
        embedding=embedding,
        limit=limit,
        database_="38d75272"
    )

    return [record.data() for record in records]


# ============================================================
# APPLICATION SEARCH
# ============================================================

def search_applications(query, limit=10):

    embedding = model.encode(query).tolist()

    cypher = """
    MATCH (a:applications)
    SEARCH a IN (
        VECTOR INDEX application_embedding_index
        FOR $embedding
        LIMIT $limit
    )
    SCORE AS score

    RETURN
        a.applicationID AS id,
        a.name AS application,
        a.description AS description,
        score

    ORDER BY score DESC
    """

    records, summary, keys = driver.execute_query(
        cypher,
        embedding=embedding,
        limit=limit,
        database_="38d75272"
    )

    return [record.data() for record in records]


# ============================================================
# INTERACTIVE SEARCH
# ============================================================

try:

    while True:
        
        print("\n" + "=" * 60)
        print("SEMANTIC SEARCH")
        print("=" * 60)

        search_type = input(
            "\nAre you searching for a Discovery or Application? "
            "(D/A, or 'quit'): "
        ).strip().lower()

        if search_type == "quit":
            break

        if search_type not in ["d", "a", "discovery", "application"]:
            print("Please enter D for Discovery or A for Application.")
            continue

        query = input("\nEnter your search query: ").strip()

        if not query:
            print("Please enter a query.")
            continue

        if search_type in ["d", "discovery"]:
            print("\n" + "=" * 60)
            print("DISCOVERIES")
            print("=" * 60)

            results = search_discoveries(query)

            for result in results:
                print(f"\n[{result['score']:.4f}] {result['discovery']}")
                print(result["description"][:500] if result["description"] else "")

        else:
            print("\n" + "=" * 60)
            print("APPLICATIONS")
            print("=" * 60)

            results = search_applications(query)

            for result in results:
                print(f"\n[{result['score']:.4f}] {result['application']}")
                print(result["description"][:500] if result["description"] else "")

finally:
    driver.close()