def snake_to_title(name: str) -> str:
    """
    Convert a snake_case string to Title Case.
    
    Args:
        name: The snake_case string to convert.
        
    Returns:
        str: The converted Title Case string.
        
    Example:
        "customer_order" -> "Customer Order"
    """
    return " ".join(word.capitalize() for word in name.split("_") if word)


def split_compound_name(name: str) -> list[str]:
    """
    Split a snake_case compound name into a list of words.
    
    Args:
        name: The snake_case string to split.
        
    Returns:
        list[str]: A list of constituent words.
        
    Example:
        "customer_order" -> ["customer", "order"]
    """
    return [word for word in name.split("_") if word]


def normalise_column_name(name: str) -> str:
    """
    Normalize a column name by lowercasing and stripping spaces and quotes.
    
    Args:
        name: The column name to normalize.
        
    Returns:
        str: The normalized column name.
    """
    return name.lower().strip(" '\"")


def normalize_column_name(name: str) -> str:
    """American-spelling alias for ``normalise_column_name``."""
    return normalise_column_name(name)


def is_id_column(name: str) -> bool:
    """
    Check if a column name indicates an ID.
    
    Args:
        name: The column name to check.
        
    Returns:
        bool: True if it ends with '_id' or '_key' or is exactly 'id'.
    """
    norm_name = normalise_column_name(name)
    return norm_name == "id" or norm_name.endswith("_id") or norm_name.endswith("_key")


def is_date_column(name: str) -> bool:
    """
    Check if a column name indicates a date or time.
    
    Args:
        name: The column name to check.
        
    Returns:
        bool: True if it ends with '_date', '_at', or '_time'.
    """
    norm_name = normalise_column_name(name)
    return norm_name.endswith("_date") or norm_name.endswith("_at") or norm_name.endswith("_time")


def is_amount_column(name: str) -> bool:
    """
    Check if a column name indicates an amount.
    
    Args:
        name: The column name to check.
        
    Returns:
        bool: True if it ends with '_amount', '_total', '_price', or '_sum'.
    """
    norm_name = normalise_column_name(name)
    return (
        norm_name.endswith("_amount")
        or norm_name.endswith("_total")
        or norm_name.endswith("_price")
        or norm_name.endswith("_sum")
    )


def is_status_column(name: str) -> bool:
    """
    Check if a column name indicates a status.
    
    Args:
        name: The column name to check.
        
    Returns:
        bool: True if it ends with '_status' or '_state'.
    """
    norm_name = normalise_column_name(name)
    return norm_name.endswith("_status") or norm_name.endswith("_state")


def is_boolean_column(name: str) -> bool:
    """
    Check if a column name indicates a boolean value.
    
    Args:
        name: The column name to check.
        
    Returns:
        bool: True if it starts with 'is_', 'has_', or ends with '_flag'.
    """
    norm_name = normalise_column_name(name)
    return norm_name.startswith("is_") or norm_name.startswith("has_") or norm_name.endswith("_flag")
