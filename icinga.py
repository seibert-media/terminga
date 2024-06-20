from datetime import datetime
from getpass import getuser

from requests import get, post
from urllib.parse import quote_plus

import urllib3

urllib3.disable_warnings()

class IcingaItem(object):
    def __init__(self, json, only_host_name=None):
        if json is None and only_host_name:
            self.host_name = only_host_name
            self.service_name = '-- HOST --'
            self.type = 'Host'
            self.acknowledgement = 0
            self.downtime_depth = 0
            self.output_lines = []
            self.state = 0
            self.state_type = 0
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

    def __eq__(self, other):
        return (
            isinstance(other, IcingaItem) and
            self.acknowledgement == other.acknowledgement and
            self.downtime_depth == other.downtime_depth and
            self.host_name == other.host_name and
            self.output_lines == other.output_lines and
            self.service_name == other.service_name and
            self.state == other.state and
            self.state_type == other.state_type and
            self.type == other.type
        )

    def __hash__(self):
        return hash(
            (
                self.acknowledgement,
                self.downtime_depth,
                self.host_name,
                tuple(self.output_lines),
                self.service_name,
                self.state,
                self.state_type,
                self.type,
            )
        )

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
        # Filtering for groups has to be done differently depending on
        # whether you use terminga-proxy or not. In plain Icinga, you
        # need to use a full-blown filter query ("filter=..."). Filter
        # queries are not implemented in terminga-proxy at all. Instead,
        # we pass "hostgroup=..." directly (which is ignored by plain
        # Icinga).

        filters = {
            'host': [None],
            'service': [None],
        }

        if self.settings['use_group_filters']:
            filters['host'] = self.settings['group_filters'].get('host_groups', [None])
            filters['service'] = self.settings['group_filters'].get('service_groups', [None])

        results = {
            'hosts': [],
            'services': [],
        }

        for thing in ('host', 'service'):
            for group in filters[thing]:
                params = {}
                if group is not None:
                    group = quote_plus(group)
                    params = f'filter="{group}"%20in%20{thing}.groups'
                    params += f'&{thing}group={group}'

                r = get(
                    self._api(f'objects/{thing}s'),
                    auth=self.settings['auth'],
                    params=params,
                    verify=self.settings['ssl_verify'],
                    timeout=5,
                )
                r.raise_for_status()
                decoded_json = r.json()

                results[f'{thing}s'].extend([IcingaItem(i) for i in decoded_json['results']])

        return results

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
                verify=self.settings['ssl_verify'],
                timeout=5,
            )

    def queue_check(self, items):
        self._queue_check_typed(items, 'Host')
        self._queue_check_typed(items, 'Service')

    def _set_ack_typed(self, items, comment, end_time, item_type):
        items = [i for i in items if i.type == item_type]

        chunk_size = 20
        for c in range(0, len(items), chunk_size):
            filters = []
            for i in items[c:c + chunk_size]:
                filters.append('(' + i.get_filter() + ')')

            data = {
                'author': getuser(),
                'comment': comment,
                'expiry': end_time,
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
                verify=self.settings['ssl_verify'],
                timeout=5,
            )

    def set_ack(self, items, comment, end_time):
        self._set_ack_typed(items, comment, end_time, 'Host')
        self._set_ack_typed(items, comment, end_time, 'Service')

    def set_ack_for_host(self, items, all_items, comment, end_time):
        items_for_action = set()

        for i in all_items['hosts'] + all_items['services']:
            for sel in items:
                if i.host_name == sel.host_name:
                    items_for_action.add(i)

        self._set_ack_typed(items_for_action, comment, end_time, 'Host')
        self._set_ack_typed(items_for_action, comment, end_time, 'Service')

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
                verify=self.settings['ssl_verify'],
                timeout=5,
            )

    def set_downtime(self, items, comment, start_time, end_time):
        self._set_downtime_typed(items, comment, start_time, end_time, 'Host')
        self._set_downtime_typed(items, comment, start_time, end_time, 'Service')

    def set_downtime_for_host(self, items, comment, start_time, end_time):
        host_names = set()
        for i in items:
            host_names.add(i.host_name)

        dummys = set()
        for i in host_names:
            dummys.add(IcingaItem(None, only_host_name=i))

        self.set_downtime(dummys, comment, start_time, end_time)
