from datetime import datetime
from getpass import getuser

from requests import get, post
from urllib.parse import quote_plus


class IcingaItem(object):
    def __init__(self, json, only_host_name=None):
        if json is None and only_host_name:
            self.host_name = only_host_name
            self.service_name = '-- HOST --'
            self.type = 'Host'
            return

        self.acknowledgement = int(json['attrs']['acknowledgement'])
        self.downtime_depth = int(json['attrs']['downtime_depth'])
        self.state = int(json['attrs']['state'])
        self.state_type = int(json['attrs']['state_type'])
        self.type = json['type']

        if self.type == 'Service':
            self.host_name = json['attrs']['host_name']
            self.service_name = json['attrs']['display_name']
        else:
            if self.state != 0:
                self.state = 2
            self.host_name = json['attrs']['display_name']
            self.service_name = '-- HOST --'

        lcr = json['attrs'].get('last_check_result', {})
        if lcr is not None:
            self.output_lines = lcr.get('output', '').splitlines()
        else:
            self.output_lines = []

    def __lt__(self, other):
        if self.state == other.state:
            if self.host_name == other.host_name:
                return self.service_name < other.service_name
            else:
                return self.host_name < other.host_name
        else:
            return -self.state < -other.state

    def __str__(self):
        # Only useful for debugging. Use get_line_to_show() for
        # formatted output.
        return f'{self.host_name} {self.service_name}'

    def get_filter(self):
        f = f'match("{self.host_name}", host.name)'
        if self.type == 'Service':
            f += f' && match("{self.service_name}", service.name)'
        return f

    def get_line_to_show(self, len_col1):
        prefixes = ''
        prefixes += 'S' if self.state_type == 0 else ' '
        prefixes += 'A' if self.acknowledgement != 0 else ' '
        prefixes += 'D' if self.downtime_depth > 0 else ' '
        host_name = self.host_name + ' ' * (len_col1 - len(self.host_name))
        return f'{prefixes}  {host_name}  {self.service_name}'


class Icinga(object):
    def _api(self, endpoint):
        return self.settings['base_url'] + '/api/v1/' + endpoint

    def get_current_state(self):
        host_params = {}
        service_params = {}

        # Filtering for groups has to be done differently depending on
        # whether you use terminga-proxy or not. In plain Icinga, you
        # need to use a full-blown filter query ("filter=..."). Filter
        # queries are not implemented in terminga-proxy at all. Instead,
        # we pass "hostgroup=..." directly (which is ignored by plain
        # Icinga).
        if self.settings['use_group_filters']:
            if self.settings['group_filters'].get('hostgroup'):
                hg = quote_plus(self.settings['group_filters']['hostgroup'])
                host_params = f'filter="{hg}"%20in%20host.groups'
                host_params += f'&hostgroup={hg}'
            if self.settings['group_filters'].get('servicegroup'):
                sg = quote_plus(self.settings['group_filters']['servicegroup'])
                service_params = f'filter="{sg}"%20in%20service.groups'
                service_params += f'&servicegroup={sg}'

        r = get(self._api('objects/hosts'),
                auth=self.settings['auth'],
                params=host_params)
        r.raise_for_status()
        hosts = r.json()

        r = get(self._api('objects/services'),
                auth=self.settings['auth'],
                params=service_params)
        r.raise_for_status()
        services = r.json()

        return {
            'hosts': [IcingaItem(i) for i in hosts['results']],
            'services': [IcingaItem(i) for i in services['results']],
        }

    def _queue_check_typed(self, items, item_type):
        items = [i for i in items if i.type == item_type]

        chunk_size = 20
        for c in range(0, len(items), chunk_size):
            filters = []
            for i in items[c:c + chunk_size]:
                filters.append('(' + i.get_filter() + ')')

            data = {
                'type': item_type,
                'filter': ' || '.join(filters),
                'force': True,
            }
            r = post(
                self._api('actions/reschedule-check'),
                auth=self.settings['auth'],
                headers={'Accept': 'application/json'},
                json=data,
            )

    def queue_check(self, items):
        self._queue_check_typed(items, 'Host')
        self._queue_check_typed(items, 'Service')

    def _set_ack_typed(self, items, comment, item_type):
        items = [i for i in items if i.type == item_type]

        chunk_size = 20
        for c in range(0, len(items), chunk_size):
            filters = []
            for i in items[c:c + chunk_size]:
                filters.append('(' + i.get_filter() + ')')

            data = {
                'author': getuser(),
                'comment': comment,
                'type': item_type,
                'filter': ' || '.join(filters),

                # "Whether the acknowledgement will be set until the
                # service or host fully recovers. Defaults to false."
                'sticky': True,
            }

            r = post(
                self._api('actions/acknowledge-problem'),
                auth=self.settings['auth'],
                headers={'Accept': 'application/json'},
                json=data,
            )

    def set_ack(self, items, comment):
        if not comment:
            return

        self._set_ack_typed(items, comment, 'Host')
        self._set_ack_typed(items, comment, 'Service')

    def set_ack_for_host(self, items, all_items, comment):
        if not comment:
            return

        items_for_action = set()

        for i in all_items['hosts'] + all_items['services']:
            for sel in items:
                if i.host_name == sel.host_name:
                    items_for_action.add(i)

        self._set_ack_typed(items_for_action, comment, 'Host')
        self._set_ack_typed(items_for_action, comment, 'Service')

    def _set_downtime_typed(self, items, comment, start_time, end_time, item_type):
        items = [i for i in items if i.type == item_type]

        chunk_size = 20
        for c in range(0, len(items), chunk_size):
            filters = []
            for i in items[c:c + chunk_size]:
                filters.append('(' + i.get_filter() + ')')

            data = {
                'author': getuser(),
                'comment': comment,
                'start_time': start_time,
                'end_time': end_time,
                'type': item_type,
                'filter': ' || '.join(filters),
                'child_options': 'DowntimeTriggeredChildren',
            }

            r = post(
                self._api('actions/schedule-downtime'),
                auth=self.settings['auth'],
                headers={'Accept': 'application/json'},
                json=data,
            )

    def set_downtime(self, items, comment, duration):
        if not comment or not duration:
            return

        try:
            if duration.endswith('s'):
                seconds = int(duration[:-1])
            elif duration.endswith('m'):
                seconds = int(duration[:-1]) * 60
            elif duration.endswith('h'):
                seconds = int(duration[:-1]) * 60 * 60
            elif duration.endswith('d'):
                seconds = int(duration[:-1]) * 60 * 60 * 24
            else:
                return
        except:
            return

        start_time = datetime.now().timestamp()
        end_time = start_time + seconds

        self._set_downtime_typed(items, comment, start_time, end_time, 'Host')
        self._set_downtime_typed(items, comment, start_time, end_time, 'Service')

    def set_downtime_for_host(self, items, comment, duration):
        host_names = set()
        for i in items:
            host_names.add(i.host_name)

        dummys = set()
        for i in host_names:
            dummys.add(IcingaItem(None, only_host_name=i))

        self.set_downtime(dummys, comment, duration)
