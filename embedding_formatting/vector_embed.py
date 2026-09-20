import pandas as pd
from sentence_transformers import SentenceTransformer

print("1. Loading CSV...")
df = pd.read_csv("applications.csv")
print(f"   Loaded {len(df)} discoveries.")

print("2. Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")
print("   Model loaded!")

print("3. Preparing text...")
texts = (
    "Name: " + df["name"].fillna("") +
    ". Field: " + df["field"].fillna("") +
    ". Description: " + df["description"].fillna("")
)

print("4. Generating embeddings...")
embeddings = model.encode(
    texts.tolist(),
    normalize_embeddings=True,
    show_progress_bar=True
)
print("   Embeddings generated!")

print("5. Adding embeddings to CSV...")
df["embedding"] = [
    "[" + ",".join(map(str, vector)) + "]"
    for vector in embeddings
]

print("6. Saving CSV...")
df.to_csv("applications_with_embeddings.csv", index=False)

print("DONE!")
print("Saved: applications_with_embeddings.csv")