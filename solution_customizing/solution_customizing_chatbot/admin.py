from django.contrib import admin
from .models import Conversation, Message

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('conversation_id', 'user_id', 'started_at', 'updated_at', 'is_archived')
    actions = ['archive_conversations']

    def has_delete_permission(self, request, obj=None):
        return False

    def archive_conversations(self, request, queryset):
        for conversation in queryset:
            conversation.delete()
    archive_conversations.short_description = "Archive selected conversations"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'conversation', 'sender', 'created_at')
    def has_delete_permission(self, request, obj=None):
        return False