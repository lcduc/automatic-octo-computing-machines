"""
Fine-tune the embedding model on the synthetic ``(question, chunk)`` pairs.

Loss: sentence-transformers' ``MultipleNegativesRankingLoss`` (every other chunk in the batch is a
negative). Batches never hold two questions of the same chunk, or that chunk would be its own
negative. After every epoch the validation questions rank all chunks of the corpus; training
stops when their MRR@10 has not improved for ``EARLY_STOPPING_PATIENCE`` epochs and the best
epoch's weights are saved. The human golden sets are never read here.

A plain PyTorch loop rather than ``SentenceTransformerTrainer``: the trainer needs the ``datasets``
package, which this project does not install for ~250 pairs.

The saved model keeps the E5 query/passage prompts in its config, so ``EMBEDDING_MODEL=<output dir>``
loads it with the right prompts. Usage (from the repository root, with the venv active)::

    python -m scripts.finetune_embedding_model --output model_weights/finetuned/e5-small-synthetic
"""

# Standard library imports
import argparse
import copy
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from sentence_transformers.util import batch_to_device
from transformers import get_linear_schedule_with_warmup

# Local imports
from config.settings import Config
from core.retrieval.embeddings import MODEL_PROMPTS
from scripts.synthetic_dataset import CORPUS_FILE, TRAIN_FILE, VAL_FILE, chunk_mrr, read_jsonl

logger = logging.getLogger(__name__)

BASE_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_OUTPUT_DIR = Path("model_weights") / "finetuned" / "multilingual-e5-small-synthetic"
BATCH_SIZE = 32
#: Batches left with fewer distinct chunks than this are skipped for the epoch (too few negatives).
MIN_BATCH_SIZE = 8
LEARNING_RATE = 2e-5
WEIGHT_DECAY = 0.01
WARMUP_FRACTION = 0.1
MAX_EPOCHS = 10
EARLY_STOPPING_PATIENCE = 2
SEED = 13


def no_duplicate_batches(pairs: List[Dict[str, Any]], batch_size: int, rng: random.Random) -> List[List[Dict[str, Any]]]:
    """
    Shuffle the pairs into batches in which every chunk appears at most once.

    # ceiling: quadratic greedy fill, fine for a few thousand pairs; use a per-chunk queue beyond that.
    """
    remaining = list(pairs)
    rng.shuffle(remaining)
    batches = []
    while remaining:
        batch, chunks, leftover = [], set(), []
        for pair in remaining:
            if len(batch) < batch_size and pair["chunk_id"] not in chunks:
                batch.append(pair)
                chunks.add(pair["chunk_id"])
            else:
                leftover.append(pair)
        batches.append(batch)
        remaining = leftover
    return batches


