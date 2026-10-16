"""Test a built image on an isolated Docker network, including persisted pairing."""

import argparse
import json
import subprocess
import uuid

PROBE = r"""
import http.cookiejar
import json
import urllib.request
from pathlib import Path
from server import daily_reading, learning_audio, source_audio
from server.content import load_curriculum
from scripts.asr_model import validate_model
from server.reading_recognition import MODEL_PATH

base = "http://127.0.0.1:8000"
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def request(path, body=None, headers=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
        headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    with client.open(req, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if response.headers.get_content_type() == "application/json" else raw

assert b'<html' in request('/').lower()
request('/api/v1/health')
if Path('/data/docker-smoke.json').exists():
    saved = json.loads(Path('/data/docker-smoke.json').read_text())
    result = request('/api/v1/bootstrap', headers={"Cookie": saved['cookie']})
    assert result['paired'] and result['profile']['id'] == saved['profile']
    assert result['profile']['selectedLessonId'] == saved['lesson']
    progress = request('/api/v1/profiles/progress', headers={'Cookie': saved['cookie']})
    assert len(progress['attempts']) == 1
    print('Container recreation: pairing, selected lesson and learning attempt persisted')
else:
    for target in load_curriculum()['audioRequirements']:
        if target['kind'] != 'instruction':
            assert request('/api/v1/guest/audio/' + target['id'])
    for key in learning_audio.expected_assets():
        assert request('/api/v1/guest/voice/' + key)
    for asset in daily_reading.load()['assets']:
        assert request('/api/v1/guest/daily-audio/' + asset['id'])
    validate_model(MODEL_PATH)
    from pywhispercpp.model import Model
    Model(str(MODEL_PATH), context_params={"use_gpu": False},
        print_progress=False, print_realtime=False)
    code = request('/api/v1/local/pairing-code', {})['code']
    request('/api/v1/pair', {'code': code, 'label': 'Docker smoke'})
    profile = request('/api/v1/bootstrap')['profile']
    csrf = next(c.value for c in jar if c.name == 'lp_csrf')
    lesson = load_curriculum()['lessons'][-1]['id']
    request('/api/v1/household/current-lesson',
        {'lessonId': lesson, 'expectedRevision': profile['revision']},
        {'X-LP-CSRF': csrf}, 'PUT')
    session = request('/api/v1/sessions', {}, {'X-LP-CSRF': csrf})
    task = session['tasks'][0]
    request('/api/v1/instances/' + task['instanceId'] + '/answer',
        {'requestId': 'docker-smoke-answer-0001',
         'answerOptionId': task['exercise']['options'][0]['id']}, {'X-LP-CSRF': csrf})
    Path('/data/docker-smoke.json').write_text(json.dumps({
        'cookie': '; '.join(c.name + '=' + c.value for c in jar),
        'profile': profile['id'], 'lesson': lesson,
    }))
    result = request('/api/v1/guest/operate', {'path': '/sessions', 'method': 'POST',
        'body': {'lessonId': load_curriculum()['lessons'][0]['id']}})
    assert len(result['result']['tasks']) == 6
    print('Offline: webpage, all audio, Whisper initialization, pairing and guest session passed')
"""


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="love-pinyin:local")
    args = parser.parse_args()
    name = "lp-smoke-" + uuid.uuid4().hex[:10]
    network, volume = name + "-net", name + "-data"
    try:
        docker("network", "create", "--internal", network)
        docker("volume", "create", volume)
        for _ in range(2):
            docker(
                "run",
                "-d",
                "--name",
                name,
                "--network",
                network,
                "--mount",
                f"type=volume,src={volume},dst=/data",
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                args.image,
            )
            docker(
                "exec",
                name,
                "python",
                "-c",
                """
import time, urllib.request
for attempt in range(60):
    try:
        urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=1)
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('API did not become healthy')
""",
            )
            docker("exec", name, "python", "-m", "scripts.check_bundled_resources")
            docker("exec", name, "python", "-m", "scripts.validate_audio_resources")
            docker("exec", name, "python", "-m", "scripts.validate_daily_reading", "--release")
            docker("exec", "-i", name, "python", "-", input=PROBE, text=True)
            docker("stop", "--time", "60", name)
            docker("rm", name)
        print(json.dumps({"image": args.image, "offlineSmoke": "passed"}))
    finally:
        # These randomly named resources belong only to this smoke test.
        for command in [("rm", "-f", name), ("volume", "rm", volume), ("network", "rm", network)]:
            subprocess.run(["docker", *command], capture_output=True, check=False)


if __name__ == "__main__":
    main()
