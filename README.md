# 🤖 RAG Chatbot

A modular Retrieval-Augmented Generation (RAG) chatbot for intelligent Q&A over your documents and URLs. Upload files, process web content, and chat with your data using AI. **Now powered by Docling with embedded EasyOCR for superior document conversion to Markdown format.**

---

## Features

- **Multi-format Support:** PDF, DOCX, DOC, TXT, CSV, XLSX, XLS, PPTX, PPT, Images, Audio, EPUB, ZIP
- **Docling Integration:** Superior document conversion to LLM-friendly Markdown format with embedded EasyOCR
- **Embedded OCR:** Docling's built-in EasyOCR for seamless text extraction
- **URL Content Extraction:** Process and extract web content
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
cp .env.example .env
# Add your OpenAI API key to .env
```

**2. Run**

**Option A: Docker (Recommended)**
```bash
docker-compose up --build
```

**Option B: Local Installation**

**Automated Setup:**
```bash
# Run the automated setup script
setup_venv.bat
```

**Manual Installation:**
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate

## PyTorch Installation

The setup script automatically installs the correct PyTorch version. For manual installation:

| Your System         | Command                                                                                                         |
|---------------------|-----------------------------------------------------------------------------------------------------------------|
| **CPU only**        | `pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1`                                               |
| **CUDA 11.8**       | `pip install torch==2.7.1+cu118 torchvision==0.22.1+cu118 torchaudio==2.7.1+cu118 --index-url https://download.pytorch.org/whl/cu118` |
| **CUDA 12.1**       | `pip install torch==2.7.1+cu121 torchvision==0.22.1+cu121 torchaudio==2.7.1+cu121 --index-url https://download.pytorch.org/whl/cu121` |
| **Other CUDA**      | [Find your version here](https://pytorch.org/get-started/locally/)                                              |

**To check your CUDA version:**  
- Run `nvidia-smi` in your terminal.  
- Or visit the [PyTorch Get Started page](https://pytorch.org/get-started/locally/) for more help.

# Install project dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

---

## API Endpoints

| Endpoint           | Method | Description                        |
|--------------------|--------|------------------------------------|
| `/`                | GET    | Health check                       |
| `/chat`            | GET    | Ask questions                      |
| `/files/upload`    | POST   | Upload files                       |
| `/files/url`       | POST   | Process URLs                       |
| `/docs`            | GET    | API documentation                  |

---

## Project Structure

```
automatic-octo-computing-machine/
├── api/                            # FastAPI routes and middleware
│   └── routes/                     # API endpoints (chat, files, health)
├── core/                           # Core functionality modules
│   ├── llm/                        # Language model integration
│   ├── ocr/                        # OCR processing with GPU support
│   ├── processing/                 # Document processors (now Docling-based)
│   │   └── docling_processor.py    # Docling integration with embedded EasyOCR
│   ├── rag/                        # Retrieval-Augmented Generation
│   └── storage/                    # Vector and document storage
├── services/                       # Business logic layer
├── utils/                          # Shared utilities
├── models/                         # Data models and schemas
├── data/                           # Runtime data storage
│   ├── chunks/                     # Document chunks
│   ├── vectors/                    # Vector embeddings
│   ├── logs/                       # Application logs
│   └── temp/                       # Temporary files
├── main.py                         # Application entry point
├── config.py                       # Configuration management
├── requirements.txt                # Python dependencies
├── docker-compose.yml              # Docker orchestration
├── Dockerfile                      # Container definition
├── CONFIGURATION.md                # Configuration documentation
└── README.md                       # This file
```

---

## Requirements

- Python 3.10+
- 8GB+ RAM
- OpenAI API key
- 8GB+ VRAM NVIDIA GPU

---

For advanced configuration, see [CONFIGURATION.md](CONFIGURATION.md).
