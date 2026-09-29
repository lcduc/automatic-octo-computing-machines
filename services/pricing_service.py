"""
LLM prices (ADM-08): kept in the database, edited in the admin web, applied to every recorded call.

# ceiling: prices are cached per process and refreshed on this process's edits;
# reload them on a timer if several API processes ever run.
"""

# Standard library imports
import logging
from decimal import Decimal
from typing import Dict, List, Tuple

# Third-party imports
from sqlalchemy import delete, select

# Local imports
from core.storage.database import Database
from core.storage.tables.usage_tables import ModelPrice
from .errors import NotFoundError

logger = logging.getLogger(__name__)


class PricingService:
    """Model price table with an in-memory cache for cost calculation on the chat path."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database
        self._prices: Dict[str, Tuple[Decimal, Decimal]] = {}

    async def load(self) -> None:
        """Read every price into the cache (at start-up and after edits)."""
        async with self._database.session() as session:
            rows = (await session.execute(select(ModelPrice))).scalars().all()
        self._prices = {row.model: (row.input_usd_per_million, row.output_usd_per_million) for row in rows}
        logger.info("Loaded %d model prices", len(self._prices))

    def has_price(self, model: str) -> bool:
        """True when ``model`` has a price (its calls count toward the spend cap)."""
        return model in self._prices

    def cost_micro_usd(self, model: str, prompt_tokens: int, completion_tokens: int) -> int:
        """
        Cost of one call in micro-dollars; 0 for a model without a price.

        Prices are USD per million tokens, so ``tokens × price`` is already micro-dollars.
        """
        price = self._prices.get(model)
        if price is None:
            return 0
        return int((Decimal(prompt_tokens) * price[0] + Decimal(completion_tokens) * price[1]).to_integral_value())

    async def list(self) -> List[ModelPrice]:
        """Every price, by model name."""
        async with self._database.session() as session:
            return list((await session.execute(select(ModelPrice).order_by(ModelPrice.model))).scalars().all())

    async def upsert(self, model: str, input_usd: Decimal, output_usd: Decimal, updated_by: str) -> ModelPrice:
        """Create or change the price of ``model``."""
        async with self._database.session() as session:
            price = await session.get(ModelPrice, model)
            if price is None:
                price = ModelPrice(model=model)
                session.add(price)
            price.input_usd_per_million = input_usd
            price.output_usd_per_million = output_usd
            price.updated_by = updated_by
        await self.load()
        logger.info("Price of %s set by %s", model, updated_by)
        return price

    async def delete(self, model: str) -> None:
        """
        Remove the price of ``model``.

        Raises:
            NotFoundError: No price for that model.
        """
        async with self._database.session() as session:
            result = await session.execute(delete(ModelPrice).where(ModelPrice.model == model))
        if not result.rowcount:
            raise NotFoundError("No price for this model")
        await self.load()
