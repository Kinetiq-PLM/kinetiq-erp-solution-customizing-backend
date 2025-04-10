from django.urls import path
from . import views   # Use a relative import to avoid ImportError

urlpatterns = [
    path('chatbot/', views.chatbot, name='chatbot'),  # Define a valid route
]