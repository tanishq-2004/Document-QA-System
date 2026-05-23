import os
import shutil
import hashlib
import pickle
import time
from pathlib import Path

import docx
from fastapi import FastAPI, File, UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from sentence_transformers import CrossEncoder


UPLOAD_DIR = "uploaded_docs"
VECTOR_STORE_PATH = "vector_store"

os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = None

if os.path.exists(f"{VECTOR_STORE_PATH}/index.faiss"):

    vectorstore = FAISS.load_local(

        VECTOR_STORE_PATH,

        embeddings,

        allow_dangerous_deserialization=True
    )

reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2"
)

LLM_MODEL = "llama-3.1-8b-instant"


def clean_text(text):

    text = text.replace("\n", " ")

    text = " ".join(text.split())

    return text


def extract_text(file_path):

    if file_path.endswith(".pdf"):

        loader = PyPDFLoader(file_path)

        docs = loader.load()

        text = "\n".join(

            [doc.page_content for doc in docs]
        )

        return clean_text(text)

    elif file_path.endswith(".txt"):

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            return clean_text(f.read())

    elif (
        file_path.endswith(".docx")
        or file_path.endswith(".doc")
    ):

        doc = docx.Document(file_path)

        text = "\n".join(

            [para.text for para in doc.paragraphs]
        )

        return clean_text(text)

    else:

        raise ValueError(
            "Unsupported file type."
        )


def get_file_hash(file_path):

    with open(file_path, "rb") as f:

        return hashlib.sha256(
            f.read()
        ).hexdigest()


def split_text(text, filename):

    splitter = RecursiveCharacterTextSplitter(

        chunk_size=500,

        chunk_overlap=50
    )

    chunks = splitter.create_documents([text])

    for i, chunk in enumerate(chunks):

        chunk.metadata = {

            "source": filename,

            "chunk_id": i
        }

    return chunks


def save_vectorstore():

    global vectorstore

    if vectorstore:

        vectorstore.save_local(
            VECTOR_STORE_PATH
        )


def generate_answer(
    question,
    context,
    api_key
):

    if not api_key:

        return (

            "Retrieval-only mode "
            "(no Groq API key provided).\n\n"

            f"Top retrieved context:\n\n"

            f"{context[:800]}"
        )

    try:

        client = OpenAI(

            api_key=api_key,

            base_url="https://api.groq.com/openai/v1"
        )

        response = client.chat.completions.create(

            model=LLM_MODEL,

            messages=[

                {
                    "role": "system",

                    "content": (
                        "You are a helpful assistant. "
                        "Answer ONLY using the provided context. "
                        "If the answer is not present "
                        "in the context, say that clearly."
                    )
                },

                {
                    "role": "user",

                    "content": (
                        f"Context:\n{context}\n\n"
                        f"Question:\n{question}"
                    )
                }
            ],

            max_tokens=300,

            temperature=0.3
        )

        return response.choices[0].message.content

    except Exception as e:

        return (

            f"LLM generation failed: {e}\n\n"

            f"Retrieved context:\n\n"

            f"{context[:600]}"
        )


@app.get("/")
def home():

    return {

        "message":
        "Document QA System Running"
    }


@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...)
):

    global vectorstore

    file_path = os.path.join(
        UPLOAD_DIR,
        file.filename
    )

    with open(file_path, "wb") as f:

        shutil.copyfileobj(
            file.file,
            f
        )

    file_hash = get_file_hash(file_path)

    cache_path = (
        f"{VECTOR_STORE_PATH}/{file_hash}.pkl"
    )

    if os.path.exists(cache_path):

        return {

            "message":
            "Document already indexed"
        }

    text = extract_text(file_path)

    chunks = split_text(
        text,
        file.filename
    )

    if vectorstore is None:

        vectorstore = FAISS.from_documents(

            chunks,

            embeddings
        )

    else:

        vectorstore.add_documents(chunks)

    save_vectorstore()

    with open(cache_path, "wb") as f:

        pickle.dump(

            {"indexed": True},

            f
        )

    return {

        "filename": file.filename,

        "characters": len(text),

        "chunks": len(chunks),

        "indexed": True
    }


@app.post("/api/query")
def query_documents(data: dict):

    global vectorstore

    t0 = time.perf_counter()

    question = data["question"]

    hf_token = data.get("hf_token")

    if vectorstore is None:

        return {

            "error":
            "No documents indexed"
        }

    if len(question.strip()) < 3:

        return {

            "error":
            "Query too short"
        }

    candidates = vectorstore.similarity_search(

        question,

        k=10
    )

    t1 = time.perf_counter()

    pairs = [

        (question, doc.page_content)

        for doc in candidates
    ]

    scores = reranker.predict(pairs)

    ranked_docs = sorted(

        zip(scores, candidates),

        key=lambda x: x[0],

        reverse=True
    )

    top_docs = [

        doc

        for score, doc in ranked_docs[:3]
    ]

    t2 = time.perf_counter()

    context = "\n\n".join([

        doc.page_content

        for doc in top_docs
    ])

    answer = generate_answer(

        question,

        context,

        hf_token
    )

    t3 = time.perf_counter()

    sources = []

    for score, doc in ranked_docs[:3]:

        sources.append({

            "source_file": doc.metadata.get(
                "source",
                "unknown"
            ),

            "chunk_id": doc.metadata.get(
                "chunk_id",
                "N/A"
            ),

            "score": round(
                float(score),
                2
            ),

            "content": (

                doc.page_content

                .replace("\n", " ")

                .strip()[:350]

                + (

                    "..."

                    if len(doc.page_content) > 350

                    else ""
                )
            )
        })

    return {

        "question": question,

        "answer": answer,

        "sources": sources,

        "metrics": {

            "faiss_ms": round(

                (t1 - t0) * 1000,

                1
            ),

            "reranking_ms": round(

                (t2 - t1) * 1000,

                1
            ),

            "generation_ms": round(

                (t3 - t2) * 1000,

                1
            ),

            "total_ms": round(

                (t3 - t0) * 1000,

                1
            ),

            "stage1_candidates": len(
                candidates
            ),

            "final_sources": len(
                top_docs
            )
        }
    }


@app.get("/api/health")
def health():

    total_chunks = 0

    if vectorstore:

        total_chunks = vectorstore.index.ntotal

    return {

        "status": "healthy",

        "indexed_chunks": total_chunks
    }


@app.get("/api/documents")
def list_documents():

    files = []

    for file in os.listdir(UPLOAD_DIR):

        files.append(file)

    total_chunks = 0

    if vectorstore:

        total_chunks = vectorstore.index.ntotal

    return {

        "indexed_files": files,

        "total_files": len(files),

        "total_chunks": total_chunks
    }


@app.delete("/api/reset")
def reset_index():

    global vectorstore

    vectorstore = None

    if os.path.exists(VECTOR_STORE_PATH):

        shutil.rmtree(VECTOR_STORE_PATH)

    os.makedirs(
        VECTOR_STORE_PATH,
        exist_ok=True
    )

    for file in os.listdir(UPLOAD_DIR):

        file_path = os.path.join(
            UPLOAD_DIR,
            file
        )

        if os.path.isfile(file_path):

            os.remove(file_path)

    return {

        "message":
        "Index and uploaded files cleared successfully."
    }