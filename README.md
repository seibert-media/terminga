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

Use a valid API user.

You will want to use [terminga-proxy], if you're still running a version
of Icinga that leaks memory on API requests.

[terminga-proxy]: https://bitbucket.apps.seibert-media.net/projects/SYS/repos/terminga-proxy/browse
