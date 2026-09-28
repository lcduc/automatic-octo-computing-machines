"""
Admin chunking contract: the strategies a document can be split with, previews and re-chunking.
"""

# Standard library imports
from typing import Annotated, Any, Dict, List, Literal, Union

# Third-party imports
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# Local imports
from config.settings import Config
from core.document_processing.chunking import MAX_CHUNK_CHARS, STRATEGY_DESCRIPTIONS
from models.knowledge import ChunkingResult, ChunkingSpec

#: Smallest size cap an admin may set, in characters.
MIN_CHUNK_CHARS = 200
#: Size cap for the structural strategies unless the admin sets one.
DEFAULT_STRUCTURED_MAX_CHARS = 3000
DEFAULT_PREVIEW_LIMIT = 200
MAX_PREVIEW_LIMIT = 1000

MaxChars = Annotated[int, Field(ge=MIN_CHUNK_CHARS, le=MAX_CHUNK_CHARS, description="Size cap per chunk, in characters")]


class _Strategy(BaseModel):
    """Strategy parameters; unknown keys are rejected so typos fail loudly."""

    model_config = ConfigDict(extra="forbid")


class AutoChunking(_Strategy):
    strategy: Literal["auto"] = "auto"


class SizeChunking(_Strategy):
    strategy: Literal["size"]
    max_chars: MaxChars = Field(default_factory=Config.File.CHUNK_SIZE)
    overlap: bool = Field(False, description="Repeat the last sentence of a chunk at the start of the next")


class HeadingChunking(_Strategy):
    strategy: Literal["heading"]
    max_level: int = Field(2, ge=1, le=6, description="Deepest markdown heading level that starts a chunk")
    max_chars: MaxChars = DEFAULT_STRUCTURED_MAX_CHARS


class LegalArticleChunking(_Strategy):
    strategy: Literal["legal_article"]
    split_at: Literal["chapter", "section", "article", "clause"] = "article"
    max_chars: MaxChars = DEFAULT_STRUCTURED_MAX_CHARS
    breadcrumb: bool = Field(True, description="Prefix each chunk with its Chương / Mục titles")


class QaPairChunking(_Strategy):
    strategy: Literal["qa_pair"]


class TableRowsChunking(_Strategy):
    strategy: Literal["table_rows"]
    rows_per_chunk: int = Field(10, ge=1, le=200)
    max_chars: MaxChars = DEFAULT_STRUCTURED_MAX_CHARS


class WholeChunking(_Strategy):
    strategy: Literal["whole"]


STRATEGY_MODELS = (
    AutoChunking, SizeChunking, HeadingChunking, LegalArticleChunking, QaPairChunking, TableRowsChunking, WholeChunking
)
ChunkingConfig = Annotated[
    Union[
        AutoChunking, SizeChunking, HeadingChunking, LegalArticleChunking, QaPairChunking, TableRowsChunking, WholeChunking
    ],
    Field(discriminator="strategy"),
]
#: Validates the JSON ``chunking`` form field of an upload.
CHUNKING_ADAPTER: TypeAdapter = TypeAdapter(ChunkingConfig)


def to_spec(config: BaseModel) -> ChunkingSpec:
    """The internal spec for a validated strategy model (defaults filled in)."""
    return ChunkingSpec.from_json(config.model_dump())


class ChunkingPreviewRequest(BaseModel):
    """Try a strategy on a document's stored text."""

    chunking: ChunkingConfig
    limit: int = Field(DEFAULT_PREVIEW_LIMIT, ge=1, le=MAX_PREVIEW_LIMIT, description="Chunks returned (all are counted)")


class RechunkRequest(BaseModel):
    """Replace a document's chunks with its stored text split by a strategy."""

    chunking: ChunkingConfig
    discard_manual_edits: bool = Field(False, description="Required when chunks were edited by hand")


class PreviewChunk(BaseModel):
    """One chunk a strategy would produce."""

    position: int
    content: str
    metadata: Dict[str, Any]
    char_count: int


class ChunkingPreview(BaseModel):
    """What a strategy would produce, with size statistics and warnings."""

    chunk_count: int
    min_chars: int
    max_chars: int
    avg_chars: int
    warnings: List[str]
    chunks: List[PreviewChunk]

    @classmethod
    def from_result(cls, result: ChunkingResult, limit: int) -> "ChunkingPreview":
        """Summarise ``result`` and include its first ``limit`` chunks."""
        sizes = [len(draft.content) for draft in result.drafts]
        return cls(
            chunk_count=len(sizes),
            min_chars=min(sizes),
            max_chars=max(sizes),
            avg_chars=round(sum(sizes) / len(sizes)),
            warnings=result.warnings,
            chunks=[
                PreviewChunk(position=i, content=d.content, metadata=d.metadata, char_count=len(d.content))
                for i, d in enumerate(result.drafts[:limit])
            ],
        )


class ChunkingStrategyInfo(BaseModel):
    """A strategy and the JSON schema of its parameters, for building the admin form."""

    name: str
    description: str
    params_schema: Dict[str, Any]


def strategy_catalog() -> List[ChunkingStrategyInfo]:
    """Every strategy with its description and parameter schema."""
    catalog = []
    for model in STRATEGY_MODELS:
        name = model.model_fields["strategy"].annotation.__args__[0]
        catalog.append(
            ChunkingStrategyInfo(name=name, description=STRATEGY_DESCRIPTIONS[name], params_schema=model.model_json_schema())
        )
    return catalog
