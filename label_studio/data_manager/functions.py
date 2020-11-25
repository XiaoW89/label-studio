from flask import session
from label_studio.utils.misc import DirectionSwitch, timestamp_to_local_datetime
from label_studio.utils.uri_resolver import resolve_task_data_uri

DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
TASKS = 'tasks:'


class DataManagerException(Exception):
    pass


def create_default_tabs():
    """ Create default state for all tabs as initialization
    """
    return {
        'tabs': [
            {
                'id': 1,
                'title': 'Tab 1',
                'hiddenColumns': None
            }
        ]
    }


def column_type(key):
    if key == 'image':
        return 'Image'
    elif key == 'audio':
        return 'Audio'
    elif key == 'audioplus':
        return 'AudioPlus'
    else:
        return 'String'


def make_columns(project):
    """ Make columns info for the frontend data manager
    """
    result = {'columns': []}

    # frontend uses MST data model, so we need two directional referencing parent <-> child
    task_data_children = []
    for key, data_type in project.data_types.items():
        column = {
            'id': key,
            'title': key,
            'type': column_type(key),  # data_type,
            'target': 'tasks',
            'parent': 'data'
        }
        result['columns'].append(column)
        task_data_children.append(column['id'])

    result['columns'] += [
        # --- Tasks ---
        {
            'id': 'id',
            'title': "Task ID",
            'type': "Number",
            'target': 'tasks'
        },
        {
            'id': 'completed_at',
            'title': "Completed at",
            'type': "Datetime",
            'target': 'tasks',
            'help': 'Last completion date'
        },
        {
            'id': 'total_completions',
            'title': "Completion number",
            'type': "String",
            'target': 'tasks',
            'help': 'Total completions per task'
        },
        {
            'id': 'has_cancelled_completions',
            'title': "Cancelled",
            'type': "Number",
            'target': 'tasks',
            'help': 'Number of cancelled completions'
        },
        {
            'id': 'data',
            'title': "data",
            'type': "List",
            'target': 'tasks',
            'children': task_data_children
        }
    ]
    return result


def load_tab(tab_id, raise_if_not_exists=False):
    """ Load tab info from DB
    """
    # load tab data
    data = create_default_tabs() if 'tab_data' not in session else session['tab_data']

    # select by tab id
    for tab in data['tabs']:
        if tab['id'] == tab_id:
            break
    else:
        if raise_if_not_exists:
            raise DataManagerException('No tab with id: ' + str(tab_id))

        # create a new tab
        tab = {'id': tab_id}
    return tab


def save_tab(tab_id, tab_data):
    """ Save tab info to DB
    """
    # load tab data
    data = create_default_tabs() if 'tab_data' not in session else session['tab_data']
    tab_data['id'] = tab_id

    # select by tab id
    for i, tab in enumerate(data['tabs']):
        if tab['id'] == tab_id:
            data['tabs'][i] = tab_data
            break
    else:
        # create a new tab
        tab_data['id'] = tab_id
        data['tabs'].append(tab_data)

    session['tab_data'] = data


def delete_tab(tab_id):
    """ Delete tab from DB
    """
    # load tab data
    if 'tab_data' not in session:
        return False

    data = session['tab_data']

    # select by tab id
    for i, tab in enumerate(data['tabs']):
        if tab['id'] == tab_id:
            del data['tabs'][i]
            break
    else:
        return False

    session['tab_data'] = data
    return True


def preload_tasks(project, resolve_uri=False):
    """ Preload tasks: get completed_at, has_cancelled_completions,
        evaluate pre-signed urls for storages, aggregate over completion data, etc.
    """
    task_ids = project.source_storage.ids()  # get task ids for all tasks in DB
    all_completed_at = project.get_completed_at()  # task can have multiple completions, get the last of completed
    all_cancelled_status = project.get_cancelled_status()  # number of all cancelled completions in task

    # get tasks with completions
    tasks = []
    for i in task_ids:
        task = project.get_task_with_completions(i)

        # no completions at task, get task without completions
        if task is None:
            task = project.source_storage.get(i)

        # with completions
        else:
            # completed_at
            if i in all_completed_at:
                completed_at = all_completed_at[i]
                if completed_at != 0 and isinstance(completed_at, int):
                    completed_at = timestamp_to_local_datetime(completed_at).strftime(DATETIME_FORMAT)
                task['completed_at'] = completed_at

            # cancelled completions number
            if i in all_cancelled_status:
                task['has_cancelled_completions'] = all_cancelled_status[i]

            # total completions
            task['total_completions'] = len(task['completions'])

        # don't resolve data (s3/gcs is slow) if it's not necessary (it's very slow)
        if resolve_uri:
            task = resolve_task_data_uri(task, project=project)

        tasks.append(task)

    return tasks


