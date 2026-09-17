"""
DEPRECATED: Thin re-export from app.core and app.services.panorama_service.
Use app.core.database, app.core.auth, and app.services.panorama_service directly.
"""
from app.core.database import get_supabase
from app.core.auth import (
    get_current_user,
    get_profile,
    ensure_profile,
    require_auth,
    require_admin,
    require_superadmin,
)
from app.services.panorama_service import (
    get_panorama_with_access,
    list_panoramas_for_user,
    get_panorama_by_id,
    can_edit_plots,
    can_delete_panorama,
)

__all__ = [
    'get_supabase',
    'get_current_user',
    'get_profile',
    'ensure_profile',
    'require_auth',
    'require_admin',
    'require_superadmin',
    'get_panorama_with_access',
    'list_panoramas_for_user',
    'get_panorama_by_id',
    'can_edit_plots',
    'can_delete_panorama',
]
