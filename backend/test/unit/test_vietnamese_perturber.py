from collections import Counter

from scripts.vietnamese_perturber import VietnamesePerturber, telex_keys

QUESTION = "Học nghề ở Đức có được trả lương không vậy anh, chi phí bao nhiêu?"


def test_telex_keys_put_shapes_after_the_vowel_and_the_tone_last():
    assert telex_keys("được") == "dduwowcj"
    assert telex_keys("Đức") == "DDuwcs"
    assert telex_keys("tiếng") == "tieengs"
    assert telex_keys("ăn") == "awn"


def test_no_diacritics_leaves_plain_ascii():
    assert VietnamesePerturber().perturb("Đức được không", "no_diacritics") == "Duc duoc khong"


def test_abbreviations_replace_whole_words_only():
    perturbed = VietnamesePerturber().perturb("bao nhiêu thì không được, khôngkhí", "abbreviations")
    words = perturbed.replace(",", "").split()
    assert words[0] in ("bn", "bnh") and words[2] in ("ko", "k", "hok", "kh") and words[3] in ("dc", "đc", "đk")
    assert words[-1] == "khôngkhí"


def test_a_variant_depends_only_on_seed_perturbation_and_text():
    first, second, other_seed = VietnamesePerturber(7), VietnamesePerturber(7), VietnamesePerturber(8)
    for name in first.names:
        assert first.perturb(QUESTION, name) == second.perturb(QUESTION, name)
    assert any(first.perturb(QUESTION, name) != other_seed.perturb(QUESTION, name) for name in ("typos", "telex"))


def test_typos_and_missing_spaces_only_lose_or_move_characters():
    perturber, text = VietnamesePerturber(), QUESTION * 5
    typos = perturber.perturb(text, "typos")
    assert typos != text and Counter(typos) <= Counter(text)
    no_spaces = perturber.perturb(text, "no_spaces")
    assert no_spaces.replace(" ", "") == text.replace(" ", "") and no_spaces.count(" ") < text.count(" ")
