"""The no-answer marker is caught at the start of a stream and never shown; real answers pass untouched."""

import pytest

from core.agent.answer_marker import NoAnswerFilter

MARKER = "[NO_ANSWER]"


def _run(pieces):
    stream = NoAnswerFilter()
    shown = "".join(stream.feed(piece) for piece in pieces) + stream.finish()
    return shown, stream.no_answer


@pytest.mark.parametrize(
    "pieces",
    [
        [MARKER],
        ["[NO", "_ANS", "WER]"],
        ["  [NO_ANSWER]\n"],
        ["[", "N", "O", "_", "A", "N", "S", "W", "E", "R", "]", " thêm chữ"],
    ],
)
def test_the_marker_is_swallowed_however_it_is_split(pieces):
    assert _run(pieces) == ("", True)


@pytest.mark.parametrize(
    "pieces",
    [
        ["Visa D ", "có lệ phí khoảng 75 EUR."],
        ["[1] Một danh sách đánh số"],
        ["[NO", " chắc là vậy"],  # starts like the marker, is not
        ["["],  # a reply that ends while still ambiguous is released at the end
        [""],
    ],
)
def test_real_answers_are_released_unchanged(pieces):
    assert _run(pieces) == ("".join(pieces), False)


def test_text_is_held_back_only_until_it_cannot_be_the_marker():
    stream = NoAnswerFilter()
    assert stream.feed("[NO") == ""
    assert stream.feed("T so") == "[NOT so"  # decided: released together
    assert stream.feed(" far") == " far"
