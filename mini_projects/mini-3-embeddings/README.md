# 🧮 Mini 3: Embeddings Basics
 
Generate and compare embeddings (vector representations of text).
 
## 🎯 Learning Objectives
 
- ✅ What are embeddings
- ✅ Vector math (distance, similarity)
- ✅ Cosine similarity calculation
- ✅ Normalization
- ✅ Dimensionality concepts
- ✅ Running an embedding model locally
 
## 📚 What Are Embeddings?
 
Embeddings convert text into vectors (arrays of numbers).
 
````
Text: "python is a programming language"
    ↓
Embedding: [-0.23, 0.45, 0.12, ..., 0.78]  (384 dimensions)
    ↓
Properties:
- Each dimension represents semantic meaning
- Similar texts = similar vectors
- Distance between vectors = semantic similarity
````
 
## 🏗️ Architecture
 
````
Text Input
    ↓
Embedding Model (runs in-process, no API call)
    ↓
Vector (384-D)
    ↓
Store or Compare
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **sentence-transformers** - Embedding generation, running locally
- **NumPy** - Vector math
- **Pydantic** - Data validation
 
> **Why a local model instead of an API?** Anthropic does not offer an embedding
> model — its docs point to third-party providers (Voyage AI among them).
> Running `all-MiniLM-L6-v2` locally means no API key, no per-request cost, and
> no rate limit, so you can generate thousands of embeddings while experimenting.
> The tradeoff is a one-time ~90MB model download (plus PyTorch as a dependency).
> Swapping in a hosted provider later only changes `services/embeddings.py`.
 
## 🚀 Quick Start
 
```bash
# 1. Install dependencies
uv add sentence-transformers numpy
 
# 2. Run app — no API key needed.
#    The model downloads automatically on first use (~90MB, cached afterwards),
#    so the first startup is slower than the ones after it.
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Generate embedding for text
POST /embeddings/embed
{
  "text": "Python is awesome"
}
 
Response:
{
  "text": "Python is awesome",
  "embedding": [-0.23, 0.45, ..., 0.78],  # 384 numbers
  "dimension": 384
}
 
# Compare similarity
POST /embeddings/similarity
{
  "text1": "python",
  "text2": "programming"
}
 
Response:
{
  "text1": "python",
  "text2": "programming",
  "similarity": 0.75  # 0-1 scale, 1=identical
}
```
 
## 📊 Vector Similarity
 
### Cosine Similarity
 
````
Similarity = (A · B) / (||A|| * ||B||)
 
Where:
- A · B = dot product
- ||A|| = magnitude of A
- ||B|| = magnitude of B
Range: -1 to 1 (typically 0 to 1 for normalized)
- 1.0 = identical
- 0.5 = somewhat similar
- 0.0 = unrelated
````
 
## 🧪 Examples
 
```python
# Get embeddings
emb1 = embed("cat")      # [-0.2, 0.3, ..., 0.1]
emb2 = embed("dog")      # [-0.19, 0.29, ..., 0.11]
emb3 = embed("bicycle")  # [0.5, -0.3, ..., 0.8]
 
# Calculate similarities
similarity(emb1, emb2) → 0.95  # Cat and dog are similar
similarity(emb1, emb3) → 0.15  # Cat and bicycle are different
```
 
## 🎓 Key Concepts
 
**Embedding Dimension:**
- Fixed by the model, not by you — every model outputs its own size
- `all-MiniLM-L6-v2` (this mini): 384D · Voyage 4: 1024D · OpenAI ada-002: 1536D
- Higher = more nuance captured, but more storage and slower comparisons
- 128D to 3072D is the common range
- Vectors from different models are **not comparable** — you can't compare a 384-D
  vector to a 1024-D one, and even at equal size the dimensions mean different
  things. Switching models means regenerating every stored embedding.
 
**Normalization:**
```python
# Important for accurate similarity
def normalize(embedding):
    norm = np.linalg.norm(embedding)
    return embedding / norm
```
 
**Distance Metrics:**
- Cosine: Best for embeddings
- Euclidean: Alternative but slower
- Manhattan: Rarely used
 
## 📂 Folder Structure
 
````
mini-3-embeddings/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── services/
│   │   └── embeddings.py      # Core logic
│   ├── schemas/
│   │   └── embedding.py       # Request/response
│   └── routes/
│       └── embeddings.py      # Endpoints
├── tests/
│   └── test_embeddings.py
└── pyproject.toml
````
 
## 🔬 Testing Similarity
 
```bash
# Test identical texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -H "Content-Type: application/json" \
  -d '{
    "text1": "hello",
    "text2": "hello"
  }'
# Response: similarity = 1.0
 
# Test different texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -d '{
    "text1": "cat",
    "text2": "dog"
  }'
# Response: similarity ≈ 0.8
 
# Test unrelated texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -d '{
    "text1": "cat",
    "text2": "bicycle"
  }'
# Response: similarity ≈ 0.1
```
 
## 📈 Performance
 
- First call: several seconds (downloads and loads the model into memory)
- Generation after that: ~5-20ms per text on CPU (no network round trip)
- Similarity: ~1ms (vector math only)
- Batch: much more efficient — pass a list to `encode()` instead of looping
 
Load the model **once** at startup, not per request. Re-instantiating
`SentenceTransformer` on every call re-reads the model from disk and turns a
20ms operation into a multi-second one.
 
## 💾 Storage (Preview)
 
In Mini 4, you'll store embeddings in PostgreSQL:
````
Text: "Python is a language"
Embedding: [384 numbers]
    ↓
Store in database
    ↓
Query with similarity search
````
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 3: Embeddings"
git push
```
 
## ❓ Troubleshooting
 
**First run is very slow / seems stuck?**
```bash
# It's downloading the model (~90MB). Verify it landed in the cache:
ls ~/.cache/huggingface/hub/
 
# Check the model loads and reports the expected dimension:
uv run python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('all-MiniLM-L6-v2')
print(m.get_sentence_embedding_dimension())  # 384
"
```
 
**Every request is slow, not just the first?**
````
The model is being reloaded per request. Instantiate SentenceTransformer once
at module level (or in the lifespan startup), never inside the route handler.
````
 
**Different embeddings for same text?**
````
This shouldn't happen — the model is deterministic for identical input.
Check for stray whitespace or casing differences in what you're actually passing.
````
 
## 📚 Resources
 
- [What are embeddings? (Anthropic)](https://platform.claude.com/docs/en/build-with-claude/embeddings)
- [sentence-transformers docs](https://sbert.net/)
- [all-MiniLM-L6-v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [Cosine Similarity](https://en.wikipedia.org/wiki/Cosine_similarity)
- [Vector Databases](https://www.pinecone.io/learn/vector-database/)
 
## ⏱️ Timeline
 
- Setup: 20 min
- Core logic: 1 hour
- API endpoints: 45 min
- Testing: 30 min
- **Total: 2-3 hours**
 
## ✅ Checklist
 
- [ ] Install dependencies
- [ ] Create embedding service
- [ ] Test embedding generation
- [ ] Implement similarity calculation
- [ ] Create API endpoints
- [ ] Test embeddings and similarity
- [ ] Push to GitHub
 
## 🎯 Next: Mini 4
 
Ready for vector search? Go to `../mini-4-pgvector/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
