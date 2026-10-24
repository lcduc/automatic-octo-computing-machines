"""
Router classifier comparison: the nearest-example rule vs logistic regression on the same e5 embeddings.

Nested, stratified cross-validation over the 189 labelled router messages of ``eval_robustness``. Each
outer fold trains on ``routes.json`` plus the other folds and tests on the held-out fold, clean and under
every perturbation of ``vietnamese_perturber`` (shorthands written out, as the pipeline does). Both methods see exactly the same examples, including the
accent-free copies the router adds (``with_accent_free_forms``):

- ``nearest_example``: the production ``EmbeddingRouter`` (thresholds, margin, short-message rule);
- ``logistic_regression``: class-balanced multinomial logistic regression on the example embeddings. It
  takes a shortcut only when its probability reaches ``min_probability`` and the short-message rule allows
  it; anything else is a question. ``C`` and ``min_probability`` are chosen per outer fold by an inner
  stratified CV on clean input: fewest stolen questions first, then accuracy.

No LLM calls are made. Usage (from the repository root, with the venv active)::

    python -m scripts.eval_router_classifier
    python -m scripts.eval_router_classifier --out logs/router_classifier.json
"""

# Standard library imports
import argparse
import itertools
import json
import logging
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-party imports
import numpy as np
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

load_dotenv()

# Local imports
from core.routing.embedding_router import (  # noqa: E402
    ROUTES_FILE, SHORT_MESSAGE_MAX_CHARS, SHORT_ONLY, EmbeddingRouter, RouteIntent, with_accent_free_forms,
)
from scripts import vietnamese_perturber  # noqa: E402
from scripts.eval_robustness import as_searched, load_router_cases, router_metrics, variants  # noqa: E402
from scripts.vietnamese_perturber import VietnamesePerturber  # noqa: E402

logger = logging.getLogger(__name__)

OUTER_FOLDS = 5
#: Three, not five: the smallest route has six messages, too few for five inner folds.
INNER_FOLDS = 3
C_GRID = (10.0, 30.0, 100.0)
MIN_PROBABILITY_GRID = (0.5, 0.6, 0.7, 0.8)
CV_SEED = 0
#: Enough iterations for lbfgs to converge on ~400 unit vectors.
MAX_ITERATIONS = 5000
RAG = RouteIntent.RAG_QUESTION.value
METHODS = ("nearest_example", "logistic_regression")


class CachedEmbeddings:
    """The embedding service, embedding each distinct text once (every fold re-uses the same examples)."""

    def __init__(self, service):
        """
        Args:
            service: Exposes ``embed_query(text)`` -> unit vector.
        """
        self._service = service
        self._vectors: Dict[str, np.ndarray] = {}

    def embed_query(self, text: str) -> np.ndarray:
        """The cached query embedding of ``text``."""
        if text not in self._vectors:
            self._vectors[text] = np.asarray(self._service.embed_query(text), dtype=np.float32).reshape(-1)
        return self._vectors[text]

    def matrix(self, texts: Sequence[str]) -> np.ndarray:
        """Embeddings of ``texts``, one row each."""
        return np.vstack([self.embed_query(text) for text in texts])


class LogisticRouteClassifier:
    """Logistic regression over example embeddings, with the router's question-by-default rule."""

    def __init__(self, embeddings: CachedEmbeddings, c: float, min_probability: float):
        """
        Args:
            embeddings: Embeds the training and test texts.
            c: Inverse regularization strength.
            min_probability: Lowest class probability that takes a shortcut.
        """
        self._embeddings = embeddings
        self._min_probability = min_probability
        self._model = LogisticRegression(C=c, max_iter=MAX_ITERATIONS, class_weight="balanced")

    def fit(self, texts: Sequence[str], routes: Sequence[str]) -> "LogisticRouteClassifier":
        """Train on labelled examples; returns ``self``."""
        self._model.fit(self._embeddings.matrix(texts), np.asarray(routes))
        return self

    def decide(self, texts: Sequence[str]) -> List[str]:
        """The route of each text: the most probable one when confident and allowed, else a question."""
        decisions = []
        for text, probabilities in zip(texts, self._model.predict_proba(self._embeddings.matrix(texts))):
            best = int(probabilities.argmax())
            route = RouteIntent(self._model.classes_[best])
            too_long = route in SHORT_ONLY and len(text.strip()) > SHORT_MESSAGE_MAX_CHARS
            confident = probabilities[best] >= self._min_probability
            decisions.append(route.value if confident and not too_long else RAG)
        return decisions


