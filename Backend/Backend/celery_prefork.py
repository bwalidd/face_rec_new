from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
import django

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Backend.settings')

# Setup Django first
django.setup()

# Now we can import Django models
from Api.models import Detections, DetectionPerson
import tempfile
import time
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)

# Create Celery app
app = Celery('Prefork')

# Configure Celery using Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all registered Django apps
app.autodiscover_tasks()

# Celery Beat schedule configuration
app.conf.beat_schedule = {
    'worker-ping': {
        'task': 'Api.task.ping_worker',
        'schedule': 15.0,  # Run every 15 seconds
    },
    'cleanup-old-detections': {
        'task': 'Backend.celery_prefork.cleanup_old_detections',
        'schedule': 60.0,  # Run every minute
    },
    'cleanup-old-temp-files': {
        'task': 'Backend.celery_prefork.cleanup_old_temp_files',
        'schedule': 3600.0,  # Run every hour
    },
}

app.conf.timezone = 'UTC'

# Redis configuration
app.conf.update(
    broker_url='redis://default:admin@redis:6379/11',  
    result_backend='redis://default:admin@redis:6379/11',
    broker_connection_retry_on_startup=True,
    broker_heartbeat=10,
    worker_send_task_events=True,
    worker_heartbeat_interval=30,
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    task_compression=None,
    worker_concurrency=4,  # One worker per GPU
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    task_soft_time_limit=3300,  # 55 minutes
    worker_max_tasks_per_child=1000,
    worker_max_memory_per_child=2000000,  # 2GB
)

# Task routing configuration
app.conf.task_routes = {
    'Api.task.insertion_database_task_unknown': {'queue': 'prefork_queue'},
    'Api.task.insertion_database_task_known_high': {'queue': 'prefork_queue'},
    'Api.task.mainloop': {'queue': 'prefork_queue'},
}

app.conf.task_queues = {
    'prefork_queue': {
        'exchange': 'prefork_queue',
        'routing_key': 'prefork_queue',
    }
}

# GPU configuration
app.conf.update(
    gpu_count=2,  # 2 GPUs per node
    gpu_devices="0,1",  # Local GPU devices
    cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES', '0,1'),
    pytorch_cuda_alloc_conf='max_split_size_mb:256',
    nccl_debug='INFO',
    nccl_ib_disable='1',
    nccl_p2p_disable='1',
    cuda_version='12.6',
    cuda_launch_blocking='0',
    omp_num_threads='4',
    malloc_trim_threshold='100000',
)

@app.task(queue="prefork_queue", soft_time_limit=2, ignore_result=True, acks_late=True)
def periodic_task_to_do() -> None:
    return "hello"

@app.task(queue="prefork_queue", soft_time_limit=2, ignore_result=True, acks_late=True)
def cleanup_old_temp_files():
    """Cleanup temporary files older than 1 hour"""
    temp_dir = tempfile.gettempdir()
    current_time = time.time()
    max_age = 10 
    
    try:
        for filename in os.listdir(temp_dir):
            if filename.endswith('.jpg'):
                filepath = os.path.join(temp_dir, filename)
                try:
                    if os.path.getctime(filepath) < (current_time - max_age):
                        os.unlink(filepath)
                except OSError as e:
                    logger.error(f"Error removing old temp file {filepath}: {e}")
        return "Temp files cleaned up"
    except Exception as e:
        logger.error(f"Error during temp file cleanup: {e}")
        raise

@app.task(queue="prefork_queue", soft_time_limit=2, ignore_result=True, acks_late=True)
def cleanup_old_detections():
    """
    Removes detections and their associated detection-person relationships that are older than 1 minute.
    Uses efficient bulk delete operations and proper error handling.
    """
    try:
        cutoff_time = timezone.now() - timedelta(minutes=1440)
        
        # Get IDs of old detections
        old_detection_ids = Detections.objects.filter(
            created__lt=cutoff_time
        ).values_list('id', flat=True)
        
        # Delete associated DetectionPerson records first
        detection_persons_deleted = DetectionPerson.objects.filter(
            detection_id__in=old_detection_ids
        ).delete()[0]
        
        # Then delete the Detections
        detections_deleted = Detections.objects.filter(
            id__in=old_detection_ids
        ).delete()[0]
        
        logger.info(
            f"Cleanup completed: removed {detections_deleted} detections and "
            f"{detection_persons_deleted} detection-person relationships"
        )
        
        return detections_deleted, detection_persons_deleted
        
    except Exception as e:
        logger.error(f"Error during detection cleanup: {str(e)}")
        raise