import { createClient } from "jsr:@supabase/supabase-js@2";
import Anthropic from "npm:@anthropic-ai/sdk";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? Deno.env.get("SUPABASE_SERVICE_KEY")!;
const VOYAGE_API_KEY = Deno.env.get("VOYAGE_API_KEY")!;
const EMBED_MODEL = Deno.env.get("VOYAGE_EMBED_MODEL") ?? "voyage-3.5";
const EMBED_DIM = Number(Deno.env.get("EMBEDDING_DIM") ?? "1024");
const RERANK_MODEL = Deno.env.get("VOYAGE_RERANK_MODEL") ?? "rerank-2.5";
const CLAUDE_MODEL = Deno.env.get("CLAUDE_MODEL") ?? "claude-opus-5";
const MATCH_COUNT = Number(Deno.env.get("MATCH_COUNT") ?? "10");

const LICENSE_NOTICE =
  "Fuente: Genshin Impact Wiki (Fandom), https://genshin-impact.fandom.com — contenido bajo licencia CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/).";

const SYSTEM_PROMPT = `You are a lore assistant for Genshin Impact. You answer using ONLY the wiki fragments provided in the user message, which come from the Genshin Impact Wiki on Fandom.

Rules:
1. Use exclusively the information contained in the fragments. Do not add anything from general knowledge, memory, or assumptions, even if you believe it is true.
2. Cite every fact with the URL of the fragment it comes from, in the form [n](URL), right after the sentence that uses it. If a sentence combines several fragments, cite all of them.
3. If the fragments do not contain the information needed, say so explicitly (for example: "Esta información no aparece en los fragmentos recuperados."). If they contain only part of it, answer that part and state clearly what is missing. Never fill the gaps.
4. Distinguish confirmed facts from community theories. Treat as confirmed only what the fragments present as in-game text (dialogue, books, item descriptions, voice-overs, quest text) or as established wiki fact. Anything the fragments present as speculation, theory, fan interpretation, trivia hedged with "possibly", "may", "it is theorized", or as unconfirmed, must be labelled as a community theory or speculation.
5. When fragments disagree, show both versions with their citations instead of choosing one.
6. For chronology questions, order events only as far as the fragments support it, and say where the ordering is uncertain.
7. Answer in the same language as the question. Keep in-game proper names as they appear in the fragments.
8. Be concise and structured: a direct answer first, then supporting details.`;

type Chunk = {
  id: string;
  content: string;
  context: string;
  metadata: Record<string, unknown>;
  url: string;
  revision_id: number;
  score: number;
  fts_rank: number | null;
  semantic_rank: number | null;
  rerank_score?: number;
};

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

async function voyage(path: string, body: unknown): Promise<any> {
  let delay = 1000;
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(`https://api.voyageai.com/v1/${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${VOYAGE_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) return await res.json();
    if (res.status !== 429 && res.status < 500) throw new Error(`Voyage ${path} ${res.status}: ${await res.text()}`);
    await new Promise((r) => setTimeout(r, delay));
    delay *= 2;
  }
  throw new Error(`Voyage ${path} failed after retries`);
}

async function embedQuery(text: string): Promise<number[]> {
  const data = await voyage("embeddings", {
    input: [text],
    model: EMBED_MODEL,
    input_type: "query",
    output_dimension: EMBED_DIM,
  });
  return data.data[0].embedding;
}

async function rerank(question: string, chunks: Chunk[]): Promise<Chunk[]> {
  if (chunks.length <= 1) return chunks;
  const data = await voyage("rerank", {
    query: question,
    documents: chunks.map((c) => `${c.context}\n\n${c.content}`),
    model: RERANK_MODEL,
    truncation: true,
  });
  return data.data.map((r: { index: number; relevance_score: number }) => ({
    ...chunks[r.index],
    rerank_score: r.relevance_score,
  }));
}

function buildUserMessage(question: string, chunks: Chunk[]): string {
  const fragments = chunks
    .map(
      (c, i) =>
        `<fragment n="${i + 1}" url="${c.url}">\n<context>${c.context}</context>\n<content>\n${c.content}\n</content>\n</fragment>`,
    )
    .join("\n\n");
  return `<fragments>\n${fragments}\n</fragments>\n\n<question>${question}</question>`;
}

function sourcesFooter(chunks: Chunk[]): string {
  const urls = [...new Set(chunks.map((c) => c.url))];
  return `\n\n---\nFragmentos consultados:\n${urls.map((u) => `- ${u}`).join("\n")}\n\n${LICENSE_NOTICE}`;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  let payload: {
    question?: string;
    region?: string;
    character?: string;
    content_type?: string;
    match_count?: number;
  };
  try {
    payload = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }
  const question = payload.question?.trim();
  if (!question) return json({ error: "Missing 'question'" }, 400);

  try {
    const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, { auth: { persistSession: false } });
    const embedding = await embedQuery(question);
    const { data, error } = await supabase.rpc("hybrid_search", {
      query_text: question,
      query_embedding: embedding,
      match_count: payload.match_count ?? MATCH_COUNT,
      filter_region: payload.region ?? null,
      filter_character: payload.character ?? null,
      filter_content_type: payload.content_type ?? null,
    });
    if (error) throw new Error(`hybrid_search: ${error.message}`);

    const retrieved = (data ?? []) as Chunk[];
    if (retrieved.length === 0) {
      return json({
        answer: `No se encontraron fragmentos relevantes en la wiki para esta pregunta.\n\n${LICENSE_NOTICE}`,
        fragments: [],
        sources: [],
        attribution: LICENSE_NOTICE,
      });
    }
    const ranked = await rerank(question, retrieved);

    const anthropic = new Anthropic();
    const response = await anthropic.beta.messages.create({
      model: CLAUDE_MODEL,
      max_tokens: 16000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: buildUserMessage(question, ranked) }],
    } as any);

    let answer: string;
    if (response.stop_reason === "refusal") {
      answer = "El modelo no pudo responder a esta pregunta.";
    } else {
      answer = response.content
        .filter((b: { type: string }) => b.type === "text")
        .map((b: { text: string }) => b.text)
        .join("")
        .trim();
    }

    return json({
      answer: answer + sourcesFooter(ranked),
      model: response.model,
      stop_reason: response.stop_reason,
      sources: [...new Set(ranked.map((c) => c.url))],
      attribution: LICENSE_NOTICE,
      fragments: ranked.map((c, i) => ({
        rank: i + 1,
        id: c.id,
        context: c.context,
        url: c.url,
        hybrid_score: c.score,
        fts_rank: c.fts_rank,
        semantic_rank: c.semantic_rank,
        rerank_score: c.rerank_score ?? null,
        metadata: c.metadata,
        content: c.content,
      })),
    });
  } catch (err) {
    return json({ error: err instanceof Error ? err.message : String(err) }, 500);
  }
});