class RouterCrossValidation:
    """Runs the nested cross-validation of both methods."""

    def __init__(
        self, embeddings: CachedEmbeddings, cases: List[Dict[str, str]], texts: Dict[str, List[str]], workdir: Path
    ):
        """
        Args:
            embeddings: Shared embedding cache.
            cases: The labelled messages (clean text and expected route).
            texts: Input variant name -> the cases' texts under it.
            workdir: Scratch folder for the per-fold routes files.
        """
        self._embeddings = embeddings
        self._labels = np.asarray([case["intent"] for case in cases])
        self._texts = texts
        self._workdir = workdir
        self._routes: Dict[str, List[str]] = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))["routes"]

    def run(self) -> Dict[str, Any]:
        """Per method and input variant, the metrics of the pooled held-out decisions; plus the chosen settings."""
        decided = {method: {name: [""] * len(self._labels) for name in self._texts} for method in METHODS}
        chosen = []
        folds = StratifiedKFold(OUTER_FOLDS, shuffle=True, random_state=CV_SEED)
        for fold, (train, test) in enumerate(folds.split(np.zeros(len(self._labels)), self._labels)):
            examples = self._examples(train)
            c, min_probability = self._select(train)
            chosen.append({"c": c, "min_probability": min_probability})
            router = self._nearest_example(examples, f"fold{fold}")
            classifier = LogisticRouteClassifier(self._embeddings, c, min_probability).fit(*self._flatten(examples))
            for name, texts in self._texts.items():
                held_out = [texts[index] for index in test]
                for index, route in zip(test, [router.classify(text).intent.value for text in held_out]):
                    decided["nearest_example"][name][index] = route
                for index, route in zip(test, classifier.decide(held_out)):
                    decided["logistic_regression"][name][index] = route
            logger.info("Fold %d done (C=%s, min probability %s)", fold, c, min_probability)
        report = {
            method: {name: router_metrics(self._labels, routes) for name, routes in by_variant.items()}
            for method, by_variant in decided.items()
        }
        report["logistic_regression_settings"] = chosen
        return report

    def _examples(self, indices: Sequence[int]) -> Dict[str, List[str]]:
        """``routes.json`` plus the clean messages at ``indices``, by route."""
        examples = {name: list(texts) for name, texts in self._routes.items()}
        for index in indices:
            examples[self._labels[index]].append(self._texts["clean"][index])
        return examples

    @staticmethod
    def _flatten(examples: Dict[str, List[str]]) -> Tuple[List[str], List[str]]:
        """``(texts, routes)`` with the accent-free copies the router would add."""
        texts, routes = [], []
        for name, route_examples in examples.items():
            forms = with_accent_free_forms(RouteIntent(name), route_examples)
            texts += forms
            routes += [name] * len(forms)
        return texts, routes

    def _nearest_example(self, examples: Dict[str, List[str]], tag: str) -> EmbeddingRouter:
        """The production router over ``examples`` (it adds the accent-free copies itself)."""
        path = self._workdir / f"routes_{tag}.json"
        path.write_text(json.dumps({"routes": examples}, ensure_ascii=False), encoding="utf-8")
        return EmbeddingRouter(self._embeddings, path)

    def _select(self, train: np.ndarray) -> Tuple[float, float]:
        """``(C, min_probability)`` with the fewest stolen questions, then the best accuracy, on inner folds."""
        tally: Dict[Tuple[float, float], List[int]] = defaultdict(lambda: [0, 0])
        inner = StratifiedKFold(INNER_FOLDS, shuffle=True, random_state=CV_SEED)
        for inner_train, validation in inner.split(train, self._labels[train]):
            texts, routes = self._flatten(self._examples(train[inner_train]))
            held_out = [self._texts["clean"][index] for index in train[validation]]
            expected = self._labels[train[validation]]
            for c, min_probability in itertools.product(C_GRID, MIN_PROBABILITY_GRID):
                decided = LogisticRouteClassifier(self._embeddings, c, min_probability).fit(texts, routes).decide(held_out)
                metrics = router_metrics(expected, decided)
                tally[(c, min_probability)][0] += metrics["questions_stolen"]
                tally[(c, min_probability)][1] += metrics["correct"]
        return min(tally, key=lambda setting: (tally[setting][0], -tally[setting][1], -setting[1]))


def print_table(report: Dict[str, Any]) -> None:
    """Markdown table of the report (intentional CLI output)."""
    print("\n| method | input | accuracy | macro-F1 | questions stolen | off-topic caught |")
    print("|---|---|---|---|---|---|")
    for method in METHODS:
        for name, row in report[method].items():
            print(f"| {method} | {name} | {row['accuracy']:.1%} ({row['correct']}/{row['cases']}) | {row['macro_f1']:.3f} "
                  f"| {row['questions_stolen']}/{row['questions']} | {row['off_topic_caught']}/{row['off_topic']} |")
    settings = ", ".join(f"C={s['c']:g} p>={s['min_probability']}" for s in report["logistic_regression_settings"])
    print(f"\nLogistic regression settings chosen per outer fold: {settings}")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=vietnamese_perturber.DEFAULT_SEED, help="Perturbation seed")
    parser.add_argument("--out", type=Path, default=None, help="Write the full report here as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logger.setLevel(logging.INFO)

    from core.retrieval.embeddings import get_embedding_service

    cases = load_router_cases()
    perturber = VietnamesePerturber(args.seed)
    texts = {
        name: [as_searched(text) for text in variant]
        for name, variant in variants(perturber, perturber.names, [case["text"] for case in cases]).items()
    }
    with tempfile.TemporaryDirectory() as workdir:
        report = RouterCrossValidation(CachedEmbeddings(get_embedding_service()), cases, texts, Path(workdir)).run()
    report["seed"] = args.seed
    print_table(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull report saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
