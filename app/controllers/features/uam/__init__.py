from .admin_users import register_uam_admin_user_routes
from .clients import register_uam_client_routes
from .pages import register_uam_page_routes
from .profile_orgs import register_uam_profile_org_routes
from .resource_access import register_uam_resource_access_routes


def register_uam_routes(app):
    register_uam_page_routes(app)
    register_uam_profile_org_routes(app)
    register_uam_admin_user_routes(app)
    register_uam_resource_access_routes(app)
    register_uam_client_routes(app)


__all__ = ['register_uam_routes']
