"""
Routes a message by meaning, before any retrieval or LLM work is spent on it.

Each route (greeting, thanks, ...) is a list of example messages in ``routes.json``. The message is
embedded with the same model the retriever uses and compared with every example; the closest
route wins when it is similar enough and clearly ahead of the runner-up. Anything the router is
not sure about is a ``RAG_QUESTION`` and goes to retrieval: a missed shortcut costs one retrieval,
a wrong shortcut would refuse or misroute a real question.
"""

# Standard library imports
import json
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Third-party imports
import numpy as np

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)

ROUTES_FILE = Path(__file__).parent / "routes.json"
#: Greeting / thanks / ambiguous shortcuts only apply to short messages, so "hi, delete my account" is a question.
SHORT_MESSAGE_MAX_CHARS = 40


class RouteIntent(str, Enum):
    """What the pipeline should do with a message; values are the route names in ``routes.json``."""

    GREETING = "greeting"
    THANKS = "thanks"
    HANDOFF_REQUEST = "handoff_request"
    AMBIGUOUS = "ambiguous"
    OFF_TOPIC = "off_topic"
    RAG_QUESTION = "rag_question"


#: Calibrated with ``python -m scripts.eval_router`` for the default embedding model; override per environment.
DEFAULT_THRESHOLDS: Dict[RouteIntent, float] = {
    RouteIntent.GREETING: 0.90,
    RouteIntent.THANKS: 0.90,
    RouteIntent.HANDOFF_REQUEST: 0.90,
    RouteIntent.AMBIGUOUS: 0.90,
    RouteIntent.OFF_TOPIC: 0.93,
}
#: Routes that only act on short messages.
SHORT_ONLY = frozenset({RouteIntent.GREETING, RouteIntent.THANKS, RouteIntent.AMBIGUOUS})


@dataclass(frozen=True)
class RouteDecision:
    """The router's verdict on one message, with the scores behind it (logged and used by the pipeline)."""

    intent: RouteIntent
    #: Similarity to the best route's examples.
    score: float
    #: Best route's name and the runner-up's name and score (for threshold tuning).
    best_route: str
    runner_up: str
    runner_up_score: float
    #: Similarity to every route's examples.
    scores: Dict[str, float]

    @property
    def off_topic_lead(self) -> float:
        """How much closer the message is to the off-topic examples than to the on-topic ones (negative: closer to on-topic)."""
        return self.scores.get(RouteIntent.OFF_TOPIC.value, 0.0) - self.scores.get(RouteIntent.RAG_QUESTION.value, 0.0)

    @property
    def looks_off_topic(self) -> bool:
        """
        True when the message sits nearer the off-topic examples than the on-topic ones.

        The second off-topic signal: only used after retrieval found nothing, to refuse instead of
        handing a message that was never about this assistant's subject to staff.
        """
        return self.off_topic_lead >= Config.Routing.OFF_TOPIC_LEAD()

    def is_off_topic(self, best_rerank: Optional[float]) -> bool:
        """
        Whether a message that found nothing should be refused instead of handed to staff.

        Either it sits nearer the off-topic examples (:attr:`looks_off_topic`), or nothing in the
        knowledge base relates to it at all (a near-zero best reranker score) and it is not clearly
        on topic. ``best_rerank`` is ``None`` when no reranker scored, which leaves the first test only.
        """
        if self.looks_off_topic:
            return True
        return (
            best_rerank is not None
            and best_rerank < Config.Routing.OFF_TOPIC_MAX_RERANK()
            and self.off_topic_lead > Config.Routing.OFF_TOPIC_MIN_LEAD()
        )


class EmbeddingRouter:
    """Classifies a message against the example messages of each route."""

    def __init__(self, embedding_service, routes_path: Path = ROUTES_FILE):
        """
        Args:
            embedding_service: The retriever's embedding service (``embed_query(text)`` -> unit vector).
            routes_path: JSON file with ``{"routes": {<route name>: [<example>, ...]}}``.
        """
        self._embedding = embedding_service
        self._routes_path = routes_path
        self._lock = threading.Lock()
        self._names: List[str] = []
        self._owners: Optional[np.ndarray] = None
        self._vectors: Optional[np.ndarray] = None

    def classify(self, text: str) -> RouteDecision:
        """
        Route one message. Blocking (embeds the message); call it from a worker thread.

        Returns:
            The decision; ``RAG_QUESTION`` unless a shortcut route is confident.
        """
        self._load()
        vector = np.asarray(self._embedding.embed_query(text), dtype=np.float32).reshape(-1)
        similarities = self._vectors @ vector
        scores = {name: float(similarities[self._owners == index].max()) for index, name in enumerate(self._names)}
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        (best, best_score), (second, second_score) = ranked[0], ranked[1]

        intent = self._decide(text, best, best_score, second_score)
        decision = RouteDecision(
            intent=intent, score=best_score, best_route=best, runner_up=second, runner_up_score=second_score,
            scores=scores,
        )
        logger.info(
            "Router: %s (best %s %.3f, runner-up %s %.3f, off-topic lead %+.3f)",
            intent.value, best, best_score, second, second_score, decision.off_topic_lead,
        )
        return decision

    @staticmethod
    def _decide(text: str, best: str, best_score: float, runner_up_score: float) -> RouteIntent:
        """The shortcut route the best match confirms, else ``RAG_QUESTION``."""
        route = RouteIntent(best)
        if route == RouteIntent.RAG_QUESTION:
            return route
        if route in SHORT_ONLY and len(text.strip()) > SHORT_MESSAGE_MAX_CHARS:
            return RouteIntent.RAG_QUESTION
        threshold = Config.Routing.ROUTE_THRESHOLD(route.value, DEFAULT_THRESHOLDS[route])
        if best_score >= threshold and best_score - runner_up_score >= Config.Routing.ROUTE_MARGIN():
            return route
        return RouteIntent.RAG_QUESTION

    def _load(self) -> None:
        """Embed every example once (first use), thread-safe."""
        if self._vectors is not None:
            return
        with self._lock:
            if self._vectors is not None:
                return
            routes = json.loads(self._routes_path.read_text(encoding="utf-8"))["routes"]
            names, owners, vectors = [], [], []
            for index, (name, examples) in enumerate(routes.items()):
                names.append(name)
                for example in examples:
                    owners.append(index)
                    vectors.append(np.asarray(self._embedding.embed_query(example), dtype=np.float32).reshape(-1))
            self._names, self._owners = names, np.asarray(owners)
            self._vectors = np.vstack(vectors)
            logger.info("Router loaded %d examples over %d routes", len(vectors), len(names))

    @staticmethod
    def thresholds() -> Dict[str, Tuple[float, float]]:
        """``route -> (threshold, margin)`` in force, for the eval report."""
        margin = Config.Routing.ROUTE_MARGIN()
        return {
            route.value: (Config.Routing.ROUTE_THRESHOLD(route.value, default), margin)
            for route, default in DEFAULT_THRESHOLDS.items()
        }
