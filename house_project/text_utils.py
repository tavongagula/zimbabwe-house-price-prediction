"""Helpers shared by extract_features.py and 03_models.ipynb."""
import re

# Many adverts quote the price in the description ("USD 670,000", "$450k", "asking 380 000"). The price is the
# variable we are predicting, so any amount of money is replaced by a neutral token before the text is embedded.
_NUM = r"\d{1,3}(?:[ ,\.]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_CURRENCY_FIRST = re.compile(rf"(?i)(?:us\s?\$\.?|u\$d|usd|zwg|zig|\$)\s*\.?\s*(?:{_NUM})(?:\s?(?:k|m|mil(?:lion)?|thousand)\b)?")
_CURRENCY_LAST = re.compile(rf"(?i)(?:{_NUM})\s?(?:k|m|mil(?:lion)?|thousand)?\s?(?:usd|us\s?\$|dollars?|zwg)\b")
_K_SUFFIX = re.compile(r"(?i)\b\d{2,4}\s?k\b")
_PRICE_WORD = re.compile(rf"(?i)\b(?:asking|price[d]?|selling for|for sale at|offers? (?:over|from|above)|valued at)\b[^.\n\d]{{0,25}}(?:{_NUM})(?!\s?(?:m2|m²|sqm|sq|square|ha\b|hectares?|acres?|bed|bath|%|metres?|meters?|km|rooms?))")

def mask_prices(text):
    """Replace amounts of money in advert text with '<price>'."""
    if not isinstance(text, str):
        return ""
    for pattern in (_CURRENCY_FIRST, _CURRENCY_LAST, _K_SUFFIX, _PRICE_WORD):
        text = pattern.sub("<price>", text)
    return re.sub(r"\s+", " ", text).strip()

def numbers_in(text):
    """All numbers in a text (as floats), including '450k' -> 450000. Used to check for price leakage."""
    out = []
    for m in re.finditer(rf"(?i)({_NUM})\s?(k|m)?\b", text or ""):
        s = re.sub(r"[ ,]", "", m.group(1))
        try:
            v = float(s)
        except ValueError:
            continue
        if m.group(2):
            v *= 1_000 if m.group(2).lower() == "k" else 1_000_000
        out.append(v)
    return out

def leaks_price(text, price, tol=0.02):
    """True if any number in the text is within `tol` of the asking price."""
    return any(abs(v - price) / price < tol for v in numbers_in(text))
