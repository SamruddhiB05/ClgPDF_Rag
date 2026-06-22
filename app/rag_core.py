import json
import math
import os
import re
import shutil
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
INDEX_PATH = DATA_DIR / "index" / "chunks.json"

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
STOPWORDS = {
    "a",
    "about",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "give",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "tell",
    "that",
    "the",
    "there",
    "this",
    "to",
    "up",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}

QUERY_EXPANSIONS = {
    "fest": ["festival", "event", "events", "main", "pre"],
    "fests": ["festival", "event", "events", "main", "pre"],
    "event": ["events", "fest", "festival"],
    "events": ["event", "fest", "festival"],
    "test": ["exam", "assessment", "schedule", "date"],
    "tests": ["exam", "assessment", "schedule", "date"],
    "exam": ["test", "assessment", "schedule", "date"],
    "upcoming": ["incoming", "schedule", "date", "events"],
    "incoming": ["upcoming", "schedule", "date", "events"],
    "date": ["schedule", "time", "day"],
    "dates": ["schedule", "time", "day"],
}


def ensure_data_dirs():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)


def tokenize(text):
    return [token.lower() for token in TOKEN_RE.findall(text)]


def search_tokens(text):
    tokens = [token for token in tokenize(text) if token not in STOPWORDS]
    expanded = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(QUERY_EXPANSIONS.get(token, []))
    return expanded


def clean_extracted_text(text):
    clean = re.sub(r"\s+", " ", text).strip()
    for size in range(6, 0, -1):
        pattern = re.compile(
            r"\b((?:[a-zA-Z0-9]+\s+){" + str(size - 1) + r"}[a-zA-Z0-9]+)(?:\s+\1\b)+",
            re.IGNORECASE,
        )
        previous = None
        while previous != clean:
            previous = clean
            clean = pattern.sub(r"\1", clean)
    return clean


def chunk_text(text, chunk_size=900, overlap=160):
    clean = clean_extracted_text(text)
    if not clean:
        return []

    chunks = []
    start = 0
    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(clean):
            break
        start = max(0, end - overlap)
    return chunks


def load_chunks():
    ensure_data_dirs()
    if not INDEX_PATH.exists():
        return []
    with INDEX_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_chunks(chunks):
    ensure_data_dirs()
    with INDEX_PATH.open("w", encoding="utf-8") as file:
        json.dump(chunks, file, indent=2, ensure_ascii=False)


def list_documents():
    chunks = load_chunks()
    documents = {}
    for chunk in chunks:
        doc_id = chunk["document_id"]
        documents.setdefault(
            doc_id,
            {
                "document_id": doc_id,
                "filename": chunk["filename"],
                "chunk_count": 0,
                "pages": set(),
            },
        )
        documents[doc_id]["chunk_count"] += 1
        documents[doc_id]["pages"].add(chunk["page"])

    result = []
    for document in documents.values():
        pages = sorted(document["pages"])
        document["page_count"] = len(pages)
        document["pages"] = pages
        result.append(document)
    return sorted(result, key=lambda item: item["filename"].lower())


def ingest_pdf(source_path, original_filename=None):
    ensure_data_dirs()
    source_path = Path(source_path)
    filename = original_filename or source_path.name
    document_id = str(uuid.uuid4())
    stored_name = f"{document_id}_{filename}"
    stored_path = UPLOAD_DIR / stored_name
    shutil.copy2(source_path, stored_path)

    reader = PdfReader(str(stored_path))
    new_chunks = []

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for index, chunk in enumerate(chunk_text(text), start=1):
            new_chunks.append(
                {
                    "id": f"{document_id}:p{page_number}:c{index}",
                    "document_id": document_id,
                    "filename": filename,
                    "stored_path": str(stored_path.relative_to(BASE_DIR)),
                    "page": page_number,
                    "text": chunk,
                }
            )

    chunks = load_chunks()
    chunks.extend(new_chunks)
    save_chunks(chunks)
    return {
        "document_id": document_id,
        "filename": filename,
        "chunks_added": len(new_chunks),
        "pages": len(reader.pages),
    }


def delete_document(document_id):
    chunks = load_chunks()
    kept = []
    removed_paths = set()
    removed_count = 0
    for chunk in chunks:
        if chunk["document_id"] == document_id:
            removed_count += 1
            removed_paths.add(chunk.get("stored_path"))
        else:
            kept.append(chunk)
    save_chunks(kept)

    for relative_path in removed_paths:
        if relative_path:
            path = BASE_DIR / relative_path
            if path.exists() and path.is_file():
                path.unlink()

    return removed_count


def _build_search_stats(chunks):
    document_frequency = defaultdict(int)
    tokenized_chunks = []
    for chunk in chunks:
        tokens = search_tokens(chunk["text"])
        tokenized_chunks.append(tokens)
        for token in set(tokens):
            document_frequency[token] += 1

    total = max(1, len(chunks))
    average_length = sum(len(tokens) for tokens in tokenized_chunks) / total
    idf = {
        token: math.log((total + 1) / (frequency + 1)) + 1
        for token, frequency in document_frequency.items()
    }
    return idf, tokenized_chunks, max(1, average_length)


