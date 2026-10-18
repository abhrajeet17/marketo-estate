"""
In-memory stand-ins for Supabase (PostgREST + Auth admin) and S3 storage.

The query builder implements the subset of supabase-py the app uses (select/insert/update/
upsert/delete, eq/neq/in_/is_/gt/gte/lt/lte/like/ilike/contains/or_/not_, order/limit/range,
count). Tables and column types mirror the production schema (SCHEMA), so inserts get real
defaults: integer or uuid ids, timestamps, and NULL for columns not given. Embedded selects such
as `*, workspaces(name)` attach related rows through `<table>_id` columns.

Nothing here opens a connection: unit tests stay hermetic and can never touch real data.
"""
import copy
import fnmatch
import itertools
import re
import threading
import uuid
from datetime import datetime, timezone

# Production schema (public tables): column -> type. Kept in sync from information_schema.
_RAW_SCHEMA = {
    'building_map_images': 'id:uuid,building_map_id:uuid,name:text,image_filename:text,image_width:int,image_height:int,sort_order:int,created_at:ts',
    'building_maps': 'id:uuid,user_id:uuid,org_id:uuid,catalogue_id:uuid,name:text,image_filename:text,image_width:int,image_height:int,share_token:text,created_at:ts,updated_at:ts,workspace_id:uuid,view_config:json',
    'building_zones': 'id:int,building_map_id:uuid,name:text,floor_number:int,linked_panorama_id:int,linked_floor_plan_item_id:uuid,color:text,points:json,sort_order:int,created_at:ts,updated_at:ts,image_id:uuid,linked_building_map_id:uuid,link_type:text,meta:json',
    'buy_interests': 'id:uuid,panorama_id:int,submitted_by:uuid,customer_name:text,customer_email:text,customer_phone:text,category:text,plots:json,status:text,notes:text,created_at:ts,updated_at:ts,is_contacted:bool,contacted_at:ts,contact_id:uuid,assigned_to:uuid,assigned_at:ts,client_id:uuid,reference_user_id:uuid,customer_birthday:text,customer_address:text,customer_street:text,customer_city:text,customer_state:text,customer_country:text,customer_zip_code:text,lead_source:text,lead_category:text,lead_status:text,campaign_type:text,campaign_status:text,deal_stage:text,title:text,description:text,custom_fields:json,contact_revealed_at:ts',
    'client_join_requests': 'id:uuid,client_id:uuid,org_id:uuid,user_id:uuid,member_role:text,message:text,status:text,decided_by:uuid,decided_at:ts,created_at:ts,updated_at:ts',
    'client_members': 'id:int,client_id:uuid,user_id:uuid,member_role:text,invited_by:uuid,created_at:ts',
    'client_team_invites': 'id:uuid,client_id:uuid,org_id:uuid,invited_by:uuid,email:text,display_name:text,member_role:text,invite_token:text,invite_link:text,status:text,expires_at:ts,accepted_at:ts,accepted_user_id:uuid,created_at:ts,updated_at:ts',
    'clients': 'id:uuid,org_id:uuid,name:text,description:text,created_by:uuid,created_at:ts,updated_at:ts,members_allowed:int',
    'crm_contacts': 'id:uuid,org_id:uuid,panorama_id:int,full_name:text,email:text,phone:text,email_norm:text,phone_norm:text,source_interest_id:uuid,created_by:uuid,notes:text,created_at:ts,updated_at:ts,client_id:uuid,custom_fields:json,birthday:text,address:text',
    'crm_deal_quotes': 'id:uuid,deal_id:uuid,contact_id:uuid,quote_payload:json,share_token:text,sent_to_email:text,sent_to_phone:text,shared_via:text,sent_at:ts,created_by:uuid,created_at:ts,updated_at:ts,template_id:uuid,status:text',
    'crm_deals': 'id:uuid,org_id:uuid,panorama_id:int,interest_id:uuid,contact_id:uuid,title:text,stage:text,is_active:bool,amount:text,currency:text,plots:json,project_name:text,notes:text,created_by:uuid,created_at:ts,updated_at:ts,client_id:uuid,custom_fields:json',
    'crm_leads': 'id:uuid,record_status:text,org_id:uuid,client_id:uuid,panorama_id:int,submitted_by:uuid,reference_user_id:uuid,reference_user_role:text,contact_revealed_at:ts,assigned_to:uuid,assigned_at:ts,customer_name:text,customer_email:text,customer_phone:text,customer_birthday:text,customer_address:text,customer_street:text,customer_city:text,customer_state:text,customer_country:text,customer_zip_code:text,email_norm:text,phone_norm:text,title:text,description:text,category:text,lead_source:text,lead_category:text,lead_status:text,campaign_type:text,campaign_status:text,plots:json,notes:text,custom_fields:json,deal_title:text,deal_stage:text,deal_amount:text,deal_currency:text,deal_is_active:bool,deal_project_name:text,converted_at:ts,converted_by:uuid,legacy_interest_id:uuid,legacy_deal_id:uuid,legacy_contact_id:uuid,created_at:ts,updated_at:ts',
    'crm_master_attributes': 'id:uuid,client_id:uuid,field_key:text,label:text,is_required:bool,is_optional:bool,is_enabled:bool,sort_order:int,created_at:ts,updated_at:ts,owner_user_id:uuid,applies_to:arr',
    'crm_master_values': 'id:uuid,client_id:uuid,field_key:text,value:text,is_enabled:bool,sort_order:int,created_at:ts,updated_at:ts,owner_user_id:uuid',
    'crm_normal_plots': 'id:int,owner_user_id:uuid,project_id:int,project_name:text,name:text,area:text,price:text,status:text,description:text,panorama_id:int,created_at:ts,updated_at:ts,custom_fields:json',
    'crm_normal_projects': 'id:int,owner_user_id:uuid,name:text,location:text,description:text,project_type:text,created_at:ts,updated_at:ts,builder_name:text,location_address:text,location_city:text,location_state:text,google_maps_link:text,location_lat:num,location_lng:num,rera_registration:text,total_area:text,launch_date:text,possession_date:text,contact_phone:text,contact_email:text,amenities:json,custom_fields:json',
    'crm_quote_templates': 'id:uuid,org_id:uuid,panorama_id:int,name:text,template_payload:json,is_default:bool,created_by:uuid,created_at:ts,updated_at:ts',
    'daynight_projects': 'id:uuid,user_id:uuid,org_id:uuid,name:text,media_type:text,stitched_filename:text,stitched_width:int,stitched_height:int,video_filename:text,video_duration:num,join_positions:json,source_images:json,share_token:text,created_at:ts,updated_at:ts,drag_speed:num,workspace_id:uuid',
    'earth_view_markers': 'id:uuid,earth_view_id:uuid,linked_panorama_id:int,name:text,description:text,marker_color:text,image_filename:text,voiceover_filename:text,media_photo:text,media_video:text,longitude:num,latitude:num,created_at:ts,updated_at:ts',
    'earth_view_plots': 'id:int,earth_view_id:uuid,linked_panorama_id:int,name:text,area:text,price:text,status:text,description:text,color:text,media_photo:text,media_video:text,points:json,sort_order:int,created_at:ts,updated_at:ts',
    'earth_views': 'id:uuid,user_id:uuid,org_id:uuid,name:text,share_token:text,center_lng:num,center_lat:num,zoom:num,created_at:ts,updated_at:ts,workspace_id:uuid',
    'floor_plan_catalogues': 'id:uuid,workspace_id:uuid,user_id:uuid,org_id:uuid,name:text,share_token:text,created_at:ts,updated_at:ts',
    'floor_plan_items': 'id:uuid,catalogue_id:uuid,name:text,image_filename:text,image_width:int,image_height:int,file_size_bytes:int,sort_order:int,created_at:ts,updated_at:ts',
    'full_view_configs': 'id:uuid,workspace_id:uuid,org_id:uuid,user_id:uuid,is_active:bool,created_at:ts,updated_at:ts,style:json',
    'full_view_tabs': 'id:uuid,config_id:uuid,icon:text,name:text,tab_type:text,ref_panorama_id:int,ref_daynight_id:uuid,ref_floor_plan_id:uuid,ref_gallery_id:uuid,ref_project_plan_id:uuid,content_data:json,sort_order:int,is_visible:bool,created_at:ts,updated_at:ts,ref_sales_map_id:uuid,ref_sales_flat360_id:uuid',
    'galleries': 'id:uuid,user_id:uuid,org_id:uuid,name:text,share_token:text,created_at:ts,updated_at:ts,workspace_id:uuid',
    'gallery_items': 'id:uuid,gallery_id:uuid,name:text,media_type:text,filename:text,file_size_bytes:int,media_width:int,media_height:int,sort_order:int,created_at:ts,updated_at:ts,is_360:bool',
    'mobile_panoramas': 'id:int,user_id:uuid,org_id:uuid,workspace_id:uuid,panorama_parent_id:int,name:text,filename:text,original_filename:text,width:int,height:int,is_360:bool,use_animated_icons:bool,start_view:json,image_data:text,image_content_type:text,created_at:ts,updated_at:ts',
    'organizations': 'id:uuid,name:text,accent_color:text,created_at:ts,updated_at:ts',
    'panorama_access': 'id:int,panorama_id:int,user_id:uuid,access_type:text,granted_by:uuid,created_at:ts,client_member_id:int',
    'panoramas': 'id:int,user_id:uuid,name:text,filename:text,original_filename:text,width:int,height:int,is_360:bool,created_at:ts,updated_at:ts,image_data:text,image_content_type:text,org_id:uuid,workspace_id:uuid,use_animated_icons:bool,start_view:json,audio_filename:text',
    'plot_lock_access': 'id:uuid,panorama_id:int,user_id:uuid,granted_by:uuid,org_id:uuid,created_at:ts',
    'plot_locks': 'id:uuid,plot_id:int,locked_by:uuid,locked_for_name:text,locked_for_email:text,locked_at:ts',
    'plot_markers': 'id:uuid,plot_id:text,name:text,description:text,image_base64:text,longitude:num,latitude:num,created_at:ts,marker_style:text,marker_icon:text,marker_color:text,status:text,linked_panorama_id:int,image_filename:text,voiceover_filename:text,rotation_x:num,rotation_y:num,rotation_z:num,link_mode:text',
    'plots': 'id:int,panorama_id:int,name:text,area:text,price:text,status:text,description:text,color:text,media_photo:text,media_video:text,points:json,created_at:ts,updated_at:ts,image_data:text,image_content_type:text,linked_panorama_id:int,image_filename:text,label_longitude:num,label_latitude:num',
    'profiles': 'id:uuid,user_id:uuid,role:text,display_name:text,email:text,created_at:ts,updated_at:ts,org_id:uuid',
    'project_plan_maps': 'id:int,project_plan_id:uuid,building_map_id:uuid,sort_order:int,created_at:ts',
    'project_plans': 'id:uuid,user_id:uuid,org_id:uuid,name:text,share_token:text,created_at:ts,updated_at:ts,workspace_id:uuid',
    'sales_flat360_views': 'id:uuid,user_id:uuid,org_id:uuid,workspace_id:uuid,name:text,image_filename:text,image_width:int,image_height:int,share_token:text,created_at:ts,updated_at:ts',
    'sales_route_map_hover_routes': 'id:uuid,map_id:uuid,label:text,path_points:json,color:text,line_width:int,sort_order:int,created_at:ts,updated_at:ts,line_style:text',
    'sales_route_map_markers': 'id:uuid,map_id:uuid,marker_type:text,label:text,x_ratio:num,y_ratio:num,sort_order:int,created_at:ts,updated_at:ts,icon_key:text,pointer_type:text,icon_color:text,icon_look:text,marker_size:num',
    'sales_route_map_routes': 'id:uuid,map_id:uuid,from_marker_id:uuid,to_marker_id:uuid,path_points:json,color:text,line_width:int,sort_order:int,created_at:ts,updated_at:ts,distance_km:num,line_style:text',
    'sales_route_maps': 'id:uuid,user_id:uuid,org_id:uuid,workspace_id:uuid,name:text,image_filename:text,image_width:int,image_height:int,share_token:text,created_at:ts,updated_at:ts',
    'user_invites': 'id:uuid,org_id:uuid,invited_by:uuid,email:text,display_name:text,role:text,status:text,invited_user_id:uuid,created_at:ts,accepted_at:ts',
    'workspace_access': 'id:int,workspace_id:uuid,user_id:uuid,access_type:text,granted_by:uuid,created_at:ts,client_member_id:int',
    'workspace_share_endpoints': 'id:int,workspace_id:uuid,endpoint:text,created_by:uuid,updated_by:uuid,created_at:ts,updated_at:ts',
    'workspaces': 'id:uuid,user_id:uuid,org_id:uuid,name:text,created_at:ts,updated_at:ts,main_panorama_id:int,location_address:text,location_city:text,location_state:text,location_lat:num,location_lng:num,google_maps_link:text,rera_registration:text,launch_date:text,possession_date:text,builder_name:text,project_type:text,total_area:text,description:text,amenities:json,is_published:bool,brochure_url:text,contact_phone:text,contact_email:text,panaroma_menu_config:json',
}
SCHEMA = {t: dict(c.split(':') for c in cols.split(',')) for t, cols in _RAW_SCHEMA.items()}

