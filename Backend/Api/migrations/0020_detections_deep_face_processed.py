# Generated by Django 5.0.1 on 2024-12-25 10:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Api', '0019_imageproc_webrtc_stream_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='detections',
            name='deep_face_processed',
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
    ]
