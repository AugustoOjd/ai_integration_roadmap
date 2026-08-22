-- Corre una sola vez, al primer boot de un volumen vacío.
-- CREATE EXTENSION es por base de datos: registra el tipo `vector`, los
-- operadores <=> <-> <#> y los métodos ivfflat/hnsw en su catálogo.
CREATE EXTENSION IF NOT EXISTS vector;
