from .assets import register_asset_routes
from .crm import register_crm_broker_routes, register_crm_contact_routes, register_crm_lock_routes, register_crm_master_routes, register_crm_plot_routes, register_crm_quote_routes
from .crm_normal import register_crm_normal_routes
from .crm_records import register_crm_record_list_routes
from .daynight import register_daynight_routes
from .full_view import register_full_view_routes
from .gallery import register_gallery_routes
from .page_access import register_page_access_routes
from .resource_filters import register_resource_filters_routes
from .sales_route_maps import register_sales_route_map_routes
from .uam import register_uam_routes

__all__ = [
    'register_asset_routes',
    'register_crm_quote_routes',
    'register_crm_record_list_routes',
    'register_crm_normal_routes',
    'register_crm_broker_routes',
    'register_crm_contact_routes',
    'register_crm_lock_routes',
    'register_crm_master_routes',
    'register_crm_plot_routes',
    'register_daynight_routes',
    'register_full_view_routes',
    'register_gallery_routes',
    'register_page_access_routes',
    'register_resource_filters_routes',
    'register_sales_route_map_routes',
    'register_uam_routes',
]
