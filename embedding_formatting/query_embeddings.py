from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

query = input("Search: ")

print("\nType:", type(query))
print("Characters:", len(query))


embedding = model.encode(query).tolist()
print(len(embedding))
print(embedding)