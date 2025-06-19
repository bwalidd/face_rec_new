import cv2
import numpy as np
import os, sys
from os import listdir
from PIL import Image
from progress.bar import Bar
import threading
from os import path
import pickle
from datetime import datetime
import shutil
import os
import json
from .helpers import send_stream_status
from Backend.celery import app as solo_worker
from Backend.celery_prefork import app as prefork_worker
import time
os.environ["CUDA_VISIBLE_DEVICES"] = "1"  

# @prefork_worker.task
# def write_frame_to_ffmpeg(frame_bytes, ffmpeg_pid):
#     import os
    
#     try:
#         # Open file descriptor for the existing FFmpeg process
#         fd = os.open(f"/proc/{ffmpeg_pid}/fd/0", os.O_WRONLY)
#         os.write(fd, frame_bytes)
#         os.close(fd)
#     except Exception as e:
#         print(f"Error writing to FFmpeg process: {e}")

os.environ["CUDA_VISIBLE_DEVICES"] = "1"  
import os
import tempfile
import uuid
from pathlib import Path
from django.core.files import File
from django.utils import timezone
from datetime import timedelta
import cv2

import face_recognition
import numpy as np
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.files.base import ContentFile



@prefork_worker.task
def insertion_database_task_unknown(random_filename, best_match_index, face_distances, known_face_names, 
                                    place_id, name, image_file_path, original_frame_path, current_time, 
                                    last_minute, array_of_names):
    from Api.models import Detections, Person
    from Api.serializers import DetectionsSerializer
    from django.core.files.base import ContentFile
    import base64

    import time
    
    start_time = time.time()
    try:
        checker = Detections.filter_by_person_name_and_time_array(
            array_of_names, last_minute, current_time, place_id
        ).exists()
        
        if not checker:
            # Create Django File objects from temp files
            with open(image_file_path, 'rb') as img_file, \
                 open(original_frame_path, 'rb') as orig_file:
                img_data = img_file.read()
                orig_data = orig_file.read()
                detection_data = {
                    'name': random_filename,
                    'video_source': place_id,
                    'detection_frame': ContentFile(orig_data, name=random_filename),
                    'detection_frame_with_box': ContentFile(img_data, name=random_filename)
                }
                
                serializer = DetectionsSerializer(data=detection_data)
                if serializer.is_valid():
                    serializer.save()
        else:
            return
        
        detection_instance = Detections.objects.get(name=random_filename)
        for best_match_idx in best_match_index:
            matched_name = known_face_names[best_match_idx]
            try:
                person = Person.objects.get(name=matched_name)
                detection_instance.add_person(person, face_distances[best_match_idx])
            except Person.DoesNotExist:
                print(f"Person {matched_name} not found.")
            except Exception as e:
                print("Error adding person to detection:", e)

        detection_instance_serializer = DetectionsSerializer(detection_instance)
        saved_detection_instance = detection_instance_serializer.data
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "notifications",
            {
                "type": "send_notification",
                "message": saved_detection_instance
            }
        )
    except Exception as e:
        print("e : ", e)
    finally:
        # Clean up temporary files
        try:
            os.remove(image_file_path)
            os.remove(original_frame_path)
        except Exception as e:
            print(f"Error removing temporary files: {e}")
    
    end_time = time.time()
    iteration_time_ms = (end_time - start_time) * 1000
    print(f"iteration task inside unknown {iteration_time_ms} ms")

