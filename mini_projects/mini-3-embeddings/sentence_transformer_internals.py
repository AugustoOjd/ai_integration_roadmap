"""What SentenceTransformer does for you, written out by hand.

ILLUSTRATIVE ONLY. Nothing in the app imports this, and it isn't meant to be run
(it would need `transformers` and `torch`, which come with sentence-transformers
anyway). It exists to show what a single line of app code is actually hiding:

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    vector = model.encode("el gato duerme", normalize_embeddings=True)
    # -> array of 384 floats

Everything below is that one call, unpacked into the five steps it performs.
"""

import torch
from transformers import AutoModel, AutoTokenizer

# On Hugging Face, models live under "<org>/<name>". SentenceTransformer lets you
# write just "all-MiniLM-L6-v2" and fills in the org for you.
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
TEXT = "el gato duerme"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Download the weights and load them into memory
# ─────────────────────────────────────────────────────────────────────────────
# Two separate downloads, because a model is two things:
#
#   - the TOKENIZER: the vocabulary and the rules for splitting text into tokens.
#     Small, just lookup tables.
#   - the MODEL: the learned weights — the ~88MB of numbers. This is what ends up
#     occupying ~900MB of RAM once expanded into tensors.
#
# from_pretrained() checks ~/.cache/huggingface first and only hits the network
# if the files aren't there. That's why the first run is slow and the rest aren't.

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModel.from_pretrained(MODEL_ID)

# Switch the network to inference mode. Some layers (dropout, batch norm) behave
# differently while training, and we're not training — we only want predictions.
model.eval()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Tokenize: text -> numbers the network can read
# ─────────────────────────────────────────────────────────────────────────────
# A neural network can't read strings. The tokenizer splits the text into known
# pieces and maps each to an integer id from its vocabulary.
#
#   "el gato duerme"  ->  ["el", "gat", "##o", "duer", "##me"]  ->  [101, 10131, ...]
#
# Note the word pieces: uncommon words get split into fragments, which is how a
# fixed vocabulary handles words it has never seen.

encoded = tokenizer(
    TEXT,
    padding=True,       # pad short texts so a batch forms a rectangular tensor
    truncation=True,    # cut anything longer than the model can handle
    max_length=256,     # ← this model's ceiling. Text past here is DISCARDED,
                        #   which is why very long inputs waste compute.
    return_tensors="pt",  # give me PyTorch tensors, not plain lists
)

# encoded is a dict with two tensors:
#   input_ids       -> the token ids                      e.g. [[101, 10131, 1420, 102]]
#   attention_mask  -> 1 for real tokens, 0 for padding   e.g. [[  1,     1,    1,   1]]
#
# The mask matters in step 4: padding is filler, and averaging it in would drag
# every vector toward the same meaningless point.


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Run the network
# ─────────────────────────────────────────────────────────────────────────────
# no_grad() tells PyTorch not to record operations for backpropagation. We're not
# training, so that bookkeeping would be pure wasted memory and time.

with torch.no_grad():
    output = model(**encoded)

# THE SURPRISING PART: the transformer returns one vector PER TOKEN, not one per
# sentence. Shape is (batch, n_tokens, 384):
#
#   "el"     -> [384 numbers]
#   "gat"    -> [384 numbers]
#   "##o"    -> [384 numbers]
#   "duer"   -> [384 numbers]
#   "##me"   -> [384 numbers]
#
# So the raw model gives us 5 vectors and we want 1. Collapsing them is the next
# step — and it is literally what puts the "Sentence" in SentenceTransformer.

token_embeddings = output.last_hidden_state


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Pooling: many token vectors -> one sentence vector
# ─────────────────────────────────────────────────────────────────────────────
# The strategy this model uses is MEAN POOLING: average the token vectors.
# Simple, and it works well in practice.
#
# The only subtlety is ignoring padding, which is what the attention mask is for.

# Reshape the mask from (batch, tokens) to (batch, tokens, 384) so it lines up
# with the embeddings element by element.
mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()

# Multiplying by the mask zeroes out the padding positions, so they contribute
# nothing to the sum.
summed = torch.sum(token_embeddings * mask, dim=1)

# Divide by the count of REAL tokens, not the padded length — otherwise a short
# text in a padded batch would come out artificially shrunk.
# clamp(min=1e-9) avoids dividing by zero on a hypothetical empty input.
counts = torch.clamp(mask.sum(dim=1), min=1e-9)

sentence_embedding = summed / counts  # shape: (batch, 384) — one vector at last


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Normalize (this is `normalize_embeddings=True` in the app)
# ─────────────────────────────────────────────────────────────────────────────
# Scale the vector to length 1, keeping its direction. Once both vectors being
# compared are unit length, the cosine formula's denominator becomes 1 and
# cosine similarity collapses into a plain dot product.
#
#   p=2   -> Euclidean norm, i.e. sqrt(x1² + x2² + ... + x384²)
#   dim=1 -> normalize along the 384-number axis, per row

sentence_embedding = torch.nn.functional.normalize(sentence_embedding, p=2, dim=1)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Hand it back as ordinary Python
# ─────────────────────────────────────────────────────────────────────────────
# [0] drops the batch dimension (we only sent one text), and .tolist() turns the
# tensor into a plain list so Pydantic and JSON can handle it. That last part is
# exactly what services/embeddings.py does after calling encode().

vector = sentence_embedding[0].tolist()

print(f"{len(vector)} numbers")   # 384
print(vector[:5])                 # a peek at the first few


# ─────────────────────────────────────────────────────────────────────────────
# WHAT THIS BUYS US
# ─────────────────────────────────────────────────────────────────────────────
# ~40 lines of tensor manipulation, versus:
#
#     vector = SentenceTransformer(MODEL_ID).encode(TEXT, normalize_embeddings=True)
#
# The library also handles what this file skips: batching many texts efficiently,
# picking GPU over CPU when available, per-model pooling strategies (not every
# model uses mean pooling — some take the first token instead), and reading each
# model's own config so you don't have to know max_length or the pooling method
# ahead of time.
#
# Worth reading once to know what's underneath, then never writing again.
