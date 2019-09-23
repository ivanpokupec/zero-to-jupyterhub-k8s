import os
import subprocess
import time

import pytest
import requests
import yaml

## DEV NOTES:
## A lot of logs are currently in the code for debugging purposes.
##
## ref: https://travis-ci.org/jupyterhub/zero-to-jupyterhub-k8s/jobs/589410196
##

# Makes heavy use of JupyterHub's API:
# http://petstore.swagger.io/?url=https://raw.githubusercontent.com/jupyterhub/jupyterhub/master/docs/rest-api.yml

# load app version of chart
here = os.path.dirname(os.path.abspath(__file__))
chart_yaml = os.path.join(here, os.pardir, 'jupyterhub', 'Chart.yaml')

with open(chart_yaml) as f:
    chart = yaml.safe_load(f)
    jupyterhub_version = chart['appVersion']


def test_api(api_request):
    print("asking for the hub's version")
    r = api_request.get('')
    assert r.status_code == 200
    assert r.json().get("version", "version-missing") == jupyterhub_version

    """kubectl logs deploy/hub - on a successful run
    [I 2019-09-25 12:03:12.051 JupyterHub log:174] 200 GET /hub/api (test@127.0.0.1) 9.57ms
    """


def test_api_info(api_request):
    print("asking for the hub information")
    r = api_request.get('/info')
    assert r.status_code == 200
    result = r.json()
    assert result['spawner']['class'] == 'kubespawner.spawner.KubeSpawner'

    """kubectl logs deploy/hub - on a successful run
    [I 2019-09-25 12:03:12.086 JupyterHub log:174] 200 GET /hub/api/info (test@127.0.0.1) 10.21ms
    """


def test_hub_api_create_user_and_get_information_about_user(api_request, jupyter_user):
    # NOTE: The jupyter user is created and commited to the hub database through
    #       the jupyter_user pytest fixture declared in conftest.py. Due to
    #       this, this first test is actually testing both the fixture to create
    #       the user, and the ability to get information from the hub about the
    #       user.
    #
    #       Also note that the fixture will automatically clean up the
    #       user from the hub's database when the function exit.
    print("create a user, and get information about the user")
    r = api_request.get('/users/' + jupyter_user)
    assert r.status_code == 200
    assert r.json()['name'] == jupyter_user

    """kubectl logs deploy/hub - on a successful run
    [I 2019-09-25 12:03:12.126 JupyterHub log:174] 201 POST /hub/api/users/testuser-7c70eb90-035b-4d9f-92a5-482e441e307d (test@127.0.0.1) 20.74ms
    [I 2019-09-25 12:03:12.153 JupyterHub log:174] 200 GET /hub/api/users/testuser-7c70eb90-035b-4d9f-92a5-482e441e307d (test@127.0.0.1) 11.91ms
    [D 2019-09-25 12:03:12.180 JupyterHub user:240] Creating <class 'kubespawner.spawner.KubeSpawner'> for testuser-7c70eb90-035b-4d9f-92a5-482e441e307d:
    [I 2019-09-25 12:03:12.204 JupyterHub reflector:199] watching for pods with label selector='component=singleuser-server' in namespace jh-ci
    [D 2019-09-25 12:03:12.205 JupyterHub reflector:202] Connecting pods watcher
    [I 2019-09-25 12:03:12.229 JupyterHub reflector:199] watching for events with field selector='involvedObject.kind=Pod' in namespace jh-ci
    [D 2019-09-25 12:03:12.229 JupyterHub reflector:202] Connecting events watcher
    [I 2019-09-25 12:03:12.269 JupyterHub log:174] 204 DELETE /hub/api/users/testuser-7c70eb90-035b-4d9f-92a5-482e441e307d (test@127.0.0.1) 98.85ms
    """


