"""Initial reference data for a genuinely new ledger, shared by adapters."""

DEFAULT_ACCOUNTS = (("Checking", "Bank"), ("Cash", "Cash"))
DEFAULT_CATEGORIES = {
    "Income": ("Sales", "Services", "Interest", "Other income"),
    "Expense": (
        "Advertising", "Bank fees", "Insurance", "Meals", "Office",
        "Professional fees", "Rent", "Software", "Supplies", "Travel",
        "Utilities", "Other expense",
    ),
}
