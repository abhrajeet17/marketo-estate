from flask import request

from app.services.portal_identity_service import invalidate_portal_identity

from .admin_users import register_uam_admin_user_routes
from .clients import register_uam_client_routes
from .onboarding import register_uam_onboarding_routes
from .pages import register_uam_page_routes
from .profile_orgs import register_uam_profile_org_routes
from .resource_access import register_uam_resource_access_routes

# Successful writes under these prefixes can change someone's portal role.
_IDENTITY_WRITE_PREFIXES = ('/api/clients', '/api/client-team-invites', '/api/admin/users', '/api/admin/invite',
                           '/api/onboarding', '/api/join-requests')


def _register_identity_invalidation(app):
    @app.after_request
    def _drop_identity_cache_after_membership_writes(response):
        if (
            request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            and response.status_code < 400
            and request.path.startswith(_IDENTITY_WRITE_PREFIXES)
        ):
            invalidate_portal_identity()
        return response


def register_uam_routes(app):
    register_uam_page_routes(app)
    register_uam_profile_org_routes(app)
    register_uam_admin_user_routes(app)
    register_uam_resource_access_routes(app)
    register_uam_client_routes(app)
    register_uam_onboarding_routes(app)
    _register_identity_invalidation(app)


__all__ = ['register_uam_routes']
