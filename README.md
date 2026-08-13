# RAG Chatbot

[![CI](https://github.com/lcduc/automatic-octo-computing-machines/actions/workflows/ci.yml/badge.svg)](https://github.com/lcduc/automatic-octo-computing-machines/actions/workflows/ci.yml)

A modular Retrieval-Augmented Generation (RAG) chatbot for intelligent Q&A over your documents. Upload files and chat with your data using AI. **Now powered by Docling with embedded EasyOCR for superior document conversion to Markdown format.**

## Architecture

This project follows a **domain-driven design** approach with clear separation of concerns:

### 🏗️ **Domain Organization**

- **Agent Domain** (`core/agent`): LLM integration, prompts, tool calling, confidence scoring
- **Document Processing Domain** (`core/document_processing`): File handling, format conversion, text extraction, OCR
- **Retrieval Domain** (`core/retrieval`): Search, reranking, embeddings, query expansion
- **Storage Domain** (`core/storage`): Vector storage, document metadata
- **Infrastructure Domain** (`core/infrastructure`): Audit trail, caching, lifecycle

### 🔧 **Key Benefits**

- **Maintainability**: Clear domain boundaries make code easier to understand and modify
- **Scalability**: Easy to add new features within appropriate domains
- **Testability**: Each domain can be tested independently
- **Team Development**: Different teams can work on different domains
- **Code Reusability**: Well-organized modules promote code reuse

---

## Features

- **Multi-format Support:** PDF, DOCX, TXT, CSV, XLSX
- **Docling Integration:** Superior document conversion to LLM-friendly Markdown format with embedded EasyOCR
- **Embedded OCR:** Docling's built-in EasyOCR for seamless text extraction
- **RAG-Powered Chat:** Context-aware answers from your knowledge base
- **Hybrid Search:** Combines semantic and keyword search
- **Query Expansion:** Improves retrieval with automatic query variations
- **Confidence Scoring:** Quality assessment for every response
- **Batch Processing:** Efficient vector storage and updates
- **Configurable:** 50+ environment variables

---

## Quick Start

**1. Clone & Configure**
```bash
git clone https://github.com/lcduc/automatic-octo-computing-machines.git
cd automatic-octo-computing-machine

# Create environment file
echo "OPENAI_API_KEY=your_api_key_here" > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
echo "HOST=0.0.0.0" >> .env
echo "PORT=8500" >> .env
echo "DEBUG=False" >> .env
```

**2. Run**

**Option A: Docker (Recommended)**
```bash
# Build and run with Docker Compose
docker-compose up --build

# Access the application at http://localhost:8500
# API docs at http://localhost:8500/docs
```

**Option B: Local Installation**

**Automated Setup:**
```bash
# Create the venv first, then bootstrap directories, .env and dependencies
python -m venv venv
venv\Scripts\activate          # Linux/Mac: source venv/bin/activate
python scripts/setup.py

python main.py
```

Note: `scripts/setup.py` installs everything in `requirements.txt`, but **not**
PyTorch — that needs a hardware-specific index URL, so install it separately as
shown under Manual Installation below.

**Manual Installation:**
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install PyTorch (choose based on your system)
# CPU only:
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1

# CUDA 11.8:
pip install torch==2.7.1+cu118 torchvision==0.22.1+cu118 torchaudio==2.7.1+cu118 --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1:
pip install torch==2.7.1+cu121 torchvision==0.22.1+cu121 torchaudio==2.7.1+cu121 --index-url https://download.pytorch.org/whl/cu121

# Install project dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

**3. Configure Environment**

Create a `.env` file in the project root with your configuration:

```bash
# Copy the example environment file
cp .env.example .env

# Edit the .env file with your settings
# Most importantly, set your OpenAI API key:
OPENAI_API_KEY=your_openai_api_key_here
```

**Note**: The `.env.example` file contains all available configuration options with their default values. Copy it to `.env` and customize as needed.

**4. Access the Application**

- **FastAPI Server**: http://localhost:8500
- **API Documentation**: http://localhost:8500/docs
- **Streamlit UI**: `streamlit run app.py` (runs on http://localhost:8501)

**To check your CUDA version:**  
- Run `nvidia-smi` in your terminal  
- Visit [PyTorch Get Started](https://pytorch.org/get-started/locally/) for more help

---

## Testing & Linting

Both run in CI on every push and pull request (see `.github/workflows/ci.yml`).

```bash
# Run the automated test suite
pytest

# Lint
ruff check .
```

`pytest` needs no API keys or network access: every setting in
`config/settings.py` falls back to a safe default and the suites stub out their
LLM clients.

Configuration for both tools lives in `pyproject.toml`. Note that
`test/test_chunk_ranking.py`, `test/test_model_response.py` and
`test/test_rag_process.py` are **manual CLI diagnostics**, not automated tests —
they need a populated vector store and downloaded models, so they are excluded
from collection. Run one directly when you want it:

```bash
python -m test.test_model_response "your query here"
```

---

## Security

See [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) for the security review,
including the deployment checklist. Two settings matter most before exposing
this service:

- **`API_KEY`** — unset by default, and while unset there is **no authentication
  on any endpoint**. Set it unless the service is on a trusted private network.
- **`DESTRUCTIVE_CLEANUP_ENABLED`** — keep `false` outside maintenance windows;
  it gates the endpoints that wipe or overwrite the knowledge base.

---

## API Endpoints

### Health & Status
| Endpoint           | Method | Description                        |
|--------------------|--------|------------------------------------|
| `/`                | GET    | Health check                       |
| `/status`          | GET    | System status                      |
| `/performance`     | GET    | Performance metrics                |
| `/cache-stats`     | GET    | Cache statistics                   |

### Chat & AI
| Endpoint           | Method | Description                        |
|--------------------|--------|------------------------------------|
| `/chat`            | POST   | Ask questions (RAG-powered)        |

### File Management
| Endpoint           | Method | Description                        |
|--------------------|--------|------------------------------------|
| `/files/upload`    | POST   | Upload files for processing        |

### Models & Maintenance
| Endpoint                         | Method | Description                                          |
|----------------------------------|--------|-------------------------------------------------------|
| `/models`                        | GET    | Model status and availability                        |
| `/cleanup`                       | POST   | Wipe all data & logs — disabled by default, see `DESTRUCTIVE_CLEANUP_ENABLED` |
| `/cleanup/vectors/rebuild`       | POST   | Rebuild vector store from existing chunks (non-destructive) |
| `/cleanup/query-adapter/update`  | POST   | Update query adapter                                 |

### Documentation
| Endpoint           | Method | Description                        |
|--------------------|--------|------------------------------------|
| `/docs`            | GET    | Interactive API documentation      |
| `/redoc`           | GET    | Alternative API documentation      |

---

## Project Structure

```
automatic-octo-computing-machine/
├── api/                            # FastAPI routes and middleware
│   └── routes/                     # API endpoints (chat, files, health)
├── core/                           # Core functionality modules (domain-organized, flat within each domain)
│   ├── llm/                        # LLM integration, prompts, and response confidence scoring
│   │   └── tools/                  # Tool-calling agent tools
│   ├── document_processing/        # Document handling: extraction, format processors (Docling-based), OCR engines
│   ├── retrieval/                  # Search, reranking, RAG context assembly, embeddings, and query expansion
│   ├── storage/                    # Vector and document/metadata persistence
│   └── infrastructure/             # System infrastructure (audit, caching, lifecycle)
├── config/                         # Configuration management (domain-organized)
│   ├── settings.py                 # Centralized configuration
│   ├── llm/                        # LLM config
│   ├── document_processing/        # Document processing config
│   ├── file/                       # File handling config
│   ├── rag/                        # RAG config
│   └── server/                     # Server config
├── services/                       # Business logic layer
├── utils/                          # Shared utilities (file management, text processing, performance, system/asyncio)
├── models/                         # Data models and schemas
├── scripts/                        # Utility scripts
├── data/                           # Runtime data storage
│   ├── chunks/                     # Document chunks
│   ├── vectors/                    # Vector embeddings
│   ├── logs/                       # Application logs
│   └── temp/                       # Temporary files
├── main.py                         # FastAPI application entry point
├── app.py                          # Streamlit application entry point
├── requirements.txt                # Python dependencies
├── docker-compose.yml              # Docker orchestration
├── Dockerfile                      # Container definition
└── README.md                       # This file
```

---

## Environment Configuration

The application uses environment variables for configuration. Key variables include:

### 🔑 **Required Variables**
- `OPENAI_API_KEY`: Your OpenAI API key for LLM functionality

### ⚙️ **Optional Variables**
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8500)
- `EMBEDDING_MODEL`: Embedding model, multilingual EN+VI (default: paraphrase-multilingual-MiniLM-L12-v2)
- `RERANKER_MODEL`: Reranker model, multilingual EN+VI (default: BAAI/bge-reranker-v2-m3)
- `MODELS_DIR`: Local cache dir for downloaded model weights (default: model_weights)
- `MAX_FILE_SIZE`: Maximum file size in bytes (default: 52428800)
- `CHUNK_SIZE`: Document chunk size (default: 1000)
- `SIMILARITY_THRESHOLD`: Search similarity threshold (default: 0.7)
- `MAX_HISTORY_LENGTH`: Max prior messages replayed into the prompt (default: 10)
- `RETRIEVAL_MAX_CONCURRENCY`: Concurrent GPU-bound retrieval ops per process (default: 4)
- `API_KEY`: Optional shared-secret header auth, empty = disabled (default: empty)
- `DESTRUCTIVE_CLEANUP_ENABLED`: Enables `POST /cleanup` (default: False)

See `.env.example` for a complete list of available configuration options.

---

## Requirements

### System Requirements
- **Python**: 3.10+ (3.11 recommended)
- **RAM**: 8GB+ (16GB recommended for large documents)
- **Storage**: 2GB+ free space
- **GPU**: 8GB+ VRAM NVIDIA GPU (optional, for faster processing)

### API Keys
- **OpenAI API Key**: Required for chat functionality
- **Optional**: Hugging Face token for model downloads

### System Dependencies (for local installation)
- **Windows**: Visual Studio Build Tools (for compiling packages)
- **Linux**: `gcc`, `g++`, `libgl1-mesa-glx`, `poppler-utils`
- **macOS**: Xcode Command Line Tools

### Optional Dependencies
- **Tesseract OCR**: For advanced OCR processing
  - Windows: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
  - Linux: `sudo apt-get install tesseract-ocr`
  - macOS: `brew install tesseract`

---

For advanced configuration, see [CONFIGURATION.md](CONFIGURATION.md).
