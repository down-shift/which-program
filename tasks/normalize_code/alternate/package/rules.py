import re

def normalize_code(code):
    return re.sub(r" +", "-", code.strip()).upper()