@prefork_worker.task
def insertion_database_task_known_high(random_filename, best_match_index, face_distances, known_face_names, 
                                       place_id, name, image_file_path, original_frame_path, current_time, 
                                       last_minute):
    from Api.models import Detections, Person
    from Api.serializers import DetectionsSerializer
    import time
    from django.core.files.base import ContentFile
    import base64
    start_time = time.time()
    try:
        conf_range = "known" if face_distances[best_match_index[0]] <= 0.4 else "high"
        
        checker = Detections.filter_by_person_name_and_time(
            name, last_minute, current_time, place_id, conf_range
        ).exists()
        
        if checker:
            return
        
        # Create Django File objects from temp files
        with open(image_file_path, 'rb') as img_file, \
             open(original_frame_path, 'rb') as orig_file:
            img_data = img_file.read()
            orig_data = orig_file.read()
            detection_data = {
                'name': random_filename,
                'video_source': place_id,
                'detection_frame': ContentFile(orig_data, name=random_filename),
                'detection_frame_with_box': ContentFile(img_data, name=random_filename)
            }
            
            serializer = DetectionsSerializer(data=detection_data)
            if serializer.is_valid():
                serializer.save()
                detection_instance = Detections.objects.get(name=random_filename)
                
                for best_match_idx in best_match_index:
                    if face_distances[best_match_idx] >= 0.50:
                        break
                    matched_name = known_face_names[best_match_idx]
                    try:
                        person = Person.objects.get(name=matched_name)
                        detection_instance.add_person(person, face_distances[best_match_idx])
                    except Person.DoesNotExist:
                        print(f"Person {matched_name} not found.")
                    except Exception as e:
                        print("Error adding person to detection:", e)

                detection_instance_serializer = DetectionsSerializer(detection_instance)
                saved_detection_instance = detection_instance_serializer.data
                
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "notifications",
                    {
                        "type": "send_notification",
                        "message": saved_detection_instance
                    }
                )
    except Exception as e:
        print("Error processing detection:", e)
    finally:
        # Clean up temporary files
        try:
            os.remove(image_file_path)
            os.remove(original_frame_path)
        except Exception as e:
            print(f"Error removing temporary files: {e}")
    
    end_time = time.time()
    iteration_time_ms = (end_time - start_time) * 1000
    # print(f"iteration task inside known {iteration_time_ms} ms")

def face_recognition_worker(frame, place_id, known_face_names, known_face_encodings, cudadevice):
    import os
    def save_frame_to_temp(frame_data, suffix='.jpg'):
        """Helper function to save frame data to a temporary file"""
        try:
            # Use tempfile.NamedTemporaryFile instead of manual file creation
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_path = temp_file.name
            
            if isinstance(frame_data, (bytes, ContentFile)):
                if isinstance(frame_data, ContentFile):
                    temp_file.write(frame_data.read())
                else:
                    temp_file.write(frame_data)
            else:
                temp_file.close()
                cv2.imwrite(temp_path, frame_data)
                
            return temp_path
        except Exception as e:
            print(f"Error saving temporary file: {e}")
            if 'temp_file' in locals():
                temp_file.close()
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise
    os.environ["CUDA_VISIBLE_DEVICES"] = str(cudadevice)
    
    current_time = timezone.now()
    last_minute = current_time - timedelta(seconds=30)

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=0, model="cnn")
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
    
    face_names = []
    save_frame = frame
    random_filename = f"{uuid.uuid4()}.jpg"
    
    # Save original frame to temp file
    original_frame_path = save_frame_to_temp(save_frame)
    returned_color = (0, 0, 255)
    for face_encoding in face_encodings:
        matches = face_recognition.compare_faces(known_face_encodings, face_encoding, 1)
        face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_match_index = np.argsort(face_distances)[:6]

        if face_distances[best_match_index[0]] <= 0.45:
            returned_color = (255, 0, 0)
            name = known_face_names[best_match_index[0]]
            face_names.append(name)
            
            # Draw rectangles and text
            for (top, right, bottom, left), name in zip(face_locations, face_names):
                cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
                cv2.rectangle(frame, (left, top - 35), (right, top), (255, 0, 0), cv2.FILLED)
                cv2.putText(frame, name, (left + 6, top - 6), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 1)
            
            # Save processed frame to temp file
            processed_frame_path = save_frame_to_temp(frame)
            
            start_time = time.time()
            insertion_database_task_known_high.apply_async(
                args=[
                    random_filename,
                    best_match_index.tolist(),
                    face_distances.tolist(),
                    list(known_face_names),
                    place_id,
                    name,
                    processed_frame_path,
                    original_frame_path,
                    current_time,
                    last_minute
                ],
                queue='prefork_queue'
            )
            
            end_time = time.time()
            # print(f"iteration task high {(end_time - start_time) * 1000} ms")
        else:
            face_names = ["unknown"]
            for (top, right, bottom, left), name in zip(face_locations, face_names):
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
                cv2.rectangle(frame, (left, top - 35), (right, top), (0, 0, 255), cv2.FILLED)
                cv2.putText(frame, name, (left + 6, top - 6), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 1)
                break
            
            # Save processed frame to temp file
            # original_frame_path = save_frame_to_temp(save_frame)
            processed_frame_path = save_frame_to_temp(frame)
            array_of_names = [known_face_names[idx] for idx in best_match_index]
            
            try:
                start_time = time.time()
                insertion_database_task_unknown.apply_async(
                    args=[
                        random_filename,
                        best_match_index.tolist(),
                        face_distances.tolist(),
                        list(known_face_names),
                        place_id,
                        name,
                        processed_frame_path,
                        original_frame_path,
                        current_time,
                        last_minute,
                        array_of_names,
                    ],
                    queue='prefork_queue'
                )
                end_time = time.time()
                # print(f"iteration task unknown {(end_time - start_time) * 1000} ms")
            except Exception as e:
                print("Error in checking existing detections:", e)

    return frame, face_locations, face_names, returned_color
