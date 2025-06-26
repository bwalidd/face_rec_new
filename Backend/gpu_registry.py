import os
import time
import redis
import socket
import json

REDIS_URL = os.getenv('REDIS_URL', 'redis://:admin@redis-primary-service:6379/0')
REGISTRY_KEY = 'gpu_registry'
HEARTBEAT_INTERVAL = 10  # seconds
STALE_THRESHOLD = 30    # seconds

r = redis.Redis.from_url(REDIS_URL)


def get_pod_id():
    return os.getenv('HOSTNAME', socket.gethostname())

def get_node_name():
    return os.getenv('NODE_NAME', 'unknown-node')

def get_service_name():
    # Try to get from env, else infer from GPU_SERVICE_NAME or GPU_GROUP or fallback to pod_id
    # Recommend setting BACKEND_SERVICE_NAME in deployment
    svc = os.getenv('BACKEND_SERVICE_NAME')
    if svc:
        return svc
    # Fallback: try to infer from pod_id or group
    group = os.getenv('GPU_GROUP')
    if group:
        return f'django-backend-gpu-{group}-service'
    # Fallback: use pod_id (not recommended)
    return f'django-backend-gpu-{get_pod_id()}-service'

def register_pod_gpus(gpu_ids):
    pod_id = get_pod_id()
    node = get_node_name()
    service = get_service_name()
    now = int(time.time())
    gpus = [
        {'id': gpu_id, 'status': 'idle', 'last_heartbeat': now}
        for gpu_id in gpu_ids
    ]
    pod_info = {
        'node': node,
        'service': service,
        'gpus': gpus,
        'last_heartbeat': now
    }
    r.hset(REGISTRY_KEY, pod_id, json.dumps(pod_info))


def update_gpu_status(gpu_id, status):
    pod_id = get_pod_id()
    now = int(time.time())
    pod_info = r.hget(REGISTRY_KEY, pod_id)
    if not pod_info:
        return
    pod_info = json.loads(pod_info)
    for gpu in pod_info['gpus']:
        if gpu['id'] == gpu_id:
            gpu['status'] = status
            gpu['last_heartbeat'] = now
    pod_info['last_heartbeat'] = now
    r.hset(REGISTRY_KEY, pod_id, json.dumps(pod_info))


def heartbeat():
    pod_id = get_pod_id()
    now = int(time.time())
    pod_info = r.hget(REGISTRY_KEY, pod_id)
    if not pod_info:
        return
    pod_info = json.loads(pod_info)
    pod_info['last_heartbeat'] = now
    for gpu in pod_info['gpus']:
        gpu['last_heartbeat'] = now
    r.hset(REGISTRY_KEY, pod_id, json.dumps(pod_info))


def get_all_gpus():
    all_pods = r.hgetall(REGISTRY_KEY)
    result = []
    for pod_id, pod_info in all_pods.items():
        pod_info = json.loads(pod_info)
        service = pod_info.get('service', None)
        for gpu in pod_info['gpus']:
            result.append({
                'pod': pod_id.decode() if isinstance(pod_id, bytes) else pod_id,
                'node': pod_info['node'],
                'gpu_id': gpu['id'],
                'status': gpu['status'],
                'last_heartbeat': gpu['last_heartbeat'],
                'service': service
            })
    return result


def cleanup_stale_entries():
    now = int(time.time())
    all_pods = r.hgetall(REGISTRY_KEY)
    for pod_id, pod_info in all_pods.items():
        pod_info = json.loads(pod_info)
        if now - pod_info.get('last_heartbeat', 0) > STALE_THRESHOLD:
            r.hdel(REGISTRY_KEY, pod_id)


def find_and_mark_idle_gpu():
    """Find the first idle GPU and mark it as busy. Returns (pod_id, gpu_id) or (None, None) if none available."""
    all_pods = r.hgetall(REGISTRY_KEY)
    now = int(time.time())
    for pod_id, pod_info in all_pods.items():
        pod_info = json.loads(pod_info)
        for gpu in pod_info['gpus']:
            if gpu['status'] == 'idle' and now - gpu['last_heartbeat'] < STALE_THRESHOLD:
                gpu['status'] = 'busy'
                gpu['last_heartbeat'] = now
                pod_info['last_heartbeat'] = now
                r.hset(REGISTRY_KEY, pod_id, json.dumps(pod_info))
                return (pod_id.decode() if isinstance(pod_id, bytes) else pod_id, gpu['id'])
    return (None, None)


def mark_gpu_idle(pod_id, gpu_id):
    pod_info = r.hget(REGISTRY_KEY, pod_id)
    if not pod_info:
        return
    pod_info = json.loads(pod_info)
    for gpu in pod_info['gpus']:
        if gpu['id'] == gpu_id:
            gpu['status'] = 'idle'
            gpu['last_heartbeat'] = int(time.time())
    pod_info['last_heartbeat'] = int(time.time())
    r.hset(REGISTRY_KEY, pod_id, json.dumps(pod_info)) 





# {
#   "gpus": [
#     {
#       "pod": "pod-0-uuid",
#       "node": "worker-node-1",
#       "gpu_id": 0,
#       "status": "idle",
#       "last_heartbeat": 1710000000,
#       "service": "django-backend-gpu0-service"
#     },
#     {
#       "pod": "pod-0-uuid",
#       "node": "worker-node-1",
#       "gpu_id": 1,
#       "status": "busy",
#       "last_heartbeat": 1710000001,
#       "service": "django-backend-gpu0-service"
#     },
#     {
#       "pod": "pod-0-uuid",
#       "node": "worker-node-1",
#       "gpu_id": 2,
#       "status": "idle",
#       "last_heartbeat": 1710000002,
#       "service": "django-backend-gpu0-service"
#     },
#     {
#       "pod": "pod-1-uuid",
#       "node": "worker-node-2",
#       "gpu_id": 3,
#       "status": "idle",
#       "last_heartbeat": 1710000003,
#       "service": "django-backend-gpu1-service"
#     },
#     {
#       "pod": "pod-1-uuid",
#       "node": "worker-node-2",
#       "gpu_id": 4,
#       "status": "idle",
#       "last_heartbeat": 1710000004,
#       "service": "django-backend-gpu1-service"
#     },
#     {
#       "pod": "pod-1-uuid",
#       "node": "worker-node-2",
#       "gpu_id": 5,
#       "status": "busy",
#       "last_heartbeat": 1710000005,
#       "service": "django-backend-gpu1-service"
#     },
#     {
#       "pod": "pod-2-uuid",
#       "node": "worker-node-3",
#       "gpu_id": 6,
#       "status": "idle",
#       "last_heartbeat": 1710000006,
#       "service": "django-backend-gpu2-service"
#     }
#     // ... and so on for GPUs 7, 8, 9
#   ]
# }