import streamlit as st
import requests

API_URL = "http://localhost:8000"

st.set_page_config(

    page_title="Document QA System",

    layout="wide"
)

st.title("🔍 Document QA System")

# ====================================
# SIDEBAR
# ====================================

st.sidebar.header("Settings")

hf_token = st.sidebar.text_input(

    "Groq API Key (Optional)",

    type="password"
)

# ====================================
# HEALTH STATUS
# ====================================

try:

    health = requests.get(
        f"{API_URL}/api/health"
    ).json()

    st.sidebar.success(
        f"System: {health['status']}"
    )

    st.sidebar.write(
        f"Indexed Chunks: "
        f"{health['indexed_chunks']}"
    )

except:

    st.sidebar.error(
        "Backend offline"
    )

# ====================================
# DOCUMENTS
# ====================================

try:

    docs = requests.get(
        f"{API_URL}/api/documents"
    ).json()

    st.sidebar.subheader(
        "Indexed Documents"
    )

    st.sidebar.write(
        f"Total Files: "
        f"{docs['total_files']}"
    )

    for file in docs["indexed_files"]:

        st.sidebar.caption(file)

except:

    pass

# ====================================
# RESET BUTTON
# ====================================

if st.sidebar.button(
    "Clear Vector Store"
):

    response = requests.delete(
        f"{API_URL}/api/reset"
    )

    st.sidebar.success(

        response.json()["message"]
    )

# ====================================
# FILE UPLOAD
# ====================================

st.sidebar.subheader(
    "Upload Document"
)

uploaded_file = st.sidebar.file_uploader(

    "Upload PDF/TXT/DOCX",

    type=["pdf", "txt", "docx"]
)

# ====================================
# UPLOAD BUTTON
# ====================================

if uploaded_file and st.sidebar.button(
    "Upload Document"
):

    files = {

        "file": (

            uploaded_file.name,

            uploaded_file.getvalue()
        )
    }

    try:

        response = requests.post(

            f"{API_URL}/api/upload",

            files=files
        )

        data = response.json()

        if response.status_code == 200:

            if "message" in data:

                st.sidebar.success(
                    data["message"]
                )

            else:

                st.sidebar.success(

                    f"Indexed {data['chunks']} chunks "
                    f"from {data['filename']}"
                )

        else:

            st.sidebar.error(
                "Upload failed."
            )

    except Exception as e:

        st.sidebar.error(
            f"Connection error: {e}"
        )

# ====================================
# CHAT INPUT
# ====================================

question = st.chat_input(
    "Ask your documents..."
)

if question:

    st.chat_message("user").write(
        question
    )

    with st.spinner(
        "Generating answer..."
    ):

        try:

            response = requests.post(

                f"{API_URL}/api/query",

                json={

                    "question": question,

                    "hf_token": hf_token
                }
            )

            data = response.json()

            # ====================================
            # ERROR HANDLING
            # ====================================

            if "error" in data:

                st.error(
                    data["error"]
                )

            else:

                # ====================================
                # ANSWER
                # ====================================

                st.chat_message(
                    "assistant"
                ).write(

                    data["answer"]
                )

                # ====================================
                # METRICS
                # ====================================

                metrics = data["metrics"]

                st.subheader("Metrics")

                col1, col2, col3 = st.columns(3)

                col1.metric(

                    "Retrieval",

                    f"{metrics['faiss_ms']} ms"
                )

                col2.metric(

                    "Reranking",

                    f"{metrics['reranking_ms']} ms"
                )

                col3.metric(

                    "Generation",

                    f"{metrics['generation_ms']} ms"
                )

                st.metric(

                    "Total Latency",

                    f"{metrics['total_ms']} ms"
                )

                # ====================================
                # SOURCES
                # ====================================

                st.subheader("Sources")

                for source in data["sources"]:

                    with st.expander(

                        f"{source['source_file']} "

                        f"(Chunk "
                        f"{source['chunk_id']})"
                    ):

                        st.write(
                            source["content"]
                        )

                        st.caption(

                            f"Relevance Score: "
                            f"{source['score']}"
                        )

        except Exception as e:

            st.error(

                f"Backend connection failed: {e}"
            )