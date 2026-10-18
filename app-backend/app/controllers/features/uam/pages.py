from flask import redirect, render_template

from app.controllers.features.shared import auth_ctx


def register_uam_page_routes(app):
    @app.route('/organizations')
    def organizations_page():
        return render_template('organizations.html', **auth_ctx())

    @app.route('/users')
    def users_page():
        return redirect('/user-management?open=invite')

    @app.route('/user-management')
    def user_management_page():
        return render_template('user_management.html', **auth_ctx())

    @app.route('/client-management')
    def client_management_page():
        return render_template('client_management.html', **auth_ctx())

    @app.route('/onboarding')
    def onboarding_page():
        return render_template('onboarding.html', **auth_ctx())

    @app.route('/requests')
    def join_requests_page():
        return render_template('join_requests.html', **auth_ctx())

    @app.route('/broker/invites')
    def broker_invites_page():
        return render_template('broker_invites.html', **auth_ctx())

    @app.route('/customer-dashboard')
    def customer_dashboard_page():
        return render_template('customer_dashboard.html', **auth_ctx())

    @app.route('/projects')
    def client_projects_page():
        return render_template('projects.html', **auth_ctx())

    @app.route('/panorama/<int:panorama_id>/access')
    def panorama_access_page(panorama_id):
        return render_template('panorama_access.html', panorama_id=panorama_id, **auth_ctx())

    @app.route('/workspace/<workspace_id>/access')
    def workspace_access_page(workspace_id):
        # Project access is managed in a modal on /projectselection (by organization).
        return redirect('/projectselection')


