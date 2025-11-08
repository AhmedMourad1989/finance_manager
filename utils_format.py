# utils_format.py
SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "$", "AUD": "$"}

def fmt_money(amount: float, currency: str = "GBP") -> str:
    try:
        a = float(amount)
    except Exception:
        a = 0.0
    sym = SYMBOL.get(str(currency).upper(), "")
    return f"{sym}{a:,.2f}"