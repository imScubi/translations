# Genshin Impact Lore RAG

Sistema RAG sobre el lore de Genshin Impact cuya única fuente es la [Genshin Impact Wiki de Fandom](https://genshin-impact.fandom.com/wiki/Genshin_Impact_Wiki).

## Atribución y licencia del contenido

Todo el texto indexado procede de la **Genshin Impact Wiki (Fandom)**, <https://genshin-impact.fandom.com>, y se distribuye bajo la licencia **[Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0)](https://creativecommons.org/licenses/by-sa/3.0/)**. Cada fragmento conserva la URL de su página y sección de origen, y cada respuesta del sistema cita esas URLs e incluye este aviso de licencia. Cualquier redistribución del contenido derivado debe mantener la misma licencia y la atribución a los colaboradores de la wiki. Genshin Impact es una marca de HoYoverse; este proyecto no tiene relación con HoYoverse ni con Fandom.

## Estructura

| Carpeta | Contenido |
|---|---|
| `extract/` | Cliente MediaWiki (1 req/s, reintentos con backoff, User-Agent descriptivo), descubrimiento de categorías, limpieza con mwparserfromhell y actualización incremental con `list=recentchanges`. |
| `chunk/` | Troceado estructural (secciones, escenas de diálogo, libros) de ~800 tokens con 100 de solapamiento solo en secciones largas, contexto jerárquico y metadatos. |
| `db/` | Migración SQL: tabla `chunks`, pgvector con HNSW, `tsvector` con GIN y RPC `hybrid_search` (RRF + filtros). |
| `load/` | Embeddings por lotes con Voyage AI y upsert idempotente (solo re-embebe fragmentos cuyo hash cambió; borra los obsoletos). |
| `query/` | Edge Function `rag-query` (búsqueda híbrida → rerank Voyage → Claude) y CLI `ask.py`. |
| `eval/` | 20 preguntas de prueba y script que muestra respuesta y fragmentos para revisión manual. |
| `common/` | Configuración y utilidades compartidas. |

## Configuración

`.env` (copiar de `.env.example`):

| Variable | Uso |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Proyecto Supabase (clave service role). |
| `VOYAGE_API_KEY` | Embeddings y rerank. |
| `ANTHROPIC_API_KEY` | Generación con Claude. |
| `VOYAGE_EMBED_MODEL` | Modelo de embeddings (por defecto `voyage-3.5`). |
| `EMBEDDING_DIM` | Dimensión (por defecto `1024`; si cambia, ajustar `vector(1024)` en la migración). |
| `VOYAGE_RERANK_MODEL` | Modelo de rerank (por defecto `rerank-2.5`). |
| `CLAUDE_MODEL` | Modelo de Claude (por defecto `claude-opus-5`). |
| `WIKI_USER_AGENT` | User-Agent para la API de la wiki (recomendado incluir un contacto). |

## Pipeline

1. **Descubrimiento**: `extract.run discover` consulta `list=allcategories` y `list=search` (namespace 14) para resolver los nombres exactos de las categorías por grupo (personajes, Archon/Story/World Quests, libros, artefactos, armas, regiones/naciones, facciones, eventos, lore general) y los guarda en `data/categories.json`. Se puede editar a mano antes de extraer (`roots` y `depth`).
2. **Extracción**: `extract.run full` recorre las categorías y subcategorías, añade las subpáginas `/Lore` y `/Voice-Overs` de cada personaje, descarga el wikitext en lotes de 50 títulos y escribe cada página en `data/raw/*.md` con frontmatter (título, URL, categorías, fecha y id de revisión).
3. **Troceado**: `chunk.chunker` genera `data/chunks.jsonl`.
4. **Carga**: `load.load` embebe y hace upsert en Supabase.
5. **Actualización incremental**: `extract.run update` usa `list=recentchanges` desde la última ejecución (la wiki conserva ~90 días de cambios; si ha pasado más tiempo, ejecutar `full`), reprocesa solo las páginas modificadas, borradas o movidas, y después `chunk` + `load` actualizan únicamente los fragmentos cuyo contenido cambió.

## Endpoint

`POST /functions/v1/rag-query`

```json
{ "question": "¿Quién es Morax?", "region": "Liyue", "character": "Zhongli", "content_type": "character", "match_count": 10 }
```

Valores de `content_type`: `character`, `archon_quest`, `story_quest`, `world_quest`, `book`, `artifact`, `weapon`, `region`, `faction`, `event`, `lore`.

La respuesta incluye `answer` (con citas por URL, lista de fuentes y aviso CC BY-SA), `sources`, `attribution` y `fragments` (contexto, URL, puntuaciones híbrida y de rerank, contenido).
