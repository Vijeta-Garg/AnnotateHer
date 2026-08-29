

from neo4j import GraphDatabase

# Connect to your Aura instance
URI = "neo4j+s://<your-aura-db-id>.databases.neo4j.io"
AUTH = ("neo4j", "your-password")

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    # Use an explicit write transaction
    with driver.session() as session:
        result = session.run(
            "MERGE (u:User {id: $id}) SET u.name = $name RETURN u.name AS name",
            id="user_123", name="Alice"
        )
        record = result.single()
        print(f"Created user: {record['name']}")
