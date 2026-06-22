# Campus RAG Notice Hub

A small RAG-based web project for college students. Admins upload PDF notices, timetables, fest circulars, and test schedules. Students open the website and ask questions in natural language.

This version supports PDF input first. Image support can be added later by running OCR on uploaded images and passing the extracted text into the same indexing flow.

## Setup

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The app works without an LLM by using local PDF retrieval. To enable Gemini-written answers, create a `.env` file in the project folder:

```text
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-1.5-flash
LLM_PROVIDER=gemini
```

You can copy `.env.example` and fill in your real key. Do not share or commit your `.env` file.

## Run

```powershell
flask --app app.main run --debug
```

Open:

- Student Q&A: http://127.0.0.1:5000/
- Admin upload: http://127.0.0.1:5000/admin

Default admin password:

```text
admin123
```

To change it:

```powershell
$env:ADMIN_PASSWORD="your-password"
flask --app app.main run --debug
```

## Using the sample PDF

The admin page has a button to index the existing `sample_1.pdf` file. After indexing, go to the student page and ask questions about the PDF.

## Project structure

```text
app/
  main.py              Flask routes
  rag_core.py          PDF extraction, chunking, retrieval, answers
  templates/           HTML pages
  static/styles.css    UI styles
data/
  uploads/             Uploaded PDFs
  index/chunks.json    Local searchable index
sample_1.pdf           Existing sample document
```

## Next step for image support

Add an image upload route for the admin, run OCR with a tool such as Tesseract or a vision API, then store the extracted text as chunks just like the PDF text. That is the right direction: make PDF RAG work first, then add image OCR as another ingestion source.

## Deploy

Recommended for a college demo: Render or Railway.

Important: this app stores uploaded PDFs and the local RAG index in `data/`. On a hosted server, use persistent storage for that folder or uploads can disappear after redeploys/restarts.

Render settings:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn app.main:app
```

Environment variables to add on the hosting platform:

```text
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-1.5-flash
LLM_PROVIDER=gemini
ADMIN_PASSWORD=choose-a-strong-password
SECRET_KEY=choose-a-random-secret
DATA_DIR=/opt/render/project/src/data
```

On Render, add a persistent disk mounted at:

```text
/opt/render/project/src/data
```

For a simple demo where you do not need uploaded files to survive redeploys, you can skip the disk. For a real submission/demo used over multiple days, use the disk or move storage to a database/cloud bucket later.
