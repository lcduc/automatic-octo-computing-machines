from utils.text_utils import TextUtils


def test_chat_shorthands_are_written_out_in_the_message_own_accent_style():
    assert TextUtils.expand_chat_abbreviations("Học nghề có dc trả lương ko vậy?") == "Học nghề có được trả lương không vậy?"
    assert TextUtils.expand_chat_abbreviations("hoc nghe co dc tra luong ko") == "hoc nghe co duoc tra luong khong"
    assert TextUtils.looks_like_unaccented_vietnamese(TextUtils.expand_chat_abbreviations("co dc ko j"))


def test_only_whole_words_and_not_k_after_a_number_are_expanded():
    assert TextUtils.expand_chat_abbreviations("phí 500 k, ko rẻ") == "phí 500 k, không rẻ"
    assert TextUtils.expand_chat_abbreviations("kong dcm Visa B1") == "kong dcm Visa B1"


def test_letters_inside_dotted_or_hyphenated_tokens_are_not_shorthands():
    # "v.v." is "etc." in Vietnamese and "J-1" a visa code, not "vậy" or "gì".
    assert TextUtils.expand_chat_abbreviations("hộ chiếu, bằng cấp, v.v. đúng ko?") == "hộ chiếu, bằng cấp, v.v. đúng không?"
    assert TextUtils.expand_chat_abbreviations("Visa J-1 khác j visa lao động?") == "Visa J-1 khác gì visa lao động?"
    assert TextUtils.expand_chat_abbreviations("Đi Đức có cần tiếng Đức ko.") == "Đi Đức có cần tiếng Đức không."