class EmbeddingFineTuner:
    """Trains a ``SentenceTransformer`` with in-batch negatives and early stopping on validation MRR."""

    def __init__(self, model: SentenceTransformer, epochs: int, batch_size: int, learning_rate: float, seed: int):
        """
        Args:
            model: Model to train in place; its ``query`` / ``document`` prompts are applied to the texts.
            epochs: Maximum epochs.
            batch_size: Pairs per batch (in-batch negatives = batch size - 1).
            learning_rate: Peak AdamW learning rate.
            seed: Seed of the batch shuffling.
        """
        self._model = model
        self._epochs = epochs
        self._batch_size = batch_size
        self._learning_rate = learning_rate
        self._rng = random.Random(seed)
        self._loss = MultipleNegativesRankingLoss(model)

    def fit(self, train: List[Dict[str, Any]], val: List[Dict[str, Any]], corpus: List[Dict[str, Any]]) -> List[Dict[str, float]]:
        """
        Train, keep the epoch with the best validation MRR@10 (the base model if none beats it), and load its weights back.

        Returns:
            One ``{"epoch", "train_loss", "val_mrr_at_10"}`` entry per epoch (epoch 0 = before training).
        """
        index = {chunk["chunk_id"]: position for position, chunk in enumerate(corpus)}
        val_targets = [index[item["chunk_id"]] for item in val]
        corpus_texts = [chunk["content"] for chunk in corpus]
        optimizer = torch.optim.AdamW(self._model.parameters(), lr=self._learning_rate, weight_decay=WEIGHT_DECAY)
        # Estimated from one shuffle: the batch count varies a little between epochs.
        steps_per_epoch = sum(
            1 for batch in no_duplicate_batches(train, self._batch_size, random.Random(0)) if len(batch) >= MIN_BATCH_SIZE
        )
        scheduler = get_linear_schedule_with_warmup(
            optimizer, int(WARMUP_FRACTION * steps_per_epoch * self._epochs), steps_per_epoch * self._epochs
        )

        history = [{"epoch": 0, "train_loss": None, "val_mrr_at_10": self._validate(val, val_targets, corpus_texts)}]
        best_mrr, best_state, stale_epochs = history[0]["val_mrr_at_10"], copy.deepcopy(self._model.state_dict()), 0
        logger.info("Epoch 0 (base model): validation MRR@10 %.4f", best_mrr)
        for epoch in range(1, self._epochs + 1):
            loss = self._train_epoch(train, optimizer, scheduler)
            mrr = self._validate(val, val_targets, corpus_texts)
            history.append({"epoch": epoch, "train_loss": loss, "val_mrr_at_10": mrr})
            logger.info("Epoch %d: train loss %.4f, validation MRR@10 %.4f", epoch, loss, mrr)
            if mrr > best_mrr:
                best_mrr, best_state, stale_epochs = mrr, copy.deepcopy(self._model.state_dict()), 0
            else:
                stale_epochs += 1
                if stale_epochs >= EARLY_STOPPING_PATIENCE:
                    logger.info("No improvement for %d epochs; stopping", stale_epochs)
                    break
        self._model.load_state_dict(best_state)
        return history

    def _train_epoch(self, train: List[Dict[str, Any]], optimizer, scheduler) -> float:
        """One pass over the pairs; returns the mean batch loss."""
        self._model.train()
        prompts = self._model.prompts
        losses = []
        for batch in no_duplicate_batches(train, self._batch_size, self._rng):
            if len(batch) < MIN_BATCH_SIZE:
                continue
            features = [
                batch_to_device(self._model.preprocess([p["query"] for p in batch], prompt=prompts["query"]), self._model.device),
                batch_to_device(self._model.preprocess([p["positive"] for p in batch], prompt=prompts["document"]), self._model.device),
            ]
            loss = self._loss(features, None)
            loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            losses.append(float(loss.detach()))
        return sum(losses) / len(losses)

    def _validate(self, val: List[Dict[str, Any]], targets: List[int], corpus_texts: List[str]) -> float:
        """Chunk-level MRR@10 of the validation questions over the whole corpus."""
        self._model.eval()
        with torch.no_grad():
            queries = self._model.encode_query([item["query"] for item in val], convert_to_numpy=True)
            corpus = self._model.encode_document(corpus_texts, convert_to_numpy=True)
        return chunk_mrr(queries, corpus, targets)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=MAX_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # fp32 weights for training (the app loads them in fp16 on GPU).
    model = SentenceTransformer(
        BASE_MODEL, device=device, cache_folder=Config.Paths.MODELS_DIR(), prompts=MODEL_PROMPTS[BASE_MODEL]
    )
    train, val, corpus = read_jsonl(TRAIN_FILE), read_jsonl(VAL_FILE), read_jsonl(CORPUS_FILE)
    logger.info("Fine-tuning %s on %d pairs (%d validation) over %d chunks", BASE_MODEL, len(train), len(val), len(corpus))
    tuner = EmbeddingFineTuner(model, args.epochs, args.batch_size, args.learning_rate, args.seed)
    history = tuner.fit(train, val, corpus)

    args.output.mkdir(parents=True, exist_ok=True)
    model.save(str(args.output))
    summary = {
        "base_model": BASE_MODEL, "output": str(args.output), "train_pairs": len(train), "val_pairs": len(val),
        "batch_size": args.batch_size, "learning_rate": args.learning_rate, "seed": args.seed,
        "best_epoch": max(history, key=lambda entry: entry["val_mrr_at_10"])["epoch"], "history": history,
    }
    (args.output / "training_history.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
