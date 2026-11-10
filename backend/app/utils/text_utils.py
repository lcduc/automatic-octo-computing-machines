"""
Text processing utilities: extraction quality checks (OCR fallback), Vietnamese chat
normalisation, search tokenisation and sentence-based chunking.
"""

# Standard library imports
import re
from typing import List


#: Common Vietnamese words with the accents stripped, chosen to be rare in English ("can", "the", "day" are left out).
UNACCENTED_VIETNAMESE_WORDS = frozenset({
    "khong", "nhieu", "nao", "duoc", "cua", "toi", "minh", "em", "anh", "chi", "gi", "vay", "nhe", "nha", "thi",
    "phai", "roi", "sang", "duc", "viec", "muon", "biet", "hoi", "cho", "voi", "nhung", "mot", "cac", "nay", "dau",
    "tien", "het", "luong", "nghe", "hoc", "bao", "lam", "khi", "sao", "co", "va", "la", "o",
})
#: Unaccented-Vietnamese words a message needs before it counts as Vietnamese typed without accents.
UNACCENTED_MIN_HITS = 3
#: Chat shorthands with one clear meaning -> their full form. Ambiguous ones are left out on purpose:
#: "bn" (bao nhiêu / bạn), "đk" (được / điều kiện / đăng ký), "bh" (bây giờ / bảo hiểm), "hs" (hồ sơ /
#: học sinh), "tt", "tl", "ts", "đt", "s", and single-letter pronouns ("a", "e", "c", "b", "t").
CHAT_SHORTHANDS = {
    "ko": "không", "k": "không", "hok": "không", "dc": "được", "đc": "được", "j": "gì", "v": "vậy", "z": "vậy",
    "r": "rồi", "rùi": "rồi", "vs": "với", "ntn": "như thế nào", "bnh": "bao nhiêu", "mn": "mọi người",
    "sđt": "số điện thoại", "sdt": "số điện thoại", "cty": "công ty", "vn": "Việt Nam", "bít": "biết", "bik": "biết",
    "ng": "người", "mk": "mình", "mik": "mình", "chx": "chưa", "trc": "trước", "nhìu": "nhiều", "cg": "cũng",
    "thui": "thôi", "lm": "làm", "wá": "quá", "qá": "quá",
}
#: Shorthands that mean something else right after a number ("500 k" is 500 nghìn).
SHORTHANDS_KEPT_AFTER_NUMBERS = frozenset({"k"})
#: A whole word, and not part of a dotted or hyphenated token: "v.v." (etc.) and "J-1" stay as they are,
#: while a shorthand ending a sentence ("... ko.") is still written out.
_SHORTHAND_PATTERN = re.compile(
    r"(?<!\w)(?<!\w[.\-])("
    + "|".join(re.escape(short) for short in sorted(CHAT_SHORTHANDS, key=len, reverse=True))
    + r")(?!\w)(?![.\-]\w)",
    re.IGNORECASE,
)


