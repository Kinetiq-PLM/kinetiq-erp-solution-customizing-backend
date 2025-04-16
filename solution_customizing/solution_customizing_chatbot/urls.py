from django.urls import path
from .views import (
    conversation_list_by_user,
    archive_conversation,
    create_conversation,
    message_list,
    handle_user_message,
    chatbot,
)

urlpatterns = [
    path('conversations/user/<str:user_id>/', conversation_list_by_user, name='conversation_list_by_user'),
    path('conversations/<str:conversation_id>/', archive_conversation, name='archive_conversation'),
    path('conversations/', create_conversation, name='create_conversation'),
    path('messages/<str:conversation_id>/', message_list, name='message_list'),
    path('messages/user/<str:user_id>/', handle_user_message, name='handle_user_message'),
    path('chatbot/', chatbot, name='chatbot'),
]