def test_hub_api_list_users(api_request, jupyter_user):
    print("create a test user, get information about all users, and find the test user")
    r = api_request.get('/users')
    assert r.status_code == 200
    assert any(u['name'] == jupyter_user for u in r.json())

    """kubectl logs deploy/hub - on a successful run
    [I 2019-09-25 12:03:12.303 JupyterHub log:174] 201 POST /hub/api/users/testuser-0d2b0fc9-5ac4-4d8c-8d25-c4545665f81f (test@127.0.0.1) 15.53ms
    [I 2019-09-25 12:03:12.331 JupyterHub log:174] 200 GET /hub/api/users (test@127.0.0.1) 10.83ms
    [D 2019-09-25 12:03:12.358 JupyterHub user:240] Creating <class 'kubespawner.spawner.KubeSpawner'> for testuser-0d2b0fc9-5ac4-4d8c-8d25-c4545665f81f:
    [I 2019-09-25 12:03:12.365 JupyterHub log:174] 204 DELETE /hub/api/users/testuser-0d2b0fc9-5ac4-4d8c-8d25-c4545665f81f (test@127.0.0.1) 18.44ms
    """


def test_hub_can_talk_to_proxy(api_request, request_data):
    endtime = time.time() + request_data['test_timeout']
    while time.time() < endtime:
        try:
            r = api_request.get('/proxy')
            if r.status_code == 200:
                break
            print(r.json())
        except requests.RequestException as e:
            print(e)
        time.sleep(1)
    assert r.status_code == 200, 'Failed to get /proxy'

    """kubectl logs deploy/hub - on a successful run
    [I 2019-09-25 12:03:12.395 JupyterHub log:174] 200 GET /hub/api/proxy (test@127.0.0.1) 13.48ms
    """


def test_hub_api_request_user_spawn(api_request, jupyter_user, request_data):
    print("asking kubespawner to spawn a server for a test user")
    r = api_request.post('/users/' + jupyter_user + '/server')
    assert r.status_code in (201, 202)
    try:
        server_model = _wait_for_user_to_spawn(api_request, jupyter_user, request_data['test_timeout'])
        assert server_model
        r = requests.get(request_data['hub_url'].partition('/hub/api')[0] + server_model['url'] + "api")
        assert r.status_code == 200
        assert 'version' in r.json()
    finally:
        _delete_server(api_request, jupyter_user, request_data['test_timeout'])


def test_singleuser_netpol(api_request, jupyter_user, request_data):
    print("asking kubespawner to spawn a server for a test user to test network policies")
    r = api_request.post('/users/' + jupyter_user + '/server')
    assert r.status_code in (201, 202)
    try:
        server_model = _wait_for_user_to_spawn(api_request, jupyter_user, request_data['test_timeout'])
        assert server_model
        print(server_model)
        pod_name = server_model['state']['pod_name']

        # Must match CIDR in dev-config-netpol.yaml
        allowed_url = 'http://jupyter.org'
        blocked_url = 'http://mybinder.org'

        c = subprocess.run([
            'kubectl', '--namespace=jh-ci', 'exec', pod_name, '--',
            'wget', '-q', '-t1', '-T5', allowed_url])
        assert c.returncode == 0, "Unable to get allowed domain"

        c = subprocess.run([
            'kubectl', '--namespace=jh-ci', 'exec', pod_name, '--',
            'wget', '-q', '-t1', '-T5', blocked_url])
        assert c.returncode > 0, "Blocked domain was allowed"

    finally:
        _delete_server(api_request, jupyter_user, request_data['test_timeout'])


def _wait_for_user_to_spawn(api_request, jupyter_user, timeout):
    endtime = time.time() + timeout
    while time.time() < endtime:
        # NOTE: If this fails with a 503 response from the proxy, the hub pod has
        #       probably crashed by the tests interaction with it.
        r = api_request.get('/users/' + jupyter_user)
        r.raise_for_status()
        user_model = r.json()

        # will be pending while starting,
        # server will be set when ready
        if '' not in user_model['servers']:
            # spawn failed!
            raise RuntimeError("Server never started!")

        server_model = user_model['servers']['']
        if server_model['ready']:
            return server_model

        time.sleep(1)
    return False


def _delete_server(api_request, jupyter_user, timeout):
    # NOTE: If this fails with a 503 response from the proxy, the hub pod has
    #       probably crashed by the tests interaction with it.

    r = api_request.delete('/users/' + jupyter_user + '/server')
    assert r.status_code in (202, 204)

    endtime = time.time() + timeout
    while time.time() < endtime:
        r = api_request.get('/users/' + jupyter_user)
        r.raise_for_status()
        user_model = r.json()
        if '' not in user_model['servers']:
            return True
        time.sleep(1)
    return False
