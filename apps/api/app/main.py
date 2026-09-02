from app.core.config import get_settings
from app.factory import create_app

# Configuration is intentionally validated during module import so an unsafe
# trading endpoint or mode prevents the process from starting.
app = create_app(get_settings())