class TextUtils:
    """
    Stateless text helpers shared by document processing, retrieval and routing.
    """

    @staticmethod
    def is_probably_gibberish(text: str, threshold: float = 0.3) -> bool:
        """
        Determine if extracted text is likely gibberish and needs OCR processing.
        Analyzes Unicode character categories to detect low-quality text, e.g.
        a PDF font with a broken encoding that extracts as private-use or
        replacement characters. Whitespace is ignored — newlines are control
        characters but are normal in extracted page text.
        """
        # Import unicodedata here to avoid dependency issues
        import unicodedata

        # ceiling: character categories only, mis-mapped fonts that decode to real letters pass; add a dictionary/language score if they show up
        visible = [c for c in text if not c.isspace()]
        if not visible:
            return True

        # Check for too many control/symbol characters
        bad_chars = sum(
            1 for c in visible if unicodedata.category(c).startswith(("C", "S"))
        )
        return bad_chars / len(visible) > threshold

    @staticmethod
    def needs_ocr_fallback(text: str) -> bool:
        """
        Determine if OCR fallback is needed for the extracted text.
        Consolidated from OCR utils for unified text quality assessment.
        """
        return (
            not text  # Empty text
            or not text.strip()  # Only whitespace
            or TextUtils.is_probably_gibberish(text)  # Gibberish content
        )

    @staticmethod
    def strip_vietnamese_accents(text: str) -> str:
        """
        Remove Vietnamese diacritics from a string while preserving ASCII characters.
        Ensures special Vietnamese letters 'đ'/'Đ' are mapped to 'd'/'D'.
        """
        if not text:
            return ""

        import unicodedata

        # Normalize to NFD to separate base chars and combining marks
        normalized = unicodedata.normalize("NFD", text)
        # Drop all combining marks
        without_marks = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
        # Map special Vietnamese letters
        without_marks = without_marks.replace("đ", "d").replace("Đ", "D")
        # Return as-is (do not recompose) to avoid reintroducing marks
        return without_marks

    @staticmethod
    def normalize_chat_text(text: str) -> str:
        """
        Canonical form of a visitor's message, applied before anything reads it.

        NFKC folds look-alike forms (fullwidth letters, decomposed Vietnamese accents) into plain
        ones; zero-width and other invisible characters are dropped, so a phrase cannot be split by
        them to slip past a pattern; other control characters become spaces and spaces are collapsed.
        Newlines survive (at most one blank line in a row).
        """
        if not text:
            return ""

        import unicodedata

        folded = unicodedata.normalize("NFKC", text)
        kept = []
        for char in folded:
            category = unicodedata.category(char)
            if category == "Cf":
                continue
            kept.append(" " if category == "Cc" and char not in "\n\t" else char)
        cleaned = re.sub(r"[ \t]+", " ", "".join(kept).replace("\r\n", "\n"))
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    @staticmethod
    def looks_like_unaccented_vietnamese(text: str) -> bool:
        """
        True for Vietnamese typed without diacritics ("tien phong o duc bao nhieu").

        No accent anywhere and at least two common Vietnamese function words written without them;
        English text and already-accented Vietnamese never match. A cheap check, not a language detector.
        """
        if not text or TextUtils.strip_vietnamese_accents(text) != text or "đ" in text.lower():
            return False
        tokens = re.findall(r"[a-z]+", text.lower())
        return sum(token in UNACCENTED_VIETNAMESE_WORDS for token in tokens) >= UNACCENTED_MIN_HITS

    @staticmethod
    def expand_chat_abbreviations(text: str) -> str:
        """
        Chat shorthands written out ("có dc ko" -> "có được không"); see :data:`CHAT_SHORTHANDS`.

        A message typed without accents gets the full forms without accents ("co dc ko" -> "co duoc khong"),
        so it still reads as unaccented Vietnamese to :meth:`looks_like_unaccented_vietnamese`.
        """
        if not text:
            return ""
        unaccented = TextUtils.strip_vietnamese_accents(text) == text

        def full_form(match: re.Match) -> str:
            short = match.group(1).lower()
            if short in SHORTHANDS_KEPT_AFTER_NUMBERS and text[: match.start()].rstrip()[-1:].isdigit():
                return match.group(1)
            form = CHAT_SHORTHANDS[short]
            return TextUtils.strip_vietnamese_accents(form) if unaccented else form

        return _SHORTHAND_PATTERN.sub(full_form, text)

    @staticmethod
    def tokenize_for_search(text: str) -> List[str]:
        """
        Keyword-search tokens: lower-cased, accent-free, punctuation stripped.

        Accents are removed so a query typed without diacritics ("hop dong")
        still matches the document text ("hợp đồng").
        """
        if not text:
            return []
        folded = TextUtils.strip_vietnamese_accents(text.lower())
        folded = re.sub(r"[^\w\s]", " ", folded)
        return folded.split()

    @staticmethod
    def clean_chunk_text(text: str) -> str:
        """
        Remove empty lines and table border lines from a chunk.
        """
        lines = text.splitlines()
        filtered = [
            line
            for line in lines
            if line.strip() and not re.fullmatch(r"\|[-| ]+\|", line.strip())
        ]
        return "\n".join(filtered)

    @staticmethod
    def chunk_text(
        text: str, chunk_size: int = 1000, overlap: int = 200, language: str = "vi"
    ) -> list:
        """
        Hybrid chunking: group full sentences into chunks up to chunk_size, with overlap at sentence boundaries.
        Uses NLTK's sent_tokenize for sentence splitting if available, supporting English and Vietnamese.
        Falls back to regex if NLTK is unavailable.
        Args:
            text: Input text
            chunk_size: Max chunk size (characters)
            overlap: Overlap size (characters)
            language: Language code for sentence splitting ('en' or 'vi')
        Returns:
            List of chunked strings
        """
        import re

        if not text or not text.strip():
            return []
        text = text.strip()
        if len(text) <= chunk_size:
            return [text]
        # For markdown content, preserve line structure and only split at major boundaries
        lines = text.split('\n')
        current_section = []
        sections = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if this line starts a new section or is a separator
            is_header = line.startswith('##')
            # Check if the entire row is NaN (all cells contain NaN)
            is_nan_separator = line.strip().startswith('|') and line.strip().endswith('|') and all('NaN' in cell.strip() for cell in line.strip().split('|')[1:-1] if cell.strip())

            if is_header and current_section:
                # Save current section and start new one
                sections.append('\n'.join(current_section))
                current_section = [line]
            elif is_nan_separator and current_section:
                # Save current section and start new one, but don't include the separator row
                sections.append('\n'.join(current_section))
                current_section = []  # Don't add the separator row
            else:
                current_section.append(line)

        # Add the last section
        if current_section:
            sections.append('\n'.join(current_section))

        # If no sections were created, treat the whole text as one section
        if not sections:
            sections = [text]

        # Now chunk each section using the original logic
        all_chunks = []
        for section in sections:
            if len(section) <= chunk_size:
                all_chunks.append(section)
            else:
                # Use original sentence-based chunking for large sections
                try:
                    import nltk
                    try:
                        nltk.data.find("tokenizers/punkt")
                    except LookupError:
                        nltk.download("punkt")
                    from nltk.tokenize import sent_tokenize

                    lang_map = {"vi": "vietnamese", "en": "english"}
                    lang = lang_map.get(language, "vietnamese")
                    sentences = sent_tokenize(section, language=lang)
                except Exception:
                    if language == "vi":
                        sentences = re.split(r"(?<=[.!?。！？])\s+", section)
                    else:
                        sentences = re.split(r"(?<=[.!?])\s+", section)

                # Chunk the sentences within this section
                chunks = []
                current_chunk = []
                current_len = 0

                for sentence in sentences:
                    if not sentence.strip():
                        continue

                    if current_len + len(sentence) + 1 > chunk_size and current_chunk:
                        chunks.append(" ".join(current_chunk).strip())
                        if overlap > 0 and current_chunk:
                            overlap_text = current_chunk[-1]
                            current_chunk = [overlap_text]
                            current_len = len(overlap_text)
                        else:
                            current_chunk = []
                            current_len = 0

                    current_chunk.append(sentence)
                    current_len += len(sentence) + 1

                if current_chunk:
                    chunks.append(" ".join(current_chunk).strip())

                all_chunks.extend([c for c in chunks if c.strip()])

        return all_chunks
