terminga
========

TUI for Icinga.


Dependencies
------------

-   Python 3.7
-   python-requests


Configuration
-------------

Create `~/.terminga`:

    https://icinga-terminga-proxy.smedia.tools
    myapiuser
    myapiuserspassword
    /home/foo/bin/terminga-handler

Use a valid API user.

You will want to use [terminga-proxy], if you're still running a version
of Icinga that leaks memory on API requests.

[terminga-proxy]: https://bitbucket.apps.seibert-media.net/projects/SYS/repos/terminga-proxy/browse

The last line contains a path to a user-supplied script and this line is
*optional*. This script will be invoked with `-h $host -s $service` when
you press `t` in terminga.
