import os

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.rag_core import (
    BASE_DIR,
    answer_question,
    delete_document,
    ensure_data_dirs,
    ingest_pdf,
    list_documents,
)


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    @app.get("/")
    def home():
        query = request.args.get("q", "").strip()
        result = answer_question(query) if query else None
        return render_template("index.html", query=query, result=result)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        history = data.get("history") or []
        if not message:
            return jsonify({"error": "Message is required."}), 400

        result = answer_question(message, history=history)
        return jsonify(result)

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")

        if request.method == "POST":
            submitted_password = request.form.get("password", "")
            if submitted_password != admin_password:
                flash("Incorrect admin password.", "error")
                return redirect(url_for("admin"))

            upload = request.files.get("document")
            if not upload or not upload.filename:
                flash("Choose a PDF file to upload.", "error")
                return redirect(url_for("admin"))

            filename = secure_filename(upload.filename)
            if not filename.lower().endswith(".pdf"):
                flash("Only PDF files are supported in this first version.", "error")
                return redirect(url_for("admin"))

            ensure_data_dirs()
            temp_path = BASE_DIR / "data" / "uploads" / f"tmp_{filename}"
            upload.save(temp_path)
            try:
                info = ingest_pdf(temp_path, filename)
                flash(
                    f"Indexed {info['filename']} with {info['chunks_added']} searchable chunks.",
                    "success",
                )
            finally:
                if temp_path.exists():
                    temp_path.unlink()

            return redirect(url_for("admin"))

        return render_template(
            "admin.html",
            documents=list_documents(),
            has_sample=(BASE_DIR / "sample_1.pdf").exists(),
        )

    @app.post("/admin/ingest-sample")
    def ingest_sample():
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        if request.form.get("password", "") != admin_password:
            flash("Incorrect admin password.", "error")
            return redirect(url_for("admin"))

        sample_path = BASE_DIR / "sample_1.pdf"
        if not sample_path.exists():
            flash("sample_1.pdf was not found in the project folder.", "error")
            return redirect(url_for("admin"))

        info = ingest_pdf(sample_path, "sample_1.pdf")
        flash(
            f"Indexed {info['filename']} with {info['chunks_added']} searchable chunks.",
            "success",
        )
        return redirect(url_for("admin"))

    @app.post("/admin/delete/<document_id>")
    def remove_document(document_id):
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        if request.form.get("password", "") != admin_password:
            flash("Incorrect admin password.", "error")
            return redirect(url_for("admin"))

        removed = delete_document(document_id)
        flash(f"Removed {removed} chunks from the index.", "success")
        return redirect(url_for("admin"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
