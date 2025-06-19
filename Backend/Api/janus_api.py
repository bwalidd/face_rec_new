
from Backend.celery_prefork import app as prefork_worker
@prefork_worker.task
def main_api(stream_id, webrtc_stream_id, local_stream_url):
    import requests
    import json
    import os
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Backend.settings')
    django.setup()
    # Janus server URL
    IP = "34.60.157.241"
    JANUS_URL = f'http://{IP}:8088/janus'

    def create_session():
        create_payload = {
            "janus": "create",
            "transaction": "unique_transaction_id_11"
        }
        try:
            session_response = requests.post(JANUS_URL, json=create_payload)
            session_response.raise_for_status()
            session_id = session_response.json()['data']['id']
            return session_id
        except requests.exceptions.RequestException as e:
            print(f"Failed to create session: {e}")
            if 'session_response' in locals():
                print(f"Response content: {session_response.content}")
            return None

    def attach_plugin(session_id):
        attach_payload = {
            "janus": "attach",
            "plugin": "janus.plugin.streaming",
            "transaction": "unique_transaction_id_12"
        }
        try:
            attach_response = requests.post(f"{JANUS_URL}/{session_id}", json=attach_payload)
            attach_response.raise_for_status()
            handle_id = attach_response.json()['data']['id']
            return handle_id
        except requests.exceptions.RequestException as e:
            print(f"Failed to attach to plugin: {e}")
            if 'attach_response' in locals():
                print(f"Response content: {attach_response.content}")
            return None
    from urllib.parse import quote, urlparse, urlunparse

    def encode_rtsp_url(url):
        try:
            # Parse URL into components
            parsed = urlparse(url)
            
            # Split userinfo (if exists)
            if '@' in parsed.netloc:
                userinfo, hostname = parsed.netloc.rsplit('@', 1)
                username, password = userinfo.split(':', 1)
                
                # Encode username and password separately
                encoded_username = quote(username, safe='')
                encoded_password = quote(password, safe='')
                
                # Reconstruct netloc with encoded credentials
                new_netloc = f"{encoded_username}:{encoded_password}@{hostname}"
                
                # Reconstruct URL with encoded parts
                encoded_url = urlunparse((
                    parsed.scheme,
                    new_netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
                print(f"Encoded URL: {encoded_url}")
                return encoded_url
            return url
        except Exception as e:
            print(f"Error encoding RTSP URL: {e}")
            return url
    def add_stream(session_id, handle_id, stream_id, stream_url):
        
        new_url = encode_rtsp_url(stream_url)
        add_stream_payload = {
        "janus": "message",
        "body": {
                "request": "create",
                "type": "rtsp",
                "id": stream_id,
                "description": "RTSP Stream",
                "url": stream_url,
                # Use standard ports for better firewall traversal
                "videoport": 8004,
                "videopt": 96,  # Standard payload type for H.264
                
                # Disable audio to reduce complexity
                "audio": False,
                "video": True,
                
                # H.264 configuration for maximum compatibility
                "videocodec": "h264",
                "videofmtp": (
                    "profile-level-id=42e01f;"  # Baseline profile, level 3.1
                    "packetization-mode=1;"     # Single NAL unit mode
                    "level-asymmetry-allowed=1" # Allow different levels for sender/receiver
                ),
                "videortpmap": "H264/90000",    # Standard clock rate
                
                # Streaming optimization parameters
                "min_delay": 0,                 # Minimize initial delay
                "max_delay": 500,              # Maximum buffering (ms)
                "buffer_size": 2048,           # Reasonable buffer size
                
                # Additional options for better compatibility
                "rtp_profile": "RTP/SAVPF",    # Required for WebRTC
            },
            "transaction": f"stream_{stream_id}"
        }
        try:
            add_stream_response = requests.post(f"{JANUS_URL}/{session_id}/{handle_id}", json=add_stream_payload)
            add_stream_response.raise_for_status()
            
            return add_stream_response.json()
        except requests.exceptions.RequestException as e:
            print(f"Failed to add stream: {e}")
            async_to_sync(channel_layer.group_send)(
                "stat",
                {
                    "type": "ready_state",
                    "message": "Can't start stream"
                }
            )
            if 'add_stream_response' in locals():
                print(f"Response content: {add_stream_response.content}")
            return None

    session_id = create_session()
    if not session_id:
        return
    
    handle_id = attach_plugin(session_id)
    if not handle_id:
        return
    stream_url = f'rtsp://{IP}:8554/live/{stream_id}'
    new_url = stream_url
    try:
        MEDIAMTX_API_URL = f"http://admin:admin@normal_stream:9997/v3/config/paths/add/live/{stream_id}" 
        body = {         
            "name": f"test",
            "source": f"{encode_rtsp_url(local_stream_url)}",
            "sourceOnDemand": True,
            # "readUser": "admin",
            # "readPass": "admin"
        }
        mediamtx_response = requests.post(MEDIAMTX_API_URL, json=body)
        print(mediamtx_response)
       
        # print(f"----------------MediaMTX response: {mediamtx_response}")
        new_url = f'rtsp://{IP}:8556/live/{stream_id}'
    except Exception as e:
        print(f"------------ Error adding stream to MediaMTX: {e}")
    add_stream_response = add_stream(session_id, handle_id, stream_id, stream_url)
    
    print(json.dumps(add_stream_response, indent=2))
   
    add_stream_response = add_stream(session_id, handle_id,webrtc_stream_id,new_url)
    
    channel_layer = get_channel_layer('status')
    async_to_sync(channel_layer.group_send)(
        "stat",
        {
            "type": "ready_state",
            "message": "Stream is ready"
        }
    )
    print(json.dumps(add_stream_response, indent=2))


def main_api_delete(stream_id):
    import requests
    import json
    import os
    # Janus server URL
    IP = "34.60.157.241"
    JANUS_URL = f'http://{IP}:8088/janus'

    def create_session():
        create_payload = {
            "janus": "create",
            "transaction": "unique_transaction_id_11"
        }
        try:
            session_response = requests.post(JANUS_URL, json=create_payload)
            session_response.raise_for_status()
            session_id = session_response.json()['data']['id']
            return session_id
        except requests.exceptions.RequestException as e:
            print(f"Failed to create session: {e}")
            if 'session_response' in locals():
                print(f"Response content: {session_response.content}")
            return None

    def attach_plugin(session_id):
        attach_payload = {
            "janus": "attach",
            "plugin": "janus.plugin.streaming",
            "transaction": "unique_transaction_id_12"
        }
        try:
            attach_response = requests.post(f"{JANUS_URL}/{session_id}", json=attach_payload)
            attach_response.raise_for_status()
            handle_id = attach_response.json()['data']['id']
            return handle_id
        except requests.exceptions.RequestException as e:
            print(f"Failed to attach to plugin: {e}")
            if 'attach_response' in locals():
                print(f"Response content: {attach_response.content}")
            return None

    def delete_stream(session_id, handle_id, stream_id):

        delete_stream_payload = {
            "janus": "message",
            "body": {
                "request": "destroy",
                "id": stream_id,
            },
            "transaction": "unique_transaction_id_13"
        }
        try:
            delete_stream_response = requests.post(f"{JANUS_URL}/{session_id}/{handle_id}", json=delete_stream_payload)
            delete_stream_response.raise_for_status()
            return delete_stream_response.json()
        except requests.exceptions.RequestException as e:
            print(f"Failed to add stream: {e}")
            if 'add_stream_response' in locals():
                print(f"Response content: {add_stream_response.content}")
            return None

    session_id = create_session()
    if not session_id:
        return
    
    handle_id = attach_plugin(session_id)
    if not handle_id:
        return
    
    delete_stream_response = delete_stream(session_id, handle_id,stream_id)
    if not delete_stream_response:
        return
    
    print(json.dumps(delete_stream_response, indent=2))