def kill_ffmpeg_process(process):
    import psutil
    try:
        if process is None:
            return True
            
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        
        # First try graceful termination
        process.terminate()
        
        try:
            process.wait(timeout=3)
            print("FFmpeg process terminated gracefully")
            return True
        except:
            print("Graceful termination failed, forcing kill")
            
        # Force kill children and parent
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        
        if parent.is_running():
            parent.kill()
            
        return True
        
    except (psutil.NoSuchProcess, ProcessLookupError) as e:
        print(f"Process already terminated: {e}")
        return True
    except Exception as e:
        print(f"Error killing FFmpeg process: {e}")
        return False

def start_ffmpeg_process(width, height, stream_url):
    import subprocess
    ffmpeg_command = [
        'ffmpeg',
        # Global options
        '-y',                           # Overwrite output without asking
        '-hwaccel', 'cuda',            # Enable CUDA hardware acceleration
     
        
        # Input options
        '-f', 'rawvideo',              # Force input format to raw video
        '-vcodec', 'rawvideo',         # Input video codec
        '-s', f'{width}x{height}',     # Input frame size
        '-pix_fmt', 'bgr24',           # Input pixel format
        '-framerate', '30',            # Input framerate
        '-i', '-',                     # Read from pipe
        
        # Video encoding options
        '-c:v', 'h264_nvenc',          # Use NVIDIA H.264 encoder
        '-preset', 'p1',               # Lowest latency preset
        '-tune', 'ull',                # Ultra-low latency tuning
        '-profile:v', 'baseline',      # Maximum compatibility profile
        '-level', '4.1',               # Widely supported H.264 level
        
        # Performance optimization
        '-rc', 'cbr',                  # Constant bitrate mode for stable streaming
        '-zerolatency', '1',           # Enable zero-latency operation
        '-delay', '0',                 # Minimize encoding delay
        '-g', '30',                    # GOP size = framerate for 1-second GOPs
        '-sc_threshold', '0',          # Disable scene change detection
        
        # Quality and bitrate settings
        '-b:v', '4M',                  # Target bitrate (4 Mbps)
        '-maxrate', '4M',              # Maximum bitrate
        '-bufsize', '8M',              # Buffer size (2x bitrate)
        '-qmin', '17',                 # Minimum quantizer
        '-qmax', '28',                 # Maximum quantizer
        
        # Format conversion
        '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p',
        
        # RTSP output settings
        '-f', 'rtsp',                  # Output format
        '-rtsp_transport', 'tcp',      # Use TCP for more reliable streaming
        '-rtsp_flags', 'prefer_tcp+listen',  # Prefer TCP and enable server mode
        '-fflags', '+nobuffer',        # Reduce buffering
        '-flags', 'low_delay',         # Enable low delay flags
        '-avioflags', 'direct',        # Minimize IO operations
        
        # Maximum compatibility options
        '-strict', 'experimental',     # Allow experimental features
        '-max_muxing_queue_size', '1024',  # Prevent muxing queue overflow
        
        stream_url                     # Output URL
    ]
    
    # Start process with pipe configuration
    process = subprocess.Popen(
        ffmpeg_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=10**8  # Increase buffer size
    )
    
    return process

