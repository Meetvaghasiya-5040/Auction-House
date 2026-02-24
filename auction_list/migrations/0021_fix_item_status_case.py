from django.db import migrations


def fix_status_case(apps, schema_editor):
    """Normalize any lowercase status values saved by the old admin code."""
    Item = apps.get_model('auction_list', 'Item')
    Item.objects.filter(status='lotted').update(status='Lotted')
    Item.objects.filter(status='sold').update(status='Sold')
    Item.objects.filter(status='available').update(status='Available')


class Migration(migrations.Migration):

    dependencies = [
        ('auction_list', '0020_auction_start_email_sent_alter_auction_auction_type_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_status_case, migrations.RunPython.noop),
    ]
