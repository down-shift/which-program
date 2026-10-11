import re

def normalize_code(code):
    return re.sub(r"\s+", "-", code.strip()).replace("_", "-")