@solo_worker.task
def mainloop(rtsp_url, title, place_id, cudadevice, webrtc_stream_id, local_stream_url):
    import torch
    import os
    import dlib
    import subprocess
    import psutil
    import cv2
    def extract_column(data_list, key_to_extract):
        return [item[key_to_extract] for item in data_list if key_to_extract in item]
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Backend.settings')
    django.setup()
    from Api.serializers import ImageProcSerializer , PersonSerializer
    from Api.models import Person , Detections , ImageProc
    import numpy as np
    import redis
    # from rq import Queue
    # from rq.worker import Worker
    from datetime import datetime, timedelta
    from .janus_api import main_api 
    from redis import Redis
    import redis
    import face_recognition
    os.environ["CUDA_VISIBLE_DEVICES"] = str(cudadevice)
    print("CUDA available:", torch.cuda.is_available())
    print("CUDA version:", torch.version.cuda)
    print("PyTorch version:", torch.__version__)
    print(f"Current CUDA device: {torch.cuda.current_device()}") 
    print(torch.cuda.device_count())
    print("---------------")
    def handle_ffmpeg_process(frame, ffmpeg_process, width, height, stream_url):
        try:
            if ffmpeg_process.poll() is not None:
                # Process has terminated, check error output
                _, stderr = ffmpeg_process.communicate(timeout=1)
                print(f"FFmpeg process terminated with error: {stderr.decode() if stderr else 'No error message'}")
                
                # Restart the process
                ffmpeg_process = start_ffmpeg_process(width, height, stream_url)
                time.sleep(0.5)  # Short delay before resuming
                
            # Ensure frame is contiguous and properly formatted
            frame_bytes = np.ascontiguousarray(frame).tobytes()
            ffmpeg_process.stdin.write(frame_bytes)
            ffmpeg_process.stdin.flush()  # Ensure data is written
                
        except BrokenPipeError:
            print("FFmpeg pipe broken, restarting process...")
            kill_ffmpeg_process(ffmpeg_process)
            time.sleep(1)
            return start_ffmpeg_process(width, height, stream_url)
            
        except subprocess.TimeoutExpired:
            print("FFmpeg process timeout, restarting...")
            kill_ffmpeg_process(ffmpeg_process)
            time.sleep(1)
            return start_ffmpeg_process(width, height, stream_url)
            
        except Exception as e:
            print(f"Unexpected error in FFmpeg handling: {e}")
            kill_ffmpeg_process(ffmpeg_process)
            time.sleep(1)
            return start_ffmpeg_process(width, height, stream_url)
            
        return ffmpeg_process
    def initialize_stream(url, max_retries=10):
        """Initialize video capture with retries"""
        for attempt in range(max_retries):
            try:
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        return cap, frame
            except Exception as e:
                print(f"Stream initialization attempt {attempt + 1} failed: {e}")
            
            print(f"Retrying stream initialization in 5 seconds... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(5)
        return None, None

    # Initialize face recognition
    
    persons = Person.objects.all()
    serializer = PersonSerializer(persons, many=True, context={'include_encoding': True})

    known_face_names = extract_column(serializer.data, 'name')
    known_face_encodings = []
    
    send_stream_status("Start Loading faces database")
    for entry in serializer.data:
        images = entry['images']
        for image in images:
            encoding = image.get('encoding')
            if encoding:
                if isinstance(encoding, str):
                    array_encodings = [float(x) for x in encoding.split(',')]
                else:
                    array_encodings = encoding
                known_face_encodings.append(array_encodings)
                
    known_face_encodings_np = np.array(known_face_encodings)
    if len(serializer.data) <= 0:
        send_stream_status("Can't start stream because no faces are found")
        return
    
    send_stream_status("Trying Start Stream")
    try:
            # Connect to Redis
        redis_client = redis.from_url('redis://default:admin@redis:6379/0')
        
        redis_client.select(0)  # Queue database
        redis_client.flushdb()
        import channels.layers
        channels.layers._channel_layers = {}  # Clear channel layer cache
        channel_layer = get_channel_layer()
        
        # Wait a moment for connections to reestablish
        import time
        time.sleep(1)
        
        print("Redis cache successfully flushed")
    except redis.RedisError as e:
        send_stream_status("Can't start stream")
        print(f"Error setting up Redis queue: {e}")
        exit(1)
    try:
        main_api.apply_async(countdown=15,args=[place_id,webrtc_stream_id,local_stream_url],queue='prefork_queue')
    except Exception as e:
        send_stream_status("Can't start stream")
        print(f"Error setting up Redis queue: {e}")
        exit(1)
        
    # Main processing loop with reconnection logic
    while True:
        try:
            # Initialize video capture with retry mechanism
            print("Initializing video capture...")
            video_capture, frame = initialize_stream(rtsp_url)
            if video_capture is None or frame is None:
                print("Failed to initialize stream, retrying in 10 seconds...")
                time.sleep(10)
                continue

            height, width, _ = frame.shape
            stream_url = f'rtsp://{os.environ.get("STREAM_IP")}:8554/live/{place_id}'
            ffmpeg_process = start_ffmpeg_process(width, height, stream_url)
            # ffmpeg_process.stdin.write(frame.tobytes())
            

            ffmpeg_restart_delay = 5
            face_locations = []
            face_names = []
            color = (0, 0, 255)
            frame_skip = 5
            frame_count = 0
            consecutive_failures = 0
            max_consecutive_failures = 5

            # Frame processing loop
            while True:
                # start_time = time.time()

                try:
                    # start_time = time.time()

                    ret, frame = video_capture.read()
                    if not ret:
                        consecutive_failures += 1
                        print(f"Failed to grab frame (attempt {consecutive_failures}/{max_consecutive_failures})")
                        
                        if consecutive_failures >= max_consecutive_failures:
                            print("Too many consecutive failures, reinitializing stream...")
                            break
                        
                        # Quick retry
                        video_capture.release()
                        time.sleep(0.1)
                        video_capture = cv2.VideoCapture(rtsp_url)
                        continue

                    # Reset failure counter on successful frame grab
                    consecutive_failures = 0

                    frame_count += 1
                    if frame_count >= frame_skip:
                        frame_count = 0
                        newframe, face_locations, face_names, color = face_recognition_worker(frame, place_id, known_face_names, known_face_encodings, cudadevice)
                    else:
                        newframe = frame.copy()
                        for (top, right, bottom, left), name in zip(face_locations, face_names):
                            cv2.rectangle(newframe, (left, top), (right, bottom), color, 2)
                            cv2.rectangle(newframe, (left, top - 35), (right, top), color, cv2.FILLED)
                            font = cv2.FONT_HERSHEY_DUPLEX
                            cv2.putText(newframe, name, (left + 6, top - 6), font, 1.0, (255, 255, 255), 1)

                    try:
                        
            
                     
                        ffmpeg_process = handle_ffmpeg_process(newframe, ffmpeg_process, width, height, stream_url)
                    
                    except BrokenPipeError:
                        print("FFmpeg process has terminated, restarting...")
                        kill_ffmpeg_process(ffmpeg_process)
                        time.sleep(ffmpeg_restart_delay)
                        ffmpeg_process = start_ffmpeg_process(width, height, stream_url)

                    # end_time = time.time()
                    # iteration_time_ms = (end_time - start_time) * 1000
                    # print(f"iteration is --> {iteration_time_ms} ms")
                except Exception as e:
                    print(f"Error in frame processing: {e}")
                    time.sleep(1)
                    
                    # Check if FFmpeg needs restart
                    if ffmpeg_process.poll() is not None:
                        print("FFmpeg process has ended, restarting...")
                        kill_ffmpeg_process(ffmpeg_process)
                        time.sleep(ffmpeg_restart_delay)
                        ffmpeg_process = start_ffmpeg_process(width, height, stream_url)

        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)

        finally:
            print("Cleaning up resources before retry...")
            try:
                if 'video_capture' in locals() and video_capture is not None:
                    video_capture.release()
                if 'ffmpeg_process' in locals() and ffmpeg_process is not None:
                    kill_ffmpeg_process(ffmpeg_process)
            except Exception as e:
                print(f"Error during cleanup: {e}")

            time.sleep(5)
            


from celery import shared_task

@shared_task(name='Backend.tasks.keep_worker_alive')
def keep_worker_alive():
    """Health check task to keep the worker alive"""
    return "Worker is alive"
@prefork_worker.task
def keep_worker_alive(arg):
    return "Worker is alive" 
@prefork_worker.task
def ping_worker():
    return "pong"

