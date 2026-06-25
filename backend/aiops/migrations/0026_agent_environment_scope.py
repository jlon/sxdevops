from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('aiops', '0025_alter_aiopschatmessage_message_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiopsagentprofile',
            name='allowed_knowledge_environment_ids',
            field=models.JSONField(blank=True, default=list, verbose_name='允许知识图谱环境'),
        ),
        migrations.AddField(
            model_name='aiopsagentprofile',
            name='default_knowledge_environment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='default_agent_profiles',
                to='aiops.aiopsknowledgeenvironment',
                verbose_name='默认知识图谱环境',
            ),
        ),
    ]
