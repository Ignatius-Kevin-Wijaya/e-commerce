"""Product client — proxy requests to the product service."""
from clients.auth_client import ServiceClient

# Re-exports the generic client; the gateway uses ServiceClient directly via routes.py
__all__ = ["ServiceClient"]
