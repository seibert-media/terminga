from datetime import datetime

from requests import get, post


class Icinga(object):
    def _api(self, endpoint):
        return self.settings['base_url'] + '/api/v1/' + endpoint

    def get_current_state(self):
        r = get(self._api('objects/hosts'), auth=self.settings['auth'])
        r.raise_for_status()
        hosts = r.json()

        r = get(self._api('objects/services'), auth=self.settings['auth'])
        r.raise_for_status()
        services = r.json()

        return {
            'hosts': hosts,
            'services': services,
        }

    def set_downtime(self, items, seconds):
        start_time = datetime.now().timestamp()
        end_time = start_time + seconds

        # TODO Parallelize.
        for i in items:
            if len(i) == 1:
                self._set_downtime_host(i[0], start_time, end_time)
            elif len(i) == 2:
                self._set_downtime_service(i[0], i[1], start_time, end_time)

    def _set_downtime_host(self, host, start_time, end_time):
        data = {
            'author': 'terminga',  # FIXME
            'comment': 'terminga',  # FIXME
            'start_time': start_time,
            'end_time': end_time,
            'type': 'Host',
            'filter': f'match("{host}", host.name)',
            'child_options': 'DowntimeTriggeredChildren',
        }
        r = post(
            self._api('actions/schedule-downtime'),
            auth=self.settings['auth'],
            headers={'Accept': 'application/json'},
            json=data,
        )

    def _set_downtime_service(self, host, service, start_time, end_time):
        data = {
            'author': 'terminga',  # FIXME
            'comment': 'terminga',  # FIXME
            'start_time': start_time,
            'end_time': end_time,
            'type': 'Service',
            'filter': f'match("{host}", host.name) && match("{service}", service.name)',
        }
        r = post(
            self._api('actions/schedule-downtime'),
            auth=self.settings['auth'],
            headers={'Accept': 'application/json'},
            json=data,
        )
