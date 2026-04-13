# Generated migration to remove UserProfile model

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0021_permission_system'),
    ]

    operations = [
        # Delete the UserProfile model
        migrations.DeleteModel(
            name='UserProfile',
        ),
    ]
