"""
Seeded, deterministic perturbations that make clean Vietnamese look like real chat input.

Used by ``scripts/eval_robustness.py`` to build synthetic messy variants of the existing eval sets,
so robustness is measured without any real visitor data:

- ``no_diacritics``: every accent dropped, ``đ`` -> ``d`` ("chi phí" -> "chi phi");
- ``abbreviations``: common chat shorthands ("không" -> "ko"/"k", "được" -> "dc"/"đc", "gì" -> "j");
- ``telex``: words left as raw Telex keystrokes by a failed input method ("được" -> "dduwowcj");
- ``typos``: letters dropped or swapped with the next one, at :data:`TYPO_CHAR_RATE`;
- ``no_spaces``: spaces dropped, at :data:`SPACE_DROP_RATE`;
- ``chat_mix``: abbreviations, then no diacritics, the most common real combination.

The randomness of a variant depends only on the seed, the perturbation and the text, so a variant
never changes when cases are added, removed or reordered.
"""

# Standard library imports
import hashlib
import random
import re
import unicodedata
from typing import Callable, Dict, Tuple

# Local imports
from utils.text_utils import TextUtils

DEFAULT_SEED = 13
#: Share of accented words left as raw Telex keystrokes.
TELEX_WORD_RATE = 0.3
#: Chance per letter of a typo (half drop the letter, half swap it with the next letter).
TYPO_CHAR_RATE = 0.05
#: Chance per space of being dropped.
SPACE_DROP_RATE = 0.3

#: Full form -> the shorthands people type for it. Longer phrases are replaced first.
CHAT_ABBREVIATIONS: Dict[str, Tuple[str, ...]] = {
    "như thế nào": ("ntn",),
    "số điện thoại": ("sđt", "sdt"),
    "thế nào": ("ntn",),
    "bao nhiêu": ("bn", "bnh"),
    "bây giờ": ("bh", "bjo"),
    "mọi người": ("mn", "mng"),
    "trả lời": ("tl",),
    "tại sao": ("tại s", "ts"),
    "công ty": ("cty",),
    "thông tin": ("tt",),
    "hồ sơ": ("hs",),
    "điện thoại": ("đt", "dt"),
    "việt nam": ("vn",),
    "không": ("ko", "k", "hok", "kh"),
    "được": ("dc", "đc", "đk"),
    "gì": ("j",),
    "vậy": ("v", "z"),
    "rồi": ("r", "rùi"),
    "với": ("vs",),
    "biết": ("bít", "bik", "bt"),
    "người": ("ng",),
    "mình": ("mk", "mik"),
    "chưa": ("chx",),
    "trước": ("trc",),
    "nhiều": ("nhìu",),
    "cũng": ("cg",),
    "thôi": ("thui",),
    "đang": ("đg",),
    "làm": ("lm",),
    "quá": ("wá", "qá"),
    "sao": ("s",),
    "anh": ("a",),
    "em": ("e",),
    "chị": ("c",),
    "bạn": ("b",),
    "tôi": ("t",),
    "triệu": ("tr",),
    "nghìn": ("k",),
}

#: Telex key typed after the vowel for each Vietnamese vowel shape (circumflex doubles the vowel instead).
_TELEX_SHAPE_KEYS = {"̆": "w", "̛": "w"}
_CIRCUMFLEX = "̂"
#: Telex key for each tone, typed at the end of the word.
_TELEX_TONE_KEYS = {"́": "s", "̀": "f", "̉": "r", "̃": "x", "̣": "j"}
_WORD = re.compile(r"\w+")
_ABBREVIATION_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(full) for full in sorted(CHAT_ABBREVIATIONS, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


class VietnamesePerturber:
    """Applies one named perturbation to a text, deterministically for a given seed."""

    def __init__(self, seed: int = DEFAULT_SEED):
        """
        Args:
            seed: Base seed; with the perturbation name and the text it fixes every random choice.
        """
        self._seed = seed
        self._perturbations: Dict[str, Callable[[str, random.Random], str]] = {
            "no_diacritics": lambda text, rng: TextUtils.strip_vietnamese_accents(text),
            "abbreviations": self._abbreviate,
            "telex": self._telex,
            "typos": self._typos,
            "no_spaces": self._drop_spaces,
            "chat_mix": lambda text, rng: TextUtils.strip_vietnamese_accents(self._abbreviate(text, rng)),
        }

    @property
    def names(self) -> Tuple[str, ...]:
        """Every perturbation this perturber knows, in report order."""
        return tuple(self._perturbations)

    def perturb(self, text: str, perturbation: str) -> str:
        """
        Return ``text`` with ``perturbation`` applied.

        Raises:
            KeyError: Unknown perturbation name.
        """
        transform = self._perturbations[perturbation]
        digest = hashlib.sha256(f"{self._seed}:{perturbation}:{text}".encode("utf-8")).digest()
        return transform(unicodedata.normalize("NFC", text), random.Random(int.from_bytes(digest[:8], "big")))

    @staticmethod
    def _abbreviate(text: str, rng: random.Random) -> str:
        """Every known full form replaced by one of its shorthands."""
        return _ABBREVIATION_PATTERN.sub(lambda match: rng.choice(CHAT_ABBREVIATIONS[match.group(1).lower()]), text)

    @staticmethod
    def _telex(text: str, rng: random.Random) -> str:
        """A share of the accented words spelled as the Telex keys that type them."""
        def maybe_encode(match: re.Match) -> str:
            word = match.group(0)
            if TextUtils.strip_vietnamese_accents(word) == word or rng.random() >= TELEX_WORD_RATE:
                return word
            return telex_keys(word)

        return _WORD.sub(maybe_encode, text)

    @staticmethod
    def _typos(text: str, rng: random.Random) -> str:
        """Letters dropped or swapped with the following letter, each at :data:`TYPO_CHAR_RATE`."""
        chars = list(text)
        result = []
        index = 0
        while index < len(chars):
            char = chars[index]
            if not char.isalpha() or rng.random() >= TYPO_CHAR_RATE:
                result.append(char)
                index += 1
                continue
            following = chars[index + 1] if index + 1 < len(chars) else ""
            if rng.random() < 0.5 and following.isalpha():
                result.extend((following, char))
                index += 2
            else:
                index += 1
        return "".join(result)

    @staticmethod
    def _drop_spaces(text: str, rng: random.Random) -> str:
        """Each space dropped at :data:`SPACE_DROP_RATE`."""
        return "".join(char for char in text if char != " " or rng.random() >= SPACE_DROP_RATE)


def telex_keys(word: str) -> str:
    """
    The Telex keystrokes that type ``word`` ("được" -> "dduwowcj", "Đức" -> "DDuwcs").

    Vowel shapes are typed right after their vowel and the tone at the end of the word,
    the way an input method that failed to convert leaves them.
    """
    keys, tone = [], ""
    for char in word:
        if char in "đĐ":
            keys.append(char.replace("đ", "dd").replace("Đ", "DD"))
            continue
        base, *marks = unicodedata.normalize("NFD", char)
        keys.append(base)
        for mark in marks:
            if mark == _CIRCUMFLEX:
                keys.append(base.lower())
            elif mark in _TELEX_SHAPE_KEYS:
                keys.append(_TELEX_SHAPE_KEYS[mark])
            elif mark in _TELEX_TONE_KEYS:
                tone = _TELEX_TONE_KEYS[mark]
    return "".join(keys) + tone
