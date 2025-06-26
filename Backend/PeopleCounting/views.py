from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
import cv2 
from Api.serializers import ImageProcSerializer 
from Api.models import ImageProc
from Api.task import mainloop
import os 
from rest_framework import status 
import subprocess
from django.core.files.base import ContentFile
import uuid
from .execution import run_prediction_task
from django.http import JsonResponse, HttpResponseForbidden
import psutil
import time
from Api.janus_api import main_api , main_api_delete
from AiLine.predict import main
from AiLine.zone import main_zone
import requests
from Api.helpers import send_stream_status
YOLO_MODELS = {"people":"/app/Backend/AiModels/models/PersonYolov8M/weights/best.pt","cars":"/app/Backend/AiModels/models/Cars-model/best_1000.pt"}
WEB_SOCKET_URL = "ws://34.67.24.106:3000"
@permission_classes([IsAuthenticated])
@api_view(['GET'])
@csrf_exempt
def GetStreamImage(request) -> Response:
    url = request.GET.get('url')
    image = cv2.imread(url)
    return Response(image)
    
@permission_classes([IsAuthenticated])
@api_view(['GET'])
@csrf_exempt
def GetStream(request, id) -> Response:
    if request.method == "GET": 
        stream = ImageProc.objects.filter(stream_type="counting",place__id=id).order_by("-created")
        serializer = ImageProcSerializer(stream, many=True)
        return Response(serializer.data)

# @permission_classes([IsAuthenticated])
@api_view(['POST', 'PATCH'])
@csrf_exempt
def PostStream(request):
    # if request.user.username != "bluedove":
    #     return Response("Not allowed", status=status.HTTP_401_UNAUTHORIZED)
    
    # Check if pod_id and gpu_id match this pod's configuration (for GPU tasks)
    if request.method in ["POST", "PATCH"] and request.data.get("pod_id") and request.data.get("gpu_id") is not None:
        import socket
        current_pod = os.getenv('HOSTNAME', socket.gethostname())
        current_gpu_ids = os.getenv('GPU_ID', '0').split(',')
        if request.data["pod_id"] != current_pod:
            return HttpResponseForbidden("This pod cannot process GPU tasks for another pod.")
        if str(request.data["gpu_id"]) not in current_gpu_ids:
            return HttpResponseForbidden("This pod does not have the requested GPU ID.")
    
    if request.method == "PATCH":
        try:
            print(f"cuda device is {request.data['cuda_device']}")
            instance = ImageProc.objects.filter(id=request.data['id']).first()
            if not instance:
                return Response({"error 1": "No matching record found"}, status=status.HTTP_404_NOT_FOUND)

            number_of_cameras = ImageProc.objects.filter(place__id=request.data['place'], camera_type=request.data['camera_type']).count()

            yolo_model = YOLO_MODELS.get(request.data['model_type'])
            if not yolo_model:
                return Response({"error 2": "YOLO model for 'people' not found"}, status=status.HTTP_400_BAD_REQUEST)

            
            try:
                # run_prediction_task.apply_async(
                #     args=[yolo_model,
                #     instance.url,
                #     0.5,
                #     request.data['cords'],
                #     request.data['place_name'],
                #     number_of_cameras,
                #     f"{instance.title}_{instance.category_name}_{str(instance.place)}",
                #     WEB_SOCKET_URL,
                #     request.data['cords_type'],
                #     request.data['title'],
                #     request.data['camera_type'],
                #     request.data['model_type'],
                #     ],queue="prefork_queue"
                    
                    
                # )
                if request.data['cords_type'] == "line":
                    main.apply_async(
                        args=[yolo_model,
                            instance.url,
                            0.5,
                            request.data['cords'],
                            request.data['place_name'],
                            number_of_cameras,
                            f"{instance.title}_{instance.category_name}_{str(instance.place)}",
                            WEB_SOCKET_URL,
                            request.data['cords_type'],
                            request.data['title'],
                            request.data['camera_type'],
                            request.data['model_type'],
                            instance.id,
                            "0",
                            ],queue="yolo_queue"
                    )
                elif request.data['cords_type'] == "region":
                    main_zone.apply_async(
                        args=[yolo_model,
                            instance.url,
                            0.5,
                            request.data['cords'],
                            request.data['place_name'],
                            number_of_cameras,
                            f"{instance.title}_{instance.category_name}_{str(instance.place)}",
                            WEB_SOCKET_URL,
                            request.data['cords_type'],
                            request.data['title'],
                            request.data['camera_type'],
                            request.data['model_type'],
                            instance.id,
                            "0",
                            ],queue="yolo_queue"
                    )
                send_stream_status("Ai process is starting")
                print("task is ",f"{instance.title}_{instance.category_name}_{str(instance.place)}",)
            except Exception as e:
                print(f"Error queuing task: {e}")

            detection = {
                'camera_number': number_of_cameras,
                'model_type': yolo_model,
                'cords': request.data['cords'],
                'status': True,
            }

            serializer = ImageProcSerializer(instance, data=detection, partial=True)

            if serializer.is_valid():
                serializer.save()
                stream = ImageProc.objects.filter(stream_type="counting", place__id=request.data['place']).order_by("-created")
                serializer = ImageProcSerializer(stream, many=True)
                try:
                    webrtc_stream_id = 2147483647 - int(instance.id)
                    main_api.apply_async(countdown=60,args=[instance.id,webrtc_stream_id,instance.url],queue='prefork_queue')
                    
                except Exception as e:
                    send_stream_status("Can't start stream")
                    print(f"Error setting up Redis queue: {e}")
                    exit(1)
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error 3": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "POST":
        if request.data.get('url') is None:
            newdata = request.data.copy()
            newdata['url'] = 'none'
            serializer = ImageProcSerializer(data=newdata)
            if serializer.is_valid():
                instance = serializer.save()
                res = {"id":instance.id}
                return JsonResponse(res)
        try:
            video_capture = cv2.VideoCapture(request.data['url'])
            ret, frame = video_capture.read()
            if not ret:
                return Response({"error": "Video or stream not found."}, status=status.HTTP_404_NOT_FOUND)
            
            _, encoded_frame = cv2.imencode('.jpg', frame)
            image_data = encoded_frame.tobytes()
            random_filename = str(uuid.uuid4()) + '.jpg'
            image_file = ContentFile(image_data, name=random_filename)

            serializer = ImageProcSerializer(data=request.data)
            if serializer.is_valid():
                instance = None
                if request.data.get('id') is not  None:
                    stream = ImageProc.objects.filter(id=request.data['id']).first()
                    url = {"url": request.data['url']}  
                    serializer = ImageProcSerializer(stream, data=url, partial=True)
                    if serializer.is_valid():
                        instance = serializer.save()  
                else:
                    serializer = ImageProcSerializer(data=request.data)
                    if serializer.is_valid():
                        instance = serializer.save()

              

                command = ['celery', '-A', 'Backend', 'worker', '--pool=solo', '--queues=yolo_queue','--loglevel=info']
                env = os.environ.copy()

                env['DJANGO_SETTINGS_MODULE'] = 'Backend.settings'
                env['PYTHONPATH'] = '/app' 
                env['CUDA_VISIBLE_DEVICES'] = request.data['cuda_device']
                env['CUDA_HOME'] = '/usr/local/cuda'
                env['LD_LIBRARY_PATH'] = f"{env['CUDA_HOME']}/lib64:{env['LD_LIBRARY_PATH']}"
                job_id = subprocess.Popen(command,env=env)
                # job_id = None
                detection = {
                    'title': request.data['title'],
                    'place': request.data['place'],
                    'thumbnail': image_file,
                    'url': request.data['url'],
                    'camera_number': None,
                    'model_type': YOLO_MODELS[request.data["model_type"]],
                    'stream_type': 'counting',
                    'camera_type': request.data['camera_type'],
                    'websocket_url': None,
                    'cords': None,
                    'status': False,
                    'procId': str(job_id.pid),
                }

                serializer = ImageProcSerializer(instance, data=detection, partial=True) 
                if serializer.is_valid():
                    serializer.save()
                    
                    return Response(serializer.data)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
