import os
import urllib.request

request = urllib.request.Request("http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/health")
if os.environ.get("API_TOKEN"):
    request.add_header("Authorization", "Bearer " + os.environ["API_TOKEN"])
with urllib.request.urlopen(request, timeout=4) as response:
    assert response.status == 200
