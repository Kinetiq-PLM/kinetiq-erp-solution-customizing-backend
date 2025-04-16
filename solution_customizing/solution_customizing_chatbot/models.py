from django.utils import timezone
from django.db import models
import uuid

class Conversation(models.Model):
    def generate_convo_id():
        return f"convo_{uuid.uuid4().hex}"
    
    conversation_id = models.CharField(
        max_length=255, 
        primary_key=True,
        default=generate_convo_id,
        editable=False
    )
    role_id = models.CharField(max_length=255, null=True, blank=True)
    user_id = models.CharField(max_length=255, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    def delete(self, *args, **kwargs):
        """Override delete to set is_archived to True instead of deleting"""
        self.is_archived = True
        self.updated_at = timezone.now()
        self.save()
        return self

    def hard_delete(self, *args, **kwargs):
        """Provide method for actually deleting the record if needed"""
        super().delete(*args, **kwargs)

    class Meta:
        
        db_table = '"solution_customizing"."conversations"'


class Message(models.Model):
    def generate_message_id():
        return f"msg_{uuid.uuid4().hex}"
    
    SENDER_CHOICES = [
        ('user', 'User'),
        ('bot', 'Bot'),
    ]
    
    message_id = models.CharField(
        max_length=255, 
        primary_key=True,
        default=generate_message_id,
        editable=False
    )
    conversation = models.ForeignKey(
        Conversation, 
        on_delete=models.CASCADE,
        to_field='conversation_id',
        db_column='conversation_id'
    )
    sender = models.CharField(max_length=4, choices=SENDER_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    intent = models.TextField(null=True, blank=True)
    error = models.BooleanField(default=False)
    sql_query = models.TextField(null=True, blank=True)

    class Meta:
        db_table = '"solution_customizing"."messages"'