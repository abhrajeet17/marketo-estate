from .assets import register_asset_routes
from .building_plan import invalidate_building_plan_cache, register_building_plan_routes, sign_many
from .crm import register_crm_broker_routes, register_crm_lock_routes, register_crm_master_routes, register_crm_plot_routes
from .crm_dashboard import register_crm_dashboard_routes
from .crm_leads import register_crm_lead_routes
from .crm_normal import register_crm_normal_routes
from .crm_quotes import register_crm_quote_routes
from .crm_records import register_crm_record_list_routes
from .daynight import register_daynight_routes
from .full_view import register_full_view_routes
from .gallery import register_gallery_routes
from .media import register_media_routes
from .markers import register_marker_routes
from .building_map import register_building_map_routes
from .floorplan import register_floorplan_routes
from .project_plan import register_project_plan_routes
from .earth_view import register_earth_view_routes
from .portal import register_portal_routes
from .page_access import register_page_access_routes
from .resource_filters import register_resource_filters_routes
from .sales_route_maps import register_sales_route_map_routes
from .seo import register_seo_routes
from .uam import register_uam_routes

__all__ = [
    'invalidate_building_plan_cache',
    'register_asset_routes',
    'register_building_plan_routes',
    'sign_many',
    'register_crm_quote_routes',
    'register_crm_record_list_routes',
    'register_crm_normal_routes',
    'register_crm_broker_routes',
    'register_crm_dashboard_routes',
    'register_crm_lead_routes',
    'register_crm_lock_routes',
    'register_crm_master_routes',
    'register_crm_plot_routes',
    'register_daynight_routes',
    'register_full_view_routes',
    'register_seo_routes',
    'register_gallery_routes',
    'register_media_routes',
    'register_marker_routes',
    'register_building_map_routes',
    'register_floorplan_routes',
    'register_project_plan_routes',
    'register_earth_view_routes',
    'register_portal_routes',
    'register_page_access_routes',
    'register_resource_filters_routes',
    'register_sales_route_map_routes',
    'register_uam_routes',
]