@csrf_exempt
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteCounting(request,stream_id,id):
    ss= stream_id
    if request.method == "DELETE":
        if request.user.username != "bluedove":
            return Response("Not allowed", status=401)
        stream_id = ImageProc.objects.filter(id=stream_id).values("id").first()
        print(f"ss is ----> {ss}")
        id2 = (2147483647 - int(ss))
        main_api_delete(int(ss))
        main_api_delete(id2)
        jobId = ImageProc.objects.filter(id=ss).values("procId").first()
        print(f"job id iss ----> {jobId}")
        try:       
            jjid = int(jobId['procId']) 
            try:
                os.kill(jjid, 0) 
            except OSError:
                pass 
            process = psutil.Process(jjid)

            try:
                process.terminate()
                process.wait(timeout=2)
            except psutil.TimeoutExpired:
                process.kill() 
        except Exception as e:
            print("error is ",e)
        try:
            rtsp_delete_respons = requests.delete(f"http://admin:admin@normal_stream:9997/v3/config/paths/delete/live/{id}")
            print(f"rtsp_delete_respons is {rtsp_delete_respons}")
        except Exception as e:
            print(f"Error deleting rtsp stream {e}")
        ImageProc.objects.filter(id=ss).delete()
        stream = ImageProc.objects.filter(stream_type="counting", place__id=id).order_by("-created")
        serializer = ImageProcSerializer(stream, many=True)
        return Response(serializer.data)