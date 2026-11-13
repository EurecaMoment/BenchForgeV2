"""Transport for authenticated requests to the BenchForge HTTP API."""

import json
from urllib.request import ProxyHandler, Request, build_opener, urlopen


def post_service_json(base_url, route, arguments, *, token, timeout, use_proxy=False):
    """Send a JSON request and leave HTTP errors available to the caller."""
    request = Request(
        base_url.rstrip('/') + route,
        data=json.dumps(arguments).encode('utf-8'),
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token,
        },
    )
    open_url = urlopen if use_proxy else build_opener(ProxyHandler({})).open
    with open_url(request, timeout=timeout) as response:
        return json.load(response)