def retrieve(query, top_k=6):
    chunks = load_chunks()
    query_tokens = search_tokens(query)
    if not chunks or not query_tokens:
        return []

    idf, tokenized_chunks, average_length = _build_search_stats(chunks)
    query_counts = Counter(query_tokens)
    scored = []
    query_text = " ".join(tokenize(query))

    for chunk, chunk_tokens in zip(chunks, tokenized_chunks):
        if not chunk_tokens:
            continue

        chunk_counts = Counter(chunk_tokens)
        length = len(chunk_tokens)
        score = 0.0
        coverage = 0

        for token in query_counts:
            frequency = chunk_counts.get(token, 0)
            if not frequency:
                continue

            coverage += 1
            k1 = 1.5
            b = 0.75
            numerator = frequency * (k1 + 1)
            denominator = frequency + k1 * (1 - b + b * (length / average_length))
            score += idf.get(token, 1.0) * (numerator / denominator)

        normalized_text = " ".join(tokenize(chunk["text"]))
        if query_text and query_text in normalized_text:
            score += 4.0

        if coverage:
            score += 1.5 * (coverage / max(1, len(set(query_counts))))

        if any(word in query_counts for word in ("event", "events", "fest", "festival")):
            if "pre events" in normalized_text or "main events" in normalized_text:
                score += 3.0
            if "contents" in normalized_text:
                score += 1.25
            if "registration form" in normalized_text and "register" not in query_counts:
                score -= 1.75

        if any(word in query_counts for word in ("date", "dates", "schedule", "time")):
            if re.search(r"\b(\d{1,2}[-/]\d{1,2}|\d{1,2}(st|nd|rd|th)?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", normalized_text):
                score += 1.25

        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def _format_sources(matches):
    return "\n\n".join(
        f"[{index}] {match['filename']}, page {match['page']}\n{clean_extracted_text(match['text'])}"
        for index, match in enumerate(matches, start=1)
    )


def _local_answer(query, matches):
    if not matches:
        return "I could not find this in the uploaded PDF documents yet. Ask the admin to upload the related notice, timetable, or fest circular."

    compact_points = []
    for match in matches[:4]:
        text = clean_extracted_text(match["text"])
        if len(text) > 520:
            text = text[:520].rsplit(" ", 1)[0] + "..."
        compact_points.append(f"- {text} ({match['filename']}, page {match['page']})")

    return (
        "I found these relevant details in the uploaded documents:\n\n"
        + "\n".join(compact_points)
        + "\n\nFor a more natural summary, set a Gemini API key in .env and restart the app."
    )


def _public_sources(matches):
    sources = []
    for match in matches:
        source = dict(match)
        source["text"] = clean_extracted_text(source["text"])
        sources.append(source)
    return sources


def _build_llm_prompt(query, matches, history=None):
    history = history or []
    context = _format_sources(matches)
    history_lines = []
    for item in history[-6:]:
        role = item.get("role", "").title()
        content = item.get("content", "")
        if role in {"User", "Assistant"} and content:
            history_lines.append(f"{role}: {content[:1200]}")

    return (
        "You are a helpful college notice assistant.\n"
        "Answer only from the provided PDF context.\n"
        "If the answer is not present, say that it is not available in the uploaded documents.\n"
        "Keep answers concise, student-friendly, and include source page references.\n\n"
        f"Recent chat:\n{chr(10).join(history_lines) if history_lines else 'No previous chat.'}\n\n"
        f"Question: {query}\n\n"
        f"PDF context:\n{context}"
    )


def _gemini_answer(query, matches, history=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    genai.configure(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(
        _build_llm_prompt(query, matches, history),
        generation_config={"temperature": 0.2},
        request_options={"timeout": 30},
    )
    return (response.text or "").strip()


def _openai_answer(query, matches, history=None):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key, timeout=30)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful college notice assistant. Answer only from the provided PDF context. "
                "If the answer is not present, say that it is not available in the uploaded documents. "
                "Keep answers concise, student-friendly, and include source page references."
            ),
        },
        {"role": "user", "content": _build_llm_prompt(query, matches, history)},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def _llm_answer(query, matches, history=None):
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider in {"local", "none", "off"}:
        return None

    providers = {
        "gemini": _gemini_answer,
        "openai": _openai_answer,
    }

    ordered = [providers.get(provider), _gemini_answer, _openai_answer]
    seen = set()
    for answerer in ordered:
        if answerer is None or answerer in seen:
            continue
        seen.add(answerer)
        answer = answerer(query, matches, history)
        if answer:
            return answer
    return None


def answer_question(query, history=None):
    matches = retrieve(query)
    if not matches:
        return {
            "answer": _local_answer(query, matches),
            "sources": [],
            "mode": "local",
        }

    try:
        llm_answer = _llm_answer(query, matches, history)
    except Exception as error:
        llm_answer = None
        llm_error = str(error)
    else:
        llm_error = None

    if llm_answer:
        return {"answer": llm_answer, "sources": _public_sources(matches), "mode": "llm"}

    answer = _local_answer(query, matches)
    if llm_error:
        answer += f"\n\nLLM fallback reason: {llm_error}"
    return {"answer": answer, "sources": _public_sources(matches), "mode": "local"}
