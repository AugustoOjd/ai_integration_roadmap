# 🧮 Mini 3: Embeddings Basics
 
Generate and compare embeddings (vector representations of text).
 
## 🎯 Learning Objectives
 
- ✅ What are embeddings
- ✅ Vector math (distance, similarity)
- ✅ Cosine similarity calculation
- ✅ Normalization
- ✅ Dimensionality concepts
- ✅ LLM embeddings API
 
## 📚 What Are Embeddings?
 
Embeddings convert text into vectors (arrays of numbers).
 
````
Text: "python is a programming language"
    ↓
Embedding: [-0.23, 0.45, 0.12, ..., 0.78]  (1536 dimensions)
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
Embedding Model
    ↓
Vector (1536-D)
    ↓
Store or Compare
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - Embedding generation
- **NumPy** - Vector math
- **Pydantic** - Data validation
 
## 🚀 Quick Start
 
```bash
# 1. Install dependencies
uv add anthropic numpy
 
# 2. Create .env
export ANTHROPIC_API_KEY=sk-ant-...
 
# 3. Run app
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
  "embedding": [-0.23, 0.45, ..., 0.78],  # 1536 numbers
  "dimension": 1536
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
- 1536D for Claude embeddings
- Higher = more expressive but slower
- 128D to 3072D common range
 
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
 
- Generation: ~200-500ms per text
- Similarity: ~1ms (vector math only)
- Batch: More efficient than individual calls
 
## 💾 Storage (Preview)
 
In Mini 4, you'll store embeddings in PostgreSQL:
````
Text: "Python is a language"
Embedding: [1536 numbers]
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
 
**ANTHROPIC_API_KEY not working?**
```bash
# Check .env
cat .env | grep ANTHROPIC
 
# Test directly
python -c "from anthropic import Anthropic; print('OK')"
```
 
**Different embeddings for same text?**
````
This shouldn't happen. Embeddings are deterministic.
If it does, check your hashing method (if using local generation).
````
 
## 📚 Resources
 
- [What are embeddings?](https://platform.openai.com/docs/guides/embeddings)
- [Cosine Similarity](https://en.wikipedia.org/wiki/Cosine_similarity)
- [Vector Databases](https://www.pinecone.io/learn/vector-database/)
- [Anthropic Embeddings](https://docs.anthropic.com)
 
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
