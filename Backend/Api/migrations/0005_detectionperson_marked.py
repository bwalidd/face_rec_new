# Generated by Django 5.0.1 on 2024-08-22 10:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Api', '0004_detections_is_read'),
    ]

    operations = [
        migrations.AddField(
            model_name='detectionperson',
            name='marked',
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
    ]
