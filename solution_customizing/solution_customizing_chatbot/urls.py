from django.urls import path
from .views import (
    conversation_list_by_user,
    archive_conversation,
    create_conversation,
    load_messages,
    create_message,
    chatbot,
    get_user_details,
    update_conversation_title
)

urlpatterns = [
    path('load_conversations/<str:employee_id>/', conversation_list_by_user, name='load_conversations'),
    path('load_messages/<str:conversation_id>/', load_messages, name='load_messages'),
    path('load_user_details/<str:employee_id>/', get_user_details, name='get_user_details'),
    path('archive_conversation/<str:conversation_id>/', archive_conversation, name='archive_conversation'),
    path('create_conversation/', create_conversation, name='create_conversation'),
    path('create_message/<str:conversation_id>/', create_message, name='create_message'),
    path('respond/', chatbot, name='chatbot_respond'),
    path('update_title/<str:conversation_id>/', update_conversation_title, name='update_conversation_title'),
]