"""
Migration 0010:
1. Removes the accidental 'default_profile_image' field (added by user edit)
2. Fixes upload_to from 'media/profile_images/' -> 'profile_images/'
3. DATA MIGRATION: clears stale 'profile_images/default.png' values in existing
   PostgreSQL rows that were stored by the old model default — those files don't
   exist on Render so they caused 404 errors.
"""
from django.db import migrations, models


def clear_bad_default_images(apps, schema_editor):
    """Set profile_image to '' for all rows that have the old broken defaults."""
    Profile = apps.get_model('Home', 'Profile')
    bad_values = [
        'profile_images/default.png',
        'media/profile_images/default.png',
        'media/profile_images/default-image.webp',
    ]
    Profile.objects.filter(profile_image__in=bad_values).update(profile_image='')


class Migration(migrations.Migration):

    dependencies = [
        ('Home', '0009_profile_city_profile_state_profile_zip_code'),
    ]

    operations = [
        # 1. Fix the upload_to path on profile_image
        migrations.AlterField(
            model_name='profile',
            name='profile_image',
            field=models.ImageField(blank=True, null=True, upload_to='profile_images/'),
        ),

        # 2. Clear stale bad default values from existing DB rows
        migrations.RunPython(clear_bad_default_images, migrations.RunPython.noop),
    ]