# Columns with a database default (per table first, then by column name).
_TABLE_DEFAULTS = {
    'client_join_requests': {'status': 'pending'}, 'client_team_invites': {'status': 'pending'},
    'user_invites': {'status': 'pending'}, 'crm_deal_quotes': {'status': 'draft'},
    'buy_interests': {'status': 'new'}, 'plots': {'status': 'available'},
}
_DEFAULTS = {
    'is_360': True, 'is_active': True, 'is_visible': True, 'is_enabled': True, 'is_published': False,
    'use_animated_icons': False, 'is_contacted': False, 'deal_is_active': True, 'is_default': False,
    'sort_order': 0, 'status': None, 'record_status': 'lead', 'members_allowed': 10,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class APIError(Exception):
    """Mimics postgrest.exceptions.APIError closely enough for the app's error handling."""

    def __init__(self, message, code='PGRST000'):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = None
        self.hint = None

    def json(self):
        return {'message': self.message, 'code': self.code}


def _real_api_error(message, code):
    try:
        from postgrest.exceptions import APIError as PgAPIError
        return PgAPIError({'message': message, 'code': code, 'details': None, 'hint': None})
    except Exception:  # pragma: no cover - postgrest is installed with supabase
        return APIError(message, code)


class Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _cmp_value(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    try:
        return float(text) if re.fullmatch(r'-?\d+(\.\d+)?', text) else text
    except ValueError:
        return text


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    return str(a) == str(b)


def _like(value, pattern, case_insensitive):
    if value is None:
        return False
    glob = str(pattern).replace('*', '%')
    regex = '^' + '.*'.join(re.escape(part) for part in glob.split('%')) + '$'
    return re.match(regex, str(value), re.I | re.S if case_insensitive else re.S) is not None


def _parse_list(raw):
    if isinstance(raw, (list, tuple, set)):
        return list(raw)
    text = str(raw).strip()
    if text.startswith('(') and text.endswith(')'):
        text = text[1:-1]
    return [p.strip().strip('"') for p in text.split(',') if p.strip()]


def _contains(value, wanted):
    if value is None:
        return False
    if isinstance(wanted, dict):
        return isinstance(value, dict) and all(_same(value.get(k), v) for k, v in wanted.items())
    items = wanted if isinstance(wanted, (list, tuple)) else _parse_list(wanted)
    if isinstance(value, (list, tuple)):
        return all(any(_same(v, w) for v in value) for w in items)
    return all(str(w) in str(value) for w in items)


def _op_matches(row, column, op, value):
    if '.' in column or column not in row and column.split('->')[0] not in row:
        return True  # filters on embedded resources or JSON paths are not modelled
    cell = row.get(column)
    if op == 'eq':
        return _same(cell, value)
    if op == 'neq':
        return not _same(cell, value)
    if op == 'in':
        return any(_same(cell, v) for v in _parse_list(value))
    if op == 'is':
        target = None if value in (None, 'null') else (str(value).lower() == 'true')
        return cell is None if target is None else (cell is not None and bool(cell) == target)
    if op in ('gt', 'gte', 'lt', 'lte'):
        if cell is None:
            return False
        a, b = _cmp_value(cell), _cmp_value(value)
        try:
            return {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}[op]
        except TypeError:
            a, b = str(a), str(b)
            return {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}[op]
    if op == 'like':
        return _like(cell, value, False)
    if op == 'ilike':
        return _like(cell, value, True)
    if op in ('cs', 'contains'):
        return _contains(cell, value)
    return True


def _split_top(text, sep=','):
    parts, depth, cur = [], 0, ''
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _or_matches(row, expr):
    """PostgREST or=(a.eq.1,b.ilike.*x*,and(c.eq.2,d.is.null)) for one row."""
    for part in _split_top(expr):
        if part.startswith('and(') and part.endswith(')'):
            if all(_or_matches(row, sub) for sub in _split_top(part[4:-1])):
                return True
            continue
        bits = part.split('.', 2)
        if len(bits) < 3:
            return True
        column, op, value = bits
        negate = False
        if op == 'not':
            negate = True
            op, _, value = value.partition('.')
        hit = _op_matches(row, column, op, value)
        if hit != negate:
            return True
    return False


class _Not:
    def __init__(self, query):
        self._q = query

    def __getattr__(self, name):
        method = getattr(self._q, name)

        def negated(*args, **kwargs):
            self._q._negate_next = True
            return method(*args, **kwargs)
        return negated


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.action = 'select'
        self.columns = '*'
        self.payload = None
        self.filters = []
        self.orders = []
        self.limit_n = None
        self.offset = 0
        self.count_mode = None
        self.head = False
        self.on_conflict = None
        self.single_mode = None
        self.ignore_duplicates = False
        self._negate_next = False

    # ----- actions -----
    def select(self, columns='*', count=None, head=False, **_kw):
        if self.action == 'select':
            self.columns = columns or '*'
        else:
            self.columns = columns or '*'  # insert(...).select() style
        self.count_mode = count
        self.head = head
        return self

    def insert(self, rows, **kw):
        self.action, self.payload = 'insert', rows
        self.count_mode = kw.get('count')
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False, **kw):
        self.action, self.payload, self.on_conflict = 'upsert', rows, on_conflict
        self.ignore_duplicates = ignore_duplicates
        return self

    def update(self, values, **kw):
        self.action, self.payload = 'update', values
        return self

    def delete(self, **kw):
        self.action = 'delete'
        return self

    # ----- filters -----
    def _add(self, fn):
        if self._negate_next:
            self._negate_next = False
            self.filters.append(lambda row, f=fn: not f(row))
        else:
            self.filters.append(fn)
        return self

    def _op(self, op, column, value):
        return self._add(lambda row: _op_matches(row, column, op, value))

    def eq(self, column, value):
        return self._op('eq', column, value)

    def neq(self, column, value):
        return self._op('neq', column, value)

    def in_(self, column, values):
        return self._op('in', column, list(values) if not isinstance(values, str) else values)

    def is_(self, column, value):
        return self._op('is', column, value)

    def gt(self, column, value):
        return self._op('gt', column, value)

    def gte(self, column, value):
        return self._op('gte', column, value)

    def lt(self, column, value):
        return self._op('lt', column, value)

    def lte(self, column, value):
        return self._op('lte', column, value)

    def like(self, column, pattern):
        return self._op('like', column, pattern)

    def ilike(self, column, pattern):
        return self._op('ilike', column, pattern)

    def contains(self, column, value):
        return self._op('cs', column, value)

    def match(self, query):
        for column, value in (query or {}).items():
            self.eq(column, value)
        return self

    def filter(self, column, operator, value):
        negate = operator.startswith('not.')
        op = operator[4:] if negate else operator
        fn = lambda row: _op_matches(row, column, op, value)  # noqa: E731
        return self._add((lambda row: not fn(row)) if negate else fn)

    def or_(self, expr, reference_table=None, **_kw):
        if reference_table:
            return self
        return self._add(lambda row: _or_matches(row, expr))

    @property
    def not_(self):
        return _Not(self)

    # ----- modifiers -----
    def order(self, column, desc=False, nullsfirst=False, **_kw):
        self.orders.append((column, desc))
        return self

    def limit(self, n, **_kw):
        self.limit_n = int(n)
        return self

    def range(self, start, end, **_kw):
        self.offset, self.limit_n = int(start), int(end) - int(start) + 1
        return self

    def single(self):
        self.single_mode = 'single'
        return self

    def maybe_single(self):
        self.single_mode = 'maybe'
        return self

    # ----- execution -----
    def _matching(self, rows):
        return [r for r in rows if all(f(r) for f in self.filters)]

    def _sorted(self, rows):
        for column, desc in reversed(self.orders):
            rows = sorted(rows, key=lambda r: (r.get(column) is None, _sort_key(r.get(column))), reverse=desc)
        return rows

    def execute(self):
        with self.db.lock:
            self.db.calls.append((self.action, self.table))
            self.db.call_index += 1
            at = self.db.fail_at
            if at and (self.db.call_index == at or (self.db.fail_persist and self.db.call_index > at)):
                raise _real_api_error(self.db.fail_message, self.db.fail_code)
            if self.db.fail_tables.get(self.table):
                raise _real_api_error(self.db.fail_tables[self.table], 'XX000')
            rows = self.db.rows(self.table)
            if self.action == 'select':
                matched = self._sorted(self._matching(rows))
                total = len(matched)
                if self.offset:
                    matched = matched[self.offset:]
                if self.limit_n is not None:
                    matched = matched[:self.limit_n]
                data = [self.db.project(self.table, r, self.columns) for r in matched]
            elif self.action == 'insert':
                data = [self.db.insert_row(self.table, r) for r in _as_list(self.payload)]
                total = len(data)
            elif self.action == 'upsert':
                data = [self.db.upsert_row(self.table, r, self.on_conflict, self.ignore_duplicates) for r in _as_list(self.payload)]
                data = [d for d in data if d is not None]
                total = len(data)
            elif self.action == 'update':
                matched = self._matching(rows)
                for r in matched:
                    r.update(copy.deepcopy(self.payload))
                    if 'updated_at' in SCHEMA.get(self.table, {}) and 'updated_at' not in self.payload:
                        r['updated_at'] = now_iso()
                data = [copy.deepcopy(r) for r in matched]
                total = len(data)
            else:  # delete
                matched = self._matching(rows)
                ids = {id(r) for r in matched}
                self.db.tables[self.table] = [r for r in rows if id(r) not in ids]
                data = [copy.deepcopy(r) for r in matched]
                total = len(data)
            count = total if self.count_mode else None
            if self.head:
                data = []
            if self.single_mode:
                if len(data) == 1:
                    return Result(data[0], count)
                if self.single_mode == 'maybe' and not data:
                    return None
                raise _real_api_error('JSON object requested, multiple (or no) rows returned', 'PGRST116')
            return Result(data, count)


def _sort_key(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value, '')
    return (1, 0, str(value))


def _as_list(payload):
    return list(payload) if isinstance(payload, (list, tuple)) else [payload]


_EMBED = re.compile(r'(?:(\w+):)?(\w+)(?:!\w+)?\(([^()]*(?:\([^()]*\)[^()]*)*)\)')


class FakeAuthAdmin:
    def __init__(self, db):
        self.db = db

    def _user(self, uid):
        user = self.db.auth_users.get(str(uid))
        if not user:
            raise Exception('User not found')
        return type('UserResponse', (), {'user': type('User', (), dict(user))()})()

    def get_user_by_id(self, uid):
        return self._user(uid)

    def create_user(self, attrs):
        uid = str(uuid.uuid4())
        self.db.auth_users[uid] = {'id': uid, 'email': attrs.get('email'), 'user_metadata': attrs.get('user_metadata') or {},
                                   'created_at': now_iso(), 'email_confirmed_at': now_iso()}
        return self._user(uid)

    def invite_user_by_email(self, email, options=None):
        return self.create_user({'email': email, 'user_metadata': (options or {}).get('data') or {}})

    def update_user_by_id(self, uid, attrs):
        user = self.db.auth_users.setdefault(str(uid), {'id': str(uid), 'email': None, 'user_metadata': {}})
        if 'email' in attrs:
            user['email'] = attrs['email']
        if 'user_metadata' in attrs:
            user['user_metadata'] = {**(user.get('user_metadata') or {}), **attrs['user_metadata']}
        return self._user(uid)

    def delete_user(self, uid):
        self.db.auth_users.pop(str(uid), None)

    def list_users(self, *_a, **_k):
        return [type('User', (), dict(u))() for u in self.db.auth_users.values()]


class FakeAuth:
    def __init__(self, db):
        self.admin = FakeAuthAdmin(db)

    def get_user(self, *_a, **_k):
        raise Exception('remote auth is not available in unit tests')


class FakeSupabase:
    """The object returned by get_supabase() during unit tests."""

    def __init__(self):
        self.tables = {name: [] for name in SCHEMA}
        self.auth_users = {}
        self.lock = threading.RLock()
        self.calls = []
        self.fail_tables = {}
        # Fault injection: the fail_at-th query raises (and every later one too when fail_persist).
        self.call_index = 0
        self.fail_at = None
        self.fail_persist = False
        self.fail_message = 'injected database failure'
        self.fail_code = 'XX000'
        self._ids = {}
        self.auth = FakeAuth(self)

    # ----- client API -----
    def table(self, name):
        return FakeQuery(self, name)

    from_ = table

    def rpc(self, name, params=None):
        query = FakeQuery(self, '__rpc__')
        query.execute = lambda: Result([])
        return query

    # ----- storage helpers -----
    def rows(self, table):
        return self.tables.setdefault(table, [])

    def _next_id(self, table):
        counter = self._ids.get(table)
        if counter is None:
            start = max([r.get('id') for r in self.rows(table) if isinstance(r.get('id'), int)] or [0]) + 1
            counter = self._ids[table] = itertools.count(start)
        return next(counter)

    def insert_row(self, table, values):
        schema = SCHEMA.get(table, {})
        row = {}
        for column, kind in schema.items():
            if column in values:
                continue
            if column == 'id':
                row['id'] = self._next_id(table) if kind == 'int' else str(uuid.uuid4())
            elif kind == 'ts' and column in ('created_at', 'updated_at', 'locked_at'):
                row[column] = now_iso()
            elif column in _TABLE_DEFAULTS.get(table, {}):
                row[column] = _TABLE_DEFAULTS[table][column]
            elif column in _DEFAULTS:
                row[column] = _DEFAULTS[column]
            else:
                row[column] = None
        row.update(copy.deepcopy(values))
        if not schema and 'id' not in row:
            row['id'] = str(uuid.uuid4())
        self.rows(table).append(row)
        return copy.deepcopy(row)

    def upsert_row(self, table, values, on_conflict, ignore_duplicates):
        keys = [k.strip() for k in (on_conflict or '').split(',') if k.strip()] or ['id']
        if all(k in values for k in keys):
            for row in self.rows(table):
                if all(_same(row.get(k), values[k]) for k in keys):
                    if ignore_duplicates:
                        return None
                    row.update(copy.deepcopy(values))
                    return copy.deepcopy(row)
        return self.insert_row(table, values)

    def project(self, table, row, columns):
        out = copy.deepcopy(row)
        text = re.sub(r'\s+', '', columns or '*')
        for alias, name, inner in _EMBED.findall(text):
            out[alias or name] = self._embed(table, row, name, inner)
        return out

    def _embed(self, table, row, name, inner):
        singular = name[:-1] if name.endswith('s') else name
        if name not in self.tables:
            return None
        fk = f'{singular}_id'
        if fk in row:  # many-to-one
            target = next((r for r in self.rows(name) if _same(r.get('id'), row.get(fk))), None)
            return self.project(name, target, inner) if target else None
        own = (table[:-1] if table.endswith('s') else table) + '_id'
        related = [r for r in self.rows(name) if own in r and _same(r.get(own), row.get('id'))]
        return [self.project(name, r, inner) for r in related]

    # ----- test conveniences -----
    def add(self, table, **values):
        return self.insert_row(table, values)

    def get(self, table, **where):
        return [r for r in self.rows(table) if all(_same(r.get(k), v) for k, v in where.items())]

    def one(self, table, **where):
        rows = self.get(table, **where)
        return rows[0] if rows else None


class FakeS3:
    """boto3 S3 client subset backed by a dict. Presigned URLs point at a fake host."""

    def __init__(self):
        self.objects = {}
        self.broken = False  # every call raises, like a storage outage

    _OPS = ('put_object', 'upload_fileobj', 'get_object', 'head_object', 'delete_object', 'delete_objects',
            'list_objects_v2', 'generate_presigned_url')

    def __getattribute__(self, name):
        if name in FakeS3._OPS and object.__getattribute__(self, 'broken'):
            def outage(*_a, **_k):
                from botocore.exceptions import EndpointConnectionError
                raise EndpointConnectionError(endpoint_url='https://s3.test')
            return outage
        return object.__getattribute__(self, name)

    def _missing(self, key):
        from botocore.exceptions import ClientError
        return ClientError({'Error': {'Code': '404', 'Message': f'Not Found: {key}'}}, 'HeadObject')

    def put_object(self, Bucket, Key, Body=b'', ContentType=None, **_kw):
        data = Body.read() if hasattr(Body, 'read') else (Body.encode() if isinstance(Body, str) else bytes(Body))
        self.objects[Key] = {'body': data, 'content_type': ContentType or 'application/octet-stream'}
        return {'ETag': '"fake"'}

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None, **_kw):
        self.put_object(Bucket, Key, Fileobj, (ExtraArgs or {}).get('ContentType'))

    def get_object(self, Bucket, Key, Range=None, **_kw):
        import io
        obj = self.objects.get(Key)
        if obj is None:
            raise self._missing(Key)
        body = obj['body']
        if Range:
            start, _, end = Range.replace('bytes=', '').partition('-')
            body = body[int(start):(int(end) + 1 if end else None)]
        from botocore.response import StreamingBody
        return {'Body': StreamingBody(io.BytesIO(body), len(body)), 'ContentType': obj['content_type'],
                'ContentLength': len(body)}

    def head_object(self, Bucket, Key, **_kw):
        obj = self.objects.get(Key)
        if obj is None:
            raise self._missing(Key)
        return {'ContentLength': len(obj['body']), 'ContentType': obj['content_type']}

    def delete_object(self, Bucket, Key, **_kw):
        self.objects.pop(Key, None)
        return {}

    def delete_objects(self, Bucket, Delete, **_kw):
        for item in Delete.get('Objects', []):
            self.objects.pop(item['Key'], None)
        return {}

    def list_objects_v2(self, Bucket, Prefix='', **_kw):
        keys = [k for k in self.objects if fnmatch.fnmatch(k, Prefix + '*')]
        return {'Contents': [{'Key': k, 'Size': len(self.objects[k]['body'])} for k in keys], 'KeyCount': len(keys)}

    def generate_presigned_url(self, ClientMethod, Params=None, ExpiresIn=3600, **_kw):
        return f'https://storage.test/{(Params or {}).get("Key")}?sig=fake&exp={ExpiresIn}'

    @property
    def meta(self):
        return type('Meta', (), {'events': type('Events', (), {'register': staticmethod(lambda *a, **k: None)})()})()
