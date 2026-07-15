import hashlib
import json
from pydantic import BaseModel

def compute_node_hash(model: BaseModel) -> str:
    """
    Compute a content-addressable hash for an IR node.
    
    Converts the pydantic model to a dict, recursively sorts keys, serializes
    to a JSON string without spaces, computes the SHA-256 hex digest, and 
    returns the full SHA-256 hex digest. This is useful for incremental recompilation.
    
    Args:
        model: The Pydantic model to hash.
        
    Returns:
        A SHA-256 hex digest string.
    """
    # Get a dictionary representation of the model
    # Using model_dump(mode="json") if available (Pydantic v2), else fallback to dict()
    try:
        model_dict = model.model_dump(mode="json")
    except AttributeError:
        model_dict = model.dict()
        
    # Serialize to JSON with sorted keys and no spaces
    serialized = json.dumps(model_dict, sort_keys=True, separators=(',', ':'))
    
    # Compute SHA-256 hash
    hash_obj = hashlib.sha256(serialized.encode("utf-8"))
    
    return hash_obj.hexdigest()
