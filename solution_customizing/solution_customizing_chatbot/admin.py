from django.contrib import admin
from django.utils import timezone
from .models import Conversation, Message, User, RolePerm

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('conversation_id', 'conversation_title', 'employee_id', 'started_at', 'updated_at', 'is_archived')
    list_filter = ('is_archived', 'employee_id', 'started_at')
    search_fields = ('conversation_id', 'conversation_title', 'employee_id__employee_id')
    actions = ['archive_conversations', 'unarchive_conversations']
    readonly_fields = ('conversation_id', 'started_at', 'updated_at') # Make IDs/timestamps read-only

    def has_delete_permission(self, request, obj=None):
        return False # Keep soft delete via actions

    def archive_conversations(self, request, queryset):
        updated_count = queryset.update(is_archived=True, updated_at=timezone.now())
        self.message_user(request, f"{updated_count} conversations were successfully archived.")
    archive_conversations.short_description = "Archive selected conversations"

    def unarchive_conversations(self, request, queryset):
        archived_conversations = queryset.filter(is_archived=True)
        updated_count = archived_conversations.update(is_archived=False, updated_at=timezone.now())
        self.message_user(request, f"{updated_count} conversations were successfully unarchived.")
    unarchive_conversations.short_description = "Unarchive selected conversations"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    # --- Add 'get_employee_name' to list_display ---
    list_display = ('message_id', 'conversation', 'get_employee_name', 'sender', 'message', 'role_id', 'created_at', 'error')
    list_filter = ('sender', 'role_id', 'created_at', 'error', 'conversation__employee_id') # Filter by employee is okay here
    # --- Update search_fields if needed (e.g., search by employee name) ---
    search_fields = (
        'message_id',
        'conversation__conversation_id',
        'message',
        'role_id__role_id', # If role_id is FK to RolePerm
        'conversation__employee_id__employee_id', # Search by employee ID
        'conversation__employee_id__first_name', # Search by first name (adjust field name if needed)
        'conversation__employee_id__last_name',  # Search by last name (adjust field name if needed)
    )
    readonly_fields = ('message_id', 'created_at')

    # --- Method to display employee name ---
    def get_employee_name(self, obj):
        if obj.conversation and obj.conversation.employee_id:
            # Assuming your User model has first_name and last_name fields
            # Adjust field names if your User model is different
            # Or use a method like get_full_name() if available
            user = obj.conversation.employee_id
            return f"{user.first_name} {user.last_name}" # Example: Combine first and last name
            # return user.get_full_name() # If using standard Django User or similar method
        return "N/A" # Or '-' or None, if conversation or user is missing
    get_employee_name.short_description = 'Employee Name' # Column header
    # --- Optional: Allow sorting by employee name ---
    # Adjust the field path according to your User model's name fields
    get_employee_name.admin_order_field = 'conversation__employee_id__first_name'


    def save_model(self, request, obj, form, change):
        # ... (existing save_model logic) ...
        super().save_model(request, obj, form, change)
        if obj.conversation:
            conversation = obj.conversation
            conversation.save(update_fields=['updated_at'])

    def has_delete_permission(self, request, obj=None):
        return False