def operator(op, a, b):
    """ Filter operators
    """
    if op == 'equal':
        return a == b
    if op == 'not_equal':
        return a != b
    if op == 'contains':
        return a in b
    if op == 'not_contains':
        return a not in b
    if op == 'empty' and a:  # TODO: check it
        return b is None or not b
    if op == 'not_empty' and not a:  # TODO: check it
        return b is not None or not b

    if op == 'less':
        return b < a
    if op == 'greater':
        return b > a
    if op == 'less_or_equal':
        return b <= a
    if op == 'greater_or_equal':
        return b >= a

    if op == 'in':
        a, c = a['min'], a['max']
        return a <= b <= c
    if op == 'not_in':
        a, c = a['min'], a['max']
        return not (a <= b <= c)


def resolve_task_field(task, field):
    """ Get task field from root or 'data' sub-dict
    """
    if field.startswith('data.'):
        result = task['data'].get(field[5:], None)
    else:
        result = task.get(field, None)
    return result


def order_tasks(params, tasks):
    """ Apply ordering to tasks
    """
    ordering = params.tab.get('ordering', [])  # ordering = ['id', 'completed_at', ...]
    # remove 'tasks:' prefix for tasks api, for annotations it will be 'annotations:'
    ordering = [o.replace(TASKS, '') for o in ordering if o.startswith(TASKS) or o.startswith('-' + TASKS)]
    order = 'id' if not ordering else ordering[0]  # we support only one column ordering right now

    # ascending or descending
    ascending = order[0] == '-'
    order = order[1:] if order[0] == '-' else order

    # id
    if order == 'id':
        ordered = sorted(tasks, key=lambda x: x['id'], reverse=ascending)

    # cancelled: for has_cancelled_completions use two keys ordering
    elif order == 'has_cancelled_completions':
        ordered = sorted(tasks,
                         key=lambda x: (DirectionSwitch(x.get('has_cancelled_completions', None), not ascending),
                                        DirectionSwitch(x.get('completed_at', None), False)))
    # another orderings
    else:
        ordered = sorted(tasks, key=lambda x: (DirectionSwitch(resolve_task_field(x, order), not ascending)))

    return ordered


def filter_tasks(tasks, params):
    """ Filter tasks using
    """
    # check for filtering params
    tab = params.tab
    if tab is None:
        return tasks
    filters = tab.get('filters', None)
    if not filters:
        return tasks
    conjunction = tab['conjunction']

    new_tasks = tasks if conjunction == 'and' else []

    # go over all the filters
    for f in filters:
        parts = f['filter'].split(':')  # filters:<tasks|annotations>:field_name
        target = parts[1]  # 'tasks | annotations'
        field = parts[2]  # field name
        op, value = f['operator'], f['value']

        if target != 'tasks':
            raise DataManagerException('Filtering target ' + target + ' is not yet supported')

        if conjunction == 'and':
            new_tasks = [task for task in new_tasks if operator(op, value, resolve_task_field(task, field))]

        elif conjunction == 'or':
            new_tasks += [task for task in tasks if operator(op, value, resolve_task_field(task, field))]

        else:
            raise DataManagerException('Filtering conjunction ' + op + ' is not supported')

    return new_tasks


def get_used_fields(params):
    """ Get all used fields from filter and order params
    """
    fields = []
    filters = params.tab.get('filters', None) or []
    for item in filters:
        fields.append(item['filter'])

    ordering = params.tab.get('ordering', None) or []
    ordering = [o.replace(TASKS, '') for o in ordering if o.startswith(TASKS) or o.startswith('-' + TASKS)]
    order = 'id' if not ordering else ordering[0]  # we support only one column ordering right now
    fields.append(order)
    return list(set(fields))


def prepare_tasks(project, params):
    """ Main function to get tasks
    """
    page, page_size = params.page, params.page_size
    # use only necessary fields for filtering and ordering to avoid storage (s3/gcs/etc) overloading
    working_fields = get_used_fields(params)
    need_uri_resolving = any(['data.' in field for field in working_fields])

    # load all tasks from db with some aggregations over completions
    tasks = preload_tasks(project, resolve_uri=need_uri_resolving)

    # filter
    tasks = filter_tasks(tasks, params)

    # order
    tasks = order_tasks(params, tasks)
    total = len(tasks)

    # pagination
    if page > 0 and page_size > 0:
        tasks = tasks[(page - 1) * page_size:page * page_size]

    # resolve all task fields
    for i, task in enumerate(tasks):
        tasks[i] = resolve_task_data_uri(task, project=project)

    return {'tasks': tasks, 'total': total}


def prepare_annotations(tasks, params):
    """ Main function to get annotations
    """
    page, page_size = params.page, params.page_size

    # unpack completions from tasks
    items = []
    for task in tasks:
        completions = task.get('completions', [])

        # assign task ids to have link between completion and task in the data manager
        for completion in completions:
            completion['task_id'] = task['id']
            # convert created_at
            created_at = completion.get('created_at', None)
            if created_at:
                completion['created_at'] = timestamp_to_local_datetime(created_at).strftime(DATETIME_FORMAT)

        items += completions

    total = len(items)

    # skip pagination if page<0 and page_size<=0
    if page > 0 and page_size > 0:
        items = items[(page - 1) * page_size: page * page_size]

    return {'annotations': items, 'total': total}
