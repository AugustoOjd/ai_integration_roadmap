# 📄 Mini 5: PDF Upload & Chunking
 
Process PDFs and prepare for embedding.
 
## 🎯 Learning Objectives
 
- ✅ File upload handling
- ✅ PDF text extraction
- ✅ Text chunking strategy
- ✅ Chunk overlap
- ✅ Metadata storage
- ✅ Multi-part form data
 
## 🏗️ Architecture
 
````
Upload PDF
    ↓
Extract text (pypdf)
    ↓
Chunk text (overlap strategy)
    ↓
Store chunks in DB
    ↓ (Next: Generate embeddings)
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **pypdf** - PDF extraction
- **python-multipart** - Form data parsing
- **PostgreSQL** - Storage
- **SQLAlchemy** - ORM
 
## 🚀 Quick Start
 
```bash
# 1. Install dependencies
uv add pypdf python-multipart
 
# 2. Start database
docker-compose up -d
 
# 3. Run app
uv run uvicorn app.main:app --reload
 
# 4. Upload a PDF
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@sample.pdf"
```
 
## 📝 API Endpoints
 
```bash
# Upload document
POST /documents/upload
Files: file (PDF or text)
 
Response:
{
  "id": "doc-123",
  "filename": "document.pdf",
  "chunks_count": 42
}
 
# List documents
GET /documents/
 
# Get document chunks
GET /documents/{doc_id}/chunks
 
Response:
[
  {
    "id": "chunk-1",
    "chunk_text": "First 1000 characters...",
    "chunk_index": 0
  }
]
```
 
## 🧩 Chunking Strategy
 
### Why Chunk?
 
````
Problem: LLM context window is limited (~200k tokens)
Solution: Split large documents into manageable chunks
 
Tradeoff:
- Chunks too small: lose context
- Chunks too large: waste context window
- Optimal: 1000-2000 characters per chunk
````
 
### Overlap
 
````
Text: "ABCDEFGHIJ..." (100 chars)
Chunk size: 30, Overlap: 10
 
Result:
[0:30]    "ABCDEFGHIJ..."
[20:50]   "IJKLMNOPQR..."  (10 overlap)
[40:70]   "QRSTUVWXYZ..."  (10 overlap)
 
Benefit:
- Context preserved across chunks
- No information loss at boundaries
````
 
## 📂 Database Schema
 
```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  filename VARCHAR,
  original_text TEXT,
  created_at TIMESTAMP
);
 
CREATE TABLE document_chunks (
  id UUID PRIMARY KEY,
  document_id UUID FOREIGN KEY,
  chunk_text TEXT,
  chunk_index INTEGER,
  created_at TIMESTAMP
);
```
 
## 🧪 Test Upload
 
```bash
# Create sample PDF (or use existing)
# Then upload
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@sample.pdf"
 
# Verify
curl http://localhost:8000/documents/
 
# Get chunks
curl http://localhost:8000/documents/{doc_id}/chunks
```
 
## 🎓 Key Concepts
 
**Text Extraction:**
```python
from pypdf import PdfReader
 
pdf_reader = PdfReader("document.pdf")
text = ""
for page in pdf_reader.pages:
    text += page.extract_text()
```
 
**Chunking:**
```python
def chunk_text(text, size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap  # Go back by overlap
    return chunks
```
 
**Metadata:**
```python
chunk = {
  "text": "...",
  "source": "document.pdf",
  "chunk_index": 0,
  "page_range": (0, 1)
}
```
 
## 📊 File Format Support
 
**Current:**
- PDF (.pdf)
- Plain text (.txt)
 
**Easy to extend:**
- Markdown (.md)
- Word (.docx)
- HTML (.html)
 
## 📂 Folder Structure
 
````
mini-5-pdf-processing/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── document.py        # NEW
│   │   └── chunk.py           # NEW
│   ├── services/
│   │   └── documents.py       # NEW: Processing logic
│   ├── routes/
│   │   └── documents.py       # NEW: Upload endpoints
│   └── schemas/
│       └── document.py        # NEW
├── tests/
│   └── test_documents.py
├── samples/
│   └── sample.pdf             # Test file
└── pyproject.toml
````
 
## 🧪 Testing
 
```bash
pytest tests/test_documents.py
 
# Test with actual PDF
uv run pytest -v
```
 
## 📈 Performance
 
**Processing times (for 10-page PDF):**
- Extraction: ~500ms
- Chunking: ~10ms
- Storage: ~100ms
- **Total: ~600ms**
 
## 💡 Advanced Features (Optional)
 
```python
# Extract metadata
def extract_pdf_metadata(pdf_reader):
    return {
        "pages": len(pdf_reader.pages),
        "title": pdf_reader.metadata.title,
        "author": pdf_reader.metadata.author
    }
 
# Preserve page numbers
def chunk_with_page_info(pdf_reader, chunk_size=1000):
    for page_num, page in enumerate(pdf_reader.pages):
        text = page.extract_text()
        for chunk in chunk_text(text):
            yield {
                "text": chunk,
                "page": page_num + 1
            }
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 5: PDF processing and chunking"
git push
```
 
## ❓ Troubleshooting
 
**PDF not extracting text?**
```bash
# Some PDFs are scanned images (need OCR)
# For now, stick with text-based PDFs
 
# Check extraction
uv run python -c "
from pypdf import PdfReader
pdf = PdfReader('sample.pdf')
print(pdf.pages[0].extract_text()[:100])
"
```
 
**Large PDFs slow?**
```python
# Process in chunks
CHUNK_SIZE = 1000
for i in range(0, len(text), CHUNK_SIZE):
    process_chunk(text[i:i+CHUNK_SIZE])
```
 
## 📚 Resources
 
- [pypdf Documentation](https://pypdf.readthedocs.io/)
- [PDF Text Extraction](https://github.com/py-pdf/pypdf)
- [Chunking Strategies](https://python.langchain.com/docs/modules/data_connection/document_loaders/)
 
## ⏱️ Timeline
 
- Setup: 20 min
- PDF extraction: 1 hour
- Chunking: 1 hour
- Testing: 45 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install pypdf
- [ ] Create document models
- [ ] Implement PDF extraction
- [ ] Implement chunking
- [ ] Create upload endpoint
- [ ] Store chunks in DB
- [ ] Test with sample PDF
- [ ] Push to GitHub
 
## 🎯 Next: PROJECT 1
 
Ready to integrate everything? Go to `../../PROYECTOS_COMPLETOS/project-1-rag-assistant/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
