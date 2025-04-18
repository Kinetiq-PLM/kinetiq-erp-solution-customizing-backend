from django.contrib import admin
from django.utils import timezone
from .models import Conversation, Message

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('conversation_id', 'user_id', 'started_at', 'updated_at', 'is_archived')
    list_filter = ('is_archived', 'user_id', 'started_at')
    actions = ['archive_conversations', 'unarchive_conversations']

    def has_delete_permission(self, request, obj=None):
        return False

    def archive_conversations(self, request, queryset):
        updated_count = queryset.update(is_archived=True, updated_at=timezone.now())
        self.message_user(request, f"{updated_count} conversations were successfully archived.")
    archive_conversations.short_description = "Archive selected conversations"

    def unarchive_conversations(self, request, queryset):
        """Action to unarchive selected conversations by setting is_archived=False."""
        archived_conversations = queryset.filter(is_archived=True)
        updated_count = archived_conversations.update(is_archived=False, updated_at=timezone.now())
        self.message_user(request, f"{updated_count} conversations were successfully unarchived.")
    unarchive_conversations.short_description = "Unarchive selected conversations"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'conversation', 'sender', 'created_at')
    def has_delete_permission(self, request, obj=None):
        return False